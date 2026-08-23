"""Pure governed V4 P&L editor and effective-row helpers."""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence

import pandas as pd

from rebirth.domain.s08_pnl import (
    ADJUSTMENT,
    CONCERTO_FIELD,
    MARKET_DATE,
    PL,
    PL_SEND_COLUMNS,
    PORTFOLIO,
    RISK_GREEK,
    RISK_TYPE,
    SIGNOFF_GROUP,
    apply_adjustment_overlay,
    build_pl_send_base,
    load_plsend_mapping,
    load_portfolio_governance,
)
from rebirth.domain.s01_schema import (
    PORTFOLIO_MAPPED_COLUMN,
    PORTFOLIO_METADATA_COLUMNS,
)

from .s01_common import (
    GRID_ROW_ID,
    PL_FILTER_FIELDS,
    PLSendConfig,
    apply_pl_filters,
    pl_external_filter_map,
)


_CHECKED = "\N{BALLOT BOX WITH CHECK}"
_UNCHECKED = "\N{BALLOT BOX}"


def _is_checked(value: object) -> bool:
    if isinstance(value, bool):
        return value
    normalized = str(value).strip()
    return (
        normalized in (_CHECKED, "true", "True", "1")
        or 'data-adjustment="true"' in normalized
    )


def _governance(snapshot) -> pd.DataFrame:
    columns = [PORTFOLIO, *PORTFOLIO_METADATA_COLUMNS]
    raw = snapshot.combined_pl
    if PORTFOLIO_MAPPED_COLUMN not in raw:
        raise ValueError(f"omitted P&L is missing {PORTFOLIO_MAPPED_COLUMN}")
    mapped = raw.loc[raw[PORTFOLIO_MAPPED_COLUMN].eq(True), columns].drop_duplicates()
    conflicts = mapped.duplicated(PORTFOLIO, keep=False)
    if conflicts.any():
        raise ValueError(
            "portfolio governance is inconsistent in the committed snapshot"
        )
    return load_portfolio_governance(mapped)


def _display_records(frame: pd.DataFrame) -> list[dict[str, object]]:
    display = frame.copy()
    if MARKET_DATE in display:
        display[MARKET_DATE] = pd.to_datetime(display[MARKET_DATE]).dt.date.astype(str)
    display[ADJUSTMENT] = display[ADJUSTMENT].map(
        lambda value: _CHECKED if bool(value) else _UNCHECKED
    )
    return display.to_dict("records")


def _domain_frame(records: list[dict[str, object]] | None) -> pd.DataFrame:
    frame = pd.DataFrame(records or [])
    if frame.empty:
        return pd.DataFrame(columns=list(PL_SEND_COLUMNS))
    for column in PL_SEND_COLUMNS:
        if column not in frame:
            frame[column] = None
    frame[ADJUSTMENT] = frame[ADJUSTMENT].map(_is_checked)
    return frame[list(PL_SEND_COLUMNS)]


def _risk_type_options(mapping: pd.DataFrame) -> list[str]:
    """Return the stable Risk Type domain exposed by the mapping."""
    return sorted(mapping[RISK_TYPE].astype(str).unique().tolist())


def _risk_greek_options(mapping: pd.DataFrame, risk_type: object) -> list[str]:
    """Return only Greeks governed for the selected Risk Type."""
    scoped = mapping.loc[mapping[RISK_TYPE].astype(str).eq(str(risk_type))]
    return sorted(scoped[RISK_GREEK].astype(str).unique().tolist())


def _datatable_options(values: list[str]) -> list[dict[str, str]]:
    """Convert one governed string domain to Dash DataTable options."""
    return [{"label": value, "value": value} for value in values]


def _editor_dropdowns(
    mapping: pd.DataFrame,
    allowed_portfolios: list[str],
    *,
    portfolio_editable: bool,
) -> tuple[dict[str, object], list[dict[str, object]]]:
    """Build global and Risk-Type-dependent native DataTable dropdowns."""
    risk_types = _risk_type_options(mapping)
    all_greeks = sorted(mapping[RISK_GREEK].astype(str).unique().tolist())
    dropdown: dict[str, object] = {
        RISK_TYPE: {"options": _datatable_options(risk_types)},
        RISK_GREEK: {"options": _datatable_options(all_greeks)},
    }
    if portfolio_editable:
        dropdown[PORTFOLIO] = {
            "options": _datatable_options(allowed_portfolios),
        }

    conditional: list[dict[str, object]] = []
    for risk_type in risk_types:
        escaped = risk_type.replace("\\", "\\\\").replace("'", "\\'")
        conditional.append(
            {
                "if": {
                    "column_id": RISK_GREEK,
                    "filter_query": f'{{{RISK_TYPE}}} = "{escaped}"',
                },
                "options": _datatable_options(_risk_greek_options(mapping, risk_type)),
            }
        )
    return dropdown, conditional


