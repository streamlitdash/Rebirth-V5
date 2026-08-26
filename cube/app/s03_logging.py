"""Small structured timing helpers for startup, pages, and lazy queries."""

from __future__ import annotations

from collections import deque
from contextlib import contextmanager
from datetime import datetime, timezone
import logging
import os
import re
import sys
from threading import RLock
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

_APPLICATION_LOG_RECORD_LIMIT = 200
_APPLICATION_LOG_RECORD_CHAR_LIMIT = 4_000
_APPLICATION_LOG_SNAPSHOT_LIMIT = 100
_APPLICATION_LOG_SNAPSHOT_CHAR_LIMIT = 64_000
_APPLICATION_LOG_NAMES = ("cube", "app", "__main__", "dash.dash")
_OPERATOR_EVENT_FIELDS = (
    "status",
    "incident",
    "stage",
    "source",
    "product",
    "function",
    "error_type",
    "revision",
    "attempt",
    "elapsed_seconds",
    "duration_ms",
    "rows",
    "calls",
)
_OPERATOR_VALUE_PATTERN = re.compile(r"[^A-Za-z0-9 _./:+-]")
_SECRET_PATTERN = re.compile(
    r"(?i)\b(password|passwd|secret|token|authorization|api[_ -]?key)\b"
    r"([\"']?\s*[:=]\s*)(?P<quote>[\"']?)"
    r"(?:(?:bearer|basic)\s+)?"
    r".*?(?P=quote)(?=\s*(?:[,;} ]|$))"
)


def _browser_safe_text(value: object) -> str:
    """Bound one terminal/error message and mask common credential fields."""

    text = str(value).replace("\x00", "")
    return _SECRET_PATTERN.sub(r"\1\2[redacted]", text)


def _safe_operator_value(value: object, *, limit: int = 100) -> str:
    """Return one short identifier/count value, never arbitrary log text."""

    if isinstance(value, bool):
        rendered = str(value).lower()
    elif isinstance(value, (int, float)):
        rendered = str(value)
    else:
        rendered = _OPERATOR_VALUE_PATTERN.sub("_", str(value).replace("\n", " "))
    return rendered[:limit] or "unknown"


def _render_operator_record(record: logging.LogRecord) -> str | None:
    """Render structured events plus actionable application errors."""

    raw_event = getattr(record, "cube_operator_event", None)
    timestamp = datetime.fromtimestamp(record.created, tz=timezone.utc).strftime(
        "%Y-%m-%d %H:%M:%S UTC"
    )
    if isinstance(raw_event, dict):
        event = _safe_operator_value(raw_event.get("event", "Application event"))
        fields = [
            f"{field}={_safe_operator_value(raw_event[field])}"
            for field in _OPERATOR_EVENT_FIELDS
            if raw_event.get(field) is not None
        ]
        suffix = f" | {' '.join(fields)}" if fields else ""
        summary = f"{timestamp} {record.levelname} {event}{suffix}"
        if record.levelno < logging.WARNING:
            return summary
        message = _browser_safe_text(record.getMessage())
        if record.exc_info:
            formatter = logging.Formatter()
            traceback = formatter.formatException(record.exc_info)
            message = f"{message}\n{_browser_safe_text(traceback)}"
        return f"{summary}\n{message}"
    if record.levelno < logging.WARNING:
        return None
    message = _browser_safe_text(record.getMessage())
    if record.exc_info:
        formatter = logging.Formatter()
        message = f"{message}\n{_browser_safe_text(formatter.formatException(record.exc_info))}"
    return f"{timestamp} {record.levelname} {record.name} {message}"


