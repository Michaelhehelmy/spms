from __future__ import annotations

import json
from pathlib import Path

from app_core.assistant import bundles


def test_discover_has_default(monkeypatch):
    monkeypatch.setattr(bundles.services, "get_setting", lambda k, d="": d)
    found = bundles.discover_bundles()
    assert bundles.DEFAULT_BUNDLE_ID in found
    assert found[bundles.DEFAULT_BUNDLE_ID].name == "SPMS Default"


def test_load_legacy_manifest_normalizes():
    manifest = {
        "files": [
            {"path": "models/x.gguf", "sha256": "a"},
            {"path": "models/assistant_intent_setfit/config.json"},
            {"path": "models/assistant_intent_sklearn.joblib"},
        ]
    }
    norm = bundles.load_manifest.__wrapped__(None) if False else None
    norm = bundles.normalize_legacy_cocamp_manifest(manifest)
    assert norm["bundle_id"] == "cocamp"
    assert norm["models"]["gguf"]["path"] == "models/x.gguf"
    assert norm["models"]["intent_router"]["setfit_dir"] == "models/assistant_intent_setfit"


def test_bundle_from_manifest_resolves_paths(tmp_path):
    (tmp_path / "brain").mkdir()
    (tmp_path / "brain" / "agent_brain.json").write_text("{}", encoding="utf-8")
    manifest = {
        "bundle_id": "test",
        "name": "Test",
        "brain": {"path": "brain/agent_brain.json"},
        "models": {"gguf": {"path": "model.gguf"}},
    }
    b = bundles.bundle_from_manifest(manifest, root=tmp_path, manifest_path=tmp_path / "manifest.json")
    assert b.id == "test"
    assert b.brain_path and b.brain_path.name == "agent_brain.json"


def test_active_bundle_fallback(monkeypatch):
    monkeypatch.setattr(bundles, "discover_bundles", lambda: {bundles.DEFAULT_BUNDLE_ID: bundles._builtin_default_bundle()})
    monkeypatch.setattr(bundles.services, "get_setting", lambda k, d="": "missing_bundle")
    b = bundles.get_active_bundle()
    assert b.id == bundles.DEFAULT_BUNDLE_ID