def _allowed_portfolios(
    governance: pd.DataFrame,
    *,
    scope_column: str,
    selected_scope: object,
) -> list[str]:
    """Return the governed Portfolio domain for the active editor scope."""
    if selected_scope in (None, ""):
        return []
    if scope_column == PORTFOLIO:
        selected = str(selected_scope)
        values = set(governance[PORTFOLIO].astype(str))
        return [selected] if selected in values else []
    scoped = governance.loc[
        governance[scope_column].astype(str).eq(str(selected_scope)), PORTFOLIO
    ]
    return sorted(scoped.astype(str).unique().tolist())


def _govern_row(
    row: dict[str, object],
    mapping: pd.DataFrame,
    governance: pd.DataFrame,
    *,
    allowed_portfolios: list[str],
    changed: bool,
) -> dict[str, object]:
    result = dict(row)
    portfolio = str(result.get(PORTFOLIO, ""))
    if portfolio not in allowed_portfolios:
        portfolio = allowed_portfolios[0]
    result[PORTFOLIO] = portfolio
    result[SIGNOFF_GROUP] = governance.set_index(PORTFOLIO).at[portfolio, SIGNOFF_GROUP]

    risk_type = str(result.get(RISK_TYPE, ""))
    if risk_type not in set(mapping[RISK_TYPE]):
        risk_type = str(mapping.iloc[0][RISK_TYPE])
    scoped = mapping.loc[mapping[RISK_TYPE].eq(risk_type)]
    risk_greek = str(result.get(RISK_GREEK, ""))
    pair = scoped.loc[scoped[RISK_GREEK].eq(risk_greek)]
    if pair.empty:
        pair = scoped.iloc[[0]]
        risk_greek = str(pair.iloc[0][RISK_GREEK])
    result[RISK_TYPE] = risk_type
    result[RISK_GREEK] = risk_greek
    result[CONCERTO_FIELD] = str(pair.iloc[0][CONCERTO_FIELD])
    result[ADJUSTMENT] = changed or _is_checked(result.get(ADJUSTMENT, False))
    if MARKET_DATE in result and result[MARKET_DATE] not in (None, ""):
        result[MARKET_DATE] = pd.Timestamp(result[MARKET_DATE]).date().isoformat()
    return result


def _editor_row(
    row: dict[str, object],
    mapping: pd.DataFrame,
    governance: pd.DataFrame,
    *,
    allowed_portfolios: list[str],
    changed: bool,
    row_id: str,
) -> dict[str, object]:
    """Govern one native DataTable row and preserve its stable row ID."""
    governed = _govern_row(
        row,
        mapping,
        governance,
        allowed_portfolios=allowed_portfolios,
        changed=changed,
    )
    governed[GRID_ROW_ID] = row_id
    governed[ADJUSTMENT] = (
        _CHECKED if _is_checked(governed.get(ADJUSTMENT, False)) else _UNCHECKED
    )
    return governed


def _editor_records(
    frame: pd.DataFrame,
    mapping: pd.DataFrame,
    governance: pd.DataFrame,
    *,
    allowed_portfolios: list[str],
    scope_key: str,
) -> list[dict[str, object]]:
    """Serialize scoped PL rows with deterministic native DataTable IDs."""
    if frame.empty or not allowed_portfolios:
        return []
    records: list[dict[str, object]] = []
    for index, row in enumerate(frame.to_dict("records")):
        market_date = pd.Timestamp(row[MARKET_DATE]).date().isoformat()
        row_id = ":".join(
            [
                "base",
                scope_key,
                str(index),
                market_date,
                str(row.get(PORTFOLIO, "")),
                str(row.get(CONCERTO_FIELD, "")),
            ]
        )
        records.append(
            _editor_row(
                row,
                mapping,
                governance,
                allowed_portfolios=allowed_portfolios,
                changed=False,
                row_id=row_id,
            )
        )
    return records


def _new_editor_row(
    *,
    market_date: object,
    mapping: pd.DataFrame,
    governance: pd.DataFrame,
    allowed_portfolios: list[str],
) -> dict[str, object]:
    """Create one visible, governed adjustment row for insertion at row zero."""
    first_mapping = mapping.iloc[0]
    return _editor_row(
        {
            MARKET_DATE: pd.Timestamp(market_date).date().isoformat(),
            RISK_TYPE: first_mapping[RISK_TYPE],
            RISK_GREEK: first_mapping[RISK_GREEK],
            PORTFOLIO: allowed_portfolios[0],
            PL: 0.0,
            ADJUSTMENT: True,
        },
        mapping,
        governance,
        allowed_portfolios=allowed_portfolios,
        changed=True,
        row_id=f"new:{uuid.uuid4().hex}",
    )


