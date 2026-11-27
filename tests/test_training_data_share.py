from __future__ import annotations

import json
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app_core.assistant import training_data_share as tds


class _Resp:
    def __init__(self, status=200, body=b'{"ok":true}'):
        self.status = status
        self._body = body

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


@pytest.fixture(autouse=True)
def _isolate_share_state(monkeypatch, tmp_path):
    state_path = tmp_path / "share_state.json"
    monkeypatch.setattr(tds, "SHARE_STATE_PATH", state_path)
    settings = {}

    def _get_setting(key, default=""):
        return settings.get(key, default)

    def _set_setting(key, value):
        settings[key] = value

    monkeypatch.setattr(tds.services, "get_setting", _get_setting)
    monkeypatch.setattr(tds.services, "set_setting", _set_setting)
    return settings, state_path


def test_redact_and_sanitize():
    s = tds._redact_text("email a@b.com phone +1 555 123 4567 guest #12345 cc 4111 1111 1111 1111")
    assert "[REDACTED_EMAIL]" in s
    assert "[REDACTED_PHONE]" in s
    assert "[REDACTED_ID]" in s
    assert "[REDACTED_NUMBER]" in s
    rows = tds._sanitize_feedback([{
        "message": "a@b.com", "expected_answer": "ok", "user_note": "note",
        "rating": "1", "predicted_intent": "x", "corrected_intent": "y",
        "source": "ui", "status": "approved", "created_at": "now",
    }])
    assert rows[0]["sanitized"] is True
    assert rows[0]["rating"] == 1


def test_load_jsonl_and_state(tmp_path, monkeypatch):
    p = tmp_path / "f.jsonl"
    p.write_text('{"a":1}\n\nbad\n{"b":2}\n', encoding="utf-8")
    assert tds._load_jsonl(p) == [{"a": 1}, {"b": 2}]
    assert tds._load_jsonl(tmp_path / "missing.jsonl") == []

    state_path = tmp_path / "state.json"
    monkeypatch.setattr(tds, "SHARE_STATE_PATH", state_path)
    assert tds._load_state() == {}
    state_path.write_text("{bad", encoding="utf-8")
    assert tds._load_state() == {}
    tds._save_state({"ok": True})
    assert json.loads(state_path.read_text(encoding="utf-8"))["ok"] is True


def test_setting_enabled_min_bytes_and_test_env(monkeypatch):
    monkeypatch.setattr(tds.services, "get_setting", lambda k, d="": (_ for _ in ()).throw(RuntimeError("boom")))
    assert tds._setting("x", "default") == "default"

    monkeypatch.setattr(tds.services, "get_setting", lambda k, d="": "true")
    assert tds._enabled() is True
    monkeypatch.setattr(tds.services, "get_setting", lambda k, d="": "false")
    assert tds._enabled() is False

    monkeypatch.setattr(tds.services, "get_setting", lambda k, d="": "not-int")
    assert tds._min_bytes() == tds.DEFAULT_MIN_BYTES
    monkeypatch.setattr(tds.services, "get_setting", lambda k, d="": "2048")
    assert tds._min_bytes() == 2048

    monkeypatch.setenv("SPMS_DISABLE_TRAINING_SHARE", "1")
    assert tds._is_test_env() is True
    monkeypatch.delenv("SPMS_DISABLE_TRAINING_SHARE", raising=False)
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "1")
    assert tds._is_test_env() is True


def test_build_package_and_size(monkeypatch, tmp_path):
    root = tmp_path
    (root / "data/assistant_nlu").mkdir(parents=True)
    (root / "data/datasets/curated").mkdir(parents=True)
    (root / "co-camp/co_camp/data").mkdir(parents=True)
    (root / "data/assistant_nlu/feedback.jsonl").write_text('{"message":"hi a@b.com","rating":1}\n', encoding="utf-8")
    (root / "data/assistant_nlu/intents_seed.jsonl").write_text('{"text":"book room","label":"book"}\n', encoding="utf-8")
    (root / "co-camp/co_camp/data/persona_examples.jsonl").write_text('{"text":"hello","target_answer":"world"}\n', encoding="utf-8")
    (root / "data/datasets/curated/business_history.jsonl").write_text('{"question":"q","answer":"a"}\n', encoding="utf-8")
    (root / "data/datasets/curated/app_operations_knowledge.jsonl").write_text('{"text":"ops"}\n', encoding="utf-8")
    (root / "data/datasets/manifest.json").write_text('{"version":1}', encoding="utf-8")
    monkeypatch.setattr(tds, "PROJECT_ROOT", root)

    pkg = tds.build_training_share_package()
    assert pkg["package_type"] == "spms_training_data_share"
    assert pkg["counts"]["feedback"] == 1
    assert pkg["size_bytes"] > 0
    assert len(pkg["sha256"]) == 64
    assert tds.package_size_bytes() == pkg["size_bytes"]

    # bad manifest should be tolerated
    (root / "data/datasets/manifest.json").write_text('{bad', encoding="utf-8")
    pkg2 = tds.build_training_share_package()
    assert pkg2["data"]["dataset_manifest"] == {}


