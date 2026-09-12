"""Visible Stock branches only; no cache of expanded table copies."""

import json

import pandas as pd

from .s01_data import (
    STOCK_MEASURES,
    STOCK_PROMOTION_THRESHOLD,
    stock_identifier,
    stock_index_columns,
)


def _value(value):
    if pd.isna(value):
        return None
    return value.item() if hasattr(value, "item") else value


def _token(path):
    return json.dumps(path, separators=(",", ":"), default=str)


def build_stock_tree(frame, open_paths=None, *, threshold=STOCK_PROMOTION_THRESHOLD):
    """Promotion nets dStock per identifier/sign-off group, across all its Groups.

    Open sign-off groups initially, with promoted identifiers and Other beneath.
    Group/other dimensions are calculated only when their parent is expanded.
    """
    if frame.empty:
        return []
    dimensions = stock_index_columns(frame)
    identifier = stock_identifier(frame)
    opened = set(open_paths or [])
    records = []

    def emit(
        part,
        label,
        path,
        *,
        branch=False,
        default_open=False,
        selection=None,
        promoted=False,
        values=None,
    ):
        token = _token(path)
        expanded = (default_open if open_paths is None else token in opened) and branch
        payload = {
            "path": token,
            "branch": branch,
            "open": expanded,
            "selection": selection,
        }
        prefix = ("▾ " if expanded else "▸ ") if branch else ""
        if values is None:
            values = part[list(STOCK_MEASURES)].sum(min_count=1)
        records.append(
            {
                "id": _token(payload),
                "Hierarchy": "\u00a0\u00a0\u00a0\u00a0" * (len(path) - 1)
                + prefix
                + str(label)
                + (" · Promoted" if promoted else ""),
                "Stock": _value(values["Stock"]),
                "dStock": _value(values["dStock"]),
                "Promoted": "Promoted" if promoted else "",
            }
        )
        return expanded

    def children(part, remaining, path):
        if not remaining:
            return
        column, *rest = remaining
        groups = part.groupby(column, sort=True, dropna=False, observed=True)
        totals = groups[list(STOCK_MEASURES)].sum(min_count=1)
        for key, stock, change in totals.itertuples(name=None):
            value = _value(key)
            next_path = [*path, [column, value]]
            selection = (
                {"column": identifier, "value": value} if column == identifier else None
            )
            if emit(
                None,
                "(blank)" if value is None else value,
                next_path,
                branch=bool(rest),
                selection=selection,
                values={"Stock": stock, "dStock": change},
            ):
                rows = (
                    part.loc[part[column].isna()]
                    if pd.isna(key)
                    else groups.get_group(key)
                )
                children(rows, rest, next_path)

    if not dimensions:
        emit(frame, "Total", [["total", None]])
        return records
    signoff, *remaining = dimensions
    for key, rows in frame.groupby(signoff, sort=True, dropna=False, observed=True):
        path = [[signoff, _value(key)]]
        if not emit(
            rows,
            "(blank)" if pd.isna(key) else key,
            path,
            branch=bool(remaining),
            default_open=True,
        ):
            continue
        if identifier is None or identifier == signoff:
            children(rows, remaining, path)
            continue
        groups = rows.groupby(identifier, sort=False, dropna=False, observed=True)
        totals = groups[list(STOCK_MEASURES)].sum(min_count=1)
        promoted = totals.loc[totals["dStock"].abs().gt(threshold)].sort_values(
            "dStock", key=lambda v: v.abs(), ascending=False
        )
        rest = [c for c in remaining if c != identifier]
        for identity, stock, change in promoted.itertuples(name=None):
            next_path = [*path, ["promoted", _value(identity)]]
            selection = {"column": identifier, "value": _value(identity)}
            if emit(
                None,
                identity,
                next_path,
                branch=bool(rest),
                selection=selection,
                promoted=True,
                values={"Stock": stock, "dStock": change},
            ):
                part = (
                    rows.loc[rows[identifier].isna()]
                    if pd.isna(identity)
                    else groups.get_group(identity)
                )
                children(part, rest, next_path)
        other = rows.loc[~rows[identifier].isin(promoted.index)]
        if not other.empty:
            other_path = [*path, ["other", None]]
            if emit(other, "Other", other_path, branch=bool(remaining)):
                children(other, remaining, other_path)
    return records