def _draft_key(scope_column: str, selected_scope: object) -> str:
    """Return the stable client-draft key for one editor scope."""
    return str(selected_scope)


def _matching_draft_rows(
    drafts: dict[str, object] | None,
    store: dict[str, object],
    *,
    scope_key: str,
    scope_column: str,
    selected_scope: object,
) -> list[dict[str, object]] | None:
    """Return only a populated draft created for this exact editor scope."""
    entry = (drafts or {}).get(scope_key)
    if not isinstance(entry, dict):
        return None
    guards = (
        "revision",
        "market_date",
        "include_adjustments",
        "editor_epoch",
        "filter_scope",
        "allowed_portfolios",
    )
    if any(entry.get(key) != store.get(key) for key in guards):
        return None
    if entry.get("scope_column") != scope_column:
        return None
    if str(entry.get("scope_value", "")) != str(selected_scope):
        return None
    rows = entry.get("rows")
    if not isinstance(rows, list) or not rows:
        return None
    if not all(isinstance(row, dict) for row in rows):
        return None
    if any(str(row.get(scope_column, "")) != str(selected_scope) for row in rows):
        return None
    return [dict(row) for row in rows]


def _baseline_editor_records(
    store: dict[str, object],
    mapping: pd.DataFrame,
    governance: pd.DataFrame,
    *,
    scope_column: str,
    selected_scope: object,
) -> list[dict[str, object]]:
    """Build the committed baseline for one SOG or Portfolio editor scope."""
    frame = pd.DataFrame(store.get("rows", []))
    if frame.empty or scope_column not in frame:
        return []
    scoped = frame.loc[frame[scope_column].astype(str).eq(str(selected_scope))].copy()
    allowed = _allowed_portfolios(
        governance,
        scope_column=scope_column,
        selected_scope=selected_scope,
    )
    return _editor_records(
        scoped,
        mapping,
        governance,
        allowed_portfolios=allowed,
        scope_key=_draft_key(scope_column, selected_scope),
    )


def _drafts_with_scope(
    drafts: dict[str, object] | None,
    store: dict[str, object],
    rows: list[dict[str, object]],
    *,
    scope_column: str,
    selected_scope: object,
) -> dict[str, object]:
    """Persist a draft only after an explicit user edit or Add Row action."""
    updated = dict(drafts or {})
    updated[_draft_key(scope_column, selected_scope)] = {
        "revision": store.get("revision"),
        "market_date": store.get("market_date"),
        "include_adjustments": bool(store.get("include_adjustments")),
        "editor_epoch": store.get("editor_epoch", 0),
        "filter_scope": store.get("filter_scope"),
        "allowed_portfolios": list(store.get("allowed_portfolios", [])),
        "scope_column": scope_column,
        "scope_value": str(selected_scope),
        "rows": [dict(row) for row in rows],
    }
    return updated


def _editable_signature(row: dict[str, object]) -> tuple[object, ...]:
    """Return the user-editable values used to detect unsaved changes."""
    pl_value = row.get(PL)
    try:
        normalized_pl: object = float(str(pl_value).replace(",", ""))
    except (TypeError, ValueError):
        normalized_pl = str(pl_value)
    return (
        str(row.get(RISK_TYPE, "")),
        str(row.get(RISK_GREEK, "")),
        str(row.get(PORTFOLIO, "")),
        normalized_pl,
    )


def _govern_current_editor_records(
    records: list[dict[str, object]] | None,
    store: dict[str, object],
    mapping: pd.DataFrame,
    governance: pd.DataFrame,
    *,
    scope_column: str,
    selected_scope: object,
) -> list[dict[str, object]]:
    """Re-govern current grid state independently of the UI edit callback."""
    allowed = _allowed_portfolios(
        governance,
        scope_column=scope_column,
        selected_scope=selected_scope,
    )
    if not allowed:
        return []
    baseline_frame = pd.DataFrame(store.get("rows", []))
    if not baseline_frame.empty and scope_column in baseline_frame:
        baseline_frame = baseline_frame.loc[
            baseline_frame[scope_column].astype(str).eq(str(selected_scope))
        ].copy()
    baseline = _editor_records(
        baseline_frame,
        mapping,
        governance,
        allowed_portfolios=allowed,
        scope_key=_draft_key(scope_column, selected_scope),
    )
    baseline_by_id = {str(row[GRID_ROW_ID]): row for row in baseline}

    governed: list[dict[str, object]] = []
    for row in records or []:
        current = dict(row)
        row_id = str(current.get(GRID_ROW_ID, "")) or f"save:{uuid.uuid4().hex}"
        original = baseline_by_id.get(row_id)
        changed = original is None or _editable_signature(
            current
        ) != _editable_signature(original)
        governed.append(
            _editor_row(
                current,
                mapping,
                governance,
                allowed_portfolios=allowed,
                changed=changed,
                row_id=row_id,
            )
        )
    return governed


