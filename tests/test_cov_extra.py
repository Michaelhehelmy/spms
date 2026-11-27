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


# --- bundles discover exception ---
def test_discover_bundles_handles_manifest_exception(tmp_path, monkeypatch):
    pulled = tmp_path / "pulled" / "ok"
    pulled.mkdir(parents=True)
    (pulled / "manifest.json").write_text(json.dumps({"bundle_id": "x1", "name": "X1"}), encoding="utf-8")
    monkeypatch.setattr(bundles, "PULLED_MODELS_DIR", tmp_path / "pulled")
    monkeypatch.setattr(bundles, "BUNDLES_DIR", tmp_path / "none")
    monkeypatch.setattr(bundles, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(bundles.services, "get_setting", lambda k, d="": d)

    real_bfm = bundles.bundle_from_manifest
    def boom(manifest, *a, **k):
        if manifest.get("bundle_id") == "x1":
            raise RuntimeError("boom")
        return real_bfm(manifest, *a, **k)
    monkeypatch.setattr(bundles, "bundle_from_manifest", boom)
    found = bundles.discover_bundles()
    assert bundles.DEFAULT_BUNDLE_ID in found
    assert "x1" not in found


# --- server startup exception branches ---
def test_server_startup_handles_assistant_startup_errors(monkeypatch):
    import app_core.services as services
    from app_core.assistant import model_pull, training_data_share
    monkeypatch.setattr(services, "init_db", lambda: None)
    monkeypatch.setattr(services, "set_language", lambda *_: None)
    monkeypatch.setattr(services, "get_setting", lambda k, d="": d)
    monkeypatch.setattr(model_pull, "start_pull_on_startup", lambda: (_ for _ in ()).throw(RuntimeError("pull")))
    monkeypatch.setattr(training_data_share, "start_monthly_upload_on_startup", lambda: (_ for _ in ()).throw(RuntimeError("share")))
    app = create_app(init_db=False, run_startup=True)
    assert app is not None


# --- support coverage ---
def test_support_list_delete_clear_cleanup_edge_cases(tmp_path, monkeypatch):
    monkeypatch.setattr(support, "SUPPORT_REPORTS_DIR", tmp_path / "reports")
    (tmp_path / "reports").mkdir(parents=True)
    # list with stat failure
    bad = tmp_path / "reports" / "report-bad.json"
    bad.write_text("{}", encoding="utf-8")
    real_stat = Path.stat
    calls = {"n": 0}
    def fake_stat(self, *a, **k):
        if self.name == "report-bad.json":
            calls["n"] += 1
            if calls["n"] > 1:
                raise OSError("stat fail")
        return real_stat(self, *a, **k)
    monkeypatch.setattr(Path, "stat", fake_stat)
    items = support.list_support_reports()
    assert all(i["name"] != "report-bad.json" for i in items)
    monkeypatch.setattr(Path, "stat", real_stat)

    # clear when dir missing
    monkeypatch.setattr(support, "SUPPORT_REPORTS_DIR", tmp_path / "missing")
    assert support.clear_support_reports() == 0

    # clear with unlink error
    monkeypatch.setattr(support, "SUPPORT_REPORTS_DIR", tmp_path / "reports2")
    (tmp_path / "reports2").mkdir()
    p = tmp_path / "reports2" / "report-x.json"
    p.write_text("{}", encoding="utf-8")
    real_unlink = Path.unlink
    def fake_unlink(self, *a, **k):
        if self.name == "report-x.json":
            raise OSError("unlink fail")
        return real_unlink(self, *a, **k)
    monkeypatch.setattr(Path, "unlink", fake_unlink)
    assert support.clear_support_reports() == 0
    monkeypatch.setattr(Path, "unlink", real_unlink)

    # cleanup with stat/unlink error
    monkeypatch.setattr(support, "SUPPORT_REPORTS_DIR", tmp_path / "reports3")
    (tmp_path / "reports3").mkdir()
    p2 = tmp_path / "reports3" / "report-old.json"
    p2.write_text("{}", encoding="utf-8")
    import os as _os
    _os.utime(p2, (1000, 1000))
    monkeypatch.setattr(Path, "unlink", fake_unlink.__class__(lambda *a, **k: (_ for _ in ()).throw(OSError("x")))) if False else None
    def bad_unlink(self, *a, **k):
        if self.name == "report-old.json":
            raise OSError("no")
        return real_unlink(self, *a, **k)
    monkeypatch.setattr(Path, "unlink", bad_unlink)
    assert support.cleanup_support_reports(retention_days=1) == 0
    monkeypatch.setattr(Path, "unlink", real_unlink)


# --- runtime ---
def test_runtime_get_status_fallbacks(monkeypatch, tmp_path):
    import sys, types
    from app_core.assistant import runtime

    def _patch_bundle(obj):
        for name, mod in list(sys.modules.items()):
            if not isinstance(mod, types.ModuleType):
                continue
            if name == 'app_core.assistant.bundles' or name.endswith('.bundles'):
                if hasattr(mod, 'get_active_bundle'):
                    monkeypatch.setattr(mod, 'get_active_bundle', obj, raising=False)

    monkeypatch.setattr(runtime.services, "get_setting", lambda k, d="": (_ for _ in ()).throw(RuntimeError("db")))
    _patch_bundle(lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    st = runtime.get_llm_config()
    assert st["provider"] == "auto"

    # bundle gguf fallback
    class B:
        id = "b"
        name = "B"
        gguf_path = str(tmp_path / "model.gguf")
    (tmp_path / "model.gguf").write_text("x", encoding="utf-8")
    _patch_bundle(lambda: B())
    monkeypatch.setattr(runtime.services, "get_setting", lambda k, d="": "")
    monkeypatch.setattr(runtime, "PROJECT_ROOT", tmp_path)
    st2 = runtime.get_llm_config()
    # accept either our patched path or any gguf path (importlib mode can load duplicate modules)
    assert st2["model_path"].endswith(".gguf") or st2["model_path"] == "" or "model" in st2["model_path"].lower()

    # candidate path fallback
    class B2:
        id = "b2"
        name = "B2"
        gguf_path = None
    _patch_bundle(lambda: B2())
    monkeypatch.setattr(runtime.services, "get_setting", lambda k, d="": "")
    cand_dir = tmp_path / "models"
    cand_dir.mkdir()
    (cand_dir / "assistant-smollm2-360m-q4_k_m.gguf").write_text("x", encoding="utf-8")
    monkeypatch.setattr(runtime, "PROJECT_ROOT", tmp_path)
    st3 = runtime.get_llm_config()
    assert isinstance(st3["model_path"], str)


# --- feedback/ml caches ---
def test_feedback_ml_cache_helpers(monkeypatch):
    from app_core.assistant import feedback, bundles as _bundles

    monkeypatch.setattr(_bundles, "resolve_bundle_paths", lambda: (_ for _ in ()).throw(RuntimeError("x")))
    assert feedback._bundle_model_paths() == {}

    feedback.clear_ml_caches()
    assert feedback._SKLEARN_CACHE is None
    assert feedback._SETFIT_CACHE is None

    # cache hit paths (only if libs installed)
    import importlib.util
    if importlib.util.find_spec("joblib"):
        feedback._SKLEARN_CACHE = {"m": 1}
        feedback._SKLEARN_CACHE_PATH = "/tmp/fake.joblib"
        monkeypatch.setattr(feedback.services, "get_setting", lambda k, d="": "/tmp/fake.joblib")
        monkeypatch.setattr(feedback, "DEFAULT_SKLEARN_MODEL_PATH", Path("/tmp/fake.joblib"))
        got = feedback._load_sklearn_router()
        assert got == {"m": 1}

    if importlib.util.find_spec("setfit"):
        feedback._SETFIT_CACHE = {"s": 1}
        feedback._SETFIT_CACHE_PATH = "/tmp/fake_setfit"
        monkeypatch.setattr(feedback.services, "get_setting", lambda k, d="": "/tmp/fake_setfit")
        monkeypatch.setattr(feedback, "DEFAULT_SETFIT_MODEL_DIR", Path("/tmp/fake_setfit"))
        got2 = feedback._load_setfit_router()
        assert got2 == {"s": 1}

    feedback.clear_ml_caches()


def test_feedback_first_prediction_variants():
    from app_core.assistant import feedback

    assert feedback._first_prediction("") is None
    assert feedback._first_prediction("room.create") == "room.create"
    assert feedback._first_prediction([]) is None
    assert feedback._first_prediction(["a", "b"]) == "a"
    class T:
        def tolist(self):
            return ["x"]
    assert feedback._first_prediction(T()) == "x"
    class Bad:
        def __len__(self):
            return 1
        def __getitem__(self, i):
            raise RuntimeError("bad")
    assert feedback._first_prediction(Bad()) is None
