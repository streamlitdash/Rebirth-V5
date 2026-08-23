"""Small, frame-free startup and refresh status serialization."""

from typing import Any

import pandas as pd

from rebirth.app.s02_contracts import RefreshManagerProtocol
from rebirth.app.s04_startup import StartupCoordinator


def progress_payload(
    refresh_manager: RefreshManagerProtocol | None,
    startup_coordinator: StartupCoordinator | None = None,
) -> dict[str, Any]:
    """Serialize optional progress without touching a financial snapshot lock."""

    progress: Any = None
    if refresh_manager is not None:
        try:
            progress = refresh_manager.progress
        except Exception:
            progress = None
    try:
        revision = (
            int(refresh_manager.health.revision) if refresh_manager is not None else 0
        )
    except Exception:
        revision = 0

    def timestamp(name: str) -> str | None:
        value = getattr(progress, name, None)
        return value.isoformat() if value is not None else None

    payload = {
        "attempt_id": getattr(progress, "attempt_id", None),
        "function_name": getattr(progress, "function_name", None),
        "source_type": getattr(progress, "source_type", None),
        "underlying": getattr(progress, "underlying", None),
        "product_label": getattr(progress, "product_label", None),
        "product_index": int(getattr(progress, "product_index", 0)),
        "product_total": int(getattr(progress, "product_total", 0)),
        "hold_seconds": float(getattr(progress, "hold_seconds", 0.0)),
        "stage": getattr(progress, "stage", "idle"),
        "current": int(getattr(progress, "current", 0)),
        "total": int(getattr(progress, "total", 0)),
        "message": getattr(
            progress, "message", "No live refresh progress is available."
        ),
        "running": bool(getattr(progress, "running", False)),
        "error": getattr(progress, "error", None),
        "started_at": timestamp("started_at"),
        "updated_at": timestamp("updated_at"),
        "finished_at": timestamp("finished_at"),
        "revision": revision,
        "server_time": pd.Timestamp.now(tz="UTC").isoformat(),
    }
    if startup_coordinator is not None:
        startup = startup_coordinator.status()
        payload.update(
            startup_phase=startup.phase,
            startup_attempt=startup.attempt,
            startup_attempt_id=startup.attempt_id,
            server_boot_id=startup.server_boot_id,
            startup_elapsed_seconds=startup.elapsed_seconds,
            startup_timeout_seconds=startup_coordinator.timeout_seconds,
            startup_retryable=startup.retryable,
        )
        if startup.error:
            payload["error"] = startup.error
    return payload


__all__ = ["progress_payload"]
