"""Small Data selections; current labels are cheap, archive indexing is lazy."""

from __future__ import annotations

import json
from dataclasses import replace

from cube.domain.s02_products import PRODUCT_SPECS_BY_SOURCE_TYPE
from cube.history import HistoryHandoff, HistoryIdentity, HistoryQuery
from cube.history.s01_models import _apply_risk_filters


def encode_choice(kind, value):
    return json.dumps([kind, value], ensure_ascii=False, separators=(",", ":"))


def describe(handoff):
    identity = handoff.identity
    return f"{identity.underlying} · {identity.risk_type} · {identity.risk_greek}"


class DataChoices:
    """Current text choices; archive choices use a separate lazy callback."""

    def __init__(self, manager, repository):
        self.manager = manager
        self.repository = repository

    def metadata(self, reset=0):
        try:
            revision = int(self.manager.health.revision) if self.manager else 0
            risk = list(self.manager.combine_udl_options()) if revision else []
            market = list(self.manager.market_udl_options()) if revision else []
        except RuntimeError:
            revision, risk, market = 0, [], []
        return {"revision": revision, "reset": int(reset or 0),
                "risk": risk, "market": market}

    def archive_metadata(self):
        catalog = self.repository.catalog()
        rows = [
            [f"{entry.kind.title()} history · {describe(entry.to_handoff())}",
             encode_choice("archive", entry.key)]
            for entry in catalog.entries
            if entry.kind == "market" or entry.identity.identity_mode == "reported"
        ]
        return {"generation": catalog.generation, "choices": rows}

    def resolve(self, token, reset=0):
        kind, value = json.loads(str(token))
        if kind == "archive":
            return self.repository.catalog().resolve(value).to_handoff(
                reset_generation=int(reset or 0))
        if kind == "handoff":
            return replace(HistoryHandoff.from_mapping(value),
                           reset_generation=int(reset or 0))
        if kind not in {"risk", "market"}:
            raise ValueError("Choose a listed Risk or Market identity.")
        resolved = self.manager.resolve_history_identity(
            kind, value, identity_mode="reported" if kind == "risk" else "underlying")
        return HistoryHandoff.from_resolved_identity(
            resolved, metric="risk" if kind == "risk" else "current",
            reset_generation=int(reset or 0))


def selection_for_handoff(handoff, manager, repository):
    """Keep reported Risk separate from its exact raw Market series."""
    if handoff.kind == "market":
        risk = replace(handoff, kind="risk", metric="risk")
        return {"risk": risk.to_mapping(), "markets": [handoff.to_mapping()],
                "label": describe(handoff)}
    markets = []
    _revision, rows = manager.read_data_history(handoff) if manager else (0, None)
    if rows is None or rows.empty:
        # This selected archive identity may no longer exist in current Risk.
        rows = repository.market_pairs(handoff)
    else:
        rows = _apply_risk_filters(rows, handoff.filter_view)
    if not rows.empty:
        pairs = rows[["Source Type", "Underlying"]].drop_duplicates()
        for source, underlying in pairs.itertuples(index=False, name=None):
            spec = PRODUCT_SPECS_BY_SOURCE_TYPE[source]
            market_identity = HistoryIdentity(
                source_types=(source,), risk_type=spec.risk_type,
                risk_greek=spec.risk_greek, underlying=underlying,
                identity_mode="underlying")
            market = replace(handoff, kind="market", identity=market_identity,
                             metric="current", filter_view=None)
            markets.append(market.to_mapping())
    return {"risk": handoff.to_mapping(), "markets": markets,
            "label": describe(handoff)}


def workspace_request(selection, mode, market_index, period, start, end, reset):
    if not selection:
        return None
    if mode not in {"risk", "market", "both"}:
        mode = "risk"
    handoffs = {}
    if mode in {"risk", "both"}:
        handoffs["risk"] = selection["risk"]
    if mode in {"market", "both"}:
        markets = selection.get("markets", [])
        if markets:
            index = max(0, min(int(market_index or 0), len(markets) - 1))
            handoffs["market"] = markets[index]
    # Revalidate every request. A compact browser Store is an input, not authority.
    checked = {}
    for kind, raw in handoffs.items():
        handoff = replace(HistoryHandoff.from_mapping(raw), reset_generation=int(reset or 0))
        query = HistoryQuery(handoff=handoff, period=period or "all",
                             start_date=start if period == "custom" else None,
                             end_date=end if period == "custom" else None)
        checked[kind] = query.handoff.to_mapping()
    return {"display_mode": mode, "handoffs": checked, "period": period or "all",
            "start_date": start if period == "custom" else None,
            "end_date": end if period == "custom" else None,
            "label": selection.get("label", "")}
