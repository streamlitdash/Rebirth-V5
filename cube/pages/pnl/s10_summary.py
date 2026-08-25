"""Dedicated Risk Type → Greek → Underlying P&L summary components."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence

import pandas as pd
from dash import html

from cube.history import (
    PL_RISK_SUMMARY_CURRENT,
    PL_RISK_SUMMARY_DEPTH,
    PL_RISK_SUMMARY_LABEL,
    PL_RISK_SUMMARY_LEAF,
    PL_RISK_SUMMARY_MTD,
    PL_RISK_SUMMARY_PATH,
    PL_RISK_SUMMARY_YTD,
)
from cube.ui.s01_constants import RISK_TYPE_ORDER

from .s01_common import PL_SUMMARY_HISTORY_CELL_TYPE, PL_SUMMARY_TOGGLE_TYPE


SUMMARY_METRICS = (
    (PL_RISK_SUMMARY_CURRENT, "Today"),
    (PL_RISK_SUMMARY_MTD, "Month to date"),
    (PL_RISK_SUMMARY_YTD, "Year to date"),
)
PL_SUMMARY_PAGE_TYPE = "pnl-summary-page"
PL_SUMMARY_LEAF_PAGE_SIZE = 75


def path_token(path: Sequence[object]) -> str:
    """Encode a bounded hierarchy path for a Dash component identifier."""

    return json.dumps([str(value) for value in path], separators=(",", ":"))


def decode_open_paths(raw: object) -> set[tuple[str, ...]]:
    """Validate browser-owned open-row tokens without trusting their shape."""

    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        return set()
    result: set[tuple[str, ...]] = set()
    for token in raw:
        if not isinstance(token, str) or len(token) > 8_000:
            continue
        try:
            values = json.loads(token)
        except (TypeError, ValueError):
            continue
        if (
            isinstance(values, list)
            and 1 <= len(values) <= 2
            and all(isinstance(value, str) and value for value in values)
        ):
            result.add(tuple(values))
    return result


def _number(value: object) -> str:
    if value is None or pd.isna(value):
        return "—"
    return f"{float(value):,.0f}"


def _sort_key(path: tuple[str, ...]) -> tuple[object, ...]:
    if not path:
        return (-1,)
    return (
        RISK_TYPE_ORDER.get(path[0], 99),
        *(value.casefold() for value in path),
    )


def _children(
    rows: Mapping[tuple[str, ...], Mapping[str, object]],
    parent: tuple[str, ...],
) -> list[tuple[str, ...]]:
    """Return one hierarchy level in stable business order."""

    return sorted(
        (path for path in rows if len(path) == len(parent) + 1 and path[:-1] == parent),
        key=_sort_key,
    )


def _requested_page(page_by_parent: object, parent: tuple[str, ...]) -> int:
    """Read one bounded browser page without trusting dynamic component IDs."""

    if not isinstance(page_by_parent, Mapping):
        return 0
    value = page_by_parent.get(path_token(parent), 0)
    if isinstance(value, bool) or not isinstance(value, int):
        return 0
    return min(max(value, 0), 100_000)


def build_pl_summary_table(
    summary: pd.DataFrame,
    open_tokens: object = None,
    *,
    as_of_date: str | None = None,
    page_by_parent: Mapping[str, int] | None = None,
) -> html.Div:
    """Render a bounded three-level chevron table with leaf pagination."""

    if not isinstance(summary, pd.DataFrame) or summary.empty:
        return html.Div(
            "No historical P&L matches the current saved-view filters.",
            className="empty-state",
            role="status",
        )
    required = {
        PL_RISK_SUMMARY_DEPTH,
        PL_RISK_SUMMARY_LABEL,
        PL_RISK_SUMMARY_PATH,
        PL_RISK_SUMMARY_LEAF,
        *(metric for metric, _label in SUMMARY_METRICS),
    }
    missing = sorted(required - set(summary.columns))
    if missing:
        raise ValueError(f"P&L summary is missing columns: {missing}")

    rows: dict[tuple[str, ...], dict[str, object]] = {}
    for record in summary.to_dict("records"):
        raw_path = record[PL_RISK_SUMMARY_PATH]
        if not isinstance(raw_path, Sequence) or isinstance(raw_path, (str, bytes)):
            raise ValueError("P&L summary hierarchy paths must be sequences")
        path = tuple(str(value) for value in raw_path)
        if len(path) != int(record[PL_RISK_SUMMARY_DEPTH]):
            raise ValueError("P&L summary path depth is inconsistent")
        rows[path] = record

    open_paths = decode_open_paths(open_tokens)
    body: list[html.Tr] = []

    def append_row(path: tuple[str, ...]) -> None:
        record = rows[path]
        depth = len(path)
        leaf = bool(record[PL_RISK_SUMMARY_LEAF])
        label = str(record[PL_RISK_SUMMARY_LABEL])
        label_children: list[object] = []
        if path and not leaf:
            opened = path in open_paths
            label_children.append(
                html.Button(
                    "−" if opened else "▸",
                    id={"type": PL_SUMMARY_TOGGLE_TYPE, "path": path_token(path)},
                    n_clicks=0,
                    className="tree-toggle",
                    title=f"{'Collapse' if opened else 'Expand'} {label}",
                    **{"aria-expanded": str(opened).lower()},
                )
            )
        label_children.append(html.Span(label))
        cells: list[html.Td] = [
            html.Th(
                label_children,
                scope="row",
                className="pnl-summary-label",
                style={"paddingLeft": f"{12 + max(depth - 1, 0) * 20}px"},
            )
        ]
        for metric, _metric_label in SUMMARY_METRICS:
            value = record[metric]
            rendered = _number(value)
            negative = value is not None and not pd.isna(value) and float(value) < 0
            scope_label = "all applied filters" if not path else " › ".join(path)
            content: object = html.Button(
                rendered,
                id={
                    "type": PL_SUMMARY_HISTORY_CELL_TYPE,
                    "risk_type": path[0] if len(path) >= 1 else "",
                    "risk_greek": path[1] if len(path) >= 2 else "",
                    "underlying": path[2] if len(path) >= 3 else "",
                    "metric": metric,
                },
                n_clicks=0,
                className="pnl-summary-history-button",
                title=f"Open P&L history for {scope_label}",
            )
            cells.append(
                html.Td(
                    content,
                    className=(
                        "pnl-summary-number is-negative"
                        if negative
                        else "pnl-summary-number"
                    ),
                )
            )
        body.append(
            html.Tr(
                cells,
                **{"aria-level": depth + 1},
                className="pnl-summary-total" if not path else "",
            )
        )

        if depth >= 3 or (path and path not in open_paths):
            return
        children = _children(rows, path)
        if depth != 2:
            for child in children:
                append_row(child)
            return

        total = len(children)
        requested = _requested_page(page_by_parent, path)
        last_page = max((total - 1) // PL_SUMMARY_LEAF_PAGE_SIZE, 0)
        page = min(requested, last_page)
        start = page * PL_SUMMARY_LEAF_PAGE_SIZE
        end = min(start + PL_SUMMARY_LEAF_PAGE_SIZE, total)
        for child in children[start:end]:
            append_row(child)
        if total <= PL_SUMMARY_LEAF_PAGE_SIZE:
            return
        token = path_token(path)
        body.append(
            html.Tr(
                html.Td(
                    html.Div(
                        [
                            html.Span(
                                f"Underlyings {start + 1:,}–{end:,} of {total:,}",
                                className="section-meta",
                            ),
                            html.Button(
                                "Previous",
                                id={
                                    "type": PL_SUMMARY_PAGE_TYPE,
                                    "path": token,
                                    "page": max(page - 1, 0),
                                },
                                n_clicks=0,
                                disabled=page == 0,
                                type="button",
                                className="refresh-button",
                            ),
                            html.Button(
                                "Next",
                                id={
                                    "type": PL_SUMMARY_PAGE_TYPE,
                                    "path": token,
                                    "page": min(page + 1, last_page),
                                },
                                n_clicks=0,
                                disabled=page >= last_page,
                                type="button",
                                className="refresh-button",
                            ),
                        ],
                        className="saved-view-actions pnl-summary-pagination",
                    ),
                    colSpan=len(SUMMARY_METRICS) + 1,
                ),
                className="pnl-summary-pagination-row",
            )
        )

    if () in rows:
        append_row(())

    return html.Div(
        [
            html.Div(
                [
                    html.Span("Risk Type › Greek › Underlying"),
                    html.Span(
                        f"Archive through {as_of_date}" if as_of_date else "Archive",
                        className="section-meta",
                    ),
                ],
                className="section-kicker",
            ),
            html.Div(
                html.Table(
                    [
                        html.Thead(
                            html.Tr(
                                [
                                    html.Th("P&L hierarchy", scope="col"),
                                    *[
                                        html.Th(label, scope="col")
                                        for _metric, label in SUMMARY_METRICS
                                    ],
                                ]
                            )
                        ),
                        html.Tbody(body),
                    ],
                    className="pnl-summary-table",
                    **{
                        "aria-label": "P&L current, month-to-date and year-to-date hierarchy"
                    },
                ),
                className="table-scroll",
            ),
        ],
        className="pnl-summary-wrap",
    )


__all__ = [
    "PL_SUMMARY_LEAF_PAGE_SIZE",
    "PL_SUMMARY_PAGE_TYPE",
    "SUMMARY_METRICS",
    "build_pl_summary_table",
    "decode_open_paths",
    "path_token",
]
