# Rebirth V3 implementation specifications

These documents define the proposed V3 target. They are not proof that the
current application implements that target: checked-in source, tests, and the
root [runtime manual](../../README.md) own current behavior. When documents
conflict, V3.2 wins for plot, playback, and Risk Explorer decisions.

## Read in this order

1. [V3.2 normative correction](v3.2/REVISION_V3_2.md) — latest plot,
   playback, navigation, preservation, and migration decisions.
2. [V3.1 preservation decisions](v3.1/README.md), its
   [implementation checklist](v3.1/IMPLEMENTATION_CHECKLIST.md), and the
   [V3.1 revision](v3.1/REVISION_V3_1.md).
3. Foundational chapters for [product and UI](01_product_ui_v3.md),
   [viability and simplification](02_viability_and_simplification.md), and
   [data-pipeline contracts](04_data_pipeline_contracts.md).
4. The earlier [V3 summary](REVISION_V3.md) for background only.
5. The [consolidated redesign archive](REVISION_UPDATES.md) for historical
   branch material only; later normative revisions supersede its conflicts.

The intended target remains a preservation-first refactor grounded in V1,
with exact financial tables, ProductSpec-owned plot dimensionality, isolated
historical playback, governed saved views, and fail-closed financial
boundaries. P&L and Stock history remain on their existing pages; the Data page
owns Risk and Market history.

No V3 HTML prototype, PDF bundle, machine-readable manifest, or checksum file
is checked in on this branch. Private credentials and connector bodies are
intentionally excluded.
