"""Validated, presentation-only Custom Risk View storage."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Final

from rebirth.services.saved_views import normalize_saved_view_name


RISK_VIEW_VERSION: Final = 1
RISK_VIEW_DIMENSIONS: Final = (
    "risk type",
    "risk greek",
    "display bucket",
    "region",
    "group",
    "reported underlying",
    "underlying",
    "tenor swap",
    "tenor option",
    "split",
    "product",
    "activity",
    "signoffgroup",
    "portfolio",
    "category",
    "subcategory",
)
RISK_VIEW_MEASURES: Final = (
    "risk",
    "drisk",
    "pl",
    "move",
    "open",
    "current",
    "risk expo",
    "risk hedges",
    "drisk expo",
    "drisk hedges",
    "pl expo",
    "pl hedges",
)
_IDENTIFIER_PATTERN: Final = re.compile(r"^[a-z0-9][a-z0-9-]{0,47}--[0-9a-f]{12}$")
_SLUG_CHARACTERS: Final = re.compile(r"[^a-z0-9]+")
_MAX_FILTER_VALUES: Final = 1_000
MAX_RISK_VIEWS: Final = 100


def _identifier(name: str) -> str:
    slug = _SLUG_CHARACTERS.sub("-", name.casefold()).strip("-") or "view"
    slug = slug[:48].rstrip("-") or "view"
    digest = hashlib.sha256(name.casefold().encode("utf-8")).hexdigest()[:12]
    return f"{slug}--{digest}"


def _named_selection(
    value: object,
    *,
    label: str,
    allowed: Sequence[str],
    required: bool = False,
) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise ValueError(f"Risk View {label} must be a sequence")
    selected = tuple(str(item).strip().casefold() for item in value)
    if (required and not selected) or any(not item for item in selected):
        raise ValueError(f"Risk View {label} must not be blank")
    if len(selected) != len(set(selected)):
        raise ValueError(f"Risk View {label} must be unique")
    unknown = sorted(set(selected) - set(allowed))
    if unknown:
        raise ValueError(f"Risk View {label} contains unsupported fields: {unknown}")
    return selected


def _filters(value: object) -> tuple[tuple[str, tuple[str, ...]], ...]:
    if not isinstance(value, Mapping):
        raise ValueError("Risk View filters must be a mapping")
    unknown = sorted(set(value) - set(RISK_VIEW_DIMENSIONS))
    if unknown:
        raise ValueError(f"Risk View filters contain unsupported fields: {unknown}")
    result: list[tuple[str, tuple[str, ...]]] = []
    for field in RISK_VIEW_DIMENSIONS:
        if field not in value:
            continue
        raw_values = value[field]
        if isinstance(raw_values, (str, bytes)) or not isinstance(raw_values, Sequence):
            raise ValueError(f"Risk View filter {field!r} must be a sequence")
        if len(raw_values) > _MAX_FILTER_VALUES:
            raise ValueError(f"Risk View filter {field!r} contains too many values")
        values: list[str] = []
        seen: set[str] = set()
        for raw_value in raw_values:
            if not isinstance(raw_value, str) or not raw_value.strip():
                raise ValueError(f"Risk View filter {field!r} values must be text")
            selected = raw_value.strip()
            if selected not in seen:
                seen.add(selected)
                values.append(selected)
        result.append((field, tuple(values)))
    return tuple(result)


def _sort(value: object) -> tuple[tuple[str, str], ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise ValueError("Risk View sort must be a sequence")
    allowed_fields = set((*RISK_VIEW_DIMENSIONS, *RISK_VIEW_MEASURES))
    result: list[tuple[str, str]] = []
    for item in value:
        if not isinstance(item, Mapping) or set(item) != {"field", "direction"}:
            raise ValueError("Risk View sort entries have unexpected fields")
        field = str(item["field"]).strip().casefold()
        direction = str(item["direction"]).strip().casefold()
        if field not in allowed_fields or direction not in {"asc", "desc"}:
            raise ValueError("Risk View sort entry is invalid")
        result.append((field, direction))
    if len({field for field, _direction in result}) != len(result):
        raise ValueError("Risk View sort fields must be unique")
    return tuple(result)


@dataclass(frozen=True)
class PivotSpec:
    """One bounded native-pivot presentation contract."""

    rows: tuple[str, ...]
    columns: tuple[str, ...]
    measures: tuple[str, ...]
    filters: tuple[tuple[str, tuple[str, ...]], ...] = ()
    sort: tuple[tuple[str, str], ...] = ()
    row_totals: bool = True
    column_totals: bool = False
    grand_total: bool = True
    row_limit: int = 200
    column_limit: int = 24
    density: str = "compact"
    show_zeros: bool = False
    sticky_headers: bool = True

    @classmethod
    def from_dict(cls, value: object) -> PivotSpec:
        if not isinstance(value, Mapping) or set(value) != {
            "rows",
            "columns",
            "measures",
            "filters",
            "sort",
            "totals",
            "display",
        }:
            raise ValueError("Risk View pivot has unexpected fields")
        rows = _named_selection(
            value["rows"],
            label="rows",
            allowed=RISK_VIEW_DIMENSIONS,
            required=True,
        )
        columns = _named_selection(
            value["columns"], label="columns", allowed=RISK_VIEW_DIMENSIONS
        )
        if set(rows) & set(columns):
            raise ValueError("Risk View rows and columns must not overlap")
        measures = _named_selection(
            value["measures"],
            label="measures",
            allowed=RISK_VIEW_MEASURES,
            required=True,
        )
        totals = value["totals"]
        if not isinstance(totals, Mapping) or set(totals) != {
            "rows",
            "columns",
            "grand",
        }:
            raise ValueError("Risk View totals have unexpected fields")
        if any(not isinstance(totals[key], bool) for key in totals):
            raise ValueError("Risk View totals must be boolean")
        display = value["display"]
        if not isinstance(display, Mapping) or set(display) != {
            "row_limit",
            "column_limit",
            "density",
            "show_zeros",
            "sticky_headers",
        }:
            raise ValueError("Risk View display has unexpected fields")
        row_limit = display["row_limit"]
        column_limit = display["column_limit"]
        if (
            isinstance(row_limit, bool)
            or not isinstance(row_limit, int)
            or not 10 <= row_limit <= 500
        ):
            raise ValueError("Risk View row limit must be between 10 and 500")
        if (
            isinstance(column_limit, bool)
            or not isinstance(column_limit, int)
            or not 1 <= column_limit <= 50
        ):
            raise ValueError("Risk View column limit must be between 1 and 50")
        density = str(display["density"]).strip().casefold()
        if density not in {"compact", "comfortable"}:
            raise ValueError("Risk View density is invalid")
        if not isinstance(display["show_zeros"], bool) or not isinstance(
            display["sticky_headers"], bool
        ):
            raise ValueError("Risk View display flags must be boolean")
        return cls(
            rows=rows,
            columns=columns,
            measures=measures,
            filters=_filters(value["filters"]),
            sort=_sort(value["sort"]),
            row_totals=totals["rows"],
            column_totals=totals["columns"],
            grand_total=totals["grand"],
            row_limit=row_limit,
            column_limit=column_limit,
            density=density,
            show_zeros=display["show_zeros"],
            sticky_headers=display["sticky_headers"],
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "rows": list(self.rows),
            "columns": list(self.columns),
            "measures": list(self.measures),
            "filters": {field: list(values) for field, values in self.filters},
            "sort": [
                {"field": field, "direction": direction}
                for field, direction in self.sort
            ],
            "totals": {
                "rows": self.row_totals,
                "columns": self.column_totals,
                "grand": self.grand_total,
            },
            "display": {
                "row_limit": self.row_limit,
                "column_limit": self.column_limit,
                "density": self.density,
                "show_zeros": self.show_zeros,
                "sticky_headers": self.sticky_headers,
            },
        }


CROSS_PIVOT_SPEC: Final = PivotSpec(
    rows=(
        "risk greek",
        "display bucket",
        "group",
        "reported underlying",
        "underlying",
        "tenor swap",
        "tenor option",
        "split",
        "activity",
    ),
    columns=(),
    measures=("risk", "drisk", "pl", "move"),
)
SPLITVA_PIVOT_SPEC: Final = PivotSpec(
    rows=(
        "risk greek",
        "display bucket",
        "group",
        "reported underlying",
        "underlying",
        "tenor swap",
        "tenor option",
        "split",
    ),
    columns=("activity",),
    measures=("risk", "drisk", "pl"),
    column_totals=True,
)
BUILTIN_PIVOT_SPECS: Final = {
    "cross": CROSS_PIVOT_SPEC,
    "splitva": SPLITVA_PIVOT_SPEC,
}


@dataclass(frozen=True)
class SavedRiskView:
    identifier: str
    name: str
    pivot: PivotSpec

    def option(self) -> dict[str, str]:
        return {"label": self.name, "value": self.identifier}


class RiskViewRepository:
    """Atomically persist small Custom View JSON documents under one root."""

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root).resolve()
        self._lock = RLock()

    @property
    def root(self) -> Path:
        return self._root

    def _path(self, identifier: object) -> Path:
        normalized = str(identifier).strip().casefold()
        if not _IDENTIFIER_PATTERN.fullmatch(normalized):
            raise ValueError("Risk View identifier is invalid")
        path = (self._root / f"{normalized}.json").resolve()
        if path.parent != self._root:
            raise ValueError("Risk View path escapes its repository")
        return path

    def _decode(self, path: Path) -> SavedRiskView:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"Could not read Risk View {path.name!r}: {exc}") from exc
        if not isinstance(payload, Mapping) or set(payload) != {
            "version",
            "id",
            "name",
            "pivot",
        }:
            raise ValueError(f"Risk View {path.name!r} has unexpected fields")
        if payload["version"] != RISK_VIEW_VERSION:
            raise ValueError(f"Risk View {path.name!r} uses an unsupported version")
        name = normalize_saved_view_name(payload["name"])
        identifier = str(payload["id"]).strip().casefold()
        if path.stem != identifier or identifier != _identifier(name):
            raise ValueError(f"Risk View {path.name!r} has inconsistent identity")
        return SavedRiskView(identifier, name, PivotSpec.from_dict(payload["pivot"]))

    def _write(self, view: SavedRiskView) -> None:
        self._root.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            dir=self._root,
            prefix=f".{view.identifier}.",
            suffix=".tmp",
            text=True,
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(
                    {
                        "version": RISK_VIEW_VERSION,
                        "id": view.identifier,
                        "name": view.name,
                        "pivot": view.pivot.to_dict(),
                    },
                    handle,
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self._path(view.identifier))
        finally:
            if temporary.exists():
                temporary.unlink()

    def list(self) -> tuple[SavedRiskView, ...]:
        if not self._root.exists():
            return ()
        if not self._root.is_dir():
            raise ValueError("Risk View repository is not a directory")
        views = tuple(self._decode(path) for path in self._root.glob("*.json"))
        if len({view.name.casefold() for view in views}) != len(views):
            raise ValueError("Risk View repository contains duplicate names")
        return tuple(sorted(views, key=lambda view: (view.name.casefold(), view.name)))

    def get(self, identifier: object) -> SavedRiskView:
        path = self._path(identifier)
        if not path.is_file():
            raise FileNotFoundError(f"Risk View {path.stem!r} does not exist")
        return self._decode(path)

    def save_new(
        self, name: object, pivot: PivotSpec | Mapping[str, object]
    ) -> SavedRiskView:
        normalized_name = normalize_saved_view_name(name)
        normalized_pivot = (
            pivot if isinstance(pivot, PivotSpec) else PivotSpec.from_dict(pivot)
        )
        view = SavedRiskView(
            _identifier(normalized_name), normalized_name, normalized_pivot
        )
        with self._lock:
            existing = self.list()
            if any(
                item.name.casefold() == normalized_name.casefold() for item in existing
            ):
                raise ValueError(
                    f"A Risk View named {normalized_name!r} already exists"
                )
            if len(existing) >= MAX_RISK_VIEWS:
                raise ValueError(
                    f"Risk View repository is limited to {MAX_RISK_VIEWS} views"
                )
            self._write(view)
        return view

    def update(
        self, identifier: object, pivot: PivotSpec | Mapping[str, object]
    ) -> SavedRiskView:
        normalized_pivot = (
            pivot if isinstance(pivot, PivotSpec) else PivotSpec.from_dict(pivot)
        )
        with self._lock:
            current = self.get(identifier)
            updated = SavedRiskView(current.identifier, current.name, normalized_pivot)
            self._write(updated)
        return updated

    def rename(self, identifier: object, name: object) -> SavedRiskView:
        normalized_name = normalize_saved_view_name(name)
        with self._lock:
            current = self.get(identifier)
            if any(
                item.identifier != current.identifier
                and item.name.casefold() == normalized_name.casefold()
                for item in self.list()
            ):
                raise ValueError(
                    f"A Risk View named {normalized_name!r} already exists"
                )
            renamed = SavedRiskView(
                _identifier(normalized_name), normalized_name, current.pivot
            )
            self._write(renamed)
            if renamed.identifier != current.identifier:
                self._path(current.identifier).unlink()
        return renamed

    def delete(self, identifier: object) -> SavedRiskView:
        with self._lock:
            current = self.get(identifier)
            self._path(current.identifier).unlink()
        return current

    def clone_builtin(self, builtin: object, name: object) -> SavedRiskView:
        key = str(builtin).strip().casefold()
        if key not in BUILTIN_PIVOT_SPECS:
            raise ValueError("Risk View built-in must be Cross or SplitVA")
        return self.save_new(name, BUILTIN_PIVOT_SPECS[key])


__all__ = [
    "BUILTIN_PIVOT_SPECS",
    "CROSS_PIVOT_SPEC",
    "MAX_RISK_VIEWS",
    "RISK_VIEW_DIMENSIONS",
    "RISK_VIEW_MEASURES",
    "RISK_VIEW_VERSION",
    "SPLITVA_PIVOT_SPEC",
    "PivotSpec",
    "RiskViewRepository",
    "SavedRiskView",
]
