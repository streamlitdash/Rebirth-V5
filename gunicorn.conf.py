"""Gunicorn settings for process-local refresh and progress state."""

import os


# One worker owns the in-memory snapshot; threads keep progress endpoints live.
workers = 1
threads = int(os.getenv("GUNICORN_THREADS", "4"))
worker_class = "gthread"
timeout = int(os.getenv("GUNICORN_TIMEOUT_SECONDS", "300"))
graceful_timeout = 30
keepalive = 5
