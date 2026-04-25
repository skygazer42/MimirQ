from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient


def test_create_pre_poc_dashboard_app_serves_single_page_html_and_event_stream(tmp_path: Path) -> None:
    from app.rag.tools.pre_poc_scanner.dashboard_server import create_pre_poc_dashboard_app

    html = "<!doctype html><html><body>dashboard</body></html>"
    app = create_pre_poc_dashboard_app(
        render_dashboard_html=lambda: html,
        list_events=lambda: [{"type": "summary", "data": {"total_files": 3}}],
    )
    client = TestClient(app)

    res_html = client.get("/dashboard")
    assert res_html.status_code == 200
    assert "text/html" in res_html.headers.get("content-type", "")
    assert "dashboard" in res_html.text

    res_sse = client.get("/events")
    assert res_sse.status_code == 200
    assert "text/event-stream" in res_sse.headers.get("content-type", "")
    assert '"type": "summary"' in res_sse.text


def test_pre_poc_dashboard_open_file_action_uses_injected_callback(tmp_path: Path) -> None:
    from app.rag.tools.pre_poc_scanner.dashboard_server import create_pre_poc_dashboard_app

    file_path = tmp_path / "a.txt"
    file_path.write_text("hello", encoding="utf-8")
    seen: list[str] = []

    app = create_pre_poc_dashboard_app(
        render_dashboard_html=lambda: "<html></html>",
        list_events=lambda: [],
        open_file=lambda path: seen.append(str(path)),
    )
    client = TestClient(app)

    res = client.post("/open-file", json={"path": str(file_path)})
    assert res.status_code == 200
    assert res.json()["ok"] is True
    assert seen == [str(file_path)]
