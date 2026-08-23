"""Lazy Data-page catalog and bounded Risk/Market history repository."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date
from pathlib import Path
from threading import RLock
from typing import ClassVar

import pandas as pd

from rebirth.domain.s08_pnl import MARKET_DATE
from rebirth.domain.s02_products import PRODUCT_SPECS_BY_SOURCE_TYPE
from rebirth.domain.s01_schema import PORTFOLIO_METADATA_COLUMNS
from rebirth.domain.s10_search import (
    QUICK_RISK_FILTER_COLUMNS,
    REPORTED_UNDERLYING,
    RISK_GREEK,
    RISK_TYPE,
    SOURCE_TYPE,
    SPLIT,
    UNDERLYING,
)

from .s02_contracts import (
    ALL_ARCHIVE_FILE_NAMES,
    MAPPED_HISTORY_VALUE,
    MAPPING_STATUS,
    MARKET_ARCHIVE_COLUMNS,
    PORTFOLIO,
    REVISION,
    RISK_DATE,
    RiskArchiveValidationError,
    SNAPSHOT_DATE,
)
from .s04_queries import (
    clear_archive_caches,
    load_full_market_history_for_identity,
    load_risk_history_for_identity,
)
from .s01_models import (
    HISTORY_CANONICAL_CELL_BUDGET,
    HISTORY_RAW_ROW_BUDGET,
    ORDER_AMBIGUOUS,
    ORDERED,
)
from .s01_models import (
    HistoryBundle,
    HistoryCatalogEntry,
    HistoryHandoff,
    HistoryIdentity,
    HistoryIdentityCatalog,
    HistoryOrdering,
    HistoryQuery,
    HistoryValidationError,
    _apply_risk_filters,
    _canonical_axis_order,
    _canonical_values,
    _date,
    _numeric_metric,
    _nonnegative_int,
    _positive_int,
    _text,
    resolve_actual_period_dates,
)
from .s05_store import ArchiveSQLStore

_DATE_LEAF = re.compile(r"\d{4}-\d{2}-\d{2}")


def _catalog_entries(
    generation: str,
    risk: pd.DataFrame,
    market: pd.DataFrame,
) -> HistoryIdentityCatalog:
    grouped: dict[
        tuple[str, str, str, str, str, tuple[tuple[str, str], ...]],
        dict[str, object],
    ] = {}
    for row in risk.to_dict("records"):
        source_type = str(row[SOURCE_TYPE]).strip()
        spec = PRODUCT_SPECS_BY_SOURCE_TYPE.get(source_type)
        if spec is None:
            raise HistoryValidationError(
                f"archive catalog contains unknown Source Type {source_type!r}"
            )
        axis_signature = tuple((axis.column, axis.order_column) for axis in spec.axes)
        for identity_mode, column in (
            ("reported", REPORTED_UNDERLYING),
            ("underlying", UNDERLYING),
        ):
            underlying = _text(row[column], label=column)
            key = (
                "risk",
                str(row[RISK_TYPE]).strip(),
                str(row[RISK_GREEK]).strip(),
                underlying,
                identity_mode,
                axis_signature,
            )
            selected = grouped.setdefault(
                key,
                {
                    "source_types": set(),
                    "revision": 0,
                    "snapshot_date": date.min,
                },
            )
            selected["source_types"].add(source_type)
            selected["revision"] = max(int(selected["revision"]), int(row[REVISION]))
            selected["snapshot_date"] = max(
                selected["snapshot_date"],
                _date(row[SNAPSHOT_DATE], label=SNAPSHOT_DATE),
            )

    entries: list[HistoryCatalogEntry] = []
    for key, selected in grouped.items():
        kind, risk_type, risk_greek, underlying, identity_mode, _axes = key
        entries.append(
            HistoryCatalogEntry(
                kind=kind,
                identity=HistoryIdentity(
                    source_types=tuple(sorted(selected["source_types"])),
                    risk_type=risk_type,
                    risk_greek=risk_greek,
                    underlying=underlying,
                    identity_mode=identity_mode,
                ),
                source_revision=int(selected["revision"]),
                snapshot_date=selected["snapshot_date"],
            )
        )

    for row in market.to_dict("records"):
        entries.append(
            HistoryCatalogEntry(
                kind="market",
                identity=HistoryIdentity(
                    source_types=(str(row[SOURCE_TYPE]).strip(),),
                    risk_type=str(row[RISK_TYPE]).strip(),
                    risk_greek=str(row[RISK_GREEK]).strip(),
                    underlying=_text(row[UNDERLYING], label=UNDERLYING),
                    identity_mode="underlying",
                ),
                source_revision=int(row[REVISION]),
                snapshot_date=_date(row[SNAPSHOT_DATE], label=SNAPSHOT_DATE),
            )
        )
    entries.sort(
        key=lambda entry: (
            0 if entry.kind == "risk" else 1,
            entry.identity.risk_type.casefold(),
            entry.identity.risk_greek.casefold(),
            entry.identity.underlying.casefold(),
            entry.identity.identity_mode,
            entry.identity.source_types,
        )
    )
    return HistoryIdentityCatalog(generation=generation, entries=tuple(entries))


def _risk_projection(handoff: HistoryHandoff) -> tuple[str, ...]:
    identity = handoff.identity
    columns = [
        SNAPSHOT_DATE,
        REVISION,
        RISK_DATE,
        SOURCE_TYPE,
        RISK_TYPE,
        RISK_GREEK,
        SPLIT,
        REPORTED_UNDERLYING,
        UNDERLYING,
    ]
    for axis in identity.axes:
        columns.extend((axis.column, axis.order_column))
    columns.extend((PORTFOLIO, *PORTFOLIO_METADATA_COLUMNS, *QUICK_RISK_FILTER_COLUMNS))
    columns.append(handoff.metric_column)
    return tuple(dict.fromkeys(columns))


class ArchiveHistoryRepository:
    """Lazy bounded adapter over atomic flat archive leaves."""

    _cache_clear_lock: ClassVar[RLock] = RLock()
    _cleared_reset_generations: ClassVar[dict[Path, int]] = {}

    def __init__(
        self,
        root: str | Path,
        *,
        max_rows: int = 100_000,
        max_dates: int = 2_000,
        max_raw_rows: int = HISTORY_RAW_ROW_BUDGET,
        max_cells: int = HISTORY_CANONICAL_CELL_BUDGET,
    ) -> None:
        self._root = Path(root).expanduser()
        self._max_rows = _positive_int(max_rows, label="max_rows")
        self._max_dates = _positive_int(max_dates, label="max_dates")
        self._max_raw_rows = _positive_int(max_raw_rows, label="max_raw_rows")
        self._max_cells = _positive_int(max_cells, label="max_cells")
        self._store = ArchiveSQLStore(self._root)
        self._catalog_lock = RLock()
        self._catalog_value: HistoryIdentityCatalog | None = None

    @property
    def root(self) -> Path:
        return self._root

    def generation(self) -> str:
        """Fingerprint immutable archive metadata without loading CSV frames."""

        root = self._root.resolve()
        if not root.exists():
            payload: object = {"root": str(root), "state": "missing"}
        elif not root.is_dir():
            raise HistoryValidationError(f"history root must be a directory: {root}")
        else:
            leaves: list[tuple[str, tuple[tuple[str, int, int], ...]]] = []
            for leaf in sorted(root.iterdir(), key=lambda path: path.name):
                if not leaf.is_dir() or not _DATE_LEAF.fullmatch(leaf.name):
                    continue
                files = tuple(
                    (name, path.stat().st_size, path.stat().st_mtime_ns)
                    for name in ALL_ARCHIVE_FILE_NAMES
                    if (path := leaf / name).is_file()
                )
                leaves.append((leaf.name, files))
            payload = {"root": str(root), "leaves": leaves}
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()

    fingerprint = generation

    def clear_reconstructable_cache(self) -> None:
        """Unconditionally clear process-local archive caches."""

        with type(self)._cache_clear_lock:
            self._store.clear()
            with self._catalog_lock:
                self._catalog_value = None
            clear_archive_caches()

    def clear_for_reset_generation(self, reset_generation: object) -> bool:
        """Clear shared caches once when a later reset generation is observed."""

        selected = _nonnegative_int(
            reset_generation,
            label="reset_generation",
        )
        if selected == 0:
            return False
        repository_type = type(self)
        root = self._root.resolve()
        with repository_type._cache_clear_lock:
            previous = repository_type._cleared_reset_generations.get(root, 0)
            if selected <= previous:
                return False
            self._store.clear()
            with self._catalog_lock:
                self._catalog_value = None
            clear_archive_caches()
            repository_type._cleared_reset_generations[root] = selected
            return True

    def catalog(self) -> HistoryIdentityCatalog:
        """Build the direct-selector index only after an explicit page callback."""

        generation = self.generation()
        with self._catalog_lock:
            if (
                self._catalog_value is not None
                and self._catalog_value.generation == generation
            ):
                return self._catalog_value
            risk, market = self._store.catalog_frames(generation)
            self._catalog_value = _catalog_entries(generation, risk, market)
            return self._catalog_value

    def _legacy_rows(self, handoff: HistoryHandoff) -> pd.DataFrame:
        """Keep completed V1-V3 fixtures readable without weakening V4 SQL."""

        identity = handoff.identity
        if handoff.kind == "risk":
            source_frames = [
                load_risk_history_for_identity(
                    self._root,
                    source_type,
                    identity.risk_type,
                    identity.risk_greek,
                    identity.underlying,
                    identity_mode=identity.identity_mode,
                    max_rows=self._max_rows,
                )
                for source_type in identity.source_types
            ]
            populated = [frame for frame in source_frames if not frame.empty]
            return (
                pd.concat(populated, ignore_index=True, sort=False)
                if populated
                else source_frames[0].iloc[0:0].copy()
            )
        return load_full_market_history_for_identity(
            self._root,
            identity.source_type,
            identity.risk_type,
            identity.risk_greek,
            identity.underlying,
            max_rows=self._max_rows,
        )

    def read(self, query: HistoryQuery) -> HistoryBundle:
        if not isinstance(query, HistoryQuery):
            raise HistoryValidationError("query must be a HistoryQuery")
        handoff = query.handoff
        identity = handoff.identity
        generation = self.generation()
        date_column = RISK_DATE if handoff.kind == "risk" else MARKET_DATE
        try:
            available_dates = tuple(
                _date(value, label=date_column)
                for value in self._store.available_dates(
                    generation,
                    kind=handoff.kind,
                    source_types=identity.source_types,
                    risk_type=identity.risk_type,
                    risk_greek=identity.risk_greek,
                    underlying=identity.underlying,
                    identity_mode=identity.identity_mode,
                )
            )
            legacy_raw = None
        except RiskArchiveValidationError as error:
            if "requires completed schema-v4 Parquet" not in str(error):
                raise
            legacy_raw = self._legacy_rows(handoff)
            available_dates = (
                tuple(
                    sorted(
                        {
                            _date(value, label=date_column)
                            for value in legacy_raw[date_column]
                        }
                    )
                )
                if not legacy_raw.empty
                else ()
            )
        dates = resolve_actual_period_dates(available_dates, query)
        if len(dates) > self._max_dates:
            raise HistoryValidationError(
                f"history query exceeds its {self._max_dates}-date bound"
            )
        if legacy_raw is not None:
            if legacy_raw.empty or not dates:
                period_rows = legacy_raw.iloc[0:0].copy()
            else:
                selected_date_values = set(dates)
                parsed_dates = legacy_raw[date_column].map(
                    lambda value: _date(value, label=date_column)
                )
                period_rows = legacy_raw.loc[
                    parsed_dates.isin(selected_date_values)
                ].copy()
        elif not dates:
            projection = (
                _risk_projection(handoff)
                if handoff.kind == "risk"
                else (SNAPSHOT_DATE, REVISION, *MARKET_ARCHIVE_COLUMNS)
            )
            period_rows = pd.DataFrame(columns=list(projection))
        else:
            projection = (
                _risk_projection(handoff)
                if handoff.kind == "risk"
                else (SNAPSHOT_DATE, REVISION, *MARKET_ARCHIVE_COLUMNS)
            )
            period_rows = self._store.rows(
                generation,
                kind=handoff.kind,
                source_types=identity.source_types,
                risk_type=identity.risk_type,
                risk_greek=identity.risk_greek,
                underlying=identity.underlying,
                identity_mode=identity.identity_mode,
                columns=projection,
                start_date=dates[0].isoformat(),
                end_date=dates[-1].isoformat(),
                max_rows=self._max_rows,
            )
            if len(period_rows) > self._max_rows:
                raise RiskArchiveValidationError(
                    f"historical {handoff.kind.title()} query exceeds its "
                    f"{self._max_rows}-row bound"
                )
            if handoff.kind == "risk":
                period_rows.insert(3, MAPPING_STATUS, MAPPED_HISTORY_VALUE)
        if handoff.kind == "risk":
            period_rows = _apply_risk_filters(period_rows, handoff.filter_view)
        if not period_rows.empty and date_column in period_rows:
            period_rows[date_column] = period_rows[date_column].map(
                lambda value: _date(value, label=date_column).isoformat()
            )
        if not period_rows.empty and SNAPSHOT_DATE in period_rows:
            period_rows[SNAPSHOT_DATE] = period_rows[SNAPSHOT_DATE].map(
                lambda value: _date(value, label=SNAPSHOT_DATE).isoformat()
            )
        period_rows = (
            _numeric_metric(period_rows, handoff.metric_column)
            if not period_rows.empty
            else period_rows
        )
        if len(period_rows) > self._max_raw_rows:
            suggestion = (
                "Choose a narrower period or more selective Risk filters."
                if handoff.kind == "risk"
                else "Choose a narrower period."
            )
            raise HistoryValidationError(
                f"Raw history has {len(period_rows):,} exact rows and exceeds the "
                f"{self._max_raw_rows:,}-row browser budget. {suggestion}"
            )
        axis_orders = tuple(
            _canonical_axis_order(period_rows, axis) for axis in identity.axes
        )
        ordering = HistoryOrdering(
            axes=axis_orders,
            status=(
                ORDER_AMBIGUOUS
                if any(axis.status == ORDER_AMBIGUOUS for axis in axis_orders)
                else ORDERED
            ),
        )
        values = _canonical_values(
            period_rows,
            kind=handoff.kind,
            date_column=date_column,
            dates=dates,
            metric_column=handoff.metric_column,
            ordering=ordering,
        )
        if len(values) > self._max_cells:
            raise HistoryValidationError(
                f"Canonical history has {len(values):,} cells and exceeds the "
                f"{self._max_cells:,}-cell browser budget. Choose a narrower period "
                "or exact identity."
            )
        selected_date = dates[-1] if dates else None
        if selected_date is None or period_rows.empty:
            selected_rows = period_rows.iloc[0:0].copy()
        else:
            selected_rows = period_rows.loc[
                period_rows[date_column]
                .map(lambda value: _date(value, label=date_column))
                .eq(selected_date)
            ].copy()
        return HistoryBundle(
            query=query,
            date_column=date_column,
            dates=dates,
            resolved_start=(dates[0] if dates else None),
            resolved_end=(dates[-1] if dates else None),
            selected_date=selected_date,
            metric_column=handoff.metric_column,
            ordering=ordering,
            values=values,
            selected_rows=selected_rows.reset_index(drop=True),
            raw_rows=period_rows.reset_index(drop=True),
            generation=generation,
        )


__all__ = ["ArchiveHistoryRepository"]
