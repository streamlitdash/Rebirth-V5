"""Rebirth V4 Risk defaults, promotion generations, and Custom View contracts."""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
import pytest

from rebirth.domain.risk_views import (
    CROSS_PIVOT_SPEC,
    SPLITVA_PIVOT_SPEC,
    PivotSpec,
    RiskViewRepository,
)
from rebirth.pages.risk.filter_defaults import (
    DEFAULT_RISK_FILTER_LABEL,
    default_risk_filter_values,
    resolve_default_risk_activities,
)
from rebirth.pages.risk.promotion import (
    PromotionBasis,
    PromotionGeneration,
    apply_promotion_generation,
    baseline_promotion_generation,
    calculate_current_view_promotion,
    promotion_basis_is_stale,
)
from rebirth.ui.constants import FILTER_COLUMNS


def _filters(**updates: list[str]) -> dict[str, list[str]]:
    result = {key: [] for key in FILTER_COLUMNS}
    result.update(updates)
    return result


def _promotion_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "risk type": ["IR", "IR"],
            "risk greek": ["Delta", "Delta"],
            "reported underlying": ["USD-SOFR", "USD-SOFR"],
            "portfolio": ["BOOK-A", "BOOK-B"],
            "risk": [600.0, 600.0],
            "drisk": [0.0, 0.0],
            "pl": [0.0, 0.0],
            "risk threshold": [1_000.0, 1_000.0],
            "drisk threshold": [1_000.0, 1_000.0],
            "pl threshold": [1_000.0, 1_000.0],
            "display bucket": ["Other", "Other"],
            "promotion reason": ["", ""],
            "promotion score": [0.6, 0.6],
        }
    )


def test_default_risk_filter_resolves_current_and_legacy_fixture_names() -> None:
    resolved = resolve_default_risk_activities(
        [
            "FAKE_REPLACE_ME - Macro",
            "FAKE_REPLACE_ME - Credit",
            "FAKE_REPLACE_ME - Hedge",
            "Unrelated",
        ]
    )

    assert DEFAULT_RISK_FILTER_LABEL == "Default - Activities 1-3"
    assert resolved.activities == (
        "FAKE_REPLACE_ME - Macro",
        "FAKE_REPLACE_ME - Credit",
        "FAKE_REPLACE_ME - Hedge",
    )
    assert resolved.missing == ()
    values = default_risk_filter_values(
        pd.DataFrame({"activity": list(resolved.activities)})
    )
    assert values[0] == list(resolved.activities)
    assert all(value == [] for value in values[1:])


def test_manual_promotion_is_immutable_and_revision_bound() -> None:
    basis = PromotionBasis.build(
        7,
        risk_type="IR",
        ir_family="delta",
        splits=["Risk"],
        filters=_filters(),
    )
    generation = calculate_current_view_promotion(
        _promotion_frame(),
        basis,
        identifier="manual-test",
        created_at=datetime(2026, 8, 22, tzinfo=timezone.utc),
    )
    restored = PromotionGeneration.from_store(generation.to_store())

    assert restored.identifier == generation.identifier
    assert restored.basis == generation.basis
    assert restored.rows == ()
    assert "rows" not in generation.to_store()
    assert len(generation.rows) == 1
    assert generation.rows[0].reason == "Big Risk"
    assert generation.rows[0].score == pytest.approx(1.2)

    one_book = _promotion_frame().iloc[[0]].copy()
    active = apply_promotion_generation(one_book, generation, revision=7)
    stale_revision = apply_promotion_generation(one_book, generation, revision=8)
    baseline = apply_promotion_generation(
        one_book,
        baseline_promotion_generation(7),
        revision=7,
    )
    assert active["display bucket"].tolist() == ["USD-SOFR"]
    assert active["promotion reason"].tolist() == ["Big Risk"]
    assert stale_revision["display bucket"].tolist() == ["Other"]
    assert baseline["display bucket"].tolist() == ["Other"]

    changed_basis = PromotionBasis.build(
        7,
        risk_type="IR",
        ir_family="delta",
        splits=["Risk"],
        filters=_filters(portfolio=["BOOK-A"]),
    )
    assert promotion_basis_is_stale(generation, changed_basis)


def test_custom_risk_view_repository_is_separate_and_validated(tmp_path) -> None:
    repository = RiskViewRepository(tmp_path / "risk_views")
    cross = repository.clone_builtin("cross", "Morning Cross")
    split = repository.clone_builtin("splitva", "Desk SplitVA")

    assert cross.pivot == CROSS_PIVOT_SPEC
    assert split.pivot == SPLITVA_PIVOT_SPEC
    assert [view.name for view in repository.list()] == [
        "Desk SplitVA",
        "Morning Cross",
    ]

    edited_payload = CROSS_PIVOT_SPEC.to_dict()
    edited_payload["display"]["row_limit"] = 100
    edited = repository.update(cross.identifier, edited_payload)
    assert edited.pivot.row_limit == 100
    renamed = repository.rename(edited.identifier, "Afternoon Cross")
    assert renamed.name == "Afternoon Cross"
    assert repository.delete(split.identifier) == split
    assert [view.name for view in repository.list()] == ["Afternoon Cross"]

    invalid = CROSS_PIVOT_SPEC.to_dict()
    invalid["rows"] = ["financial frame"]
    with pytest.raises(ValueError, match="unsupported fields"):
        PivotSpec.from_dict(invalid)
