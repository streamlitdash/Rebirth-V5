"""Regression tests for recovered references kept with their V4 owners."""

from __future__ import annotations

from pathlib import Path

from rebirth.domain.calculations import risk_date_for
from rebirth.domain.products import MMM_FILE, PRODUCT_SPECS


PROJECT = Path(__file__).resolve().parents[1]
PIPELINE_FILES = (
    PROJECT / "rebirth" / "domain" / "products.py",
    PROJECT / "rebirth" / "domain" / "calculations.py",
)


def test_recovered_pipeline_contracts_are_inline_and_comment_only() -> None:
    text = "\n".join(path.read_text(encoding="utf-8") for path in PIPELINE_FILES)

    for marker in (
        "RECOVERED ORIGINAL RISK-CHECKER FIELD (COMMENTED OUT)",
        '# MRX_FILE = "MRX File"',
        "RECOVERED ORIGINAL FORMULA NAMES (COMMENTED OUT)",
        '"minusabsolute"',
        '"percentage_vega"',
        "RECOVERED ORIGINAL PRODUCT METADATA (COMMENTED OUT)",
        '"irdelta", "ir/delta", "IR", "Delta", (SWAP_AXIS,), "bp", "minusabsolute"',
        "RECOVERED ORIGINAL AGE RULE (COMMENTED OUT)",
        "#     selected_age -= 1",
    ):
        assert marker in text

    assert not list((PROJECT / "core").glob("*.py"))


def test_active_pipeline_remains_on_validated_csv_compatible_contract() -> None:
    assert MMM_FILE == "MMMFile"
    assert PRODUCT_SPECS["irdelta"].pl_formula == "absolute"
    assert PRODUCT_SPECS["irdeltavega"].pl_formula == "percentage"
    assert PRODUCT_SPECS["irgamma"].gamma_move_scale == 10_000.0
    assert PRODUCT_SPECS["irgamma"].gamma_risk_step == 10.0
    assert "commodelta" in PRODUCT_SPECS
    assert "commoddelta" not in PRODUCT_SPECS

    assert risk_date_for("2026-08-14", 1).isoformat() == "2026-08-13T00:00:00"
