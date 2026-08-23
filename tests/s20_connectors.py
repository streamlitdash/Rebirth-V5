"""Connector-boundary clarity and fixture isolation tests."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from rebirth.adapters.s04_credit import build_credit_adapter
from rebirth.adapters.s03_fx import build_fx_adapters
from rebirth.adapters.s02_ir import build_ir_adapters
from rebirth.services import s05_sources as sources


PROJECT = Path(__file__).resolve().parents[1]


def test_connector_modules_contain_only_active_contracts() -> None:
    paths = [
        PROJECT / "rebirth" / "adapters" / name
        for name in (
            "s01_common.py",
            "s02_ir.py",
            "s03_fx.py",
            "s04_credit.py",
        )
    ]
    for path in paths:
        text = path.read_text(encoding="utf-8")
        assert text.count("from __future__ import annotations") == 1
        assert "COMMENTED OUT" not in text
        assert "SWITCH TO REAL" not in text
        compile(text, str(path), "exec")
    assert build_credit_adapter
    assert build_fx_adapters
    assert build_ir_adapters


def test_site_source_boundary_has_no_dead_recovered_implementation() -> None:
    path = PROJECT / "rebirth" / "services" / "s05_sources.py"
    text = path.read_text(encoding="utf-8")
    for stale_marker in (
        "=== REAL PRODUCT IMPORTS",
        "=== REAL RISK CHECKER",
        "=== REAL PORTFOLIO MAPPING",
        "=== REAL PRODUCT REGISTRATION",
        "COMMENTED OUT",
    ):
        assert stale_marker not in text
    for public_function in (
        "def get_risk_checker(",
        "def get_risk(",
        "def get_market_open(",
        "def get_market_status(",
        "def get_portfolio_config(",
        "def get_product_connector_adapters(",
    ):
        assert public_function in text
    assert not any((PROJECT / "rebirth" / "services" / "_disabled").glob("**/*"))


def test_active_product_registration_reads_the_fake_csv_boundary() -> None:
    adapter = sources.get_product_connector_adapters()["ir/delta"]

    assert adapter.risk.__module__ == "rebirth.services.s05_sources"
    assert adapter.market_open.__module__ == "rebirth.services.s05_sources"
    assert adapter.market_status.__module__ == "rebirth.services.s05_sources"

    risk = adapter.risk(pd.Timestamp("2026-08-14"))
    assert not risk.empty
    assert risk["Underlying"].str.contains("FAKE_REPLACE_ME", regex=False).all()
    assert risk["Portfolio"].str.contains("FAKE_REPLACE_ME", regex=False).all()
