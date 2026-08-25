"""Application composition, startup, routing, and diagnostics.

The package deliberately has no eager imports: low-level timing and startup
modules must remain usable before the Dash factory imports page code.
"""
