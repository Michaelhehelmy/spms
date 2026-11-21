from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from app_core.assistant import training


@pytest.fixture()
def training_env(tmp_path, monkeypatch):
    root = tmp_path / "proj"
    data = root / "data"
    datasets = data / "datasets"
    raw = datasets / "raw"
    processed = datasets / "processed"
    raw.mkdir(parents=True)
    processed.mkdir(parents=True)
    (data / "assistant_nlu").mkdir(parents=True)
    (data / "assistant_knowledge").mkdir(parents=True)
    # seed files
    (data / "assistant_nlu" / "feedback.jsonl").write_text('{"a":1}\n', encoding="utf-8")
    (data / "assistant_nlu" / "intents_seed.jsonl").write_text('{"b":2}\n{"c":3}\n', encoding="utf-8")
    (data / "assistant_knowledge" / "agent_brain.json").write_text(json.dumps({"knowledge": [{"k": 1}, {"k": 2}]}), encoding="utf-8")
    manifest = {"datasets": [{"id": "ext1", "path": "data/datasets/raw/ext1.jsonl", "type": "external", "enabled": True, "notes": "n"}]}
    (datasets / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (raw / "ext1.jsonl").write_text('{"x":1}\n', encoding="utf-8")
    (raw / "extra.csv").write_text("a,b\n1,2\n", encoding="utf-8")

    monkeypatch.setattr(training, "PROJECT_ROOT", root)
    monkeypatch.setattr(training, "DATA_DIR", data)
    monkeypatch.setattr(training, "DATASETS_DIR", datasets)
    monkeypatch.setattr(training, "RAW_DIR", raw)
    monkeypatch.setattr(training, "PROCESSED_DIR", processed)
    monkeypatch.setattr(training, "MANIFEST_PATH", datasets / "manifest.json")
    monkeypatch.setattr(training, "RUNS_PATH", datasets / "training_runs.jsonl")
    return root


def test_list_sources_includes_builtin_manifest_and_raw(training_env):
    srcs = training.list_sources()
    ids = {s["id"] for s in srcs}
    assert "spms_feedback" in ids
    assert "spms_intent_seed" in ids
    assert "spms_brain_knowledge" in ids
    assert "ext1" in ids
    assert "extra" in ids
    fb = next(s for s in srcs if s["id"] == "spms_feedback")
    assert fb["exists"] is True and fb["rows"] == 1
    brain = next(s for s in srcs if s["id"] == "spms_brain_knowledge")
    assert brain["rows"] == 2


def test_dataset_fingerprint_changes_with_selection(training_env):
    fp1 = training.dataset_fingerprint(["spms_feedback"], "sklearn", "m")
    fp2 = training.dataset_fingerprint(["spms_feedback", "spms_intent_seed"], "sklearn", "m")
    fp3 = training.dataset_fingerprint(["spms_feedback"], "setfit", "m")
    assert fp1 != fp2
    assert fp1 != fp3
    # unknown source ignored
    fp4 = training.dataset_fingerprint(["spms_feedback", "nope"], "sklearn", "m")
    assert fp1 == fp4


def test_estimate_training_backends(training_env, monkeypatch):
    monkeypatch.setattr(training, "_device_profile", lambda: {"cpu_count": 8, "ram_gb": 16.0, "platform": "x", "machine": "x", "python": "3.12"})
    e1 = training.estimate_training(["spms_feedback"], backend="sklearn", model="m")
    assert e1["ok"] and e1["feasible_on_device"] is True
    assert e1["already_trained"] is False
    e2 = training.estimate_training(["spms_feedback"], backend="setfit", model="m")
    assert e2["backend"] == "setfit"
    e3 = training.estimate_training(["spms_feedback"], backend="llm_lora", model="SmolLM2-360M-Instruct")
    assert e3["backend"] == "llm_lora"
    assert e3["feasible_on_device"] is False
    # low ram branch
    monkeypatch.setattr(training, "_device_profile", lambda: {"cpu_count": 2, "ram_gb": 2.0, "platform": "x", "machine": "x", "python": "3.12"})
    e4 = training.estimate_training(["spms_feedback"], backend="setfit", model="m")
    assert e4["feasible_on_device"] is False
    e5 = training.estimate_training(["spms_feedback"], backend="llm_lora", model="m")
    assert e5["estimate_seconds"] > e3["estimate_seconds"] / 10  # rough sanity


def test_find_existing_run_and_dedupe(training_env, monkeypatch):
    monkeypatch.setattr(training, "_device_profile", lambda: {"cpu_count": 4, "ram_gb": 8.0, "platform": "x", "machine": "x", "python": "3.12"})
    fp = training.dataset_fingerprint(["spms_feedback"], "sklearn", "m")
    assert training.find_existing_run(fp, "sklearn", "m") is None
    training._append_jsonl(training.RUNS_PATH, {"fingerprint": fp, "backend": "sklearn", "model": "m", "status": "success"})
    assert training.find_existing_run(fp, "sklearn", "m") is not None
    est = training.estimate_training(["spms_feedback"], backend="sklearn", model="m")
    assert est["already_trained"] is True


def test_start_training_blocks_duplicate(training_env, monkeypatch):
    monkeypatch.setattr(training, "_device_profile", lambda: {"cpu_count": 4, "ram_gb": 8.0, "platform": "x", "machine": "x", "python": "3.12"})
    monkeypatch.setattr(training.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not run")))
    fp = training.dataset_fingerprint(["spms_feedback"], "sklearn", "m")
    training._append_jsonl(training.RUNS_PATH, {"fingerprint": fp, "backend": "sklearn", "model": "m", "status": "success"})
    # also ensure find_existing_run sees it via same module state
    assert training.find_existing_run(fp, "sklearn", "m") is not None
    res = training.start_training(["spms_feedback"], backend="sklearn", model="m")
    assert res["ok"] is False and res["error"] == "already_trained"


def test_start_training_no_sources(training_env, monkeypatch):
    monkeypatch.setattr(training, "_device_profile", lambda: {"cpu_count": 4, "ram_gb": 8.0, "platform": "x", "machine": "x", "python": "3.12"})
    res = training.start_training([], backend="sklearn", model="m")
    assert res["ok"] is False and res["error"] == "no_sources"


def test_start_training_sklearn_success_and_failure(training_env, monkeypatch):
    monkeypatch.setattr(training, "_device_profile", lambda: {"cpu_count": 4, "ram_gb": 8.0, "platform": "x", "machine": "x", "python": "3.12"})

    def fake_run(cmd, cwd=None, capture_output=None, text=None, timeout=None):
        return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")
    monkeypatch.setattr(training.subprocess, "run", fake_run)
    res = training.start_training(["spms_feedback"], backend="sklearn", model="m")
    assert res["ok"] is True
    assert res["run"]["status"] == "success"

    # failure
    monkeypatch.setattr(training, "find_existing_run", lambda *a, **k: None)
    monkeypatch.setattr(training.subprocess, "run", lambda cmd, **kwargs: subprocess.CompletedProcess(cmd, 2, stdout="", stderr="bad"))
    res2 = training.start_training(["spms_intent_seed"], backend="sklearn", model="m2")
    assert res2["ok"] is False
    assert res2["run"]["status"] == "failed"


def test_start_training_setfit_and_llm_prepare(training_env, monkeypatch):
    monkeypatch.setattr(training, "_device_profile", lambda: {"cpu_count": 4, "ram_gb": 8.0, "platform": "x", "machine": "x", "python": "3.12"})
    calls = []
    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="prep", stderr="")
    monkeypatch.setattr(training.subprocess, "run", fake_run)
    res = training.start_training(["spms_feedback"], backend="setfit", model="m")
    assert res["ok"] is True
    assert "--backend" in calls[-1] and "setfit" in calls[-1]

    monkeypatch.setattr(training, "find_existing_run", lambda *a, **k: None)
    res2 = training.start_training(["spms_feedback"], backend="llm_lora", model="SmolLM2-360M-Instruct")
    assert res2["ok"] is True
    assert res2["run"]["status"] == "prepared"
    assert "next_steps" in res2["run"]
    assert any("prepare_assistant_dataset.py" in str(c) for c in calls)


def test_start_training_exception(training_env, monkeypatch):
    monkeypatch.setattr(training, "_device_profile", lambda: {"cpu_count": 4, "ram_gb": 8.0, "platform": "x", "machine": "x", "python": "3.12"})
    monkeypatch.setattr(training, "find_existing_run", lambda *a, **k: None)
    monkeypatch.setattr(training.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    res = training.start_training(["spms_feedback"], backend="sklearn", model="m")
    assert res["ok"] is False
    assert res["run"]["status"] == "failed"
    assert "boom" in res["run"]["error"]


def test_file_info_and_load_helpers(training_env):
    assert training._file_info("missing.jsonl")["exists"] is False
    p = training_env / "data" / "list.json"
    p.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
    assert training._file_info("data/list.json")["rows"] == 3
    p2 = training_env / "data" / "dict.json"
    p2.write_text(json.dumps({"datasets": [1, 2]}), encoding="utf-8")
    assert training._file_info("data/dict.json")["rows"] == 2
    p3 = training_env / "data" / "bad.json"
    p3.write_text("{bad", encoding="utf-8")
    assert training._file_info("data/bad.json")["rows"] == 0
    # jsonl bad line
    jl = training_env / "data" / "bad.jsonl"
    jl.write_text('{"a":1}\n{bad}\n\n', encoding="utf-8")
    rows = training._load_jsonl(jl)
    assert len(rows) == 1
    assert training._load_jsonl(training_env / "nope.jsonl") == []


def test_device_profile_and_manifest_edge_cases(training_env, monkeypatch):
    dev = training._device_profile()
    assert "cpu_count" in dev and "platform" in dev
    # bad manifest
    training.MANIFEST_PATH.write_text("{bad", encoding="utf-8")
    srcs = training.list_sources()
    assert isinstance(srcs, list)
    # manifest datasets not list / missing path / duplicate path
    training.MANIFEST_PATH.write_text(json.dumps({"datasets": ["bad", {"id": "x"}, {"id": "dup", "path": "data/assistant_nlu/feedback.jsonl"}]}), encoding="utf-8")
    srcs2 = training.list_sources()
    assert any(s["id"] == "spms_feedback" for s in srcs2)


def test_start_training_llm_prepare_fail(training_env, monkeypatch):
    monkeypatch.setattr(training, "_device_profile", lambda: {"cpu_count": 4, "ram_gb": 8.0, "platform": "x", "machine": "x", "python": "3.12"})
    monkeypatch.setattr(training, "find_existing_run", lambda *a, **k: None)
    monkeypatch.setattr(training.subprocess, "run", lambda cmd, **kwargs: subprocess.CompletedProcess(cmd, 1, stdout="", stderr="prep failed"))
    res = training.start_training(["spms_feedback"], backend="llm_lora", model="m")
    assert res["ok"] is False
    assert res["run"]["status"] == "failed"


def test_estimate_no_sources(training_env, monkeypatch):
    monkeypatch.setattr(training, "_device_profile", lambda: {"cpu_count": 4, "ram_gb": 8.0, "platform": "x", "machine": "x", "python": "3.12"})
    est = training.estimate_training([], backend="sklearn", model="m")
    assert est["ok"] is True
    assert est["total_rows"] == 0


def test_device_profile_no_meminfo(training_env, monkeypatch):
    real_exists = Path.exists
    def fake_exists(self):
        if str(self) == "/proc/meminfo":
            return False
        return real_exists(self)
    monkeypatch.setattr(training.Path, "exists", fake_exists)
    dev = training._device_profile()
    assert dev["ram_gb"] is None


def test_estimate_ram_none(training_env, monkeypatch):
    monkeypatch.setattr(training, "_device_profile", lambda: {"cpu_count": 1, "ram_gb": None, "platform": "x", "machine": "x", "python": "3.12"})
    est = training.estimate_training(["spms_feedback"], backend="llm_lora", model="m")
    assert est["ok"] is True


def test_file_info_dict_plain_and_raw_dir(training_env, monkeypatch):
    p = training_env / "data" / "plain.json"
    p.write_text(json.dumps({"a": 1, "b": 2}), encoding="utf-8")
    assert training._file_info("data/plain.json")["rows"] == 2
    # raw dir with subdir should be ignored
    sub = training.RAW_DIR / "subdir"
    sub.mkdir()
    srcs = training.list_sources()
    assert all(s["id"] != "subdir" for s in srcs)


def test_device_profile_exception(training_env, monkeypatch):
    real_read = Path.read_text
    def fake_read(self, *a, **k):
        if str(self) == "/proc/meminfo":
            raise RuntimeError("boom")
        return real_read(self, *a, **k)
    monkeypatch.setattr(Path, "read_text", fake_read)
    # force exists true
    real_exists = Path.exists
    monkeypatch.setattr(Path, "exists", lambda self: True if str(self) == "/proc/meminfo" else real_exists(self))
    dev = training._device_profile()
    assert dev["ram_gb"] is None
