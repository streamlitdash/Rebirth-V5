"""Strict, lazy Risk and Market history contracts for the native Data page.

The repository reads only immutable archive leaves and never performs connector
I/O.  ProductSpec axes own plot dimensionality; raw exact rows remain available
beside the bounded, null-preserving canonical grid used by charts/playback.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from threading import RLock
from typing import ClassVar, Literal

import numpy as np
import pandas as pd

from core.s02_pipeline import AxisSpec, PRODUCT_SPECS_BY_SOURCE_TYPE, ProductSpec
from core.s03_search import (
    CURRENT,
    MOVE,
    OPEN,
    QUICK_RISK_FILTER_COLUMNS,
    ResolvedHistoryIdentity,
)
from core.s11_risk_archive import (
    ALL_ARCHIVE_FILE_NAMES,
    MARKET_DATE,
    RISK_DATE,
    clear_archive_caches,
    load_full_market_history_for_identity,
    load_risk_history_for_identity,
)


HistoryKind = Literal["risk", "market"]
IdentityMode = Literal["reported", "underlying"]
OrderingStatus = Literal["ORDERED", "ORDER_AMBIGUOUS"]

HISTORY_HANDOFF_SCHEMA_VERSION = 1
ORDERED = "ORDERED"
ORDER_AMBIGUOUS = "ORDER_AMBIGUOUS"
HISTORY_PERIODS = frozenset({"wtd", "mtd", "ytd", "1y", "5y", "all", "custom"})
RISK_METRICS = {"risk": "Risk", "drisk": "dRisk", "pl": "PL"}
MARKET_METRICS = {"open": OPEN, "current": CURRENT, "move": MOVE}
HISTORY_RAW_ROW_BUDGET = 10_000
HISTORY_CANONICAL_CELL_BUDGET = 16_000
_MAX_HANDOFF_TEXT = 500
_TENOR_PATTERN = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*([dDwWmMyY])\s*$")
_NATURAL_PART = re.compile(r"(\d+)")
_DATE_LEAF = re.compile(r"\d{4}-\d{2}-\d{2}")


class HistoryValidationError(ValueError):
    """Raised when a history request cannot be interpreted truthfully."""


def _text(value: object, *, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise HistoryValidationError(f"{label} must be nonblank text")
    selected = value.strip()
    if len(selected) > _MAX_HANDOFF_TEXT:
        raise HistoryValidationError(
            f"{label} must be at most {_MAX_HANDOFF_TEXT} characters"
        )
    return selected


def _nonnegative_int(value: object, *, label: str) -> int:
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, np.integer)):
        raise HistoryValidationError(f"{label} must be a non-negative integer")
    selected = int(value)
    if selected < 0:
        raise HistoryValidationError(f"{label} must be a non-negative integer")
    return selected


def _positive_int(value: object, *, label: str) -> int:
    selected = _nonnegative_int(value, label=label)
    if selected < 1:
        raise HistoryValidationError(f"{label} must be a positive integer")
    return selected


def _date(value: object, *, label: str, strict_text: bool = False) -> date:
    if value is None or isinstance(value, (bool, np.bool_)):
        raise HistoryValidationError(f"{label} must be a valid date")
    if strict_text:
        if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            raise HistoryValidationError(f"{label} must be an ISO YYYY-MM-DD date")
        try:
            parsed = datetime.strptime(value, "%Y-%m-%d").date()
        except ValueError as exc:
            raise HistoryValidationError(
                f"{label} must be an ISO YYYY-MM-DD date"
            ) from exc
        if parsed.isoformat() != value:
            raise HistoryValidationError(f"{label} must be an ISO YYYY-MM-DD date")
        return parsed
    try:
        timestamp = pd.Timestamp(value)
    except (TypeError, ValueError) as exc:
        raise HistoryValidationError(f"{label} must be a valid date") from exc
    if pd.isna(timestamp):
        raise HistoryValidationError(f"{label} must be a valid date")
    if timestamp.tzinfo is not None:
        timestamp = timestamp.tz_convert("UTC").tz_localize(None)
    return timestamp.date()


def _exact_keys(value: Mapping[str, object], expected: set[str], *, label: str) -> None:
    actual = set(value)
    if actual != expected:
        raise HistoryValidationError(
            f"{label} fields must be exactly {sorted(expected)}; "
            f"missing={sorted(expected - actual)}, unknown={sorted(actual - expected)}"
        )


@dataclass(frozen=True)
class RiskFilterView:
    """Typed Quick Risk contributor filters at archived position grain."""

    filters: tuple[tuple[str, tuple[str, ...]], ...] = ()
    exclude_selected: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.exclude_selected, bool):
            raise HistoryValidationError("exclude_selected must be boolean")
        if not isinstance(self.filters, tuple):
            raise HistoryValidationError("Risk filters must be an immutable tuple")
        seen: set[str] = set()
        normalized: dict[str, tuple[str, ...]] = {}
        for item in self.filters:
            if not isinstance(item, tuple) or len(item) != 2:
                raise HistoryValidationError(
                    "each Risk filter must be a key/value tuple"
                )
            column, values = item
            column = _text(column, label="Risk filter column")
            if column in seen:
                raise HistoryValidationError(f"duplicate Risk filter {column!r}")
            seen.add(column)
            if column not in QUICK_RISK_FILTER_COLUMNS:
                raise HistoryValidationError(f"unknown Risk filter {column!r}")
            if not isinstance(values, tuple):
                raise HistoryValidationError(
                    f"Risk filter {column!r} values must be an immutable tuple"
                )
            selected = tuple(
                _text(item, label=f"Risk filter {column!r} value") for item in values
            )
            if len(selected) != len(set(selected)):
                raise HistoryValidationError(
                    f"Risk filter {column!r} values must not contain duplicates"
                )
            if selected:
                normalized[column] = selected
        ordered = tuple(
            (column, normalized[column])
            for column in QUICK_RISK_FILTER_COLUMNS
            if column in normalized
        )
        object.__setattr__(self, "filters", ordered)

    @classmethod
    def from_mapping(cls, value: object) -> RiskFilterView:
        if not isinstance(value, Mapping):
            raise HistoryValidationError("filter_view must be a mapping")
        _exact_keys(
            value,
            {"filters", "exclude_selected"},
            label="filter_view",
        )
        raw_filters = value["filters"]
        if not isinstance(raw_filters, Mapping):
            raise HistoryValidationError("filter_view filters must be a mapping")
        filters: list[tuple[str, tuple[str, ...]]] = []
        for column, raw_values in raw_filters.items():
            if isinstance(raw_values, (str, bytes)) or not isinstance(
                raw_values, Sequence
            ):
                raise HistoryValidationError(
                    f"Risk filter {column!r} values must be a sequence"
                )
            filters.append((column, tuple(raw_values)))
        return cls(
            filters=tuple(filters),
            exclude_selected=value["exclude_selected"],
        )

    def to_mapping(self) -> dict[str, object]:
        return {
            "filters": {column: list(values) for column, values in self.filters},
            "exclude_selected": self.exclude_selected,
        }


@dataclass(frozen=True)
class HistoryIdentity:
    """Exact ProductSpec-backed Risk or raw Market identity."""

    source_types: tuple[str, ...]
    risk_type: str
    risk_greek: str
    underlying: str
    identity_mode: IdentityMode = "underlying"

    def __post_init__(self) -> None:
        if not isinstance(self.source_types, tuple) or not self.source_types:
            raise HistoryValidationError(
                "source_types must be a non-empty immutable tuple"
            )
        source_types = tuple(
            _text(source_type, label="Source Type") for source_type in self.source_types
        )
        if len(source_types) != len(set(source_types)):
            raise HistoryValidationError("source_types must not contain duplicates")
        source_types = tuple(sorted(source_types))
        risk_type = _text(self.risk_type, label="Risk Type")
        risk_greek = _text(self.risk_greek, label="Risk Greek")
        underlying = _text(self.underlying, label="Underlying")
        if not isinstance(self.identity_mode, str):
            raise HistoryValidationError("identity_mode must be text")
        identity_mode = self.identity_mode.strip().casefold()
        if identity_mode not in {"reported", "underlying"}:
            raise HistoryValidationError(
                "identity_mode must be 'reported' or 'underlying'"
            )
        specs: list[ProductSpec] = []
        for source_type in source_types:
            try:
                spec = PRODUCT_SPECS_BY_SOURCE_TYPE[source_type]
            except KeyError as exc:
                raise HistoryValidationError(
                    f"unknown ProductSpec Source Type {source_type!r}"
                ) from exc
            exact_pair = (risk_type, risk_greek) == (
                spec.risk_type,
                spec.risk_greek,
            )
            derived_gamma_delta = (
                spec.key in {"fxgamma", "irgamma"}
                and risk_type == spec.risk_type
                and risk_greek == "Delta"
            )
            if not exact_pair and not derived_gamma_delta:
                raise HistoryValidationError(
                    f"Source Type {source_type!r} does not publish Risk Type="
                    f"{risk_type!r}, Risk Greek={risk_greek!r}"
                )
            specs.append(spec)
        axis_signatures = {
            tuple((axis.column, axis.order_column) for axis in spec.axes)
            for spec in specs
        }
        if len(axis_signatures) != 1:
            raise HistoryValidationError(
                "Risk history Source Types have conflicting ProductSpec axes"
            )
        object.__setattr__(self, "source_types", source_types)
        object.__setattr__(self, "risk_type", risk_type)
        object.__setattr__(self, "risk_greek", risk_greek)
        object.__setattr__(self, "underlying", underlying)
        object.__setattr__(self, "identity_mode", identity_mode)

    @property
    def product_spec(self) -> ProductSpec:
        if len(self.source_types) != 1:
            raise HistoryValidationError(
                "history identity has multiple ProductSpec sources"
            )
        return PRODUCT_SPECS_BY_SOURCE_TYPE[self.source_types[0]]

    @property
    def source_type(self) -> str:
        if len(self.source_types) != 1:
            raise HistoryValidationError("history identity has multiple Source Types")
        return self.source_types[0]

    @property
    def axes(self) -> tuple[AxisSpec, ...]:
        return PRODUCT_SPECS_BY_SOURCE_TYPE[self.source_types[0]].axes

    @classmethod
    def from_mapping(cls, value: object) -> HistoryIdentity:
        if not isinstance(value, Mapping):
            raise HistoryValidationError("history identity must be a mapping")
        _exact_keys(
            value,
            {"source_types", "risk_type", "risk_greek", "underlying", "identity_mode"},
            label="history identity",
        )
        raw_source_types = value["source_types"]
        if isinstance(raw_source_types, (str, bytes)) or not isinstance(
            raw_source_types, Sequence
        ):
            raise HistoryValidationError("source_types must be a sequence")
        return cls(
            source_types=tuple(raw_source_types),
            risk_type=value["risk_type"],
            risk_greek=value["risk_greek"],
            underlying=value["underlying"],
            identity_mode=value["identity_mode"],
        )

    def to_mapping(self) -> dict[str, object]:
        return {
            "source_types": list(self.source_types),
            "risk_type": self.risk_type,
            "risk_greek": self.risk_greek,
            "underlying": self.underlying,
            "identity_mode": self.identity_mode,
        }


@dataclass(frozen=True)
class HistoryHandoff:
    """Versioned, JSON-safe Quick-to-Data request."""

    schema_version: int
    kind: HistoryKind
    identity: HistoryIdentity
    metric: str
    source_revision: int
    snapshot_date: date
    filter_view: RiskFilterView | None = None
    reset_generation: int = 0

    def __post_init__(self) -> None:
        version = _nonnegative_int(self.schema_version, label="handoff schema_version")
        if version != HISTORY_HANDOFF_SCHEMA_VERSION:
            raise HistoryValidationError(
                f"unsupported history handoff schema_version {version}"
            )
        if not isinstance(self.kind, str):
            raise HistoryValidationError("history kind must be text")
        kind = self.kind.strip().casefold()
        if kind not in {"risk", "market"}:
            raise HistoryValidationError("history kind must be 'risk' or 'market'")
        if not isinstance(self.identity, HistoryIdentity):
            raise HistoryValidationError("identity must be a HistoryIdentity")
        metric = _text(self.metric, label="history metric").casefold()
        allowed = RISK_METRICS if kind == "risk" else MARKET_METRICS
        if metric not in allowed:
            raise HistoryValidationError(
                f"{kind} history metric must be one of {sorted(allowed)}"
            )
        source_revision = _nonnegative_int(
            self.source_revision,
            label="source_revision",
        )
        snapshot_date = _date(self.snapshot_date, label="snapshot_date")
        reset_generation = _nonnegative_int(
            self.reset_generation,
            label="reset_generation",
        )
        if self.filter_view is not None and not isinstance(
            self.filter_view, RiskFilterView
        ):
            raise HistoryValidationError("filter_view must be a RiskFilterView or None")
        if kind == "market":
            if self.filter_view is not None:
                raise HistoryValidationError(
                    "Market history does not accept Portfolio/reporting filters"
                )
            if self.identity.identity_mode != "underlying":
                raise HistoryValidationError(
                    "Market history requires underlying identity mode"
                )
            if len(self.identity.source_types) != 1:
                raise HistoryValidationError(
                    "Market history requires exactly one Source Type"
                )
            market_spec = PRODUCT_SPECS_BY_SOURCE_TYPE[self.identity.source_type]
            if (self.identity.risk_type, self.identity.risk_greek) != (
                market_spec.risk_type,
                market_spec.risk_greek,
            ):
                raise HistoryValidationError(
                    "Market history requires the exact ProductSpec Risk pair"
                )
        object.__setattr__(self, "schema_version", version)
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "metric", metric)
        object.__setattr__(self, "source_revision", source_revision)
        object.__setattr__(self, "snapshot_date", snapshot_date)
        object.__setattr__(self, "reset_generation", reset_generation)

    @property
    def metric_column(self) -> str:
        return (RISK_METRICS if self.kind == "risk" else MARKET_METRICS)[self.metric]

    @classmethod
    def from_mapping(cls, value: object) -> HistoryHandoff:
        if not isinstance(value, Mapping):
            raise HistoryValidationError("history handoff must be a mapping")
        _exact_keys(
            value,
            {
                "schema_version",
                "kind",
                "identity",
                "metric",
                "source_revision",
                "snapshot_date",
                "filter_view",
                "reset_generation",
            },
            label="history handoff",
        )
        raw_filter = value["filter_view"]
        return cls(
            schema_version=value["schema_version"],
            kind=value["kind"],
            identity=HistoryIdentity.from_mapping(value["identity"]),
            metric=value["metric"],
            source_revision=value["source_revision"],
            snapshot_date=_date(
                value["snapshot_date"],
                label="snapshot_date",
                strict_text=True,
            ),
            filter_view=(
                None if raw_filter is None else RiskFilterView.from_mapping(raw_filter)
            ),
            reset_generation=value["reset_generation"],
        )

    @classmethod
    def from_resolved_identity(
        cls,
        resolved: ResolvedHistoryIdentity,
        *,
        metric: str,
        filter_view: RiskFilterView | None = None,
        reset_generation: int = 0,
    ) -> HistoryHandoff:
        if not isinstance(resolved, ResolvedHistoryIdentity):
            raise HistoryValidationError(
                "resolved identity must come from SearchCatalog"
            )
        return cls(
            schema_version=HISTORY_HANDOFF_SCHEMA_VERSION,
            kind=resolved.kind,
            identity=HistoryIdentity(
                source_types=resolved.source_types,
                risk_type=resolved.risk_type,
                risk_greek=resolved.risk_greek,
                underlying=resolved.underlying,
                identity_mode=resolved.identity_mode,
            ),
            metric=metric,
            source_revision=resolved.source_revision,
            snapshot_date=resolved.snapshot_date,
            filter_view=filter_view,
            reset_generation=reset_generation,
        )

    def to_mapping(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "identity": self.identity.to_mapping(),
            "metric": self.metric,
            "source_revision": self.source_revision,
            "snapshot_date": self.snapshot_date.isoformat(),
            "filter_view": (
                None if self.filter_view is None else self.filter_view.to_mapping()
            ),
            "reset_generation": self.reset_generation,
        }


@dataclass(frozen=True)
class HistoryQuery:
    """One strict period request for an already typed handoff."""

    handoff: HistoryHandoff
    period: str = "all"
    start_date: date | None = None
    end_date: date | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.handoff, HistoryHandoff):
            raise HistoryValidationError("handoff must be a HistoryHandoff")
        period = _text(self.period, label="history period").casefold()
        if period not in HISTORY_PERIODS:
            raise HistoryValidationError(
                f"history period must be one of {sorted(HISTORY_PERIODS)}"
            )
        if period == "custom":
            if self.start_date is None or self.end_date is None:
                raise HistoryValidationError(
                    "custom history period requires start_date and end_date"
                )
            start_date = _date(self.start_date, label="start_date")
            end_date = _date(self.end_date, label="end_date")
            if start_date > end_date:
                raise HistoryValidationError("start_date must not be after end_date")
        else:
            if self.start_date is not None or self.end_date is not None:
                raise HistoryValidationError(
                    "start_date and end_date are only valid for custom period"
                )
            start_date = None
            end_date = None
        object.__setattr__(self, "period", period)
        object.__setattr__(self, "start_date", start_date)
        object.__setattr__(self, "end_date", end_date)


@dataclass(frozen=True)
class HistoryAxisOrder:
    """One frozen axis order for the complete query/playback bundle."""

    column: str
    order_column: str
    labels: tuple[str, ...]
    ranks: tuple[int | None, ...]
    status: OrderingStatus

    def __post_init__(self) -> None:
        if len(self.labels) != len(self.ranks):
            raise HistoryValidationError("axis labels and ranks must have equal length")
        if len(self.labels) != len(set(self.labels)):
            raise HistoryValidationError("axis labels must be unique")
        if self.status not in {ORDERED, ORDER_AMBIGUOUS}:
            raise HistoryValidationError("invalid history ordering status")


@dataclass(frozen=True)
class HistoryOrdering:
    """Frozen ProductSpec axis metadata and aggregate ordering status."""

    axes: tuple[HistoryAxisOrder, ...]
    status: OrderingStatus


@dataclass(frozen=True)
class HistoryBundle:
    """Bounded canonical grid plus exact source rows for one history request."""

    query: HistoryQuery
    date_column: str
    dates: tuple[date, ...]
    resolved_start: date | None
    resolved_end: date | None
    selected_date: date | None
    metric_column: str
    ordering: HistoryOrdering
    values: pd.DataFrame
    selected_rows: pd.DataFrame
    raw_rows: pd.DataFrame
    generation: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "values", self.values.copy(deep=True))
        object.__setattr__(self, "selected_rows", self.selected_rows.copy(deep=True))
        object.__setattr__(self, "raw_rows", self.raw_rows.copy(deep=True))

    @property
    def empty(self) -> bool:
        return not self.dates


def resolve_actual_period_dates(
    available_dates: Sequence[date],
    query: HistoryQuery,
) -> tuple[date, ...]:
    """Resolve presets against actual observations rather than assumed rows."""

    if not isinstance(query, HistoryQuery):
        raise HistoryValidationError("query must be a HistoryQuery")
    actual = tuple(
        sorted({_date(value, label="available date") for value in available_dates})
    )
    if not actual:
        return ()
    as_of = actual[-1]
    if query.period == "all":
        start, end = actual[0], as_of
    elif query.period == "wtd":
        start, end = as_of - timedelta(days=as_of.weekday()), as_of
    elif query.period == "mtd":
        start, end = as_of.replace(day=1), as_of
    elif query.period == "ytd":
        start, end = as_of.replace(month=1, day=1), as_of
    elif query.period in {"1y", "5y"}:
        years = 1 if query.period == "1y" else 5
        start = (pd.Timestamp(as_of) - pd.DateOffset(years=years)).date()
        end = as_of
    else:
        if query.start_date is None or query.end_date is None:  # pragma: no cover
            raise AssertionError("validated custom dates are unavailable")
        start, end = query.start_date, query.end_date
    return tuple(value for value in actual if start <= value <= end)


def _natural_tenor_key(value: str) -> tuple[object, ...]:
    text = value.strip().casefold()
    special = {"spot": 0, "on": 1, "tn": 2, "sn": 3}
    if text in special:
        return (0, special[text], text)
    matched = _TENOR_PATTERN.fullmatch(text)
    if matched:
        amount = float(matched.group(1))
        multiplier = {"d": 1.0, "w": 7.0, "m": 30.0, "y": 365.0}[
            matched.group(2).casefold()
        ]
        return (1, amount * multiplier, text)
    parts = tuple(
        (0, int(part)) if part.isdigit() else (1, part)
        for part in _NATURAL_PART.split(text)
        if part
    )
    return (2, parts, text)


def _canonical_axis_order(frame: pd.DataFrame, axis: AxisSpec) -> HistoryAxisOrder:
    if frame.empty:
        return HistoryAxisOrder(axis.column, axis.order_column, (), (), ORDERED)
    missing = [
        column for column in (axis.column, axis.order_column) if column not in frame
    ]
    if missing:
        raise HistoryValidationError(
            f"history rows are missing ProductSpec axis columns: {missing}"
        )
    labels = frame[axis.column]
    invalid_labels = labels.isna() | ~labels.map(lambda value: isinstance(value, str))
    invalid_labels |= labels.astype("string").str.strip().eq("")
    if invalid_labels.any():
        rows = frame.index[invalid_labels].tolist()[:5]
        raise HistoryValidationError(
            f"history axis {axis.column!r} contains blank/non-text labels at rows {rows}"
        )
    clean_labels = labels.astype(str).str.strip()
    raw_order = frame[axis.order_column]
    blank = raw_order.isna() | raw_order.astype("string").str.strip().eq("")
    boolean = raw_order.map(lambda value: isinstance(value, (bool, np.bool_)))
    numeric = pd.to_numeric(raw_order, errors="coerce")
    invalid = boolean | (~blank & numeric.isna())
    invalid |= numeric.notna() & (
        ~np.isfinite(numeric) | numeric.lt(0) | numeric.mod(1).ne(0)
    )
    if invalid.any():
        rows = frame.index[invalid].tolist()[:5]
        raise HistoryValidationError(
            f"{axis.order_column!r} must contain non-negative finite integer ranks "
            f"or missing values; invalid rows {rows}"
        )
    authority = pd.DataFrame({"label": clean_labels, "rank": numeric})
    conflicts = authority.dropna(subset=["rank"]).groupby("label")["rank"].nunique()
    if conflicts.gt(1).any():
        raise HistoryValidationError(
            f"history axis {axis.column!r} maps one label to conflicting ranks"
        )
    ranked = authority.dropna(subset=["rank"]).drop_duplicates()
    collisions = ranked.groupby("rank")["label"].nunique()
    if collisions.gt(1).any():
        raise HistoryValidationError(
            f"history axis {axis.column!r} maps multiple labels to one rank"
        )
    unique_labels = tuple(clean_labels.drop_duplicates().tolist())
    rank_by_label = ranked.set_index("label")["rank"].to_dict()
    if not rank_by_label:
        ordered_labels = tuple(sorted(unique_labels, key=_natural_tenor_key))
        return HistoryAxisOrder(
            axis.column,
            axis.order_column,
            ordered_labels,
            tuple(None for _label in ordered_labels),
            ORDER_AMBIGUOUS,
        )
    unranked = sorted(set(unique_labels) - set(rank_by_label))
    if unranked:
        raise HistoryValidationError(
            f"history axis {axis.column!r} is only partially ranked; "
            f"unranked labels={unranked}"
        )
    ordered_pairs = sorted(
        ((label, int(rank_by_label[label])) for label in unique_labels),
        key=lambda item: (item[1], item[0].casefold()),
    )
    return HistoryAxisOrder(
        axis.column,
        axis.order_column,
        tuple(label for label, _rank in ordered_pairs),
        tuple(rank for _label, rank in ordered_pairs),
        ORDERED,
    )


def _apply_risk_filters(
    frame: pd.DataFrame, view: RiskFilterView | None
) -> pd.DataFrame:
    if view is None or not view.filters or frame.empty:
        return frame.copy(deep=True)
    keep = pd.Series(True, index=frame.index)
    for column, selected in view.filters:
        if column not in frame:
            raise HistoryValidationError(
                f"historical Risk rows are missing filter column {column!r}"
            )
        matches = frame[column].isin(selected)
        keep &= ~matches if view.exclude_selected and column != "Split" else matches
    return frame.loc[keep].copy(deep=True)


def _numeric_metric(frame: pd.DataFrame, column: str) -> pd.DataFrame:
    if column not in frame:
        raise HistoryValidationError(f"history rows are missing metric {column!r}")
    result = frame.copy(deep=True)
    values = result[column]
    boolean = values.map(lambda value: isinstance(value, (bool, np.bool_)))
    blank = values.isna() | values.astype("string").str.strip().eq("")
    numeric = pd.to_numeric(values, errors="coerce")
    invalid = boolean | (~blank & numeric.isna())
    invalid |= numeric.notna() & ~np.isfinite(numeric)
    if invalid.any():
        rows = result.index[invalid].tolist()[:5]
        raise HistoryValidationError(
            f"history metric {column!r} contains invalid values at rows {rows}"
        )
    result[column] = numeric.astype(float)
    return result


def _canonical_values(
    frame: pd.DataFrame,
    *,
    kind: HistoryKind,
    date_column: str,
    dates: tuple[date, ...],
    metric_column: str,
    ordering: HistoryOrdering,
) -> pd.DataFrame:
    axes = [axis.column for axis in ordering.axes]
    columns = [date_column]
    for axis in ordering.axes:
        columns.extend((axis.column, axis.order_column))
    columns.append(metric_column)
    if not dates:
        return pd.DataFrame(columns=columns)
    work = frame.copy(deep=True)
    work[date_column] = work[date_column].map(
        lambda value: _date(value, label=date_column).isoformat()
    )
    keys = [date_column, *axes]
    if kind == "risk":
        grouped = work.groupby(
            keys,
            as_index=False,
            sort=False,
            observed=True,
            dropna=False,
        )[metric_column].sum(min_count=1)
    else:
        duplicates = work.duplicated(keys, keep=False)
        if duplicates.any():
            raise HistoryValidationError(
                "Market history contains duplicate exact daily quote cells"
            )
        grouped = work.loc[:, [*keys, metric_column]]
    date_labels = tuple(value.isoformat() for value in dates)
    if axes:
        levels: list[Sequence[str]] = [date_labels]
        levels.extend(axis.labels for axis in ordering.axes)
        complete_index = pd.MultiIndex.from_product(levels, names=keys)
        values = grouped.set_index(keys).reindex(complete_index).reset_index()
    else:
        complete_index = pd.Index(date_labels, name=date_column)
        values = grouped.set_index(date_column).reindex(complete_index).reset_index()
    for axis in ordering.axes:
        rank_by_label = dict(zip(axis.labels, axis.ranks, strict=True))
        values[axis.order_column] = (
            values[axis.column].map(rank_by_label).astype("Int64")
        )
    return values.loc[:, columns].reset_index(drop=True)


class ArchiveHistoryRepository:
    """Lazy bounded adapter over atomic flat archive leaves."""

    _cache_clear_lock: ClassVar[RLock] = RLock()
    _cleared_reset_generations: ClassVar[dict[Path, int]] = {}

    def __init__(
        self,
        root: str | Path,
        *,
        max_rows: int = 100_000,
        max_dates: int = 2_000,
        max_raw_rows: int = HISTORY_RAW_ROW_BUDGET,
        max_cells: int = HISTORY_CANONICAL_CELL_BUDGET,
    ) -> None:
        self._root = Path(root).expanduser()
        self._max_rows = _positive_int(max_rows, label="max_rows")
        self._max_dates = _positive_int(max_dates, label="max_dates")
        self._max_raw_rows = _positive_int(max_raw_rows, label="max_raw_rows")
        self._max_cells = _positive_int(max_cells, label="max_cells")

    @property
    def root(self) -> Path:
        return self._root

    def generation(self) -> str:
        """Fingerprint immutable archive metadata without loading CSV frames."""

        root = self._root.resolve()
        if not root.exists():
            payload: object = {"root": str(root), "state": "missing"}
        elif not root.is_dir():
            raise HistoryValidationError(f"history root must be a directory: {root}")
        else:
            leaves: list[tuple[str, tuple[tuple[str, int, int], ...]]] = []
            for leaf in sorted(root.iterdir(), key=lambda path: path.name):
                if not leaf.is_dir() or not _DATE_LEAF.fullmatch(leaf.name):
                    continue
                files = tuple(
                    (name, path.stat().st_size, path.stat().st_mtime_ns)
                    for name in ALL_ARCHIVE_FILE_NAMES
                    if (path := leaf / name).is_file()
                )
                leaves.append((leaf.name, files))
            payload = {"root": str(root), "leaves": leaves}
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()

    fingerprint = generation

    def clear_reconstructable_cache(self) -> None:
        """Unconditionally clear process-local archive caches."""

        with type(self)._cache_clear_lock:
            clear_archive_caches()

    def clear_for_reset_generation(self, reset_generation: object) -> bool:
        """Clear shared caches once when a later reset generation is observed."""

        selected = _nonnegative_int(
            reset_generation,
            label="reset_generation",
        )
        if selected == 0:
            return False
        repository_type = type(self)
        root = self._root.resolve()
        with repository_type._cache_clear_lock:
            previous = repository_type._cleared_reset_generations.get(root, 0)
            if selected <= previous:
                return False
            clear_archive_caches()
            repository_type._cleared_reset_generations[root] = selected
            return True

    def read(self, query: HistoryQuery) -> HistoryBundle:
        if not isinstance(query, HistoryQuery):
            raise HistoryValidationError("query must be a HistoryQuery")
        handoff = query.handoff
        identity = handoff.identity
        if handoff.kind == "risk":
            source_frames = [
                load_risk_history_for_identity(
                    self._root,
                    source_type,
                    identity.risk_type,
                    identity.risk_greek,
                    identity.underlying,
                    identity_mode=identity.identity_mode,
                    max_rows=self._max_rows,
                )
                for source_type in identity.source_types
            ]
            populated = [frame for frame in source_frames if not frame.empty]
            raw = (
                pd.concat(populated, ignore_index=True, sort=False)
                if populated
                else source_frames[0].iloc[0:0].copy()
            )
            if len(raw) > self._max_rows:
                raise HistoryValidationError(
                    f"historical Risk query exceeds its {self._max_rows}-row bound"
                )
            raw = _apply_risk_filters(raw, handoff.filter_view)
            date_column = RISK_DATE
        else:
            raw = load_full_market_history_for_identity(
                self._root,
                identity.source_type,
                identity.risk_type,
                identity.risk_greek,
                identity.underlying,
                max_rows=self._max_rows,
            )
            date_column = MARKET_DATE
        raw = _numeric_metric(raw, handoff.metric_column) if not raw.empty else raw
        if raw.empty:
            available_dates: tuple[date, ...] = ()
        else:
            if date_column not in raw:
                raise HistoryValidationError(
                    f"history rows are missing date column {date_column!r}"
                )
            available_dates = tuple(
                sorted({_date(value, label=date_column) for value in raw[date_column]})
            )
        dates = resolve_actual_period_dates(available_dates, query)
        if len(dates) > self._max_dates:
            raise HistoryValidationError(
                f"history query exceeds its {self._max_dates}-date bound"
            )
        selected_date_values = set(dates)
        if raw.empty or not dates:
            period_rows = raw.iloc[0:0].copy()
        else:
            parsed_dates = raw[date_column].map(
                lambda value: _date(value, label=date_column)
            )
            period_rows = raw.loc[parsed_dates.isin(selected_date_values)].copy()
        if len(period_rows) > self._max_raw_rows:
            suggestion = (
                "Choose a narrower period or more selective Risk filters."
                if handoff.kind == "risk"
                else "Choose a narrower period."
            )
            raise HistoryValidationError(
                f"Raw history has {len(period_rows):,} exact rows and exceeds the "
                f"{self._max_raw_rows:,}-row browser budget. {suggestion}"
            )
        axis_orders = tuple(
            _canonical_axis_order(period_rows, axis) for axis in identity.axes
        )
        ordering = HistoryOrdering(
            axes=axis_orders,
            status=(
                ORDER_AMBIGUOUS
                if any(axis.status == ORDER_AMBIGUOUS for axis in axis_orders)
                else ORDERED
            ),
        )
        values = _canonical_values(
            period_rows,
            kind=handoff.kind,
            date_column=date_column,
            dates=dates,
            metric_column=handoff.metric_column,
            ordering=ordering,
        )
        if len(values) > self._max_cells:
            raise HistoryValidationError(
                f"Canonical history has {len(values):,} cells and exceeds the "
                f"{self._max_cells:,}-cell browser budget. Choose a narrower period "
                "or exact identity."
            )
        selected_date = dates[-1] if dates else None
        if selected_date is None or period_rows.empty:
            selected_rows = period_rows.iloc[0:0].copy()
        else:
            selected_rows = period_rows.loc[
                period_rows[date_column]
                .map(lambda value: _date(value, label=date_column))
                .eq(selected_date)
            ].copy()
        generation = self.generation()
        return HistoryBundle(
            query=query,
            date_column=date_column,
            dates=dates,
            resolved_start=(dates[0] if dates else None),
            resolved_end=(dates[-1] if dates else None),
            selected_date=selected_date,
            metric_column=handoff.metric_column,
            ordering=ordering,
            values=values,
            selected_rows=selected_rows.reset_index(drop=True),
            raw_rows=period_rows.reset_index(drop=True),
            generation=generation,
        )


__all__ = [
    "HISTORY_CANONICAL_CELL_BUDGET",
    "HISTORY_HANDOFF_SCHEMA_VERSION",
    "HISTORY_PERIODS",
    "HISTORY_RAW_ROW_BUDGET",
    "MARKET_METRICS",
    "ORDER_AMBIGUOUS",
    "ORDERED",
    "RISK_METRICS",
    "ArchiveHistoryRepository",
    "HistoryAxisOrder",
    "HistoryBundle",
    "HistoryHandoff",
    "HistoryIdentity",
    "HistoryOrdering",
    "HistoryQuery",
    "HistoryValidationError",
    "RiskFilterView",
    "resolve_actual_period_dates",
]
