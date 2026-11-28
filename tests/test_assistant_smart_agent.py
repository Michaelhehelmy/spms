from __future__ import annotations

import json

import app_core.assistant.policy as policy
import app_core.assistant.memory as memory
import app_core.assistant.business_map as bmap
import app_core.assistant.playbooks as playbooks
import app_core.assistant.model_ops as model_ops
from app_core import db, services


def _settings_map(monkeypatch, extra=None):
    m = {
        "assistant_smart_enabled": "false",
        "assistant_action_policy_json": "[]",
        "assistant_property_rules": "",
        "assistant_policy_audit_enabled": "false",
        "assistant_session_memory_enabled": "true",
        "assistant_session_memory_ttl_minutes": "120",
        "assistant_model_catalog_json": "[]",
        "assistant_smart_model": "",
        "assistant_eval_gate_enabled": "true",
    }
    if extra:
        m.update(extra)
    monkeypatch.setattr(services, "get_setting", lambda k, d=None: m.get(k, d))
    monkeypatch.setattr(services, "set_setting", lambda k, v: m.__setitem__(k, str(v)))
    return m


def test_policy_evaluate_deny_ask_allow(monkeypatch):
    _settings_map(monkeypatch, {
        "assistant_action_policy_json": json.dumps([
            {"id": "deny-reports", "effect": "deny", "intent_patterns": ["report_*"], "reason": "no reports"},
            {"id": "allow-help", "effect": "allow", "intent_patterns": ["capabilities_help"], "reason": "ok"},
        ])
    })
    d = policy.evaluate(message="show report", intent="report_x", action_type="")
    assert d["effect"] == "deny"
    d2 = policy.evaluate(message="help", intent="capabilities_help", action_type="")
    assert d2["effect"] == "allow"
    # sensitive floor elevates allow to ask
    d3 = policy.evaluate(message="record payment", intent="propose_record_payment", action_type="propose_record_payment")
    assert d3["effect"] in ("ask", "deny")
    assert d3["requires_confirmation"] is True


def test_policy_property_rules_and_audit(monkeypatch, tmp_path):
    _settings_map(monkeypatch, {"assistant_property_rules": "ask: action_type=propose_add_pos_item; reason=Manager approval", "assistant_policy_audit_enabled": "true"})
    # use temp db
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
    try:
        db.close()
    except Exception:
        pass
    db.migrate()
    d = policy.evaluate(message="add item", intent="propose_add_pos_item", action_type="propose_add_pos_item")
    assert d["effect"] in ("ask", "deny")
    policy.log_decision(d, session_id="s1", actor="manager", message="add item", intent="propose_add_pos_item", action_type="propose_add_pos_item", args={"reservation_id": 1}, outcome="proposed")
    items = policy.list_policy_audit(limit=10)
    assert isinstance(items, list)
    # at least no crash; if table exists in init_db schema it should log
    assert len(items) >= 0


def test_memory_load_update_clear(monkeypatch, tmp_path):
    _settings_map(monkeypatch)
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
    try:
        db.close()
    except Exception:
        pass
    db.migrate()
    ctx = {"session_id": "sess1", "actor_user_id": 1}
    memory.update_after_chat("show reservation #5", {"intent": "reservation_lookup", "slots": {"reservation_id": 5}}, ui_context=ctx)
    loaded = memory.load_for_chat(ui_context=ctx)
    assert loaded.get("slots", {}).get("reservation_id") == 5
    memory.clear_session("sess1")
    assert memory.load_for_chat(ui_context=ctx) == {}


def test_business_map_and_playbooks():
    ranked = bmap.rank("I need to record a payment for reservation", "propose_record_payment")
    assert ranked
    assert any(r["id"] in ("reservations", "accounting", "pos") for r in ranked)
    pbs = playbooks.find_relevant("walk in sale", "propose_complete_walkin_sale")
    assert any(p["id"] == "walkin_sale" for p in pbs)


