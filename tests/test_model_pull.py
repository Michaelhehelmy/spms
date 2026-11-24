from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path

import pytest

from app_core.assistant import model_pull


def test_is_test_env_detects_pytest(monkeypatch):
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "1")
    assert model_pull._is_test_env() is True
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setenv("SPMS_DISABLE_MODEL_PULL", "1")
    assert model_pull._is_test_env() is True


def test_start_pull_skips_in_test_env(monkeypatch):
    monkeypatch.setattr(model_pull, "_is_test_env", lambda: True)
    assert model_pull.start_pull_on_startup() is None


def test_start_pull_starts_thread_when_not_test_env(monkeypatch):
    monkeypatch.setattr(model_pull, "_is_test_env", lambda: False)
    called = {"n": 0}

    def fake_pull():
        called["n"] += 1
        return {}

    monkeypatch.setattr(model_pull, "pull_models_on_startup", fake_pull)
    t = model_pull.start_pull_on_startup()
    assert isinstance(t, threading.Thread)
    t.join(timeout=2)
    assert called["n"] == 1


def test_setting_fallback(monkeypatch):
    monkeypatch.setattr(model_pull.services, "get_setting", lambda k, d="": (_ for _ in ()).throw(RuntimeError("boom")))
    assert model_pull._setting("x", "d") == "d"


def test_is_disabled(monkeypatch):
    monkeypatch.setattr(model_pull, "_setting", lambda k, d="": "false")
    assert model_pull._is_disabled() is True
    monkeypatch.setattr(model_pull, "_setting", lambda k, d="": "true")
    assert model_pull._is_disabled() is False


def test_sha256(tmp_path):
    p = tmp_path / "f.bin"
    p.write_bytes(b"hello")
    assert model_pull._sha256(p) == hashlib.sha256(b"hello").hexdigest()


def test_fetch_validates_scheme(monkeypatch):
    with pytest.raises(ValueError):
        model_pull._fetch("file:///etc/passwd")
    with pytest.raises(ValueError):
        model_pull._fetch("ftp://example.com/x")


def test_fetch_reads_url(monkeypatch):
    class Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b"ok"

    monkeypatch.setattr(model_pull.urllib.request, "urlopen", lambda url, timeout: Resp())
    assert model_pull._fetch("https://example.com/x") == b"ok"


def test_validate_rel():
    assert model_pull._validate_rel("/a/b") == "a/b"
    with pytest.raises(ValueError):
        model_pull._validate_rel("../x")
    with pytest.raises(ValueError):
        model_pull._validate_rel("")


def test_model_targets_from_manifest():
    manifest = {
        "gguf": "models/a.gguf",
        "setfit_router": "models/assistant_intent_setfit",
        "sklearn_router": "models/assistant_intent_sklearn.joblib",
        "files": [{"path": "models/a.gguf"}],
    }
    targets = model_pull._model_targets(manifest)
    assert targets["gguf"].endswith("a.gguf")
    assert "assistant_intent_setfit" in targets["setfit_router"]
    assert targets["sklearn_router"].endswith("assistant_intent_sklearn.joblib")


def test_model_targets_fallbacks():
    manifest = {
        "files": [
            {"path": "models/x.gguf"},
            {"path": "models/assistant_intent_setfit/config.json"},
            {"path": "models/assistant_intent_sklearn.joblib"},
        ]
    }
    targets = model_pull._model_targets(manifest)
    assert targets["gguf"] == "models/x.gguf"
    assert targets["setfit_router"] == "models/assistant_intent_setfit"
    assert targets["sklearn_router"] == "models/assistant_intent_sklearn.joblib"


