"""Small structured timing helpers for startup, pages, and lazy queries."""

from __future__ import annotations

from contextlib import contextmanager
import logging
import os
from time import perf_counter
from typing import Any, Iterator, MutableMapping


_SAFE_FIELDS = frozenset(
    {
        "revision",
        "rows",
        "cells",
        "bytes",
        "dates",
        "cache_hit",
        "kind",
        "operation",
        "status",
    }
)
_warned: set[tuple[str, object]] = set()


def configure_runtime_logging() -> int:
    """Configure one concise process-wide log level from ``CUBE_LOG_LEVEL``.

    Application timings use ordinary logging rather than prints so Plotly and
    Gunicorn capture the same records as a local run. Invalid values fall back
    to ``INFO`` and any existing handler setup is left intact.
    """

    raw_level = os.getenv("CUBE_LOG_LEVEL", "INFO").strip().upper()
    # ``getLevelNamesMapping`` was added in Python 3.11.  ``getLevelName`` has
    # accepted a level name since Python 3.4, so keep startup compatible with
    # older deployment runtimes while retaining the same INFO fallback.
    resolved_level = logging.getLevelName(raw_level)
    level = resolved_level if isinstance(resolved_level, int) else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    logging.getLogger().setLevel(level)
    return level


def _safe_metrics(values: MutableMapping[str, Any]) -> dict[str, Any]:
    """Keep timing records bounded and free of financial identities/values."""

    return {key: values[key] for key in _SAFE_FIELDS if key in values}


@contextmanager
def perf_span(
    logger: Any,
    event: str,
    *,
    budget_ms: float | None = None,
    **fields: Any,
) -> Iterator[MutableMapping[str, Any]]:
    """Log one monotonic duration and warn once when its budget is exceeded.

    The yielded mapping may be updated with safe counts such as ``rows`` or
    ``bytes`` before the context exits. Exact identities and financial values
    are intentionally not accepted into the emitted record.
    """

    label = str(event).strip()
    if not label:
        raise ValueError("performance event must be non-blank")
    if budget_ms is not None and float(budget_ms) <= 0:
        raise ValueError("performance budget_ms must be positive")

    metrics: MutableMapping[str, Any] = dict(fields)
    started = perf_counter()
    try:
        yield metrics
    except BaseException:
        metrics["status"] = "error"
        raise
    else:
        metrics.setdefault("status", "ok")
    finally:
        elapsed_ms = (perf_counter() - started) * 1_000.0
        duration_ms = round(elapsed_ms, 3)
        payload = {
            "event": label,
            "duration_ms": duration_ms,
            **_safe_metrics(metrics),
        }
        over_budget = budget_ms is not None and elapsed_ms > float(budget_ms)
        warning_key = (label, payload.get("revision"))
        if over_budget and warning_key not in _warned:
            _warned.add(warning_key)
            logger.warning(
                "Cube performance budget exceeded: %s",
                payload,
                extra={"cube_performance": payload},
            )
        else:
            logger.info(
                "Cube performance: %s",
                payload,
                extra={"cube_performance": payload},
            )


def reset_performance_warnings() -> None:
    """Clear process-local warning de-duplication for deterministic tests."""

    _warned.clear()


__all__ = [
    "configure_runtime_logging",
    "perf_span",
    "reset_performance_warnings",
]
