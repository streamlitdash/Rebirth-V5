import pytest
from dash import html, no_update
from dash.exceptions import PreventUpdate

from cube.ui.s08_refresh_views import refresh_view


def test_normal_output_receipt_and_mount_match():
    @refresh_view("test", revision_arg="revision", outputs=2, content=[1], stamp=[1])
    def callback(revision):
        return 5, html.Div("Result")
    value, panel, receipt = callback(9, {"id": "request-9"})
    assert value == 5
    assert receipt["revision"] == 9 and receipt["request_id"] == "request-9"
    assert receipt["status"] == "rendered"
    assert panel.to_plotly_json()["props"]["data-refresh-render"] == receipt["mounts"][0]
    assert panel.children.children == "Result"


@pytest.mark.parametrize("result", [(no_update, no_update), (1, no_update)])
def test_no_update_is_not_completion(result):
    @refresh_view("test", revision_arg="revision", outputs=2, content=[1])
    def callback(revision):
        return result
    assert callback(9, None)[-1] is no_update


def test_inactive_preventupdate_and_zero_revision():
    @refresh_view("test", revision_arg="revision", outputs=1, content=[0])
    def callback(revision):
        if revision == 1:
            raise PreventUpdate
        return html.Div("not a published result")
    assert callback(0, None)[-1] is no_update
    with pytest.raises(PreventUpdate):
        callback(1, None)


def test_failed_view_keeps_last_good_results():
    @refresh_view("test", revision_arg="revision", outputs=2, content=[1])
    def callback(revision):
        raise RuntimeError("Broken connector")
    one, two, receipt = callback(9, {"id": "request-9"})
    assert one is no_update and two is no_update
    assert receipt["status"] == "failed" and receipt["message"] == "Broken connector"


def test_error_component_is_failure_and_editor_uses_query_revision():
    @refresh_view("editor", revision_arg="query", outputs=2, content=[1], stamp=[1])
    def callback(query):
        return [], html.Div([html.Div("Unavailable", role="alert")])
    _, _, receipt = callback({"revision": 4}, None)
    assert receipt["revision"] == 4 and receipt["status"] == "failed"
    assert receipt["request_id"] is None
