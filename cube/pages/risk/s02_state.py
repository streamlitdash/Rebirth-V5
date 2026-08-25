"""V5 Risk-page action, force-date, refresh-status, and prepared-frame state."""

from __future__ import annotations

import json
from collections import OrderedDict
from dataclasses import dataclass
from threading import RLock
from typing import Any, Callable, Mapping, Sequence

import pandas as pd

from cube.domain.s01_schema import TENOR_SWAP, TENOR_SWAP_ORDER
from cube.domain.s02_products import (
    DRISK_THRESHOLD,
    PL_THRESHOLD,
    PROMOTION_REASON,
    PROMOTION_SCORE,
    RISK_GREEK,
    RISK_THRESHOLD,
    RISK_TYPE,
    SOURCE_TYPE,
    UNDERLYING,
    VOL_SCORE,
)
from cube.domain.s11_tenorreduction import (
    ADDITIVE_REDUCTION_COLUMNS,
    MARKET_QUOTE_COLUMNS,
    CatalogSource,
    MatrixProviderLike,
    ReducedTenorReducer,
)
from cube.ui.s02_aggregation import (
    apply_filters,
    filter_ir_family,
    frame_for_context,
    parse_row_key,
    prepare_risk_data,
)
from cube.app.s02_contracts import (
    ControlSnapshotProtocol,
    RefreshManagerProtocol,
    RefreshSnapshotProtocol,
)

from .s13_workspacetables import NEW_TRADE_SPLIT
from .s11_promotion import PromotionGeneration, apply_promotion_generation


FORCE_STORE_ID = "perspective-risk-cube-forced-risk-v1"
VIEW_DATE_STORE_ID = "perspective-risk-cube-view-date-v1"
AUTO_REFRESH_STORE_ID = "perspective-risk-cube-auto-refresh-v1"
COMMODITY_MARKET_STORE_ID = "perspective-risk-cube-commodity-market-v1"
RISK_CHECKER_STORE_ID = "perspective-risk-cube-risk-checker-v1"
FORCE_DRAFT_STORE_ID = "force-risk-draft-store"
FORCE_RENDER_STORE_ID = "force-risk-render-store"
REFRESH_RESULT_STORE_ID = "refresh-result-store"
RESET_GENERATION_STORE_ID = "reset-generation-store"
CLEAR_CACHE_COMPLETE_STORE_ID = "clear-cache-complete-store"
_UNSET = object()
_FILTER_CACHE_MAX_ENTRIES = 32
_FILTER_CACHE_MAX_BYTES = 96 * 1024 * 1024

_REDUCER_CANONICAL_COLUMNS = (
    SOURCE_TYPE,
    RISK_TYPE,
    RISK_GREEK,
    UNDERLYING,
    TENOR_SWAP,
    TENOR_SWAP_ORDER,
    *ADDITIVE_REDUCTION_COLUMNS,
    *MARKET_QUOTE_COLUMNS,
    VOL_SCORE,
    PROMOTION_REASON,
    PROMOTION_SCORE,
    RISK_THRESHOLD,
    DRISK_THRESHOLD,
    PL_THRESHOLD,
)
_REDUCER_COLUMN_BY_PREPARED = {
    column.casefold(): column for column in _REDUCER_CANONICAL_COLUMNS
}
_PREPARED_COLUMN_BY_REDUCER = {
    canonical: prepared for prepared, canonical in _REDUCER_COLUMN_BY_PREPARED.items()
}
_MARKET_QUOTE_IDENTITY = (SOURCE_TYPE, UNDERLYING, TENOR_SWAP)


def _to_reducer_columns(frame: pd.DataFrame) -> pd.DataFrame:
    """Bridge the prepared lowercase UI contract to canonical domain names."""

    renamed = {
        column: _REDUCER_COLUMN_BY_PREPARED[column]
        for column in frame.columns
        if column in _REDUCER_COLUMN_BY_PREPARED
    }
    return frame.rename(columns=renamed)


def _from_reducer_columns(frame: pd.DataFrame) -> pd.DataFrame:
    """Restore the prepared lowercase contract after domain reduction."""

    renamed = {
        column: _PREPARED_COLUMN_BY_REDUCER[column]
        for column in frame.columns
        if column in _PREPARED_COLUMN_BY_REDUCER
    }
    return frame.rename(columns=renamed)


def _new_trade_detail_requested(
    selected_context: Mapping[str, str],
    splits: Sequence[str] | None,
) -> bool:
    """Recognize New Trades from either the row path or its exact page filter."""

    selected_split = selected_context.get("split")
    return selected_split == NEW_TRADE_SPLIT or (
        selected_split is None and tuple(splits or ()) == (NEW_TRADE_SPLIT,)
    )


