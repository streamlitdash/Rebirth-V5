"""Process-owned cold-start coordination for the risk cube."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from threading import RLock, Thread, Timer
from time import monotonic, sleep
from typing import Any

from cube.services.s01_snapshots import RefreshInProgressError, StaleRefreshError

from .s02_contracts import RefreshManagerProtocol


STARTUP_COORDINATOR_CONFIG_KEY = "CUBE_STARTUP_COORDINATOR"
STARTUP_UI_ERROR_CONFIG_KEY = "CUBE_STARTUP_UI_ERROR"


@dataclass(frozen=True)
class StartupStatus:
    """Small lock-safe view of the one process-wide cold-start attempt."""

    phase: str
    attempt: int
    server_boot_id: str
    attempt_id: str | None
    elapsed_seconds: float
    error: str | None
    retryable: bool
    worker_alive: bool


class StartupCoordinator:
    """Run revision 1 outside the Dash request thread.

    The coordinator belongs to one application process, not to a browser
    session. Every browser follows the same writer, so repeated interval
    callbacks and simultaneous first visitors cannot launch duplicate source
    calls. Python cannot safely kill an arbitrary connector call; the
    watchdog therefore reports a stalled call while retaining ownership until
    that worker returns. This is deliberate: starting another writer would be
    more dangerous than waiting for the connector's own I/O timeout.
    """

    def __init__(
        self,
        manager: RefreshManagerProtocol,
        *,
        timeout_seconds: float = 2400.0,
        logger: Any = None,
    ) -> None:
        self._manager = manager
        self._timeout_seconds = max(1.0, float(timeout_seconds))
        self._logger = logger
        self._lock = RLock()
        self._server_boot_id = uuid.uuid4().hex
        self._phase = "idle"
        self._attempt = 0
        self._attempt_id: str | None = None
        self._started_at = 0.0
        self._error: str | None = None
        self._worker: Thread | None = None
        self._start_timer: Timer | None = None

    @property
    def timeout_seconds(self) -> float:
        return self._timeout_seconds

    def _revision(self) -> int:
        try:
            return int(self._manager.health.revision)
        except Exception:
            return 0

    @staticmethod
    def _bounded_value(value: object, *, limit: int = 120) -> str:
        text = " ".join(str(value).split())
        return text if len(text) <= limit else f"{text[: limit - 3]}..."

    @classmethod
    def _progress_context(cls, progress: object | None) -> str:
        fields: list[str] = []
        for name, value in (
            ("stage", getattr(progress, "stage", None)),
            ("function", getattr(progress, "function_name", None)),
            ("source", getattr(progress, "source_type", None)),
            ("underlying", getattr(progress, "underlying", None)),
            ("product", getattr(progress, "product_label", None)),
        ):
            if name == "stage" and value == "error":
                # The refresh manager uses ``error`` as a terminal UI state;
                # it is not the financial stage where the exception occurred.
                continue
            if value not in (None, ""):
                fields.append(f"{name}={cls._bounded_value(value)}")
        product_index = int(getattr(progress, "product_index", 0) or 0)
        product_total = int(getattr(progress, "product_total", 0) or 0)
        if product_index > 0 or product_total > 0:
            fields.append(f"item={max(0, product_index)}/{max(0, product_total)}")
        return " ".join(fields)

    @classmethod
    def _error_reason(cls, error: BaseException) -> str:
        detail = cls._bounded_value(error, limit=700) or "no detail"
        return f"{type(error).__name__}: {detail}"

    @classmethod
    def _error_text(
        cls,
        error: BaseException,
        *,
        progress: object | None = None,
    ) -> str:
        progress_error = cls._bounded_value(
            getattr(progress, "error", None) or "",
            limit=1_250,
        )
        if progress_error:
            return f"Initial data load failed. {progress_error}"[:1_500]
        labels: list[str] = []
        for value in (
            getattr(progress, "stage", None),
            getattr(progress, "source_type", None),
            getattr(progress, "product_label", None),
        ):
            if value not in (None, "", "idle", "starting", "error"):
                labels.append(cls._bounded_value(value))
        context = f" during {' / '.join(labels)}" if labels else ""
        return (
            f"Initial data load failed{context}: {type(error).__name__}. "
            "Check the terminal for the exact reason."
        )[:1_500]

    def start(self, *, retry: bool = False) -> bool:
        """Start one writer, returning whether a new worker was launched."""
        with self._lock:
            if self._revision() > 0:
                self._phase = "succeeded"
                self._error = None
                return False
            worker_alive = self._worker is not None and self._worker.is_alive()
            if worker_alive or self._phase in {"running", "stalled", "succeeded"}:
                return False
            if self._phase == "failed" and not retry:
                return False

            if self._start_timer is not None:
                self._start_timer.cancel()
                self._start_timer = None
            self._attempt += 1
            attempt = self._attempt
            self._attempt_id = f"{self._server_boot_id}:{attempt}"
            self._phase = "running"
            self._error = None
            self._started_at = monotonic()
            worker = Thread(
                target=self._run,
                args=(attempt,),
                name=f"cube-startup-{attempt}",
                daemon=True,
            )
            self._worker = worker
            worker.start()
            if self._logger is not None:
                self._logger.info(
                    "Cube initial load started; boot=%s attempt=%s.",
                    self._server_boot_id,
                    self._attempt_id,
                    extra={
                        "cube_operator_event": {
                            "event": "Initial load started",
                            "status": "running",
                            "attempt": self._attempt,
                        }
                    },
                )
            return True

    def schedule_start(self, *, delay_seconds: float = 0.25) -> bool:
        """Schedule at most one delayed first-paint start for this process."""
        delay = max(0.0, float(delay_seconds))
        with self._lock:
            if self._revision() > 0:
                self._phase = "succeeded"
                self._error = None
                return False
            worker_alive = self._worker is not None and self._worker.is_alive()
            timer_alive = self._start_timer is not None and self._start_timer.is_alive()
            if worker_alive or timer_alive or self._phase != "idle":
                return False

            timer: Timer

            def launch() -> None:
                try:
                    self.start()
                finally:
                    with self._lock:
                        if self._start_timer is timer:
                            self._start_timer = None

            timer = Timer(delay, launch)
            timer.daemon = True
            self._start_timer = timer
            timer.start()
            return True

    def status(self) -> StartupStatus:
        """Return current state and apply the non-destructive watchdog."""
        with self._lock:
            if self._revision() > 0:
                self._phase = "succeeded"
                self._error = None
            worker_alive = self._worker is not None and self._worker.is_alive()
            elapsed = (
                max(0.0, monotonic() - self._started_at) if self._started_at else 0.0
            )
            if (
                self._phase == "running"
                and worker_alive
                and elapsed >= self._timeout_seconds
            ):
                function_name = None
                try:
                    function_name = self._manager.progress.function_name
                except Exception:
                    pass
                active = f" Active call: {function_name}." if function_name else ""
                self._phase = "stalled"
                self._error = (
                    f"Initial load has exceeded the {self._timeout_seconds:g}-second "
                    f"watchdog.{active} The original connector call still owns the "
                    "writer; configure an I/O timeout in that connector."
                )
                if self._logger is not None:
                    try:
                        progress = self._manager.progress
                    except Exception:
                        progress = None
                    self._logger.error(
                        "Cube initial load stalled; boot=%s attempt=%s "
                        "elapsed_seconds=%.3f context=[%s]",
                        self._server_boot_id,
                        self._attempt_id,
                        elapsed,
                        self._progress_context(progress) or "unavailable",
                        extra={
                            "cube_operator_event": {
                                "event": "Initial load stalled",
                                "status": "stalled",
                                "stage": getattr(progress, "stage", None),
                                "source": getattr(progress, "source_type", None),
                                "product": getattr(progress, "product_label", None),
                                "function": getattr(progress, "function_name", None),
                                "attempt": self._attempt,
                                "elapsed_seconds": round(elapsed, 3),
                            }
                        },
                    )
            return StartupStatus(
                phase=self._phase,
                attempt=self._attempt,
                server_boot_id=self._server_boot_id,
                attempt_id=self._attempt_id,
                elapsed_seconds=elapsed,
                error=self._error,
                retryable=self._phase == "failed",
                worker_alive=worker_alive,
            )

    def _succeed(self, attempt: int) -> None:
        with self._lock:
            if attempt != self._attempt:
                return
            self._phase = "succeeded"
            self._error = None
            attempt_id = self._attempt_id
        if self._logger is not None:
            self._logger.info(
                "Cube initial load succeeded; boot=%s attempt=%s.",
                self._server_boot_id,
                attempt_id,
                extra={
                    "cube_operator_event": {
                        "event": "Initial load succeeded",
                        "status": "succeeded",
                        "attempt": attempt,
                    }
                },
            )

    def _fail(self, attempt: int, error: BaseException) -> None:
        try:
            failed_progress = self._manager.progress
        except Exception:
            failed_progress = None
        message = self._error_text(error, progress=failed_progress)
        with self._lock:
            if attempt != self._attempt:
                return
            self._phase = "failed"
            self._error = message
            attempt_id = self._attempt_id
        if self._logger is not None:
            self._logger.error(
                "Cube initial data load failed; boot=%s attempt=%s reason=%s "
                "context=[%s]",
                self._server_boot_id,
                attempt_id,
                self._error_reason(error),
                self._progress_context(failed_progress) or "unavailable",
                exc_info=(type(error), error, error.__traceback__),
                extra={
                    "cube_operator_event": {
                        "event": "Initial data load failed",
                        "status": "failed",
                        "stage": getattr(failed_progress, "stage", None),
                        "source": getattr(failed_progress, "source_type", None),
                        "product": getattr(failed_progress, "product_label", None),
                        "function": getattr(failed_progress, "function_name", None),
                        "error_type": type(error).__name__,
                        "attempt": attempt,
                    }
                },
            )

    def _follow_existing_writer(self, attempt: int) -> None:
        while True:
            if self._revision() > 0:
                self._succeed(attempt)
                return
            try:
                progress = self._manager.progress
                running = bool(progress.running)
                progress_error = progress.error
            except Exception as error:
                self._fail(attempt, error)
                return
            if not running:
                self._fail(
                    attempt,
                    RuntimeError(
                        str(progress_error)
                        if progress_error
                        else "The existing refresh ended without publishing revision 1."
                    ),
                )
                return
            sleep(0.2)

    def _run(self, attempt: int) -> None:
        try:
            if self._revision() > 0:
                self._succeed(attempt)
                return
            self._manager.refresh(
                forced_dates={},
                view_date=None,
                commodity_market_enabled=False,
                risk_checker_enabled=True,
                reason="initial load",
                expected_revision=0,
                copy_result=False,
            )
            if self._revision() <= 0:
                raise RuntimeError(
                    "Initial refresh returned without publishing revision 1."
                )
            self._succeed(attempt)
        except RefreshInProgressError:
            self._follow_existing_writer(attempt)
        except StaleRefreshError:
            if self._revision() > 0:
                self._succeed(attempt)
            else:
                self._fail(
                    attempt,
                    RuntimeError(
                        "The initial refresh became stale before revision 1 was published."
                    ),
                )
        except Exception as error:
            if self._revision() > 0:
                self._succeed(attempt)
            else:
                self._fail(attempt, error)


__all__ = [
    "STARTUP_COORDINATOR_CONFIG_KEY",
    "STARTUP_UI_ERROR_CONFIG_KEY",
    "StartupCoordinator",
    "StartupStatus",
]
