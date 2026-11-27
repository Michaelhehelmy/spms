from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app_core.assistant import bundles, training_data_share as tds
from app_core import support
from ui.web.server import create_app


def _client():
    app = create_app(init_db=False, run_startup=False)
    return TestClient(app)


# --- bundles ---
def test_bundle_validate_and_resolve_errors(tmp_path, monkeypatch):
    with pytest.raises(ValueError):
        bundles._validate_rel("../evil")
    assert bundles._resolve_path(tmp_path, "../evil") is None
    # safe read json bad
    p = tmp_path / "bad.json"
    p.write_text("{bad", encoding="utf-8")
    assert bundles._safe_read_json(p) is None
    # load manifest returns None for bad/empty
    assert bundles.load_manifest(p) is None
    empty = tmp_path / "empty.json"
    empty.write_text("[]", encoding="utf-8")
    assert bundles.load_manifest(empty) is None
    # legacy normalization path via load_manifest
    legacy = tmp_path / "legacy.json"
    legacy.write_text(json.dumps({"files": [{"path": "models/assistant_intent_setfit/config.json"}]}), encoding="utf-8")
    m = bundles.load_manifest(legacy)
    assert m and m.get("bundle_id") == "cocamp"


def test_discover_bundles_paths(tmp_path, monkeypatch):
    # create pulled and installed manifests
    pulled = tmp_path / "pulled" / "sub"
    pulled.mkdir(parents=True)
    (pulled / "manifest.json").write_text(json.dumps({"bundle_id": "p1", "name": "P1"}), encoding="utf-8")
    legacy = tmp_path / "pulled" / "manifest.json"
    legacy.write_text(json.dumps({"bundle_id": "cocamp", "name": "Co", "files": []}), encoding="utf-8")
    installed = tmp_path / "bundles" / "i1"
    installed.mkdir(parents=True)
    (installed / "manifest.json").write_text(json.dumps({"bundle_id": "i1", "name": "I1"}), encoding="utf-8")
    # bad manifest to hit exception
    bad = tmp_path / "bundles" / "bad"
    bad.mkdir(parents=True)
    (bad / "manifest.json").write_text("{bad", encoding="utf-8")

    monkeypatch.setattr(bundles, "PULLED_MODELS_DIR", tmp_path / "pulled")
    monkeypatch.setattr(bundles, "BUNDLES_DIR", tmp_path / "bundles")
    monkeypatch.setattr(bundles, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(bundles.services, "get_setting", lambda k, d="": d)
    found = bundles.discover_bundles()
    assert "p1" in found
    assert "i1" in found
    assert bundles.COCAMP_BUNDLE_ID in found


def test_discover_bundles_local_cocamp_dir(tmp_path, monkeypatch):
    (tmp_path / "co-camp").mkdir()
    monkeypatch.setattr(bundles, "PULLED_MODELS_DIR", tmp_path / "none1")
    monkeypatch.setattr(bundles, "BUNDLES_DIR", tmp_path / "none2")
    monkeypatch.setattr(bundles, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(bundles.services, "get_setting", lambda k, d="": d)
    found = bundles.discover_bundles()
    assert bundles.COCAMP_BUNDLE_ID in found


# --- support route ---
def test_support_report_page_exception_handlers(monkeypatch):
    monkeypatch.setattr("ui.web.routes.support.services.get_setting", lambda k, d="": (_ for _ in ()).throw(RuntimeError("boom")))
    monkeypatch.setattr("ui.web.routes.support.collect_support_diagnostics", lambda **k: {})
    monkeypatch.setattr("ui.web.routes.support.cleanup_support_reports", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x")))
    monkeypatch.setattr("ui.web.routes.support.list_support_reports", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x")))
    # rendering will fail if template context bad? easier to hit route via client; but settings throws early
    # Instead, target specific exceptions: make get_setting raise only for retention
    calls = {"n": 0}
    def gs(k, d=""):
        calls["n"] += 1
        if k == "support_report_retention_days":
            raise RuntimeError("bad")
        return d
    monkeypatch.setattr("ui.web.routes.support.services.get_setting", gs)
    monkeypatch.setattr("ui.web.routes.support.cleanup_support_reports", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x")))
    monkeypatch.setattr("ui.web.routes.support.list_support_reports", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x")))
    c = _client()
    r = c.get("/support/report")
    assert r.status_code == 200


def test_support_report_send_invalid_and_record_error(monkeypatch):
    from tests.web.conftest import get_csrf, set_session
    c = _client()
    # establish session/csrf
    token = set_session(c, unlocked=True)
    page = c.get("/support/report")
    csrf = get_csrf(page.text) or token
    headers = {"X-CSRF-Token": csrf, "Content-Type": "application/json"}

    r = c.post("/support/report/send", data="not json", headers=headers)
    assert r.status_code == 400
    r = c.post("/support/report/send", json=["bad"], headers=headers)
    assert r.status_code == 400

    monkeypatch.setattr("ui.web.routes.support.record_support_report", lambda report: (_ for _ in ()).throw(RuntimeError("disk")))
    r = c.post("/support/report/send", json={"report": {"a": 1}, "share": False, "csrf": csrf}, headers=headers)
    assert r.status_code == 200
    assert r.json()["recorded"] is False


# --- training_data_share ---
def test_training_share_last_upload_bad_date(monkeypatch, tmp_path):
    monkeypatch.setattr(tds, "SHARE_STATE_PATH", tmp_path / "state.json")
    (tmp_path / "state.json").write_text(json.dumps({"last_upload_at": "not-a-date"}), encoding="utf-8")
    monkeypatch.setattr(tds.services, "get_setting", lambda k, d="": "" if k.endswith("last_upload_at") else d)
    assert tds._last_upload_at() is None


def test_training_share_upload_persist_setting_exception(monkeypatch, tmp_path):
    monkeypatch.setattr(tds, "SHARE_STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(tds, "_enabled", lambda: True)
    monkeypatch.setattr(tds, "_min_bytes", lambda: 1)
    monkeypatch.setattr(tds, "package_size_bytes", lambda: 10)
    monkeypatch.setattr(tds, "build_training_share_package", lambda: {"size_bytes": 10, "sha256": "abc", "package_type": "spms_training_data_share", "consent": {"opt_in": True}})
    class R:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return b'{"ok":true}'
    monkeypatch.setattr(tds.urllib.request, "urlopen", lambda *a, **k: R())
    monkeypatch.setattr(tds.services, "set_setting", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("db")))
    res = tds.upload_training_package()
    assert res["ok"] is True


def test_training_share_startup_check_exception(monkeypatch):
    monkeypatch.setattr(tds, "_is_test_env", lambda: False)
    monkeypatch.setattr(tds, "time", type("T", (), {"sleep": lambda *_: None}))
    monkeypatch.setattr(tds, "maybe_upload_monthly", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    t = tds.start_monthly_upload_on_startup()
    assert t is not None
    t.join(timeout=2)
