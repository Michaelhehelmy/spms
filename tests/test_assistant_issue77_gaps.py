from __future__ import annotations

import json
from pathlib import Path

from app_core import db, services
from app_core.assistant import model_ops, playbooks, training


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
        "assistant_smart_model_previous": "",
        "assistant_eval_gate_enabled": "true",
        "assistant_eval_pass_threshold": "1.0",
    }
    if extra:
        m.update(extra)
    monkeypatch.setattr(services, "get_setting", lambda k, d=None: m.get(k, d))
    monkeypatch.setattr(services, "set_setting", lambda k, v: m.__setitem__(k, str(v)))
    return m


def _init_tmp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
    try:
        db.close()
    except Exception:
        pass
    db.migrate()


def test_playbooks_load_from_file_and_find_relevant(tmp_path, monkeypatch):
    pb_path = tmp_path / "playbooks.json"
    pb_path.write_text(json.dumps({
        "playbooks": [
            {
                "id": "night_audit",
                "title": "Night audit",
                "keywords": ["night audit", "close day"],
                "steps": ["Review balances", "Run reports"],
                "routes": ["/reports"],
                "tags": ["accounting"],
                "enabled": True,
            },
            {
                "id": "disabled_pb",
                "title": "Disabled",
                "keywords": ["disabled"],
                "steps": ["no"],
                "enabled": False,
            }
        ]
    }), encoding="utf-8")
    monkeypatch.setattr(playbooks, "PLAYBOOKS_PATH", pb_path)
    items = playbooks.list_playbooks()
    ids = [p["id"] for p in items]
    assert "night_audit" in ids
    assert "disabled_pb" not in ids
    rel = playbooks.find_relevant("how do I do night audit?", limit=5)
    assert any(p["id"] == "night_audit" for p in rel)
    got = playbooks.get_playbook("night_audit")
    assert got and got["source"] == "playbooks_file"


def test_build_and_list_sanitized_datasets(tmp_path, monkeypatch):
    _settings_map(monkeypatch)
    _init_tmp_db(tmp_path, monkeypatch)
    # isolate dataset dirs
    monkeypatch.setattr(training, "DATASETS_DIR", tmp_path / "datasets")
    monkeypatch.setattr(training, "RAW_DIR", tmp_path / "datasets" / "raw")
    monkeypatch.setattr(training, "PROCESSED_DIR", tmp_path / "datasets" / "processed")
    monkeypatch.setattr(training, "MANIFEST_PATH", tmp_path / "datasets" / "manifest.json")
    monkeypatch.setattr(training, "RUNS_PATH", tmp_path / "datasets" / "training_runs.jsonl")

    # minimal sanitized package source
    from app_core.assistant import training_data_share

    def fake_pkg():
        return {
            "package_type": "spms_training_data_share",
            "version": 1,
            "created_at": "2026-01-01T00:00:00Z",
            "sha256": "pkgsha",
            "bundle_id": "spms_default",
            "app": "SPMS",
            "counts": {"feedback": 1},
            "data": {"feedback": [{"message": "hello", "rating": 1, "sanitized": True}]},
        }

    monkeypatch.setattr(training_data_share, "build_training_share_package", fake_pkg)
    res = training.build_sanitized_dataset(actor="test")
    assert res["ok"] is True
    ds = res["dataset"]
    assert ds["id"].startswith("sanitized-dataset-")
    assert ds["record_count"] == 1
    assert ds["pii_secrets_redacted"] is True
    assert ds["redaction_note"]
    jsonl = tmp_path / "datasets" / "processed" / f"{ds['id']}.jsonl"
    manifest = tmp_path / "datasets" / "processed" / f"{ds['id']}.manifest.json"
    assert jsonl.exists()
    assert manifest.exists()
    lines = [json.loads(l) for l in jsonl.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert len(lines) == 1
    assert lines[0]["_sanitized"] is True
    assert lines[0]["_provenance"]["source"] == "assistant_nlu.feedback"

    listed = training.list_sanitized_datasets()
    assert any(x["id"] == ds["id"] for x in listed)
    got = training.get_sanitized_dataset(ds["id"])
    assert got and got["fingerprint"] == ds["fingerprint"]


def test_model_job_lifecycle_cancel_fail(tmp_path, monkeypatch):
    _settings_map(monkeypatch)
    _init_tmp_db(tmp_path, monkeypatch)
    job = model_ops.create_job("train", model_id="m1", dataset_ref="ds1", dataset_fingerprint="fp1", config={"lineage": {"base_model": "m1"}})
    jid = int(job["id"])
    got = model_ops.get_job(jid)
    assert got and got["dataset_ref"] == "ds1"
    assert got["lineage"]["base_model"] == "m1"
    assert got["artifact_refs"] == []

    c = model_ops.cancel_job(jid, actor="test", reason="stop")
    assert c["ok"] is True
    assert c["job"]["status"] == "cancelled"

    # cannot cancel again
    c2 = model_ops.cancel_job(jid, actor="test")
    assert c2["ok"] is False

    j2 = model_ops.create_job("eval", model_id="m1")
    f = model_ops.mark_job_failed(int(j2["id"]), actor="test", reason="boom")
    assert f["ok"] is True
    assert f["job"]["status"] == "failed"


def test_eval_gate_blocks_activation(tmp_path, monkeypatch):
    _settings_map(monkeypatch)
    _init_tmp_db(tmp_path, monkeypatch)
    # register a fake installed model
    p = tmp_path / "m.gguf"
    p.write_bytes(b"abc")
    model_ops.upsert_catalog_model({"id": "m1", "name": "M1", "path": str(p), "provider": "local_gguf", "installed": True}, actor="test")
    # no eval -> blocked when gate enabled
    res = model_ops.select_model("m1", actor="test")
    assert res["ok"] is False
    assert res["error"] == "eval_gate_blocked"

    # failed eval -> blocked
    # insert failed eval directly
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO assistant_model_evals(created_at,job_id,model_id,dataset_ref,status,passed,metrics_json,details_json,actor) VALUES (datetime('now'),NULL,?,'','failed',0,?,?,'test')",
            ("m1", json.dumps({"pass_rate": 0.5, "checks_total": 2, "checks_passed": 1}), json.dumps({"checks": []})),
        )
        conn.commit()
    res2 = model_ops.select_model("m1", actor="test")
    assert res2["ok"] is False
    assert res2["error"] == "eval_gate_blocked"

    # passing eval -> allowed
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO assistant_model_evals(created_at,job_id,model_id,dataset_ref,status,passed,metrics_json,details_json,actor) VALUES (datetime('now'),NULL,?,'','completed',1,?,?,'test')",
            ("m1", json.dumps({"pass_rate": 1.0, "checks_total": 2, "checks_passed": 2}), json.dumps({"checks": [{"name":"x","passed":True}]})),
        )
        conn.commit()
    res3 = model_ops.select_model("m1", actor="test")
    assert res3["ok"] is True