def test_should_upload_now(monkeypatch, tmp_path):
    settings = {"assistant_training_share_enabled": "false"}
    monkeypatch.setattr(tds.services, "get_setting", lambda k, d="": settings.get(k, d))
    ok, reason = tds.should_upload_now()
    assert ok is False and reason == "disabled"

    settings["assistant_training_share_enabled"] = "true"
    settings["assistant_training_share_min_bytes"] = "99999999"
    monkeypatch.setattr(tds, "package_size_bytes", lambda: 10)
    ok, reason = tds.should_upload_now()
    assert ok is False and reason.startswith("below_min_size:")

    settings["assistant_training_share_min_bytes"] = "1"
    monkeypatch.setattr(tds, "package_size_bytes", lambda: 2048)
    monkeypatch.setattr(tds, "_last_upload_at", lambda: datetime.now(timezone.utc) - timedelta(days=2))
    ok, reason = tds.should_upload_now()
    assert ok is False and reason.startswith("recent_upload:")

    monkeypatch.setattr(tds, "_last_upload_at", lambda: datetime.now(timezone.utc) - timedelta(days=31))
    ok, reason = tds.should_upload_now()
    assert ok is True and reason == "ok"


def test_upload_training_package(monkeypatch, tmp_path, _isolate_share_state):
    settings, state_path = _isolate_share_state
    settings["assistant_training_share_enabled"] = "false"
    assert tds.upload_training_package()["error"] == "disabled"

    settings["assistant_training_share_enabled"] = "true"
    settings["assistant_training_share_upload_url"] = "ftp://bad/url"
    assert tds.upload_training_package()["error"] == "invalid_upload_url"

    settings["assistant_training_share_upload_url"] = "https://example.test/upload"
    settings["assistant_training_share_min_bytes"] = "999999"
    monkeypatch.setattr(tds, "build_training_share_package", lambda: {"size_bytes": 10, "sha256": "abc"})
    res = tds.upload_training_package()
    assert res["error"] == "below_min_size"

    settings["assistant_training_share_min_bytes"] = "1"
    pkg = {"size_bytes": 100, "sha256": "abc", "data": {}}
    monkeypatch.setattr(tds, "build_training_share_package", lambda: pkg)

    calls = {}
    def _fake_urlopen(req, timeout=0):
        calls["url"] = req.full_url
        calls["timeout"] = timeout
        return _Resp(200, b'{"ok":true,"id":"x"}')
    monkeypatch.setattr(tds.urllib.request, "urlopen", _fake_urlopen)
    res = tds.upload_training_package()
    assert res["ok"] is True
    assert calls["url"] == "https://example.test/upload"
    saved = json.loads(state_path.read_text(encoding="utf-8"))
    assert saved["last_status"] == "ok"

    def _boom(req, timeout=0):
        raise RuntimeError("network down")
    monkeypatch.setattr(tds.urllib.request, "urlopen", _boom)
    res = tds.upload_training_package()
    assert res["ok"] is False
    saved = json.loads(state_path.read_text(encoding="utf-8"))
    assert saved["last_status"].startswith("error:")


def test_maybe_upload_and_startup(monkeypatch):
    monkeypatch.setattr(tds, "should_upload_now", lambda: (False, "disabled"))
    assert tds.maybe_upload_monthly() == {"ok": False, "skipped": "disabled"}
    monkeypatch.setattr(tds, "should_upload_now", lambda: (True, "ok"))
    monkeypatch.setattr(tds, "upload_training_package", lambda: {"ok": True})
    assert tds.maybe_upload_monthly() == {"ok": True}

    # start_monthly_upload_on_startup returns None in test env; force non-test path
    monkeypatch.setattr(tds, "_is_test_env", lambda: False)
    called = []
    monkeypatch.setattr(tds, "maybe_upload_monthly", lambda: called.append(1) or {"ok": True})
    real_sleep = time.sleep
    monkeypatch.setattr(tds.time, "sleep", lambda *_: None)
    t = tds.start_monthly_upload_on_startup()
    assert isinstance(t, threading.Thread)
    t.join(timeout=2)
    assert called
    real_sleep(0)


def test_last_upload_at_and_save_state_errors(monkeypatch, tmp_path):
    monkeypatch.setattr(tds.services, "get_setting", lambda k, d="": "2026-01-01T00:00:00+00:00" if k.endswith("last_upload_at") else d)
    dt = tds._last_upload_at()
    assert dt is not None

    state_path = tmp_path / "state.json"
    monkeypatch.setattr(tds, "SHARE_STATE_PATH", state_path)
    tds._save_state({"a": 1})
    assert state_path.exists()