class _BoundedApplicationLogHandler(logging.Handler):
    """Keep a small process-local copy of operator events and terminal text."""

    def __init__(self) -> None:
        super().__init__(level=logging.NOTSET)
        self._entries: deque[str] = deque(maxlen=_APPLICATION_LOG_RECORD_LIMIT)
        self._entries_lock = RLock()

    @staticmethod
    def _accepts(record: logging.LogRecord) -> bool:
        if record.levelno >= logging.ERROR:
            return True
        name = str(record.name)
        return any(
            name == prefix or name.startswith(f"{prefix}.")
            for prefix in _APPLICATION_LOG_NAMES
        )

    def emit(self, record: logging.LogRecord) -> None:
        if not self._accepts(record):
            return
        try:
            rendered = _render_operator_record(record)
            if rendered is None:
                return
            if len(rendered) > _APPLICATION_LOG_RECORD_CHAR_LIMIT:
                # Preserve both identity/context at the start and the final
                # diagnostic fields at the end if this limit is ever reached.
                half = (_APPLICATION_LOG_RECORD_CHAR_LIMIT - 28) // 2
                rendered = f"{rendered[:half]} ... [truncated] ... {rendered[-half:]}"
            with self._entries_lock:
                self._entries.append(rendered)
        except Exception:
            self.handleError(record)

    def clear_entries(self) -> None:
        with self._entries_lock:
            self._entries.clear()

    def append_terminal_text(self, source: str, value: object) -> None:
        """Append one complete stdout line without logging recursion."""

        message = _browser_safe_text(value).strip()
        if not message:
            return
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        rendered = f"{timestamp} {source} {message}"
        if len(rendered) > _APPLICATION_LOG_RECORD_CHAR_LIMIT:
            rendered = (
                rendered[: _APPLICATION_LOG_RECORD_CHAR_LIMIT - 16] + " ... [truncated]"
            )
        with self._entries_lock:
            self._entries.append(rendered)

    def snapshot(
        self,
        *,
        limit: int = _APPLICATION_LOG_SNAPSHOT_LIMIT,
        max_chars: int = _APPLICATION_LOG_SNAPSHOT_CHAR_LIMIT,
    ) -> tuple[str, ...]:
        """Return the newest complete records within both response bounds."""

        bounded_limit = max(1, min(int(limit), _APPLICATION_LOG_RECORD_LIMIT))
        bounded_chars = max(
            1, min(int(max_chars), _APPLICATION_LOG_SNAPSHOT_CHAR_LIMIT)
        )
        with self._entries_lock:
            all_entries = list(self._entries)
        candidates = all_entries[-bounded_limit:]
        selected: list[str] = []
        used = 0
        # Reserve enough room for the bounded omission notice whenever the
        # response may need one. This keeps the final joined text below the
        # network cap without cutting a structured event in the middle.
        entry_budget = max(1, bounded_chars - (80 if len(all_entries) > 1 else 0))
        for entry in reversed(candidates):
            cost = len(entry) + (2 if selected else 0)
            if used + cost > entry_budget:
                break
            selected.append(entry)
            used += cost
        selected.reverse()
        omitted = len(all_entries) - len(selected)
        if omitted:
            selected.insert(
                0, f"... {omitted} earlier application log record(s) omitted ..."
            )
        return tuple(selected)


_APPLICATION_LOG_HANDLER = _BoundedApplicationLogHandler()


class _TerminalTee:
    """Forward stdout to Jupyter and mirror complete print lines to App Logs."""

    def __init__(self, stream: object, source: str) -> None:
        self._stream = stream
        self._source = source
        self._pending = ""
        self._lock = RLock()
        self._cube_terminal_tee = True

    def write(self, value: object) -> int:
        text = str(value)
        written = self._stream.write(text)
        with self._lock:
            self._pending += text
            lines = self._pending.splitlines(keepends=True)
            self._pending = ""
            for line in lines:
                if line.endswith(("\n", "\r")):
                    _APPLICATION_LOG_HANDLER.append_terminal_text(
                        self._source, line.rstrip("\r\n")
                    )
                else:
                    self._pending = line
        return len(text) if written is None else int(written)

    def flush(self) -> None:
        self._stream.flush()

    def __getattr__(self, name: str) -> object:
        return getattr(self._stream, name)


def _install_terminal_tees() -> None:
    """Install the stdout mirror once without changing terminal output."""

    if not getattr(sys.stdout, "_cube_terminal_tee", False):
        sys.stdout = _TerminalTee(sys.stdout, "STDOUT")


def attach_application_log_handler(logger: logging.Logger) -> None:
    """Attach one safe copy without mirroring the logger through stdout too."""

    for handler in logger.handlers:
        if not isinstance(handler, logging.StreamHandler):
            continue
        stream = getattr(handler, "stream", None)
        if isinstance(stream, _TerminalTee):
            # Dash may create its stdout handler after stdout was wrapped.
            # Keep that handler visible in Jupyter, but bypass the mirror
            # because this logger receives the bounded handler directly below.
            handler.setStream(stream._stream)

    if _APPLICATION_LOG_HANDLER not in logger.handlers:
        logger.addHandler(_APPLICATION_LOG_HANDLER)


def recent_application_log_text() -> str:
    """Return a bounded browser-safe snapshot of structured operator events."""

    entries = _APPLICATION_LOG_HANDLER.snapshot()
    return (
        "\n\n".join(entries) if entries else "No application log entries captured yet."
    )


def clear_application_logs() -> None:
    """Clear only the bounded operator copy; normal terminal logs are untouched."""

    _APPLICATION_LOG_HANDLER.clear_entries()


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
    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    _APPLICATION_LOG_HANDLER.setLevel(level)
    attach_application_log_handler(root_logger)
    _install_terminal_tees()
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
        operator_event = {
            "event": f"Performance {label}",
            "status": payload.get("status"),
            "duration_ms": duration_ms,
            "revision": payload.get("revision"),
            "rows": payload.get("rows"),
        }
        if over_budget and warning_key not in _warned:
            _warned.add(warning_key)
            logger.warning(
                "Cube performance budget exceeded: %s",
                payload,
                extra={
                    "cube_performance": payload,
                    "cube_operator_event": operator_event,
                },
            )
        else:
            logger.info(
                "Cube performance: %s",
                payload,
                extra={
                    "cube_performance": payload,
                    "cube_operator_event": operator_event,
                },
            )


def reset_performance_warnings() -> None:
    """Clear process-local warning de-duplication for deterministic tests."""

    _warned.clear()


__all__ = [
    "attach_application_log_handler",
    "clear_application_logs",
    "configure_runtime_logging",
    "perf_span",
    "recent_application_log_text",
    "reset_performance_warnings",
]
