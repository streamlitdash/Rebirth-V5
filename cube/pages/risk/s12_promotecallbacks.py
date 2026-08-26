"""V5 page-owned callbacks for explicit Risk promotion generations."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from time import perf_counter
from typing import Protocol

import pandas as pd
from dash import Dash, Input, Output, State, ctx, no_update

from cube.ui.s01_constants import RISK_FILTER_DIMENSION_FIELDS
from cube.app.s02_contracts import RefreshManagerProtocol

from .s11_promotion import (
    PROMOTION_GENERATION_STORE_ID,
    PROMOTION_RECALCULATE_ID,
    PROMOTION_RESET_ID,
    PROMOTION_STATUS_ID,
    PromotionBasis,
    PromotionGeneration,
    baseline_promotion_generation,
    calculate_current_view_promotion,
    promotion_basis_is_stale,
    promotion_basis_summary,
)


class RiskPromotionCacheProtocol(Protocol):
    @property
    def revision(self) -> int: ...

    def filtered(
        self,
        manager: RefreshManagerProtocol | None,
        active_risk_type: str | None,
        ir_family: str | None,
        splits: Sequence[str] | None,
        dimension_filters: Mapping[str, Sequence[str] | None],
        *,
        exclude_selected: bool = False,
        promotion_generation: Mapping[str, object] | None = None,
        reduced_tenor: bool = False,
    ) -> pd.DataFrame: ...

    def publish_promotion_generation(
        self,
        generation: PromotionGeneration,
    ) -> dict[str, object]: ...

    def resolve_promotion_generation(
        self,
        value: Mapping[str, object] | None,
    ) -> PromotionGeneration | None: ...


def register_promotion_callbacks(
    app: Dash,
    cache: RiskPromotionCacheProtocol,
    refresh_manager: RefreshManagerProtocol | None,
) -> None:
    """Register one promotion generation shared by every Risk Type view."""

    @app.callback(
        Output(PROMOTION_GENERATION_STORE_ID, "data"),
        Output(PROMOTION_STATUS_ID, "children"),
        Output(PROMOTION_STATUS_ID, "className"),
        Output(PROMOTION_RESET_ID, "disabled"),
        Output("promotion-generation-scope", "children"),
        Output(PROMOTION_RECALCULATE_ID, "children"),
        Output(PROMOTION_RECALCULATE_ID, "disabled"),
        Output(PROMOTION_RECALCULATE_ID, "aria-busy"),
        Input(PROMOTION_RECALCULATE_ID, "n_clicks"),
        Input(PROMOTION_RESET_ID, "n_clicks"),
        Input("data-revision-store", "data"),
        Input("dimension-filter-values-store", "data"),
        Input("risk-filter-exclude-applied-store", "data"),
        Input("risk-explorer-options", "value"),
        # The Risk reducer also owns this selector's value.  Capture it only
        # when the user explicitly recalculates to avoid a browser-side cycle.
        State("split-filter", "value"),
        State(PROMOTION_GENERATION_STORE_ID, "data"),
        prevent_initial_call=False,
    )
    def manage_promotion_generation(
        _recalculate_clicks,
        _reset_clicks,
        data_revision,
        filter_values,
        exclude_value,
        explorer_options,
        splits,
        current_store,
    ):
        revision = int(data_revision or cache.revision)
        applied_filter_values = filter_values or [
            [] for _field in RISK_FILTER_DIMENSION_FIELDS
        ]
        filters = {
            field.key: list(selected or [])
            for field, selected in zip(
                RISK_FILTER_DIMENSION_FIELDS,
                applied_filter_values,
                strict=True,
            )
        }
        reduced_tenor = "reduced-tenor" in {
            str(value) for value in (explorer_options or ())
        }
        basis = PromotionBasis.build(
            revision,
            risk_type=None,
            ir_family=None,
            splits=splits,
            filters=filters,
            exclude_selected="exclude" in (exclude_value or []),
            reduced_tenor=reduced_tenor,
        )
        scope = promotion_basis_summary(basis)
        baseline = baseline_promotion_generation(revision)
        try:
            current = PromotionGeneration.from_store(current_store)
        except (TypeError, ValueError):
            current = baseline

        triggered = ctx.triggered_id
        if triggered in {None, "data-revision-store", PROMOTION_RESET_ID} or (
            current.revision != revision
        ):
            return (
                baseline.to_store(),
                "Baseline promotion from the committed refresh is active.",
                "filter-note",
                True,
                "Scope: committed Activities 1–3 policy",
                "Recalculate all Risk views",
                False,
                "false",
            )

        if triggered == PROMOTION_RECALCULATE_ID:
            started = perf_counter()
            try:
                filtered = cache.filtered(
                    refresh_manager,
                    None,
                    None,
                    splits,
                    filters,
                    exclude_selected=basis.exclude_selected,
                    reduced_tenor=basis.reduced_tenor,
                )
                generation = calculate_current_view_promotion(filtered, basis)
                generation_store = cache.publish_promotion_generation(generation)
            except (TypeError, ValueError) as error:
                app.logger.warning(
                    "risk.promotion.calculate failed revision=%s error=%s",
                    revision,
                    error,
                )
                return (
                    baseline.to_store(),
                    f"Promotion recalculation failed; baseline restored: {error}",
                    "filter-note has-errors",
                    True,
                    scope,
                    "Recalculate all Risk views",
                    False,
                    "false",
                )
            elapsed_ms = (perf_counter() - started) * 1_000.0
            app.logger.info(
                "perf.risk.promotion.calculate revision=%s rows=%s elapsed_ms=%.1f",
                revision,
                len(filtered),
                elapsed_ms,
            )
            return (
                generation_store,
                (
                    f"All-Risk promotion is active ({len(generation.rows):,} "
                    f"exposures; {elapsed_ms:,.0f} ms)."
                ),
                "filter-note",
                False,
                scope,
                "Recalculate all Risk views",
                False,
                "false",
            )

        if promotion_basis_is_stale(current, basis):
            return (
                no_update,
                (
                    "Promotion uses the previous filter basis. Recalculate all "
                    "Risk views or reset to the committed baseline."
                ),
                "filter-note has-warning",
                False,
                scope,
                "Recalculate all Risk views",
                False,
                "false",
            )
        if current.kind == "current-view":
            active = cache.resolve_promotion_generation(current_store)
            if active is None:
                return (
                    baseline.to_store(),
                    "All-Risk promotion expired; committed baseline restored.",
                    "filter-note has-warning",
                    True,
                    "Scope: committed Activities 1–3 policy",
                    "Recalculate all Risk views",
                    False,
                    "false",
                )
            return (
                no_update,
                f"All-Risk promotion is active ({len(active.rows):,} exposures).",
                "filter-note",
                False,
                scope,
                "Recalculate all Risk views",
                False,
                "false",
            )
        return (
            no_update,
            "Baseline promotion from the committed refresh is active.",
            "filter-note",
            True,
            "Scope: committed Activities 1–3 policy",
            "Recalculate all Risk views",
            False,
            "false",
        )


__all__ = ["RiskPromotionCacheProtocol", "register_promotion_callbacks"]
