from __future__ import annotations

import json

from tests.web.conftest import get_csrf, set_session


def _patch_base(monkeypatch):
    import ui.web.routes.assistant as ar

    monkeypatch.setattr(ar.assistant, "get_llm_config", lambda: {"provider": "auto", "response_mode": "talking", "local_available": False, "enabled": False, "external": False})
    monkeypatch.setattr(ar.assistant, "INTENT_LABELS", {"capabilities_help": "Help"}, raising=False)
    monkeypatch.setattr(ar.services, "get_setting", lambda k, d=None: "true" if k == "assistant_require_unlock" else d)
    monkeypatch.setattr(ar.assistant_training, "list_sources", lambda: [{"id": "s1", "label": "S1", "path": "p", "kind": "intent", "description": "d", "default": True, "exists": True, "bytes": 10, "rows": 1}])
    monkeypatch.setattr(ar.assistant_training, "training_runs", lambda: [{"created_at": "t", "backend": "sklearn", "model": "m", "status": "success", "fingerprint": "abc"}])
    return ar


def test_training_sources_locked_and_ok(client, monkeypatch):
    ar = _patch_base(monkeypatch)
    set_session(client, unlocked=False)
    r = client.get("/assistant/training/sources")
    assert r.status_code == 403
    assert r.json()["error"] == "unlock_required"

    set_session(client, unlocked=True)
    r = client.get("/assistant/training/sources")
    assert r.status_code == 200
    j = r.json()
    assert j["ok"] is True
    assert j["training_sources"][0]["id"] == "s1"


def test_training_estimate_variants(client, monkeypatch):
    ar = _patch_base(monkeypatch)
    captured = {}

    def fake_estimate(source_ids, backend="sklearn", model="m"):
        captured["args"] = (source_ids, backend, model)
        return {"ok": True, "already_trained": False, "estimate_minutes_min": 1, "estimate_minutes_max": 2, "fingerprint": "fp"}

    monkeypatch.setattr(ar.assistant_training, "estimate_training", fake_estimate)

    set_session(client, unlocked=False)
    r = client.post("/assistant/training/estimate", json={"sources": ["s1"]})
    assert r.status_code == 403

    set_session(client, unlocked=True)
    # json list
    r = client.post("/assistant/training/estimate", json={"sources": ["s1", "s2"], "backend": "setfit", "model": "M"})
    assert r.status_code == 200 and r.json()["ok"] is True
    assert captured["args"] == (["s1", "s2"], "setfit", "M")

    # json string
    r = client.post("/assistant/training/estimate", json={"sources": '["s1"]'})
    assert r.status_code == 200
    assert captured["args"][0] == ["s1"]

    # comma string fallback
    r = client.post("/assistant/training/estimate", json={"sources": "s1, s2"})
    assert captured["args"][0] == ["s1", "s2"]

    # form repeated fields
    token = set_session(client, unlocked=True)
    r = client.post("/assistant/training/estimate", data={"csrf": token, "sources": "s1", "backend": "sklearn", "model": "m"})
    assert r.status_code == 200


def test_training_start_csrf_locked_and_flows(client, monkeypatch):
    ar = _patch_base(monkeypatch)

    def fake_start(source_ids, backend="sklearn", model="m"):
        if not source_ids:
            return {"ok": False, "error": "no_sources", "message": "Select at least one data source."}
        return {"ok": True, "run": {"status": "success", "id": "r1"}, "fingerprint": "fp", "already_trained": False}

    monkeypatch.setattr(ar.assistant_training, "start_training", fake_start)
    monkeypatch.setattr(ar.assistant_training, "estimate_training", lambda *a, **k: {"ok": True})

    # locked
    set_session(client, unlocked=False)
    r = client.post("/assistant/training/start", json={"sources": ["s1"]}, headers={"Accept": "application/json"})
    assert r.status_code == 403

    # csrf fail json
    set_session(client, unlocked=True)
    r = client.post("/assistant/training/start", json={"sources": ["s1"], "csrf": "bad"}, headers={"Accept": "application/json"})
    assert r.status_code == 403
    assert r.json()["error"] == "csrf"

    # success json
    token = set_session(client, unlocked=True)
    page = client.get("/assistant")
    csrf = get_csrf(page.text)
    r = client.post("/assistant/training/start", json={"sources": ["s1"], "csrf": csrf, "backend": "sklearn", "model": "m"}, headers={"Accept": "application/json"})
    assert r.status_code == 200
    assert r.json()["ok"] is True

    # non-json success redirect
    token = set_session(client, unlocked=True)
    page = client.get("/assistant")
    csrf = get_csrf(page.text)
    r = client.post("/assistant/training/start", data={"sources": "s1", "csrf": csrf, "backend": "sklearn", "model": "m"}, follow_redirects=False)
    assert r.status_code in (302, 303)

    # non-json error redirect
    token = set_session(client, unlocked=True)
    page = client.get("/assistant")
    csrf = get_csrf(page.text)
    monkeypatch.setattr(ar.assistant_training, "start_training", lambda *a, **k: {"ok": False, "error": "already_trained", "message": "dup"})
    r = client.post("/assistant/training/start", data={"sources": "s1", "csrf": csrf}, follow_redirects=False)
    assert r.status_code in (302, 303)
