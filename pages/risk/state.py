"""Risk-page action, force-date, refresh-status, and prepared-frame state."""

from __future__ import annotations

import json
from collections import OrderedDict
from dataclasses import dataclass
from threading import RLock
from typing import Any, Callable, Mapping, Sequence

import pandas as pd

from shared.aggregation import (
    apply_filters,
    filter_ir_family,
    frame_for_context,
    parse_row_key,
    prepare_risk_data,
    recompute_filtered_promotion,
)
from shared.contracts import (
    ControlSnapshotProtocol,
    RefreshManagerProtocol,
    RefreshSnapshotProtocol,
)

from .tables import NEW_TRADE_SPLIT


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
) -> pd.DataFrame:
    """Return position-grain New Trades behind the visible hierarchy cell.

    Promotion is deliberately recomputed after the page filters, exactly as it
    is for Risk Explorer.  This is what lets a source trade placed in the
    filtered ``Other`` bucket remain traceable even when its global snapshot
    classification was promoted by other positions.
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
    classified = recompute_filtered_promotion(filtered)
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

    snapshot: RefreshSnapshotProtocol
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
    snapshot = manager.refresh(**refresh_kwargs)
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

    def __init__(self, risk_data: pd.DataFrame, revision: int) -> None:
        self._lock = RLock()
        self._revision = int(revision)
        self._frame = risk_data
        self._filtered: dict[tuple[Any, ...], pd.DataFrame] = {}
        self._rendered: OrderedDict[str, Any] = OrderedDict()

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
        prepared = prepare_risk_data(frame)
        with self._lock:
            if int(revision) <= self._revision:
                return self._frame
            self._frame = prepared
            self._revision = int(revision)
            self._filtered.clear()
            self._rendered.clear()
            return prepared

    def clear_reconstructable(self) -> None:
        """Drop bounded query/render caches while retaining the last-good frame."""
        with self._lock:
            self._filtered.clear()
            self._rendered.clear()

    def filtered(
        self,
        manager: RefreshManagerProtocol | None,
        active_risk_type: str | None,
        ir_family: str | None,
        splits: Sequence[str] | None,
        dimension_filters: Mapping[str, Sequence[str] | None],
        *,
        exclude_selected: bool = False,
    ) -> pd.DataFrame:
        """Return filtered data with promotion computed AFTER filtering.

        This ensures that only rows matching the current UI filters participate
        in threshold aggregation, so an underlying is promoted only when its
        aggregated risk/drisk/pl exceeds the threshold within the selected
        filter context.
        """
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
            )
            with self._lock:
                cached = self._filtered.get(key)
                if cached is not None:
                    return cached
            filtered = apply_filters(
                filter_ir_family(frame, active_risk_type, ir_family),
                [active_risk_type] if active_risk_type else [],
                list(splits or ()),
                dimension_filters,
                exclude_selected=exclude_selected,
            )
            # Recompute promotion on filtered data so that only selected rows
            # participate in threshold comparison.
            if not filtered.empty:
                filtered = recompute_filtered_promotion(filtered)
            with self._lock:
                if self._revision != revision:
                    continue
                cached = self._filtered.setdefault(key, filtered)
                if len(self._filtered) > 32:
                    self._filtered.pop(next(iter(self._filtered)))
                return cached

    def rendered(self, key: str, build: Callable[[], Any]) -> Any:
        """Return one exact immutable table tree from a bounded thread-safe LRU."""
        with self._lock:
            cached = self._rendered.get(key, _UNSET)
            if cached is not _UNSET:
                self._rendered.move_to_end(key)
                return cached
        component = build()
        with self._lock:
            existing = self._rendered.get(key, _UNSET)
            if existing is not _UNSET:
                self._rendered.move_to_end(key)
                return existing
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
    snapshot: RefreshSnapshotProtocol,
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
