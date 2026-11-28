from __future__ import annotations

import json

from app_core import services
from tests.web.conftest import set_session


def test_assistant_smart_status_and_policy_audit(client, monkeypatch):
    monkeypatch.setattr(services, "get_setting", lambda k, d=None: {
        "assistant_smart_enabled": "false",
        "assistant_smart_model": "",
        "assistant_policy_audit_enabled": "true",
        "assistant_session_memory_enabled": "true",
        "assistant_playbooks_enabled": "true",
        "assistant_eval_gate_enabled": "true",
        "assistant_model_catalog_json": "[]",
    }.get(k, d))
    set_session(client, unlocked=True, csrf="tok")
    r = client.get("/assistant/smart/status")
    assert r.status_code == 200
    j = r.json()
    assert j["ok"] is True
    assert "catalog" in j

    r2 = client.get("/assistant/policy/audit?limit=5")
    assert r2.status_code == 200
    assert r2.json()["ok"] is True


def test_assistant_model_select_eval_rollback(client, monkeypatch):
    monkeypatch.setattr(services, "get_setting", lambda k, d=None: {
        "assistant_model_catalog_json": "[]",
        "assistant_smart_model": "",
        "assistant_smart_model_previous": "",
        "assistant_eval_gate_enabled": "true",
        "assistant_policy_audit_enabled": "false",
    }.get(k, d))
    store = {}
    monkeypatch.setattr(services, "set_setting", lambda k, v: store.__setitem__(k, str(v)))
    set_session(client, unlocked=True, csrf="tok")

    # eval deterministic
    r = client.post("/assistant/models/eval", data={"csrf": "tok", "model_id": "deterministic-core"}, headers={"X-CSRF-Token": "tok"})
    assert r.status_code == 200
    assert r.json()["ok"] is True

    # select deterministic
    r = client.post("/assistant/models/select", data={"csrf": "tok", "model_id": "deterministic-core"}, headers={"X-CSRF-Token": "tok"})
    assert r.status_code == 200
    assert r.json().get("ok") is True

    # rollback
    r = client.post("/assistant/models/rollback", data={"csrf": "tok"}, headers={"X-CSRF-Token": "tok"})
    assert r.status_code == 200


def test_assistant_policy_validate_and_model_ops(client, monkeypatch, tmp_path):
    from app_core import services, db
    store = {
        "assistant_action_policy_json": "[]",
        "assistant_property_rules": "",
        "assistant_model_catalog_json": "[]",
        "assistant_smart_model": "",
        "assistant_eval_gate_enabled": "true",
        "assistant_policy_audit_enabled": "false",
    }
    monkeypatch.setattr(services, "get_setting", lambda k, d=None: store.get(k, d))
    monkeypatch.setattr(services, "set_setting", lambda k, v: store.__setitem__(k, str(v)))
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
    try:
        db.close()
    except Exception:
        pass
    db.migrate()
    set_session(client, unlocked=True, csrf="tok")

    r = client.post("/assistant/policy/validate", data={"csrf":"tok","assistant_action_policy_json":"[]","assistant_property_rules":"ask: intent=report_*"}, headers={"X-CSRF-Token":"tok"})
    assert r.status_code == 200
    assert r.json()["ok"] is True

    p = tmp_path / "m.gguf"
    p.write_bytes(b"x")
    r = client.post("/assistant/models/upsert", data={"csrf":"tok","id":"m1","name":"M1","path":str(p)}, headers={"X-CSRF-Token":"tok"})
    assert r.status_code == 200 and r.json()["ok"] is True
    r = client.post("/assistant/models/verify", data={"csrf":"tok","model_id":"m1"}, headers={"X-CSRF-Token":"tok"})
    assert r.status_code == 200 and r.json()["ok"] is True
    r = client.post("/assistant/models/delete", data={"csrf":"tok","model_id":"m1"}, headers={"X-CSRF-Token":"tok"})
    assert r.status_code == 200 and r.json()["ok"] is True


def test_assistant_model_jobs_and_pull_job(client, monkeypatch, tmp_path):
    from app_core import services, db
    store = {"assistant_model_catalog_json":"[]","assistant_smart_model":"","assistant_eval_gate_enabled":"true","assistant_policy_audit_enabled":"false"}
    monkeypatch.setattr(services, "get_setting", lambda k, d=None: store.get(k, d))
    monkeypatch.setattr(services, "set_setting", lambda k, v: store.__setitem__(k, str(v)))
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
    try: db.close()
    except Exception: pass
    db.migrate()
    set_session(client, unlocked=True, csrf="tok")
    r = client.get("/assistant/models/jobs?limit=5")
    assert r.status_code == 200 and r.json()["ok"] is True
    r = client.post("/assistant/models/pull-bundle-job", data={"csrf":"tok"}, headers={"X-CSRF-Token":"tok"})
    assert r.status_code == 200
    assert r.json().get("ok") is True


def test_assistant_models_install_register_and_validation(client, monkeypatch, tmp_path):
    from app_core import services, db
    store = {"assistant_model_catalog_json":"[]","assistant_smart_model":"","assistant_eval_gate_enabled":"true","assistant_policy_audit_enabled":"false"}
    monkeypatch.setattr(services, "get_setting", lambda k, d=None: store.get(k, d))
    monkeypatch.setattr(services, "set_setting", lambda k, v: store.__setitem__(k, str(v)))
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
    try:
        db.close()
    except Exception:
        pass
    db.migrate()
    set_session(client, unlocked=True, csrf="tok")

    # register by approved/test path
    p = tmp_path / "m.gguf"
    p.write_bytes(b"abc")
    r = client.post("/assistant/models/install", data={"csrf":"tok","id":"m2","name":"M2","path":str(p)}, headers={"X-CSRF-Token":"tok"})
    assert r.status_code == 200
    j = r.json()
    assert j["ok"] is True

    # remote download requires checksum
    r = client.post("/assistant/models/install", data={"csrf":"tok","id":"m3","url":"https://huggingface.co/org/model.gguf","checksum":""}, headers={"X-CSRF-Token":"tok"})
    assert r.status_code == 200
    j = r.json()
    assert j["ok"] is False
    assert j["error"] == "checksum_required"

    # disallowed host
    r = client.post("/assistant/models/install", data={"csrf":"tok","id":"m4","url":"https://example.com/model.gguf","checksum":"a"*64}, headers={"X-CSRF-Token":"tok"})
    j = r.json()
    assert j["ok"] is False
    assert j["error"] == "url_not_allowed"


def test_assistant_models_catalog_has_availability(client, monkeypatch, tmp_path):
    from app_core import services, db
    store = {"assistant_model_catalog_json":"[]","assistant_smart_model":"","assistant_eval_gate_enabled":"true","assistant_policy_audit_enabled":"false"}
    monkeypatch.setattr(services, "get_setting", lambda k, d=None: store.get(k, d))
    monkeypatch.setattr(services, "set_setting", lambda k, v: store.__setitem__(k, str(v)))
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
    try:
        db.close()
    except Exception:
        pass
    db.migrate()
    set_session(client, unlocked=True, csrf="tok")

    r = client.get("/assistant/models/catalog")
    assert r.status_code == 200
    j = r.json()
    assert j["ok"] is True
    cat = j["catalog"]
    assert any(m["id"] == "deterministic-core" for m in cat)
    for m in cat:
        assert "selectable" in m
        assert "availability_reason" in m
        assert "provider" in m
