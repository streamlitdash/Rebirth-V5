"""V4 callback-only helpers for Quick Risk search interactions."""

from __future__ import annotations

import logging
import re
import unicodedata
from inspect import Parameter, signature
from typing import Mapping, Sequence

import pandas as pd
from dash import html, no_update

from rebirth.app.s02_contracts import RefreshManagerProtocol
from rebirth.domain.s02_products import PRODUCT_SPECS_BY_SOURCE_TYPE

from .s08_quickrisk import (
    QUICK_RISK_PIVOT_LIMIT,
    QUICK_SEARCH_DEFAULT_INDEX,
    QUICK_SEARCH_HIERARCHY_DEPTH,
    QUICK_SEARCH_INDEX_OPTIONS,
    build_quick_search_pivot,
)


_LOGGER = logging.getLogger(__name__)
_QUICK_SEARCH_NON_ALPHANUMERIC = re.compile(r"[^a-z0-9]+")


def _combine_udl_browser_search(value: str) -> str:
    """Return whitespace aliases that Dash's local dropdown search can index."""
    normalized = unicodedata.normalize("NFKC", value).casefold()
    parts = tuple(
        part for part in _QUICK_SEARCH_NON_ALPHANUMERIC.split(normalized) if part
    )
    aliases = list(parts)
    for size in range(2, min(4, len(parts)) + 1):
        aliases.extend(
            "".join(parts[start : start + size])
            for start in range(len(parts) - size + 1)
        )
    if parts:
        aliases.append("".join(parts))
    return " ".join(dict.fromkeys(aliases))


def _quick_search_result_parts(
    result: object,
) -> tuple[pd.DataFrame, int | None, int | None]:
    """Normalise the small result contract without copying manager internals."""
    if isinstance(result, pd.DataFrame):
        return result, len(result), None
    if isinstance(result, Mapping):
        frame = result.get("frame", result.get("rows", result.get("results")))
        total = result.get("total")
        revision = result.get("revision")
    else:
        frame = getattr(result, "frame", None)
        total = getattr(result, "total", None)
        revision = getattr(result, "revision", None)
    if isinstance(frame, Sequence) and not isinstance(
        frame, (str, bytes, pd.DataFrame)
    ):
        frame = pd.DataFrame(frame)
    if not isinstance(frame, pd.DataFrame):
        raise TypeError("quick search returned no DataFrame")
    return (
        frame,
        int(total) if total is not None else len(frame),
        int(revision) if revision is not None else None,
    )


def _combine_udl_dropdown_options(raw_options: object) -> list[dict[str, str]]:
    """Return stable Dash options for the snapshot's exact identity keys."""
    if raw_options is None:
        return []
    if isinstance(raw_options, pd.Series):
        candidates = raw_options.tolist()
    elif isinstance(raw_options, Sequence) and not isinstance(
        raw_options, (str, bytes)
    ):
        candidates = raw_options
    else:
        try:
            candidates = list(raw_options)  # type: ignore[arg-type]
        except TypeError:
            return []

    options: list[dict[str, str]] = []
    seen: set[str] = set()
    for candidate in candidates:
        if isinstance(candidate, Mapping):
            value = str(candidate.get("value", "")).strip()
            label = str(candidate.get("label", value)).strip()
            search = str(candidate.get("search", "")).strip()
        else:
            value = str(candidate).strip()
            label = value
            search = ""
        if not value or value in seen:
            continue
        seen.add(value)
        options.append(
            {
                "label": label or value,
                "value": value,
                "search": search or _combine_udl_browser_search(label or value),
            }
        )
    return options


def _normalise_quick_search_index(
    index_columns: object,
) -> tuple[tuple[str, ...], bool]:
    """Return a valid ordered index and whether the UI value needs restoring."""
    allowed = {value for _label, value in QUICK_SEARCH_INDEX_OPTIONS}
    if not isinstance(index_columns, Sequence) or isinstance(
        index_columns, (str, bytes)
    ):
        return QUICK_SEARCH_DEFAULT_INDEX, True
    selected = tuple(str(value) for value in index_columns)
    if (
        not selected
        or len(selected) != len(set(selected))
        or any(value not in allowed for value in selected)
    ):
        return QUICK_SEARCH_DEFAULT_INDEX, True
    return selected, False


_QUICK_SEARCH_TENOR_INDEXES = frozenset(("Tenor Swap", "Tenor Option"))
_QUICK_SEARCH_ABSENT_TENORS = frozenset(("", "n/a", "na", "spot", "unspecified"))


def _prune_quick_search_indexes(
    hierarchy: pd.DataFrame,
    index_columns: Sequence[str],
) -> tuple[str, ...]:
    """Remove tenor levels that carry no coordinate for this exact identity.

    The decision comes only from the returned data, not from Risk Type or Risk
    Greek names. This lets one-axis products drop at `Tenor Swap`, and surfaces
    retain both axes while preserving any selected reporting dimensions.
    """

    selected = tuple(str(column) for column in index_columns)
    if hierarchy.empty or QUICK_SEARCH_HIERARCHY_DEPTH not in hierarchy:
        return selected
    depths = pd.to_numeric(
        hierarchy[QUICK_SEARCH_HIERARCHY_DEPTH],
        errors="coerce",
    )
    leaves = hierarchy.loc[depths.eq(len(selected))]
    if leaves.empty:
        return selected

    effective: list[str] = []
    for column in selected:
        if column not in _QUICK_SEARCH_TENOR_INDEXES:
            effective.append(column)
            continue
        if column not in leaves:
            continue
        labels = leaves[column].astype("string").str.strip().str.casefold()
        meaningful = labels.notna() & ~labels.isin(_QUICK_SEARCH_ABSENT_TENORS)
        if meaningful.any():
            effective.append(column)

    if effective:
        return tuple(effective)
    # An exact Combine Udl identity always has an Underlying even when the user
    # selected only an unavailable tenor level. Keep the resulting hierarchy
    # useful and return the corrected picker value to the browser.
    return ("Underlying",)


