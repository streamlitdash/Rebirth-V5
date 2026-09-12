"""Shared literal column filters for server-paged Dash tables."""

from __future__ import annotations

import operator

import pandas as pd


def _filter_mask(frame: pd.DataFrame, node: dict, depth: int = 0) -> pd.Series:
    """Evaluate Dash's parsed column-filter tree, never Python or query text."""
    if not isinstance(node, dict) or depth > 24:
        raise ValueError("The table filter is too complex; simplify it.")
    kind, operation = node.get("type"), node.get("subType")
    if kind == "open-block":
        return _filter_mask(frame, node.get("block"), depth + 1)
    if kind == "logical-operator" and operation in {"&&", "||"}:
        left = _filter_mask(frame, node.get("left"), depth + 1)
        right = _filter_mask(frame, node.get("right"), depth + 1)
        return left & right if operation == "&&" else left | right

    field = node.get("left") or node.get("block") or {}
    name = field.get("value")
    if field.get("subType") != "field" or name not in frame:
        raise ValueError("Filter a column shown in this table.")
    values = frame[name]
    if kind == "unary-operator" and operation in {"is nil", "is blank"}:
        return values.isna() | values.astype("string").eq("").fillna(False)
    right = node.get("right") or {}
    if kind != "relational-operator" or right.get("subType") != "value":
        raise ValueError("Use text, =, !=, <, <=, > or >= in the column filter.")
    value = right.get("value")
    # The normal Aa filter control is encoded in Dash's operator token.
    token = str(node.get("value", operation))
    case_sensitive = token.startswith("s") or ("value" in node and not token.startswith("i"))
    operation = str(operation).removeprefix("i").removeprefix("s")
    if operation in {"contains", "datestartswith"}:
        text, needle = values.astype("string"), str(value)
        if not case_sensitive:
            text, needle = text.str.casefold(), needle.casefold()
        return (text.str.contains(needle, regex=False, na=False)
                if operation == "contains" else text.str.startswith(needle, na=False))
    comparisons = {"=": operator.eq, "!=": operator.ne, "<": operator.lt,
                   "<=": operator.le, ">": operator.gt, ">=": operator.ge}
    if operation not in comparisons:
        raise ValueError("Use text, =, !=, <, <=, > or >= in the column filter.")
    if pd.api.types.is_numeric_dtype(values):
        try:
            value = float(str(value).replace(",", ""))
        except (TypeError, ValueError) as error:
            raise ValueError(f"Enter a number in the {name} filter.") from error
    else:
        values, value = values.astype("string"), str(value)
        if not case_sensitive:
            values, value = values.str.casefold(), value.casefold()
    return comparisons[operation](values, value).fillna(False)


def filter_table_rows(frame: pd.DataFrame, filter_tree=None, *, filter_query="") -> pd.DataFrame:
    """Apply the normal per-column filter row without evaluating user code.

    The caller owns paging and totals. A missing filter leaves the source frame
    untouched; invalid or incomplete filters raise ValueError for the UI to show.
    """
    if str(filter_query or "").strip() and not filter_tree:
        raise ValueError("The table filter is incomplete; finish or clear it.")
    return frame.loc[_filter_mask(frame, filter_tree)] if filter_tree else frame


__all__ = ["filter_table_rows"]