def _merge_and_persist_adjustments(
    config: PLSendConfig,
    rows: pd.DataFrame,
    *,
    market_date: object,
    revision: int,
    replace_portfolios: set[str] | None = None,
) -> None:
    config.adjustment_repository.save(
        market_date,
        rows,
        base_revision=revision,
        replace_portfolios=replace_portfolios,
    )


def _effective_rows(
    snapshot,
    config: PLSendConfig,
    *,
    include_adjustments: bool,
    filter_values: Sequence[Sequence[object] | None] | None = None,
    exclude_value: Sequence[object] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Build governed P&L after resolving the page filter to Portfolios."""
    mapping = load_plsend_mapping(config.mapping_source)
    governance = _governance(snapshot)
    filter_scope = _pl_filter_scope(filter_values, exclude_value)
    filtered_governance = apply_pl_filters(
        governance,
        filter_scope["filters"],
        exclude_selected=bool(filter_scope["exclude_selected"]),
    )
    allowed_portfolios = set(filtered_governance[PORTFOLIO].astype(str))
    raw_portfolios = snapshot.combined_pl[PORTFOLIO].astype(str)
    filtered_raw = snapshot.combined_pl.loc[
        raw_portfolios.isin(allowed_portfolios)
    ].copy(deep=True)
    base = build_pl_send_base(filtered_raw, mapping, filtered_governance)
    adjustments = (
        config.adjustment_repository.load(snapshot.market_date)
        if include_adjustments
        else None
    )
    if adjustments is not None:
        adjustment_portfolios = adjustments[PORTFOLIO].astype(str)
        adjustments = adjustments.loc[
            adjustment_portfolios.isin(allowed_portfolios)
        ].copy(deep=True)
    effective = apply_adjustment_overlay(
        base,
        None
        if adjustments is None
        else adjustments.reindex(columns=list(PL_SEND_COLUMNS)),
        mapping,
        filtered_governance,
        include_adjustments=include_adjustments,
    )
    return effective, mapping, filtered_governance


def _pl_filter_scope(
    filter_values: Sequence[Sequence[object] | None] | None,
    exclude_value: Sequence[object] | None,
) -> dict[str, object]:
    """Return one deterministic filter payload for callbacks and stale guards."""

    values = (
        list(filter_values)
        if filter_values is not None
        else [None] * len(PL_FILTER_FIELDS)
    )
    external = pl_external_filter_map(values)
    normalized = {
        column: sorted(
            {str(value).strip() for value in selected if str(value).strip()},
            key=str.casefold,
        )
        for column, selected in external.items()
    }
    return {
        "filters": normalized,
        "exclude_selected": "exclude" in (exclude_value or []),
    }


def _filtered_store_governance(
    governance: pd.DataFrame,
    store: Mapping[str, object],
) -> pd.DataFrame:
    """Restrict editor governance to the filter scope serialized with its rows."""

    allowed = store.get("allowed_portfolios")
    if not isinstance(allowed, list):
        raise ValueError("the PL editor filter scope is missing; reload the editor")
    selected = {str(value) for value in allowed}
    return governance.loc[governance[PORTFOLIO].astype(str).isin(selected)].copy(
        deep=True
    )


def _require_current_filter_scope(
    store: Mapping[str, object],
    filter_values: Sequence[Sequence[object] | None],
    exclude_value: Sequence[object] | None,
) -> None:
    """Fail closed when an editor store predates the current page filters."""

    if store.get("filter_scope") != _pl_filter_scope(filter_values, exclude_value):
        raise ValueError("the page filters changed; reload the PL editor")


def _effective_store(
    snapshot,
    effective: pd.DataFrame,
    *,
    filtered_governance: pd.DataFrame,
    filter_scope: Mapping[str, object],
    include_adjustments: bool,
    editor_epoch: int = 0,
) -> dict[str, object]:
    """Serialize effective rows with the snapshot guard used by editors."""
    return {
        "revision": int(snapshot.revision),
        "market_date": pd.Timestamp(snapshot.market_date).date().isoformat(),
        "include_adjustments": bool(include_adjustments),
        "editor_epoch": int(editor_epoch),
        "filter_scope": dict(filter_scope),
        "allowed_portfolios": sorted(
            filtered_governance[PORTFOLIO].astype(str).unique().tolist()
        ),
        "rows": effective.to_dict("records"),
    }