def _product_shaped_quick_search_indexes(
    manager: RefreshManagerProtocol,
    combine_udl: str,
    identity_mode: str,
    index_columns: Sequence[str],
) -> tuple[str, ...]:
    """Resolve ProductSpec axes before pivoting the exact Risk identity."""

    resolved = manager.resolve_history_identity(
        "risk",
        combine_udl,
        identity_mode=identity_mode,
    )
    source_types = tuple(getattr(resolved, "source_types", ()) or ())
    supported_axes = {
        axis.column
        for source_type in source_types
        for axis in PRODUCT_SPECS_BY_SOURCE_TYPE[source_type].axes
    }
    selected = tuple(str(column) for column in index_columns)
    non_tenors = tuple(
        column for column in selected if column not in _QUICK_SEARCH_TENOR_INDEXES
    )
    axes = tuple(
        column for column in ("Tenor Swap", "Tenor Option") if column in supported_axes
    )
    return (*non_tenors, *axes) or ("Underlying", *axes)


def _render_quick_search_pivot(
    manager: RefreshManagerProtocol,
    *,
    combine_udl: object,
    identity_mode: object = "reported",
    index_columns: object,
    is_open: object,
    risk_filters: Mapping[str, Sequence[str] | None] | None = None,
    exclude_selected: bool = False,
):
    selected_mode = str(identity_mode or "reported").strip().casefold()
    selected_indexes, restore_index = _normalise_quick_search_index(index_columns)
    index_update = list(selected_indexes) if restore_index else no_update
    if not bool(is_open):
        return None, index_update
    selected_identity = str(combine_udl or "").strip()
    if not selected_identity:
        return (
            html.Div(
                "Select a Search Risk value to build the pivot.",
                className="quick-search-hint",
                role="status",
            ),
            index_update,
        )
    try:
        try:
            shaped_indexes = _product_shaped_quick_search_indexes(
                manager,
                selected_identity,
                selected_mode,
                selected_indexes,
            )
        except (AttributeError, KeyError, LookupError, TypeError, ValueError):
            shaped_indexes = selected_indexes
        if shaped_indexes != selected_indexes:
            selected_indexes = shaped_indexes
            index_update = list(selected_indexes)
        pivot = manager.pivot_combined_hierarchy
        pivot_kwargs: dict[str, object] = {
            "index_columns": selected_indexes,
            "leaf_limit": QUICK_RISK_PIVOT_LIMIT,
            "identity_mode": selected_mode,
            "risk_filters": risk_filters,
            "exclude_selected": exclude_selected,
        }
        # Filter arguments were added to the manager
        # contract after the exact-pivot helper first shipped.  Keeping this
        # small compatibility boundary lets cold fixtures and direct helper
        # callers use the older read-only protocol without catching a
        # TypeError raised *inside* the manager implementation.
        try:
            pivot_parameters = signature(pivot).parameters
        except (TypeError, ValueError):
            pivot_parameters = {}
        if pivot_parameters and not any(
            parameter.kind is Parameter.VAR_KEYWORD
            for parameter in pivot_parameters.values()
        ):
            pivot_kwargs = {
                name: value
                for name, value in pivot_kwargs.items()
                if name in pivot_parameters
            }

        result = pivot(
            selected_identity,
            **pivot_kwargs,
        )
        frame, total, revision = _quick_search_result_parts(result)
        effective_indexes = _prune_quick_search_indexes(frame, selected_indexes)
        if effective_indexes != selected_indexes:
            pivot_kwargs["index_columns"] = effective_indexes
            result = pivot(
                selected_identity,
                **pivot_kwargs,
            )
            frame, total, revision = _quick_search_result_parts(result)
            index_update = list(effective_indexes)
        return (
            build_quick_search_pivot(
                frame,
                combine_udl=selected_identity,
                index_columns=effective_indexes,
                total=total,
                revision=revision,
            ),
            index_update,
        )
    except (AttributeError, LookupError, TypeError, ValueError, RuntimeError) as error:
        _LOGGER.exception("Quick Risk Search render failed")
        detail = " ".join(str(error).splitlines()).strip() or type(error).__name__
        return (
            html.Div(
                f"Quick Risk Search failed: {type(error).__name__}: {detail[:400]}",
                className="quick-search-error",
                role="alert",
            ),
            index_update,
        )


__all__ = [
    "_combine_udl_browser_search",
    "_combine_udl_dropdown_options",
    "_normalise_quick_search_index",
    "_prune_quick_search_indexes",
    "_product_shaped_quick_search_indexes",
    "_quick_search_result_parts",
    "_render_quick_search_pivot",
]