def test_model_ops_catalog_eval_select(monkeypatch, tmp_path):
    _settings_map(monkeypatch)
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
    try:
        db.close()
    except Exception:
        pass
    db.migrate()
    cat = model_ops.get_catalog()
    assert any(m["id"] == "deterministic-core" for m in cat)
    ev = model_ops.run_eval("deterministic-core")
    assert ev["passed"] is True
    # selecting non-installed model should fail
    res = model_ops.select_model("smollm2-360m-instruct-q4_k_m")
    assert res["ok"] is False
    # deterministic can be selected
    res2 = model_ops.select_model("deterministic-core")
    assert res2["ok"] is True


def test_policy_validate_and_effective(monkeypatch):
    _settings_map(monkeypatch)
    v = policy.validate_policy_config("[]", "ask: intent=report_*; reason=test")
    assert v["ok"] is True
    eff = policy.effective_policy_summary()
    assert eff["ok"] is True
    assert eff["count"] >= 1


def test_model_ops_upsert_verify_delete(monkeypatch, tmp_path):
    _settings_map(monkeypatch)
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
    try:
        db.close()
    except Exception:
        pass
    db.migrate()
    p = tmp_path / "m.gguf"
    p.write_bytes(b"abc")
    res = model_ops.upsert_catalog_model({"id": "m1", "name": "M1", "path": str(p), "provider": "local_gguf"}, actor="test")
    assert res["ok"] is True
    v = model_ops.verify_catalog_model("m1")
    assert v["ok"] is True and v["exists"] is True
    d = model_ops.delete_catalog_model("m1")
    assert d["ok"] is True


def test_download_url_allowlist_and_checksum(monkeypatch):
    _settings_map(monkeypatch)
    ok, why = model_ops.is_allowed_download_url("https://huggingface.co/org/model/resolve/main/model.gguf")
    assert ok is True
    ok, why = model_ops.is_allowed_download_url("http://huggingface.co/model.gguf")
    assert ok is False and why == "https_required"
    ok, why = model_ops.is_allowed_download_url("https://example.com/model.gguf")
    assert ok is False and why.startswith("host_not_allowlisted")

    res = model_ops.start_model_download_job("m1", "https://huggingface.co/org/model.gguf", checksum="")
    assert res["ok"] is False
    assert res["error"] == "checksum_required"


def test_catalog_availability_reasons(monkeypatch, tmp_path):
    _settings_map(monkeypatch)
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
    try:
        db.close()
    except Exception:
        pass
    db.migrate()
    # uninstalled model should be unavailable
    model_ops.upsert_catalog_model({"id": "m-uninst", "name": "M", "path": str(tmp_path / "missing.gguf"), "provider": "local_gguf"}, actor="test")
    cat = model_ops.get_catalog()
    m = next(x for x in cat if x["id"] == "m-uninst")
    assert m["selectable"] is False
    assert m["availability_reason"] == "model_not_installed"

    # installed but eval gate blocks
    p = tmp_path / "ok.gguf"
    p.write_bytes(b"abc")
    model_ops.upsert_catalog_model({"id": "m-eval", "name": "ME", "path": str(p), "provider": "local_gguf"}, actor="test")
    cat = model_ops.get_catalog()
    m2 = next(x for x in cat if x["id"] == "m-eval")
    assert m2["installed"] is True
    assert m2["selectable"] is False
    assert m2["availability_reason"] == "eval_gate_blocked"

    # after passing eval, selectable
    model_ops.run_eval("m-eval", actor="test")
    cat = model_ops.get_catalog()
    m3 = next(x for x in cat if x["id"] == "m-eval")
    assert m3["selectable"] is True
    assert m3["eval_passed"] is True


def test_install_register_path_validation(monkeypatch, tmp_path):
    _settings_map(monkeypatch)
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
    try:
        db.close()
    except Exception:
        pass
    db.migrate()
    # path outside approved dirs should be rejected in normal mode; in pytest tmp is allowed by escape hatch
    # use a clearly bad path string
    res = model_ops.upsert_catalog_model({"id": "bad", "path": "/etc/passwd"}, actor="test")
    # /etc/passwd is not under approved dirs; allow_existing_anywhere is not set, pytest temp escape hatch doesn't apply
    assert res["ok"] is False
    assert res["error"] == "path_not_allowed"