def _new_trade_details_for_selection(
    combined: pd.DataFrame,
    selected_context: Mapping[str, str],
    active_risk_type: str | None,
    ir_family: str | None,
    splits: Sequence[str] | None,
    dimension_filters: Mapping[str, Sequence[str] | None],
    *,
    exclude_selected: bool = False,
    promotion_generation: Mapping[str, object] | None = None,
    revision: int = 0,
) -> pd.DataFrame:
    """Return position-grain New Trades behind the visible hierarchy cell.

    Promotion follows the active immutable generation. It is never recalculated
    as a side effect of opening a detail row.
    """

    if not isinstance(combined, pd.DataFrame):
        raise TypeError("combined must be a pandas DataFrame")
    if "Trade ID" not in combined:
        return combined.iloc[0:0].copy()
    valid_trade_id = combined["Trade ID"].map(
        lambda value: isinstance(value, str) and bool(value.strip())
    )
    valid_split = combined.get("Split", pd.Series("", index=combined.index))
    trace = combined.loc[valid_trade_id & valid_split.eq(NEW_TRADE_SPLIT)].copy()
    if trace.empty:
        return trace

    prepared = prepare_risk_data(trace)
    filtered = apply_filters(
        filter_ir_family(prepared, active_risk_type, ir_family),
        [active_risk_type] if active_risk_type else [],
        list(splits or ()),
        dimension_filters,
        exclude_selected=exclude_selected,
    )
    if filtered.empty:
        return trace.iloc[0:0].copy()
    trace_index_column = "__new_trade_trace_index__"
    filtered[trace_index_column] = filtered.index
    classified = apply_promotion_generation(
        filtered,
        promotion_generation,
        revision=revision,
    )
    scoped = frame_for_context(classified, dict(selected_context))
    if scoped.empty:
        return trace.iloc[0:0].copy()
    selected = trace.loc[scoped[trace_index_column].tolist()].copy()
    # The source rows have already been scoped with the filter-local promotion
    # classification above.  Drop their snapshot-global promotion columns so
    # the pure detail component cannot apply the selected display bucket a
    # second time against a stale global value.
    promotion_columns = [
        column
        for column in selected.columns
        if str(column).strip().casefold()
        in {"display bucket", "promotion reason", "promotion score"}
    ]
    return selected.drop(columns=promotion_columns)


