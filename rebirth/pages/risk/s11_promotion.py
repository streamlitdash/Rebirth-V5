"""Explicit, revision-bound promotion generations for the V4 Risk page."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Final, Literal
from uuid import uuid4

import pandas as pd
from dash import dcc, html

from rebirth.domain.s11_riskviews import RISK_VIEW_DIMENSIONS
from rebirth.ui.s02_aggregation import recompute_filtered_promotion
from rebirth.ui.s01_constants import FILTER_COLUMNS


PROMOTION_GENERATION_STORE_ID: Final = "promotion-generation-store"
PROMOTION_RECALCULATE_ID: Final = "promotion-recalculate-current-view"
PROMOTION_RESET_ID: Final = "promotion-reset-baseline"
PROMOTION_STATUS_ID: Final = "promotion-generation-status"
PROMOTION_SCHEMA_VERSION: Final = 2
PROMOTION_KEYS: Final = ("risk type", "risk greek", "reported underlying")
PROMOTION_CLASSIFICATION_COLUMNS: Final = (
    "display bucket",
    "promotion reason",
    "promotion score",
)
PROMOTION_VALUE_COLUMNS: Final = (
    "risk",
    "drisk",
    "pl",
    "risk threshold",
    "drisk threshold",
    "pl threshold",
)
_MAX_PROMOTION_ROWS: Final = 20_000


def _text(value: object, *, label: str, optional: bool = False) -> str | None:
    if value is None and optional:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be nonblank text")
    return value.strip()


def _selection(value: object, *, label: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise ValueError(f"{label} must be a sequence")
    selected = sorted({_text(item, label=label) for item in value})
    return tuple(item for item in selected if item is not None)


def _number(value: object, *, label: str, optional: bool = False) -> float | None:
    if value is None or pd.isna(value):
        if optional:
            return None
        raise ValueError(f"{label} must be numeric")
    if isinstance(value, bool):
        raise ValueError(f"{label} must be numeric")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{label} must be finite")
    return number


@dataclass(frozen=True)
class PromotionBasis:
    """Exact source-row scope used by one manual promotion calculation."""

    revision: int
    risk_type: str | None
    ir_family: str | None
    splits: tuple[str, ...]
    filters: tuple[tuple[str, tuple[str, ...]], ...]
    local_filters: tuple[tuple[str, tuple[str, ...]], ...]
    exclude_selected: bool

    @classmethod
    def build(
        cls,
        revision: object,
        *,
        risk_type: object = None,
        ir_family: object = None,
        splits: Sequence[str] | None = None,
        filters: Mapping[str, Sequence[str] | None],
        local_filters: Mapping[str, Sequence[str] | None] | None = None,
        exclude_selected: object = False,
    ) -> PromotionBasis:
        if isinstance(revision, bool) or int(revision) < 0:
            raise ValueError("Promotion revision must be a non-negative integer")
        if not isinstance(filters, Mapping) or set(filters) != set(FILTER_COLUMNS):
            raise ValueError("Promotion filters must use the governed Risk fields")
        normalized_risk_type = _text(risk_type, label="Risk Type", optional=True)
        normalized_family = _text(ir_family, label="IR family", optional=True)
        if normalized_risk_type != "IR":
            normalized_family = None
        if not isinstance(exclude_selected, bool):
            raise ValueError("Promotion include/exclude mode must be boolean")
        custom_filters = dict(local_filters or {})
        unknown_local = sorted(set(custom_filters) - set(RISK_VIEW_DIMENSIONS))
        if unknown_local:
            raise ValueError(
                "Promotion local filters contain unsupported fields: "
                + ", ".join(unknown_local)
            )
        return cls(
            revision=int(revision),
            risk_type=normalized_risk_type,
            ir_family=normalized_family,
            splits=_selection(splits, label="Promotion splits"),
            filters=tuple(
                (
                    key,
                    _selection(filters[key], label=f"Promotion filter {key!r}"),
                )
                for key in FILTER_COLUMNS
            ),
            local_filters=tuple(
                (
                    key,
                    _selection(
                        custom_filters[key], label=f"Promotion local filter {key!r}"
                    ),
                )
                for key in RISK_VIEW_DIMENSIONS
                if key in custom_filters and custom_filters[key]
            ),
            exclude_selected=exclude_selected,
        )

    @classmethod
    def from_dict(cls, value: object) -> PromotionBasis:
        if not isinstance(value, Mapping) or set(value) != {
            "revision",
            "risk_type",
            "ir_family",
            "splits",
            "filters",
            "local_filters",
            "exclude_selected",
        }:
            raise ValueError("Promotion basis has unexpected fields")
        return cls.build(
            value["revision"],
            risk_type=value["risk_type"],
            ir_family=value["ir_family"],
            splits=value["splits"],
            filters=value["filters"],
            local_filters=value["local_filters"],
            exclude_selected=value["exclude_selected"],
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "revision": self.revision,
            "risk_type": self.risk_type,
            "ir_family": self.ir_family,
            "splits": list(self.splits),
            "filters": {key: list(values) for key, values in self.filters},
            "local_filters": {key: list(values) for key, values in self.local_filters},
            "exclude_selected": self.exclude_selected,
        }


@dataclass(frozen=True)
class PromotionRow:
    """One flat governed exposure in a promotion generation."""

    risk_type: str
    risk_greek: str
    reported_underlying: str
    risk: float | None
    drisk: float | None
    pl: float | None
    risk_threshold: float
    drisk_threshold: float
    pl_threshold: float
    display_bucket: str
    reason: str
    score: float

    @classmethod
    def from_dict(cls, value: object) -> PromotionRow:
        fields = {
            "risk_type",
            "risk_greek",
            "reported_underlying",
            "risk",
            "drisk",
            "pl",
            "risk_threshold",
            "drisk_threshold",
            "pl_threshold",
            "display_bucket",
            "reason",
            "score",
        }
        if not isinstance(value, Mapping) or set(value) != fields:
            raise ValueError("Promotion row has unexpected fields")
        reason = value["reason"]
        if not isinstance(reason, str):
            raise ValueError("Promotion reason must be text")
        row = cls(
            risk_type=str(_text(value["risk_type"], label="Risk Type")),
            risk_greek=str(_text(value["risk_greek"], label="Risk Greek")),
            reported_underlying=str(
                _text(value["reported_underlying"], label="Reported Underlying")
            ),
            risk=_number(value["risk"], label="Risk", optional=True),
            drisk=_number(value["drisk"], label="dRisk", optional=True),
            pl=_number(value["pl"], label="P&L", optional=True),
            risk_threshold=float(
                _number(value["risk_threshold"], label="Risk threshold")
            ),
            drisk_threshold=float(
                _number(value["drisk_threshold"], label="dRisk threshold")
            ),
            pl_threshold=float(_number(value["pl_threshold"], label="P&L threshold")),
            display_bucket=str(_text(value["display_bucket"], label="Display Bucket")),
            reason=reason.strip(),
            score=float(_number(value["score"], label="Promotion score")),
        )
        if min(row.risk_threshold, row.drisk_threshold, row.pl_threshold) <= 0:
            raise ValueError("Promotion thresholds must be positive")
        return row

    def to_dict(self) -> dict[str, object]:
        return dict(self.__dict__)


@dataclass(frozen=True)
class PromotionGeneration:
    """Immutable baseline marker or explicit current-view result."""

    identifier: str
    kind: Literal["baseline", "current-view"]
    revision: int
    created_at: str
    basis: PromotionBasis | None
    rows: tuple[PromotionRow, ...]

    @classmethod
    def from_store(cls, value: object) -> PromotionGeneration:
        if not isinstance(value, Mapping) or set(value) != {
            "version",
            "id",
            "kind",
            "revision",
            "created_at",
            "basis",
        }:
            raise ValueError("Promotion generation has unexpected fields")
        if value["version"] != PROMOTION_SCHEMA_VERSION:
            raise ValueError("Promotion generation version is unsupported")
        identifier = _text(value["id"], label="Promotion generation ID")
        kind = value["kind"]
        if kind not in {"baseline", "current-view"}:
            raise ValueError("Promotion generation kind is invalid")
        revision = value["revision"]
        if isinstance(revision, bool) or int(revision) < 0:
            raise ValueError("Promotion generation revision is invalid")
        created_at = _text(value["created_at"], label="Promotion creation time")
        try:
            datetime.fromisoformat(str(created_at).replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("Promotion creation time is invalid") from exc
        basis = (
            PromotionBasis.from_dict(value["basis"])
            if value["basis"] is not None
            else None
        )
        if kind == "baseline" and basis is not None:
            raise ValueError("Baseline promotion must not contain an override")
        if kind == "current-view" and (
            basis is None or basis.revision != int(revision)
        ):
            raise ValueError("Current-view promotion basis is inconsistent")
        return cls(
            identifier=str(identifier),
            kind=kind,
            revision=int(revision),
            created_at=str(created_at),
            basis=basis,
            rows=(),
        )

    def to_store(self) -> dict[str, object]:
        return {
            "version": PROMOTION_SCHEMA_VERSION,
            "id": self.identifier,
            "kind": self.kind,
            "revision": self.revision,
            "created_at": self.created_at,
            "basis": self.basis.to_dict() if self.basis is not None else None,
        }


def baseline_promotion_generation(revision: object) -> PromotionGeneration:
    """Return a small marker selecting pipeline-owned promotion columns."""

    if isinstance(revision, bool) or int(revision) < 0:
        raise ValueError("Promotion revision must be a non-negative integer")
    return PromotionGeneration(
        identifier=f"baseline:{int(revision)}",
        kind="baseline",
        revision=int(revision),
        created_at=datetime.now(timezone.utc).isoformat(),
        basis=None,
        rows=(),
    )


def _summary(classified: pd.DataFrame) -> pd.DataFrame:
    required = set(
        (*PROMOTION_KEYS, *PROMOTION_VALUE_COLUMNS, *PROMOTION_CLASSIFICATION_COLUMNS)
    )
    missing = sorted(required - set(classified))
    if missing:
        raise ValueError("Promotion source is missing columns: " + ", ".join(missing))
    if classified.empty:
        return classified.reindex(
            columns=[
                *PROMOTION_KEYS,
                *PROMOTION_VALUE_COLUMNS,
                *PROMOTION_CLASSIFICATION_COLUMNS,
            ]
        )
    consistency = classified.groupby(list(PROMOTION_KEYS), dropna=False)[
        list(PROMOTION_CLASSIFICATION_COLUMNS)
    ].nunique(dropna=False)
    if consistency.gt(1).any().any():
        raise ValueError("Promotion source has inconsistent baseline classifications")
    return (
        classified.groupby(list(PROMOTION_KEYS), as_index=False, dropna=False)
        .agg(
            {
                "risk": lambda values: values.sum(min_count=1),
                "drisk": lambda values: values.sum(min_count=1),
                "pl": lambda values: values.sum(min_count=1),
                "risk threshold": "first",
                "drisk threshold": "first",
                "pl threshold": "first",
                "display bucket": "first",
                "promotion reason": "first",
                "promotion score": "first",
            }
        )
        .sort_values(
            ["promotion score", "risk type", "risk greek", "reported underlying"],
            ascending=[False, True, True, True],
            kind="stable",
        )
        .reset_index(drop=True)
    )


def _rows_from_summary(summary: pd.DataFrame) -> tuple[PromotionRow, ...]:
    if len(summary) > _MAX_PROMOTION_ROWS:
        raise ValueError("Promotion generation exceeds the bounded row limit")
    return tuple(
        PromotionRow.from_dict(
            {
                "risk_type": row["risk type"],
                "risk_greek": row["risk greek"],
                "reported_underlying": row["reported underlying"],
                "risk": row["risk"],
                "drisk": row["drisk"],
                "pl": row["pl"],
                "risk_threshold": row["risk threshold"],
                "drisk_threshold": row["drisk threshold"],
                "pl_threshold": row["pl threshold"],
                "display_bucket": row["display bucket"],
                "reason": row["promotion reason"],
                "score": row["promotion score"],
            }
        )
        for row in summary.to_dict("records")
    )


def calculate_current_view_promotion(
    frame: pd.DataFrame,
    basis: PromotionBasis,
    *,
    identifier: str | None = None,
    created_at: datetime | None = None,
) -> PromotionGeneration:
    """Calculate exactly once from an already-filtered current page scope."""

    if not isinstance(frame, pd.DataFrame):
        raise TypeError("Promotion source must be a pandas DataFrame")
    classified = recompute_filtered_promotion(frame)
    timestamp = created_at or datetime.now(timezone.utc)
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    generation = PromotionGeneration(
        identifier=identifier or uuid4().hex,
        kind="current-view",
        revision=basis.revision,
        created_at=timestamp.isoformat(),
        basis=basis,
        rows=_rows_from_summary(_summary(classified)),
    )
    identities = [
        (row.risk_type, row.risk_greek, row.reported_underlying)
        for row in generation.rows
    ]
    if len(identities) != len(set(identities)):
        raise ValueError("Promotion generation contains duplicate identities")
    return generation


def promotion_basis_is_stale(
    generation: PromotionGeneration,
    current_basis: PromotionBasis,
) -> bool:
    return generation.kind == "current-view" and generation.basis != current_basis


def apply_promotion_local_filters(
    frame: pd.DataFrame,
    filters: Mapping[str, Sequence[str] | None] | None,
) -> pd.DataFrame:
    """Apply validated Custom-view filters before an explicit recalculation."""

    result = frame
    for field, selected in (filters or {}).items():
        values = tuple(selected or ())
        if not values:
            continue
        if field not in result:
            raise ValueError(f"Promotion source is missing local filter {field!r}")
        wanted = {str(value).strip().casefold() for value in values}
        normalized = result[field].astype("string").str.strip().str.casefold()
        result = result.loc[normalized.isin(wanted).fillna(False)]
    return result


def promotion_basis_summary(basis: PromotionBasis) -> str:
    """Describe the immutable calculation scope in business language."""

    parts = [basis.risk_type or "All risk types"]
    if basis.risk_type == "IR" and basis.ir_family:
        parts.append(str(basis.ir_family).upper())
    if basis.splits:
        parts.append("Split: " + ", ".join(basis.splits))
    for field, selected in (*basis.filters, *basis.local_filters):
        if not selected:
            continue
        label = field.replace("signoffgroup", "sign-off group").title()
        values = ", ".join(selected[:3])
        if len(selected) > 3:
            values += f" +{len(selected) - 3}"
        parts.append(f"{label}: {values}")
    if basis.exclude_selected:
        parts.append("excluding selected shared filters")
    return "Scope: " + " · ".join(parts)


def apply_promotion_generation(
    frame: pd.DataFrame,
    generation: PromotionGeneration | Mapping[str, object] | None,
    *,
    revision: int,
) -> pd.DataFrame:
    """Apply a valid manual generation, otherwise retain pipeline baseline."""

    if generation is None:
        return frame.copy()
    from_browser_metadata = isinstance(generation, Mapping)
    parsed = (
        generation
        if isinstance(generation, PromotionGeneration)
        else PromotionGeneration.from_store(generation)
    )
    if parsed.kind == "baseline" or parsed.revision != int(revision):
        return frame.copy()
    if from_browser_metadata:
        raise ValueError("Current-view promotion rows must be resolved server-side")
    classification = pd.DataFrame(
        [
            {
                "risk type": row.risk_type,
                "risk greek": row.risk_greek,
                "reported underlying": row.reported_underlying,
                "display bucket": row.display_bucket,
                "promotion reason": row.reason,
                "promotion score": row.score,
            }
            for row in parsed.rows
        ]
    )
    base = frame.drop(columns=list(PROMOTION_CLASSIFICATION_COLUMNS), errors="ignore")
    if classification.empty:
        result = base.copy()
        result["display bucket"] = "Other"
        result["promotion reason"] = ""
        result["promotion score"] = 0.0
        return result
    result = base.merge(
        classification,
        on=list(PROMOTION_KEYS),
        how="left",
        validate="many_to_one",
    )
    result["display bucket"] = result["display bucket"].fillna("Other")
    result["promotion reason"] = result["promotion reason"].fillna("")
    result["promotion score"] = result["promotion score"].fillna(0.0)
    return result


def promotion_table(
    frame: pd.DataFrame,
    generation: PromotionGeneration | Mapping[str, object] | None,
    *,
    revision: int,
) -> pd.DataFrame:
    """Return the active flat promotion table without recalculating it."""

    parsed = None
    if generation is not None:
        parsed = (
            generation
            if isinstance(generation, PromotionGeneration)
            else PromotionGeneration.from_store(generation)
        )
    if (
        parsed is not None
        and parsed.kind == "current-view"
        and parsed.revision == revision
    ):
        records = [row.to_dict() for row in parsed.rows]
        return pd.DataFrame.from_records(records)
    return pd.DataFrame.from_records(
        [row.to_dict() for row in _rows_from_summary(_summary(frame))]
    )


def build_promotion_generation_controls(revision: int) -> html.Div:
    """Build the small explicit recalculation control owned by Risk Explorer."""

    baseline = baseline_promotion_generation(revision)
    return html.Div(
        [
            dcc.Store(id=PROMOTION_GENERATION_STORE_ID, data=baseline.to_store()),
            html.Button(
                "Recalculate visible view",
                id=PROMOTION_RECALCULATE_ID,
                n_clicks=0,
                type="button",
                className="refresh-button",
                title="Recalculate promotion from the currently visible Risk rows",
                **{"aria-busy": "false"},
            ),
            html.Button(
                "Reset to baseline",
                id=PROMOTION_RESET_ID,
                n_clicks=0,
                type="button",
                disabled=True,
                className="refresh-button",
            ),
            html.Div(
                "Baseline promotion from the committed refresh is active.",
                id=PROMOTION_STATUS_ID,
                className="filter-note",
                role="status",
                **{"aria-live": "polite"},
            ),
            html.Div(
                "Scope: committed Activities 1–3 policy",
                id="promotion-generation-scope",
                className="promotion-generation-scope",
            ),
        ],
        className="promotion-generation-controls",
    )


__all__ = [
    "PROMOTION_GENERATION_STORE_ID",
    "PROMOTION_RECALCULATE_ID",
    "PROMOTION_RESET_ID",
    "PROMOTION_STATUS_ID",
    "PromotionBasis",
    "PromotionGeneration",
    "PromotionRow",
    "apply_promotion_local_filters",
    "apply_promotion_generation",
    "baseline_promotion_generation",
    "build_promotion_generation_controls",
    "calculate_current_view_promotion",
    "promotion_basis_is_stale",
    "promotion_basis_summary",
    "promotion_table",
]