def test_apply_model_paths(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(model_pull.services, "set_setting", lambda k, v: calls.append((k, v)))
    manifest = {"env": {"gguf": "MY_GGUF"}}
    targets = {"gguf": "models/a.gguf", "setfit_router": "models/assistant_intent_setfit"}
    model_pull._apply_model_paths(manifest, targets, tmp_path)
    assert any(k == "assistant_local_model_path" for k, _ in calls)
    assert any(k == "assistant_setfit_model_dir" for k, _ in calls)


def test_pull_models_test_env_guard(monkeypatch):
    monkeypatch.setattr(model_pull, "_is_test_env", lambda: True)
    out = model_pull.pull_models_on_startup("https://example.com/repo")
    assert out["skipped_reason"] == "test_env"


def test_pull_models_disabled(monkeypatch):
    monkeypatch.setattr(model_pull, "_is_test_env", lambda: False)
    monkeypatch.setattr(model_pull, "_is_disabled", lambda: True)
    out = model_pull.pull_models_on_startup()
    assert out["applied"] is False


def test_pull_models_manifest_fetch_fails(monkeypatch):
    monkeypatch.setattr(model_pull, "_is_test_env", lambda: False)
    monkeypatch.setattr(model_pull, "_is_disabled", lambda: False)
    monkeypatch.setattr(model_pull, "_setting", lambda k, d="": d)
    monkeypatch.setattr(model_pull, "_fetch", lambda url: (_ for _ in ()).throw(RuntimeError("net")))
    out = model_pull.pull_models_on_startup("https://example.com/repo")
    assert out["repo"] == "https://example.com/repo"
    assert out["downloaded"] == []


def test_pull_models_bad_manifest_and_empty_files(monkeypatch):
    monkeypatch.setattr(model_pull, "_is_test_env", lambda: False)
    monkeypatch.setattr(model_pull, "_is_disabled", lambda: False)
    monkeypatch.setattr(model_pull, "_setting", lambda k, d="": d)
    monkeypatch.setattr(model_pull, "_fetch", lambda url: b"[]")
    out = model_pull.pull_models_on_startup("https://example.com/repo")
    assert out["applied"] is False

    monkeypatch.setattr(model_pull, "_fetch", lambda url: b'{"files":[]}')
    out = model_pull.pull_models_on_startup("https://example.com/repo")
    assert out["applied"] is False


def test_pull_models_downloads_and_skips(monkeypatch, tmp_path):
    monkeypatch.setattr(model_pull, "_is_test_env", lambda: False)
    monkeypatch.setattr(model_pull, "_is_disabled", lambda: False)
    monkeypatch.setattr(model_pull, "_setting", lambda k, d="": d)
    monkeypatch.setattr(model_pull, "DEST_DIR", tmp_path / "models")
    data = b"abc"
    digest = hashlib.sha256(data).hexdigest()
    manifest = {
        "files": [{"path": "models/a.gguf", "sha256": digest}],
        "env": {"gguf": "ASSISTANT_LOCAL_MODEL_PATH"},
    }

    def fake_fetch(url):
        if url.endswith("manifest.json"):
            return json.dumps(manifest).encode("utf-8")
        return data

    applied = {}
    monkeypatch.setattr(model_pull, "_fetch", fake_fetch)
    monkeypatch.setattr(model_pull, "_apply_model_paths", lambda m, t, d: applied.setdefault("ok", True))
    out = model_pull.pull_models_on_startup("https://example.com/repo")
    assert out["downloaded"] == ["models/a.gguf"]
    assert out["applied"] is True

    # second run should skip up-to-date file
    out2 = model_pull.pull_models_on_startup("https://example.com/repo")
    assert out2["skipped"] == ["models/a.gguf"]


def test_pull_models_checksum_mismatch_and_unsafe(monkeypatch, tmp_path):
    monkeypatch.setattr(model_pull, "_is_test_env", lambda: False)
    monkeypatch.setattr(model_pull, "_is_disabled", lambda: False)
    monkeypatch.setattr(model_pull, "_setting", lambda k, d="": d)
    monkeypatch.setattr(model_pull, "DEST_DIR", tmp_path / "models")
    manifest = {"files": [{"path": "../evil.bin", "sha256": "x"}, {"path": "ok.bin", "sha256": "bad"}]}

    def fake_fetch(url):
        if url.endswith("manifest.json"):
            return json.dumps(manifest).encode("utf-8")
        return b"data"

    monkeypatch.setattr(model_pull, "_fetch", fake_fetch)
    out = model_pull.pull_models_on_startup("https://example.com/repo")
    assert "../evil.bin" in out["failed"]
    assert "ok.bin" in out["failed"]


def test_start_pull_thread_exception(monkeypatch):
    monkeypatch.setattr(model_pull, "_is_test_env", lambda: False)
    monkeypatch.setattr(model_pull, "pull_models_on_startup", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    t = model_pull.start_pull_on_startup()
    t.join(timeout=2)


def test_apply_model_paths_exception(monkeypatch, tmp_path):
    def boom(k, v):
        raise RuntimeError("nope")

    monkeypatch.setattr(model_pull.services, "set_setting", boom)
    model_pull._apply_model_paths({"env": {}}, {"gguf": "a.gguf"}, tmp_path)


def test_pull_models_apply_exception(monkeypatch, tmp_path):
    monkeypatch.setattr(model_pull, "_is_test_env", lambda: False)
    monkeypatch.setattr(model_pull, "_is_disabled", lambda: False)
    monkeypatch.setattr(model_pull, "_setting", lambda k, d="": d)
    monkeypatch.setattr(model_pull, "DEST_DIR", tmp_path / "models")
    data = b"abc"
    digest = hashlib.sha256(data).hexdigest()
    manifest = {"files": [{"path": "a.gguf", "sha256": digest}]}
    monkeypatch.setattr(model_pull, "_fetch", lambda url: json.dumps(manifest).encode("utf-8") if url.endswith("manifest.json") else data)
    monkeypatch.setattr(model_pull, "_apply_model_paths", lambda *a: (_ for _ in ()).throw(RuntimeError("boom")))
    out = model_pull.pull_models_on_startup("https://example.com/repo")
    assert out["applied"] is False
