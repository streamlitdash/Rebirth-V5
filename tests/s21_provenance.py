"""Regression tests for the compact active product-pipeline contracts."""

from __future__ import annotations

from pathlib import Path

from cube.domain.s03_calculations import risk_date_for
from cube.domain.s02_products import MRX_FILE, PRODUCT_SPECS


PROJECT = Path(__file__).resolve().parents[1]
PIPELINE_FILES = (
    PROJECT / "cube" / "domain" / "s02_products.py",
    PROJECT / "cube" / "domain" / "s03_calculations.py",
)


def test_pipeline_contracts_have_no_retired_inline_implementations() -> None:
    text = "\n".join(path.read_text(encoding="utf-8") for path in PIPELINE_FILES)

    for marker in (
        "RECOVERED ORIGINAL",
        "COMMENTED OUT",
        "SWITCH TO THE RECOVERED",
        "minusabsolute",
        "percentage_vega",
    ):
        assert marker not in text

    for path in PIPELINE_FILES:
        compile(path.read_text(encoding="utf-8"), str(path), "exec")

    assert not list((PROJECT / "core").glob("*.py"))


def test_active_pipeline_remains_on_validated_csv_compatible_contract() -> None:
    assert MRX_FILE == "MRX File"
    assert PRODUCT_SPECS["irdelta"].pl_formula == "absolute"
    assert PRODUCT_SPECS["irdeltavega"].pl_formula == "percentage"
    assert PRODUCT_SPECS["irgamma"].gamma_move_scale == 10_000.0
    assert PRODUCT_SPECS["irgamma"].gamma_risk_step == 10.0
    assert "commodelta" in PRODUCT_SPECS
    assert "commoddelta" not in PRODUCT_SPECS

    assert risk_date_for("2026-08-14", 1).isoformat() == "2026-08-13T00:00:00"
