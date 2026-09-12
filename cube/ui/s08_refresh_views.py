"""Small completion receipts returned with the existing visible callback results."""

from functools import wraps
import inspect
import logging
import uuid
from collections.abc import Mapping

from dash import html, no_update
from dash.exceptions import PreventUpdate

LOGGER = logging.getLogger(__name__)


def _error_message(value):
    if isinstance(value, (list, tuple)):
        return next((message for item in value if (message := _error_message(item))), "")
    if not hasattr(value, "to_plotly_json"):
        return ""
    props = value.to_plotly_json().get("props", {})
    if props.get("role") == "alert" or "has-error" in str(props.get("className", "")).split():
        return str(props.get("children") or "The displayed result could not be loaded")[:1000]
    return _error_message(props.get("children"))


def refresh_view(owner, *, revision_arg, outputs, content, stamp=(), ready=None):
    """Append one receipt; the final callback State is the browser request.

    ``ready`` maps non-children outputs (table data/graph figures) to their DOM
    IDs. Only updated outputs are awaited; closed or unchanged views add no work.
    This observes existing work. It neither starts work nor stores financial rows.
    Keep this decorator directly below @app.callback, which owns the extra Output.
    """
    def decorate(function):
        signature = inspect.signature(function)

        @wraps(function)
        def wrapped(*args, **kwargs):
            request = args[-1]
            original_args = args[:-1]
            values = signature.bind(*original_args, **kwargs).arguments
            revision_value = values.get(revision_arg)
            if isinstance(revision_value, Mapping):
                revision_value = revision_value.get("revision")
            try:
                revision = int(revision_value or 0)
            except (TypeError, ValueError):
                revision = 0
            receipt = {
                "owner": owner, "revision": revision,
                "request_id": request.get("id") if isinstance(request, Mapping) else None,
                "status": "rendered", "message": "",
            }
            try:
                result = function(*original_args, **kwargs)
            except PreventUpdate:
                raise
            except Exception as exc:
                LOGGER.exception("Refresh view %s failed", owner)
                receipt.update(status="failed", message=str(exc)[:1000])
                return (*([no_update] * outputs), receipt)
            result = tuple(result) if outputs > 1 else (result,)
            if len(result) != outputs:
                raise ValueError(f"{owner}: expected {outputs} outputs, got {len(result)}")
            # Hidden/inactive callbacks and refresh revision zero acknowledge nothing.
            if revision <= 0 or all(result[index] is no_update for index in content):
                return (*result, no_update)
            message = _error_message([result[index] for index in content])
            if message:
                receipt.update(status="failed", message=message)
            result = list(result)
            receipt["mounts"] = []
            if ready:
                receipt["ready_ids"] = [
                    component_id for index, component_id in ready.items()
                    if result[index] is not no_update
                ]
            for index in stamp:
                if result[index] is no_update:
                    continue
                render_id = f"refresh-render-{uuid.uuid4().hex}"
                result[index] = html.Div(result[index], **{"data-refresh-render": render_id})
                receipt["mounts"].append(render_id)
            return (*result, receipt)

        return wrapped
    return decorate
