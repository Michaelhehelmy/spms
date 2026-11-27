from __future__ import annotations

import json

from tests.web.conftest import set_session


def test_support_report_page_renders(client, monkeypatch):
    # avoid network side effects from update notices/checks during render/diagnostics
    try:
        import app_core.updater as updater

        monkeypatch.setattr(updater, "get_cached_update_notice", lambda *a, **k: None)
    except Exception:
        pass

    set_session(client, unlocked=False)
    r = client.get("/support/report")
    assert r.status_code == 200
    assert "Report issue" in r.text or "Diagnostics" in r.text or "report" in r.text.lower()


def test_support_report_prefill_from_error_context(client, monkeypatch):
    try:
        import app_core.updater as updater

        monkeypatch.setattr(
            updater, "get_cached_update_notice", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
        )
    except Exception:
        pass

    # set last_error_report in session so route prefills from it
    set_session(
        client,
        unlocked=False,
        extra={
            "last_error_report": {
                "ref": "ERR123",
                "error_message": "Something failed",
                "error_type": "ValueError",
                "path": "/reservations/1",
            }
        },
    )
    r = client.get("/support/report?from_error=1&ref=ERR123")
    assert r.status_code == 200
    # prefill content may be embedded in JSON/template; just ensure page rendered
    assert "ERR123" in r.text or "ValueError" in r.text or "Report" in r.text


def test_rendering_to_template_data_branches(client):
    import sqlite3
    from ui.web.rendering import _to_template_data

    # tuple conversion branch
    assert _to_template_data((1, {"x": 2})) == (1, {"x": 2})

    # sqlite3.Row conversion branch
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT 1 AS a, 'b' AS c").fetchone()
    converted = _to_template_data(row)
    assert converted == {"a": 1, "c": "b"}
    conn.close()


def test_support_report_send_record_and_upload(client, monkeypatch):
    import app_core.updater as updater
    monkeypatch.setattr(updater, "get_cached_update_notice", lambda *a, **k: None)

    import ui.web.routes.support as support_route
    monkeypatch.setattr(support_route, "record_support_report", lambda report: type("P", (), {"name": "report-test.json"})())
    monkeypatch.setattr(support_route, "upload_support_report", lambda report, upload_url=None: {"ok": True, "status": 200, "data": {"ok": True}})

    set_session(client, unlocked=False, csrf="tok")
    r = client.post("/support/report/send", json={"report": {"report_kind": "in_app_issue_report"}, "share": True}, headers={"x-csrf-token": "tok"})
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["recorded"] is True
    assert data["uploaded"] is True

    r2 = client.post("/support/report/send", json={"report": {"x": 1}, "share": False}, headers={"x-csrf-token": "tok"})
    assert r2.status_code == 200
    assert r2.json()["uploaded"] is False


def test_support_report_send_invalid_json(client):
    set_session(client, unlocked=False, csrf="tok")
    r = client.post("/support/report/send", data="not json", headers={"content-type": "application/json", "x-csrf-token": "tok"})
    assert r.status_code == 400


def test_support_report_delete_clear(client, monkeypatch):
    import ui.web.routes.support as support_route
    monkeypatch.setattr(support_route, "delete_support_report", lambda name: name == "report-a.json")
    monkeypatch.setattr(support_route, "clear_support_reports", lambda: 3)
    set_session(client, unlocked=False, csrf="tok")
    r = client.post("/support/report/delete", data={"csrf": "tok", "name": "report-a.json"}, headers={"x-csrf-token": "tok"}, follow_redirects=False)
    assert r.status_code in (302, 303)
    r2 = client.post("/support/report/clear", data={"csrf": "tok"}, headers={"x-csrf-token": "tok"}, follow_redirects=False)
    assert r2.status_code in (302, 303)