def risk_action_view_token(
    risk_context: Mapping[str, Any] | None,
    table_view: str | None,
    dimension: str | None,
    credit_view: str | None,
    *,
    generation_state: Mapping[str, Any] | None = None,
) -> str | None:
    """Return the generation token embedded in an interactive risk table.

    Delegated browser events can arrive while a table replacement is in flight.
    Binding every event to the rendered risk generation prevents an action from
    the old table being applied to the new risk type or view.
    """
    if not isinstance(risk_context, Mapping):
        return None
    risk_type = risk_context.get("risk_type")
    if not isinstance(risk_type, str) or not risk_type:
        return None
    normalized_view = table_view if table_view in {"main", "alt"} else "main"
    payload: dict[str, Any] = {
        "data_revision": risk_context.get("data_revision"),
        "dimension": str(dimension or ""),
        "ir_family": risk_context.get("ir_family"),
        "risk_type": risk_type,
        "table_view": normalized_view,
    }
    if normalized_view == "main" and risk_type == "Credit":
        payload["credit_view"] = (
            credit_view if credit_view in {"single", "multi"} else "single"
        )
    if generation_state is not None:
        payload["generation"] = dict(generation_state)
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def _top_book_action_view_token(
    data_revision: Any,
    *,
    splits: Sequence[str] | None = None,
    dimension_filters: Mapping[str, Sequence[str] | None] | None = None,
    exclude_selected: bool = False,
) -> str:
    """Bind Top Book actions to the exact filtered hierarchy generation."""
    return json.dumps(
        {
            "data_revision": data_revision,
            "filters": {
                key: sorted(values or [])
                for key, values in sorted((dimension_filters or {}).items())
            },
            "exclude_selected": bool(exclude_selected),
            "splits": sorted(splits or []),
            "view": "top-book",
        },
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def risk_exclude_selected(value: Sequence[str] | None) -> bool:
    """Normalize the Risk-local exclusion checklist value."""
    return "exclude" in (value or [])


def filter_unmapped_portfolios(
    frame: pd.DataFrame,
    selected_portfolios: Sequence[str] | None,
    *,
    exclude_selected: bool = False,
) -> pd.DataFrame:
    """Apply the Portfolio subset of shared Risk filters to unmapped books.

    Unmapped rows deliberately have no governed Activity, Signoff Group,
    Category, or Sub Category. Portfolio is their only meaningful shared
    dimension, so mapped-only selections do not erase this diagnostic table.
    """
    if not isinstance(frame, pd.DataFrame):
        raise TypeError("unmapped frame must be a pandas DataFrame")
    selected = list(selected_portfolios or [])
    if frame.empty or not selected:
        return frame.copy()
    if "Portfolio" not in frame:
        raise ValueError("unmapped frame is missing required column 'Portfolio'")
    matches = frame["Portfolio"].isin(selected)
    mask = ~matches if exclude_selected else matches
    return frame.loc[mask].copy()


def _has_valid_action_envelope(
    action: Mapping[str, Any] | None,
    *,
    kind: str,
) -> bool:
    """Validate the common delegated-action envelope."""
    if not isinstance(action, Mapping) or action.get("kind") != kind:
        return False
    sequence = action.get("sequence")
    return not isinstance(sequence, bool) and isinstance(sequence, int) and sequence > 0


def _is_current_risk_action(
    action: Mapping[str, Any] | None,
    *,
    kind: str,
    expected_view_token: str | None,
) -> bool:
    """Validate a delegated action and reject events from a replaced table."""
    return (
        _has_valid_action_envelope(action, kind=kind)
        and bool(expected_view_token)
        and action.get("view_token") == expected_view_token
    )


def _valid_delegated_row_key(value: Any, *, allow_total: bool) -> bool:
    """Accept canonical hierarchy keys, with an empty key only for TOTAL cells."""
    if not isinstance(value, str):
        return False
    if not value:
        return allow_total
    parsed = parse_row_key(value)
    return bool(parsed) and all(str(item).strip() for item in parsed.values())


def normalize_forced_dates(values: Mapping[str, Any] | None) -> dict[str, str]:
    """Return a stable source-to-ISO-date mapping or reject malformed state."""
    if values is None:
        return {}
    if not isinstance(values, Mapping):
        raise ValueError("forced dates must be a mapping")

    normalized: dict[str, str] = {}
    for raw_source, raw_value in values.items():
        source = str(raw_source).strip()
        if not source:
            raise ValueError("forced-date source names must not be blank")
        if (
            raw_value is None
            or isinstance(raw_value, bool)
            or str(raw_value).strip() == ""
        ):
            raise ValueError(f"forced date for {source} is missing")
        try:
            timestamp = pd.Timestamp(raw_value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"forced date for {source} is invalid") from exc
        if pd.isna(timestamp):
            raise ValueError(f"forced date for {source} is invalid")
        normalized[source] = timestamp.date().isoformat()
    return dict(sorted(normalized.items()))


def normalize_view_date(value: Any) -> str | None:
    """Normalize a global Today-view override; `None` means system Today."""
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        raise ValueError("view date is invalid")
    try:
        timestamp = pd.Timestamp(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("view date is invalid") from exc
    if pd.isna(timestamp):
        raise ValueError("view date is invalid")
    return timestamp.date().isoformat()


def auto_refresh_enabled(value: Any) -> bool:
    """Use a safe On default for missing or malformed browser-local state."""
    return value if isinstance(value, bool) else True


def commodity_market_enabled(value: Any) -> bool:
    """Commodity quote connectors are opt-in and therefore default Off."""
    return value if isinstance(value, bool) else False


def risk_checker_enabled(value: Any) -> bool:
    """Risk readiness/inventory validation is enabled unless explicitly disabled."""
    return value if isinstance(value, bool) else True


def collect_forced_dates(
    check_values: Sequence[Sequence[str] | None] | None,
    dates: Sequence[Any] | None,
    check_ids: Sequence[Mapping[str, Any]] | None,
    date_ids: Sequence[Mapping[str, Any]] | None,
) -> dict[str, str]:
    """Collect pattern-matching controls by source instead of array position."""
    checked_sources = {
        str(component_id.get("source", "")).strip()
        for component_id, values in zip(check_ids or (), check_values or ())
        if "force" in (values or ()) and str(component_id.get("source", "")).strip()
    }
    dates_by_source = {
        str(component_id.get("source", "")).strip(): value
        for component_id, value in zip(date_ids or (), dates or ())
        if str(component_id.get("source", "")).strip()
    }
    missing_dates = sorted(
        source
        for source in checked_sources
        if source not in dates_by_source or dates_by_source[source] in (None, "")
    )
    if missing_dates:
        raise ValueError(
            "forced dates are required for checked sources: " + ", ".join(missing_dates)
        )
    selected = {source: dates_by_source[source] for source in checked_sources}
    return normalize_forced_dates(selected)


def snapshot_forced_dates(
    snapshot: RefreshSnapshotProtocol | ControlSnapshotProtocol,
) -> dict[str, str]:
    """Serialize the manager's authoritative applied overrides."""
    return normalize_forced_dates(snapshot.forced_dates)


def snapshot_forced_view_date(
    snapshot: RefreshSnapshotProtocol | ControlSnapshotProtocol,
) -> str | None:
    """Serialize the manager's authoritative global Today-view override."""
    return normalize_view_date(snapshot.forced_view_date)


def make_force_draft(
    applied: Mapping[str, Any] | None,
    overrides: Mapping[str, Any] | None = None,
    *,
    revision: int = 0,
    applied_view_date: Any = None,
    view_date: Any = _UNSET,
) -> dict[str, Any]:
    """Create serializable draft state with an optimistic-concurrency base."""
    base = normalize_forced_dates(applied)
    proposal = base if overrides is None else normalize_forced_dates(overrides)
    base_view = normalize_view_date(applied_view_date)
    proposal_view = base_view if view_date is _UNSET else normalize_view_date(view_date)
    return {
        "base_revision": int(revision),
        "base_overrides": base,
        "overrides": proposal,
        "base_view_date": base_view,
        "view_date": proposal_view,
        "conflict": False,
    }


def draft_forced_dates(
    draft: Mapping[str, Any] | None,
    *,
    fallback: Mapping[str, Any] | None = None,
) -> dict[str, str]:
    """Read the proposed overrides from the versioned draft envelope."""
    fallback_dates = normalize_forced_dates(fallback)
    if not draft or "overrides" not in draft:
        return fallback_dates
    return normalize_forced_dates(draft.get("overrides"))


def draft_base_dates(
    draft: Mapping[str, Any] | None,
    *,
    fallback: Mapping[str, Any] | None = None,
) -> dict[str, str]:
    """Return the applied state against which a proposal was edited."""
    fallback_dates = normalize_forced_dates(fallback)
    if not draft or "base_overrides" not in draft:
        return fallback_dates
    return normalize_forced_dates(draft.get("base_overrides"))


def draft_view_date(
    draft: Mapping[str, Any] | None,
    *,
    fallback: Any = None,
) -> str | None:
    fallback_date = normalize_view_date(fallback)
    if not draft or "view_date" not in draft:
        return fallback_date
    return normalize_view_date(draft.get("view_date"))


def draft_base_view_date(
    draft: Mapping[str, Any] | None,
    *,
    fallback: Any = None,
) -> str | None:
    fallback_date = normalize_view_date(fallback)
    if not draft or "base_view_date" not in draft:
        return fallback_date
    return normalize_view_date(draft.get("base_view_date"))


def force_dates_dirty(
    draft: Mapping[str, Any] | None,
    applied: Mapping[str, Any] | None,
    *,
    applied_view_date: Any = None,
) -> bool:
    """Whether a draft differs from the currently committed manager state."""
    normalized_applied = normalize_forced_dates(applied)
    normalized_view = normalize_view_date(applied_view_date)
    return (
        draft_forced_dates(draft, fallback=normalized_applied) != normalized_applied
        or draft_view_date(draft, fallback=normalized_view) != normalized_view
    )


def cancel_force_dates(applied: Mapping[str, Any] | None) -> dict[str, str]:
    """Discard a draft without touching the refresh manager."""
    return normalize_forced_dates(applied)


def rebase_force_draft(
    draft: Mapping[str, Any] | None,
    applied: Mapping[str, Any] | None,
    *,
    revision: int,
    applied_view_date: Any = None,
) -> dict[str, Any]:
    """Rebase clean drafts and retain dirty drafts unless they were committed."""
    current = normalize_forced_dates(applied)
    current_view = normalize_view_date(applied_view_date)
    base = draft_base_dates(draft, fallback=current)
    proposal = draft_forced_dates(draft, fallback=current)
    base_view = draft_base_view_date(draft, fallback=current_view)
    proposal_view = draft_view_date(draft, fallback=current_view)

    if (proposal == base and proposal_view == base_view) or (
        proposal == current and proposal_view == current_view
    ):
        return make_force_draft(
            current,
            current,
            revision=revision,
            applied_view_date=current_view,
            view_date=current_view,
        )
    if base != current or base_view != current_view:
        return {
            "base_revision": int(draft.get("base_revision", revision))
            if draft
            else int(revision),
            "base_overrides": base,
            "overrides": proposal,
            "base_view_date": base_view,
            "view_date": proposal_view,
            "conflict": True,
        }
    return {
        "base_revision": int(revision),
        "base_overrides": base,
        "overrides": proposal,
        "base_view_date": base_view,
        "view_date": proposal_view,
        "conflict": False,
    }


@dataclass(frozen=True)
class ForceApplyResult:
    """Outcome used to decide whether browser-local state may be persisted."""

    snapshot: ControlSnapshotProtocol
    requested: dict[str, str]
    requested_view_date: str | None
    committed: bool


def apply_force_dates(
    manager: RefreshManagerProtocol,
    requested: Mapping[str, Any] | None,
    *,
    reason: str = "apply forced risk dates",
    view_date: Any = _UNSET,
    commodity_market: bool | None = None,
    risk_checker: bool | None = None,
    expected_revision: int | None = None,
    expected_reset_generation: int | None = None,
) -> ForceApplyResult:
    """Run exactly one transactional manager refresh for an Apply action."""
    normalized = normalize_forced_dates(requested)
    view_requested = view_date is not _UNSET
    normalized_view = normalize_view_date(view_date) if view_requested else None
    refresh_kwargs: dict[str, Any] = {"forced_dates": normalized, "reason": reason}
    if expected_revision is not None:
        refresh_kwargs["expected_revision"] = expected_revision
    if expected_reset_generation is not None:
        refresh_kwargs["expected_reset_generation"] = expected_reset_generation
    if view_requested:
        refresh_kwargs["view_date"] = normalized_view
    if commodity_market is not None:
        refresh_kwargs["commodity_market_enabled"] = commodity_market
    if risk_checker is not None:
        refresh_kwargs["risk_checker_enabled"] = risk_checker
    # The Apply workflow consumes only committed control metadata. Suppress the
    # manager's defensive copies of every financial frame, then read that small
    # metadata view from the atomic commit.
    manager.refresh(**refresh_kwargs, copy_result=False)
    snapshot = manager.control_snapshot
    view_committed = (
        not view_requested or snapshot_forced_view_date(snapshot) == normalized_view
    )
    committed = (
        not snapshot.errors
        and snapshot_forced_dates(snapshot) == normalized
        and view_committed
        and (
            commodity_market is None
            or bool(snapshot.commodity_market_enabled) == commodity_market
        )
        and (
            risk_checker is None or bool(snapshot.risk_checker_enabled) == risk_checker
        )
    )
    return ForceApplyResult(
        snapshot=snapshot,
        requested=normalized,
        requested_view_date=normalized_view,
        committed=committed,
    )


def persisted_force_dates(result: ForceApplyResult) -> dict[str, str] | None:
    """Return a local-store value only for a confirmed committed snapshot."""
    return dict(result.requested) if result.committed else None


class _RiskDataCache:
    """Thread-safe prepared and filtered frames shared by callback closures."""

    def __init__(
        self,
        risk_data: pd.DataFrame,
        revision: int,
        *,
        prepared_frame_loader: Callable[..., pd.DataFrame | None] | None = None,
        reduced_tenor_catalog: CatalogSource | None = None,
        matrix_provider: MatrixProviderLike | None = None,
    ) -> None:
        if (reduced_tenor_catalog is None) != (matrix_provider is None):
            raise ValueError(
                "reduced_tenor_catalog and matrix_provider must be supplied together"
            )
        self._lock = RLock()
        self._filter_compute_lock = RLock()
        self._render_compute_lock = RLock()
        self._market_load_lock = RLock()
        self._reducer_load_lock = RLock()
        self._revision = int(revision)
        self._frame = risk_data
        self._prepared_frame_loader = prepared_frame_loader
        self._reduced_tenor_catalog = reduced_tenor_catalog
        self._matrix_provider = matrix_provider
        self._tenor_reducer: ReducedTenorReducer | None = None
        self._market_quote_revision: int | None = None
        self._market_quotes: pd.DataFrame | None = None
        self._filtered: OrderedDict[tuple[Any, ...], tuple[pd.DataFrame, int]] = (
            OrderedDict()
        )
        self._filtered_bytes = 0
        self._rendered: OrderedDict[str, Any] = OrderedDict()
        self._promotion_generations: OrderedDict[str, PromotionGeneration] = (
            OrderedDict()
        )

    def current(self, manager: RefreshManagerProtocol | None) -> pd.DataFrame:
        manager_revision = manager.health.revision if manager is not None else None
        with self._lock:
            if manager_revision is None or self._revision == manager_revision:
                return self._frame
        # Read only the dashboard frame. Date, PL, market, checker, and
        # unmapped frames stay in the manager and are not deep-copied here.
        dashboard = manager.read_frame("dashboard_frame")
        return self.replace_frame(dashboard.frame, dashboard.revision)

    def replace(self, snapshot: RefreshSnapshotProtocol) -> pd.DataFrame:
        return self.replace_frame(snapshot.dashboard_frame, snapshot.revision)

    def replace_frame(self, frame: pd.DataFrame, revision: int) -> pd.DataFrame:
        """Publish one already-defensive dashboard-frame read to the UI cache."""
        with self._lock:
            if int(revision) <= self._revision:
                return self._frame
        if self._prepared_frame_loader is None:
            prepared = prepare_risk_data(frame)
        else:
            prepared = self._prepared_frame_loader(
                revision=int(revision),
                frame=frame,
            )
            if prepared is None:
                raise RuntimeError("Committed dashboard frame is unavailable")
        with self._market_load_lock:
            with self._lock:
                if int(revision) <= self._revision:
                    return self._frame
                self._frame = prepared
                self._revision = int(revision)
                self._filtered.clear()
                self._filtered_bytes = 0
                self._rendered.clear()
                self._promotion_generations.clear()
                self._market_quote_revision = None
                self._market_quotes = None
                return prepared

    def clear_reconstructable(self) -> None:
        """Drop bounded query/render caches while retaining the last-good frame."""
        with self._market_load_lock:
            with self._lock:
                self._filtered.clear()
                self._filtered_bytes = 0
                self._rendered.clear()
                self._promotion_generations.clear()
                self._market_quote_revision = None
                self._market_quotes = None

    def _reducer(self) -> ReducedTenorReducer | None:
        """Construct the catalogue-backed reducer only for its first use."""

        if self._reduced_tenor_catalog is None or self._matrix_provider is None:
            return None
        with self._reducer_load_lock:
            if self._tenor_reducer is None:
                self._tenor_reducer = ReducedTenorReducer(
                    self._reduced_tenor_catalog,
                    self._matrix_provider,
                )
            return self._tenor_reducer

    def _compact_market_quotes(
        self,
        frame: pd.DataFrame,
        reducer: ReducedTenorReducer,
    ) -> pd.DataFrame:
        """Retain only exact quote fields for catalogued reduced underlyings."""

        canonical = _to_reducer_columns(frame)
        missing = [
            column for column in _MARKET_QUOTE_IDENTITY if column not in canonical
        ]
        if missing:
            raise ValueError(
                f"market frame is missing quote identity columns: {missing}"
            )
        mapped_underlyings = frozenset(reducer.catalog[UNDERLYING])
        selected_columns = [
            *_MARKET_QUOTE_IDENTITY,
            *[
                column
                for column in MARKET_QUOTE_COLUMNS
                if column in canonical and column not in _MARKET_QUOTE_IDENTITY
            ],
        ]
        compact = canonical.loc[
            canonical[UNDERLYING].isin(mapped_underlyings), selected_columns
        ]
        return compact.drop_duplicates(
            list(_MARKET_QUOTE_IDENTITY), keep="first"
        ).reset_index(drop=True)

    def _market_quotes_for_revision(
        self,
        manager: RefreshManagerProtocol | None,
        *,
        revision: int,
        fallback: pd.DataFrame,
        reducer: ReducedTenorReducer,
    ) -> pd.DataFrame | None:
        """Return one compact exact-quote cache, or signal a revision race."""

        with self._lock:
            if (
                self._market_quote_revision == revision
                and self._market_quotes is not None
            ):
                return self._market_quotes

        # Serialize the defensive manager read. A full MarketBook is copied at
        # most once per committed revision, then immediately compacted.
        with self._market_load_lock:
            with self._lock:
                if (
                    self._market_quote_revision == revision
                    and self._market_quotes is not None
                ):
                    return self._market_quotes
            if manager is None:
                source = fallback
            else:
                market = manager.read_frame("market_frame")
                if int(market.revision) != revision:
                    return None
                source = market.frame
            compact = self._compact_market_quotes(source, reducer)
            with self._lock:
                if self._revision != revision:
                    return None
                if (
                    self._market_quote_revision == revision
                    and self._market_quotes is not None
                ):
                    return self._market_quotes
                self._market_quote_revision = revision
                self._market_quotes = compact
                return compact

    def _reduce_filtered(
        self,
        filtered: pd.DataFrame,
        manager: RefreshManagerProtocol | None,
        *,
        revision: int,
        fallback: pd.DataFrame,
    ) -> pd.DataFrame | None:
        """Run the canonical reducer and restore the prepared UI schema."""

        reducer = self._reducer()
        if reducer is None:
            return filtered
        market_quotes = self._market_quotes_for_revision(
            manager,
            revision=revision,
            fallback=fallback,
            reducer=reducer,
        )
        if market_quotes is None:
            return None
        derived_columns = [
            column for column in ("abs pl", "rows") if column in filtered
        ]
        reducible = filtered.drop(columns=derived_columns)
        reduced = reducer.reduce(
            _to_reducer_columns(reducible),
            market_frame=market_quotes,
        )
        prepared = _from_reducer_columns(reduced)
        if "abs pl" in derived_columns:
            prepared["abs pl"] = prepared["pl"].abs()
        if "rows" in derived_columns:
            prepared["rows"] = 1
        return prepared

    @property
    def revision(self) -> int:
        with self._lock:
            return self._revision

    def publish_promotion_generation(
        self,
        generation: PromotionGeneration,
    ) -> dict[str, object]:
        """Retain one bounded server-side result and return browser-safe metadata."""

        if generation.kind != "current-view":
            raise ValueError("Only calculated current-view promotion can be published")
        with self._lock:
            if generation.revision != self._revision:
                raise ValueError("Promotion generation belongs to a stale revision")
            self._promotion_generations[generation.identifier] = generation
            self._promotion_generations.move_to_end(generation.identifier)
            while len(self._promotion_generations) > 16:
                self._promotion_generations.popitem(last=False)
            return generation.to_store()

    def resolve_promotion_generation(
        self,
        value: Mapping[str, object] | None,
    ) -> PromotionGeneration | None:
        """Resolve untrusted browser metadata to an exact server-owned result."""

        if value is None:
            return None
        try:
            metadata = PromotionGeneration.from_store(value)
        except (TypeError, ValueError):
            return None
        if metadata.kind == "baseline":
            return metadata
        with self._lock:
            generation = self._promotion_generations.get(metadata.identifier)
            if (
                generation is None
                or generation.revision != self._revision
                or generation.to_store() != metadata.to_store()
            ):
                return None
            self._promotion_generations.move_to_end(metadata.identifier)
            return generation

    def filtered(
        self,
        manager: RefreshManagerProtocol | None,
        active_risk_type: str | None,
        ir_family: str | None,
        splits: Sequence[str] | None,
        dimension_filters: Mapping[str, Sequence[str] | None],
        *,
        exclude_selected: bool = False,
        promotion_generation: Mapping[str, object] | None = None,
        reduced_tenor: bool = False,
    ) -> pd.DataFrame:
        """Return filtered data using baseline or one explicit generation."""
        parsed_generation = self.resolve_promotion_generation(promotion_generation)
        while True:
            frame = self.current(manager)
            with self._lock:
                revision = self._revision
            key = (
                revision,
                active_risk_type,
                ir_family if active_risk_type == "IR" else None,
                tuple(splits or ()),
                tuple(
                    (column, tuple(dimension_filters.get(column) or ()))
                    for column in sorted(dimension_filters)
                ),
                bool(exclude_selected),
                bool(reduced_tenor),
                (
                    parsed_generation.identifier
                    if parsed_generation is not None
                    and parsed_generation.kind == "current-view"
                    and parsed_generation.revision == revision
                    else None
                ),
            )
            with self._lock:
                cached = self._filtered.get(key)
                if cached is not None:
                    self._filtered.move_to_end(key)
                    return cached[0]
            # Serialize expensive filter/reduction construction. Concurrent
            # sessions may reuse the result, but never allocate duplicate
            # whole-book reduction tensors for the same process.
            with self._filter_compute_lock:
                with self._lock:
                    cached = self._filtered.get(key)
                    if cached is not None:
                        self._filtered.move_to_end(key)
                        return cached[0]
                filtered = apply_filters(
                    filter_ir_family(frame, active_risk_type, ir_family),
                    [active_risk_type] if active_risk_type else [],
                    list(splits or ()),
                    dimension_filters,
                    exclude_selected=exclude_selected,
                )
                filtered = apply_promotion_generation(
                    filtered,
                    parsed_generation,
                    revision=revision,
                )
                if reduced_tenor:
                    reduced = self._reduce_filtered(
                        filtered,
                        manager,
                        revision=revision,
                        fallback=frame,
                    )
                    if reduced is None:
                        continue
                    filtered = reduced
                with self._lock:
                    if self._revision != revision:
                        continue
                    cached = self._filtered.get(key)
                    if cached is not None:
                        self._filtered.move_to_end(key)
                        return cached[0]
                    size = int(filtered.memory_usage(index=True, deep=True).sum())
                    if size > _FILTER_CACHE_MAX_BYTES:
                        return filtered
                    self._filtered[key] = (filtered, size)
                    self._filtered_bytes += size
                    while len(self._filtered) > 1 and (
                        len(self._filtered) > _FILTER_CACHE_MAX_ENTRIES
                        or self._filtered_bytes > _FILTER_CACHE_MAX_BYTES
                    ):
                        _old_key, (_old_frame, old_size) = self._filtered.popitem(
                            last=False
                        )
                        self._filtered_bytes -= old_size
                    return filtered

    def rendered(self, key: str, build: Callable[[], Any]) -> Any:
        """Return one exact immutable table tree from a bounded thread-safe LRU."""
        with self._lock:
            cached = self._rendered.get(key, _UNSET)
            if cached is not _UNSET:
                self._rendered.move_to_end(key)
                return cached
        # Large hierarchy/table builds release the GIL inside pandas. Keep
        # them one-at-a-time so Dash request threads cannot consume two cores
        # and allocate duplicate component trees during the initial mount.
        with self._render_compute_lock:
            with self._lock:
                existing = self._rendered.get(key, _UNSET)
                if existing is not _UNSET:
                    self._rendered.move_to_end(key)
                    return existing
            component = build()
            with self._lock:
                self._rendered[key] = component
                while len(self._rendered) > 24:
                    self._rendered.popitem(last=False)
                return component


def _next_counter(value: Any) -> int:
    try:
        return int(value or 0) + 1
    except (TypeError, ValueError):
        return 1


def _refresh_status(
    snapshot: ControlSnapshotProtocol | RefreshSnapshotProtocol,
    *,
    action_committed: bool = True,
) -> tuple[str, str, str]:
    status_frame = snapshot.risk_status
    t_minus_one = int(
        ((status_frame["Age"] == 0) & ~status_frame["Force Risk"].astype(bool)).sum()
    )
    forced = int(status_frame["Force Risk"].astype(bool).sum())
    action_labels = {
        "portfolio mapping": "Portfolios refreshed",
        "reload all risk": "Risk refreshed",
        "manual P&L": "P&L refreshed",
        "automatic 15-minute refresh": "AutoPL refreshed",
        "dashboard settings updated": "Settings applied",
        "apply forced risk dates": "Date settings applied",
        "clear cache": "Ready · Cache cleared",
    }
    reason = str(getattr(snapshot, "refresh_reason", "") or "")
    action_succeeded = (
        action_committed and not snapshot.errors and reason in action_labels
    )
    success_label = action_labels[reason] if action_succeeded else "Last success"
    status_at = snapshot.refreshed_at
    if action_succeeded:
        last_attempt_at = getattr(snapshot, "last_attempt_at", None)
        if last_attempt_at is not None:
            status_at = max(status_at, last_attempt_at)
    status_time = status_at.strftime("%H:%M:%S UTC")
    status = (
        f"{success_label} {status_time} · T-1 risk {t_minus_one} · Forced risk {forced}"
    )
    if snapshot.errors:
        return (
            status,
            "⚠ Refresh warning\n" + "\n".join(snapshot.errors),
            "error-log has-errors",
        )
    return status, "", "error-log"


__all__ = [
    "AUTO_REFRESH_STORE_ID",
    "CLEAR_CACHE_COMPLETE_STORE_ID",
    "COMMODITY_MARKET_STORE_ID",
    "FORCE_DRAFT_STORE_ID",
    "FORCE_RENDER_STORE_ID",
    "FORCE_STORE_ID",
    "ForceApplyResult",
    "REFRESH_RESULT_STORE_ID",
    "RESET_GENERATION_STORE_ID",
    "RISK_CHECKER_STORE_ID",
    "VIEW_DATE_STORE_ID",
    "apply_force_dates",
    "auto_refresh_enabled",
    "cancel_force_dates",
    "collect_forced_dates",
    "commodity_market_enabled",
    "draft_base_dates",
    "draft_base_view_date",
    "draft_forced_dates",
    "draft_view_date",
    "filter_unmapped_portfolios",
    "force_dates_dirty",
    "make_force_draft",
    "normalize_forced_dates",
    "normalize_view_date",
    "persisted_force_dates",
    "rebase_force_draft",
    "risk_action_view_token",
    "risk_checker_enabled",
    "risk_exclude_selected",
    "snapshot_forced_dates",
    "snapshot_forced_view_date",
]
