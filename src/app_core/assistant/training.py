"""Assistant training dataset selection, estimation, dedupe, and job execution."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..paths import DATA_DIR, PROJECT_ROOT

DATASETS_DIR = DATA_DIR / "datasets"
RAW_DIR = DATASETS_DIR / "raw"
PROCESSED_DIR = DATASETS_DIR / "processed"
MANIFEST_PATH = DATASETS_DIR / "manifest.json"
RUNS_PATH = DATASETS_DIR / "training_runs.jsonl"

DEFAULT_SOURCES = [
    {
        "id": "spms_feedback",
        "label": "SPMS feedback/corrections",
        "path": "data/assistant_nlu/feedback.jsonl",
        "kind": "intent+grounded",
        "description": "Approved thumbs-up/corrections/expected answers from assistant usage.",
        "default": True,
    },
    {
        "id": "spms_intent_seed",
        "label": "SPMS intent seed examples",
        "path": "data/assistant_nlu/intents_seed.jsonl",
        "kind": "intent",
        "description": "Curated seed phrases for intent routing.",
        "default": True,
    },
    {
        "id": "spms_brain_knowledge",
        "label": "SPMS brain knowledge",
        "path": "data/assistant_knowledge/agent_brain.json",
        "kind": "grounded",
        "description": "App knowledge entries from agent_brain.json.",
        "default": True,
    },
    {
        "id": "cocamp_persona",
        "label": "Co-Camp persona & app/business examples",
        "path": "co-camp/co_camp/data/persona_examples.jsonl",
        "kind": "intent+grounded",
        "description": "Co-Camp persona, SPMS app how-to, business/operations/history awareness examples.",
        "default": True,
    },
    {
        "id": "curated_business_history",
        "label": "Business history snapshots (curated)",
        "path": "data/datasets/curated/business_history.jsonl",
        "kind": "grounded",
        "description": "Synthetic/anonymized business history snapshots and trend QA; augment with sanitized real exports.",
        "default": True,
    },
    {
        "id": "curated_ops_knowledge",
        "label": "App/operations knowledge (curated)",
        "path": "data/datasets/curated/app_operations_knowledge.jsonl",
        "kind": "grounded",
        "description": "SPMS module knowledge and operational SOP playbooks.",
        "default": True,
    },
    {
        "id": "curated_feedback_bootstrap",
        "label": "Curated feedback bootstrap",
        "path": "data/datasets/curated/feedback_bootstrap.jsonl",
        "kind": "intent+grounded",
        "description": "Curated bootstrap feedback/corrections with provenance for initial training quality.",
        "default": False,
    },
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except Exception:
            pass
    return rows


def _append_jsonl(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")


def _file_info(rel_path: str) -> dict[str, Any]:
    p = PROJECT_ROOT / rel_path
    exists = p.exists()
    size = p.stat().st_size if exists else 0
    rows = 0
    if exists:
        if p.suffix == ".jsonl":
            rows = sum(1 for l in p.read_text(encoding="utf-8", errors="ignore").splitlines() if l.strip())
        elif p.suffix == ".json":
            try:
                obj = json.loads(p.read_text(encoding="utf-8", errors="ignore"))
                if isinstance(obj, list):
                    rows = len(obj)
                elif isinstance(obj, dict):
                    # brain knowledge or manifest-like
                    if isinstance(obj.get("knowledge"), list):
                        rows = len(obj.get("knowledge") or [])
                    elif isinstance(obj.get("datasets"), list):
                        rows = len(obj.get("datasets") or [])
                    else:
                        rows = len(obj.keys())
            except Exception:
                rows = 0
    return {"path": rel_path, "exists": exists, "bytes": size, "rows": rows}


def list_sources() -> list[dict[str, Any]]:
    sources = []
    for s in DEFAULT_SOURCES:
        info = _file_info(s["path"])
        sources.append({**s, **info})
    # include raw datasets from manifest and raw dir
    manifest = {}
    if MANIFEST_PATH.exists():
        try:
            manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        except Exception:
            manifest = {}
    for ds in (manifest.get("datasets") or []):
        if not isinstance(ds, dict):
            continue
        p = ds.get("path")
        if not p or any(s["path"] == p for s in sources):
            continue
        info = _file_info(p)
        sources.append({
            "id": ds.get("id") or Path(p).stem,
            "label": ds.get("id") or Path(p).name,
            "kind": ds.get("type", "external"),
            "description": ds.get("notes", ""),
            "default": bool(ds.get("enabled", False)),
            **info,
        })
    if RAW_DIR.exists():
        for p in sorted(RAW_DIR.glob("*")):
            if p.is_dir():
                continue
            rel = str(p.relative_to(PROJECT_ROOT))
            if any(s["path"] == rel for s in sources):
                continue
            info = _file_info(rel)
            sources.append({
                "id": p.stem,
                "label": p.name,
                "kind": "external",
                "description": "Raw dataset file in data/datasets/raw/.",
                "default": False,
                **info,
            })
    return sources


def dataset_fingerprint(source_ids: list[str], backend: str, model: str) -> str:
    sources = {s["id"]: s for s in list_sources()}
    payload = {"backend": backend, "model": model, "sources": []}
    for sid in sorted(set(source_ids)):
        s = sources.get(sid)
        if not s:
            continue
        p = PROJECT_ROOT / s["path"]
        stat = p.stat() if p.exists() else None
        payload["sources"].append({
            "id": sid,
            "path": s["path"],
            "bytes": stat.st_size if stat else 0,
            "mtime": int(stat.st_mtime) if stat else 0,
        })
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def training_runs() -> list[dict[str, Any]]:
    return _load_jsonl(RUNS_PATH)


def find_existing_run(fingerprint: str, backend: str, model: str) -> dict[str, Any] | None:
    for r in reversed(training_runs()):
        if r.get("fingerprint") == fingerprint and r.get("backend") == backend and r.get("model") == model:
            if r.get("status") in {"success", "prepared"}:
                return r
    return None


def _device_profile() -> dict[str, Any]:
    cpu = os.cpu_count() or 1
    ram_gb = None
    try:
        # Linux /proc/meminfo
        meminfo = Path("/proc/meminfo")
        if meminfo.exists():
            for line in meminfo.read_text(encoding="utf-8", errors="ignore").splitlines():
                if line.startswith("MemTotal:"):
                    kb = int(line.split()[1])
                    ram_gb = round(kb / 1024 / 1024, 2)
                    break
    except Exception:
        pass
    return {
        "platform": platform.platform(),
        "machine": platform.machine(),
        "python": sys.version.split()[0],
        "cpu_count": cpu,
        "ram_gb": ram_gb,
    }


def estimate_training(source_ids: list[str], backend: str = "sklearn", model: str = "SmolLM2-360M-Instruct") -> dict[str, Any]:
    sources = {s["id"]: s for s in list_sources()}
    selected = [sources[sid] for sid in source_ids if sid in sources]
    total_rows = sum(int(s.get("rows") or 0) for s in selected)
    total_bytes = sum(int(s.get("bytes") or 0) for s in selected)
    dev = _device_profile()
    cpu = max(1, int(dev.get("cpu_count") or 1))
    ram = float(dev.get("ram_gb") or 2.0)

    # Heuristics: rough on-device estimates, not benchmarks.
    if backend == "sklearn":
        # intent classifier is fast
        seconds = 5 + (total_rows / 5000) * 20 + (total_bytes / 1_000_000) * 2
        seconds = seconds / max(1.0, cpu / 4)
        feasible = True
        notes = "Intent classifier (sklearn) usually runs locally."
    elif backend == "setfit":
        seconds = 60 + (total_rows / 1000) * 120
        seconds = seconds / max(1.0, cpu / 4)
        feasible = ram >= 4
        notes = "SetFit needs sentence-transformers/torch; may be slow on CPU-only devices."
    else:  # llm_lora / llm_gguf
        # SmolLM2-360M LoRA fine-tune: usually needs GPU; on CPU very slow
        base = 20 * 60  # 20 min baseline for tiny dataset on decent GPU
        seconds = base + (total_rows / 500) * 15 * 60
        if ram < 8:
            seconds *= 2.5
        if cpu < 8:
            seconds *= 1.5
        # CPU-only assumed on most devices here
        seconds *= 8
        feasible = False
        notes = "SmolLM2-360M fine-tuning is recommended on a GPU machine. This device estimate is rough; use external training and import GGUF."
    eta_min = round(seconds / 60, 1)
    eta_max = round((seconds * 1.8) / 60, 1)
    fp = dataset_fingerprint(source_ids, backend, model)
    existing = find_existing_run(fp, backend, model)
    return {
        "ok": True,
        "backend": backend,
        "model": model,
        "source_ids": sorted(set(source_ids)),
        "total_rows": total_rows,
        "total_bytes": total_bytes,
        "device": dev,
        "estimate_seconds": int(seconds),
        "estimate_minutes_min": eta_min,
        "estimate_minutes_max": eta_max,
        "feasible_on_device": feasible,
        "notes": notes,
        "fingerprint": fp,
        "already_trained": bool(existing),
        "existing_run": existing,
    }


def start_training(source_ids: list[str], backend: str = "sklearn", model: str = "SmolLM2-360M-Instruct") -> dict[str, Any]:
    est = estimate_training(source_ids, backend=backend, model=model)
    if est.get("already_trained"):
        return {**est, "ok": False, "error": "already_trained", "message": "Same model+backend already trained on the same selected data."}
    if not source_ids:
        return {"ok": False, "error": "no_sources", "message": "Select at least one data source."}

    run = {
        "id": hashlib.sha256(f"{time.time()}-{os.getpid()}-{est['fingerprint']}".encode()).hexdigest()[:12],
        "created_at": _now_iso(),
        "backend": backend,
        "model": model,
        "source_ids": est["source_ids"],
        "fingerprint": est["fingerprint"],
        "status": "running",
        "estimate": est,
    }
    job_id = None
    try:
        from . import model_ops
        j = model_ops.create_job(
            "train",
            model_id=model,
            dataset_ref=",".join(est.get("source_ids") or []),
            dataset_fingerprint=est.get("fingerprint", ""),
            config={
                "backend": backend,
                "source_ids": est.get("source_ids") or [],
                "lineage": {
                    "base_model": model,
                    "dataset_ref": ",".join(est.get("source_ids") or []),
                    "dataset_fingerprint": est.get("fingerprint", ""),
                    "source_ids": est.get("source_ids") or [],
                },
            },
            actor="assistant_training",
        )
        job_id = j.get("id")
        run["job_id"] = job_id
    except Exception:
        pass
    _append_jsonl(RUNS_PATH, {**run, "event": "start"})

    try:
        if backend in {"sklearn", "setfit"}:
            cmd = [sys.executable, str(PROJECT_ROOT / "scripts/train_assistant_intent.py"), "--backend", backend]
            if backend == "setfit":
                cmd += ["--base-model", "sentence-transformers/paraphrase-MiniLM-L3-v2"]
            proc = subprocess.run(cmd, cwd=str(PROJECT_ROOT), capture_output=True, text=True, timeout=60 * 30)
            ok = proc.returncode == 0
            run.update({
                "status": "success" if ok else "failed",
                "returncode": proc.returncode,
                "stdout_tail": (proc.stdout or "")[-4000:],
                "stderr_tail": (proc.stderr or "")[-4000:],
                "finished_at": _now_iso(),
            })
        else:
            # LLM fine-tune: prepare dataset and give instructions; don't claim trained on-device.
            prep_cmd = [sys.executable, str(PROJECT_ROOT / "scripts/prepare_assistant_dataset.py")]
            prep = subprocess.run(prep_cmd, cwd=str(PROJECT_ROOT), capture_output=True, text=True, timeout=60 * 10)
            run.update({
                "status": "prepared" if prep.returncode == 0 else "failed",
                "returncode": prep.returncode,
                "stdout_tail": (prep.stdout or "")[-4000:],
                "stderr_tail": (prep.stderr or "")[-4000:],
                "finished_at": _now_iso(),
                "next_steps": [
                    "Run training on a GPU machine: python scripts/train_assistant_llm.py --model HuggingFaceTB/SmolLM2-360M-Instruct --dataset data/datasets/processed/train.jsonl --eval-dataset data/datasets/processed/eval.jsonl --output models/assistant-smollm2-360m-lora",
                    "Merge LoRA and convert to GGUF Q4_K_M with llama.cpp.",
                    "Place GGUF in models/assistant-smollm2-360m-q4_k_m.gguf or set ASSISTANT_LOCAL_MODEL_PATH.",
                ],
            })
    except Exception as e:
        run.update({"status": "failed", "error": str(e), "finished_at": _now_iso()})

    _append_jsonl(RUNS_PATH, {**run, "event": "finish"})
    try:
        if job_id:
            from . import model_ops
            model_ops.update_job(int(job_id), status=str(run.get("status") or "failed"), metrics_json={"returncode": run.get("returncode"), "backend": backend}, error=str(run.get("error") or ""), artifact_path=str(run.get("artifact_path") or ""))
    except Exception:
        pass
    return {**est, "ok": run.get("status") in {"success", "prepared"}, "run": run}


# ---- Versioned sanitized dataset builder (V3, issue #77) ----

DATASET_REDACTION_NOTE = (
    "Sanitized for training: PII/secrets redacted via training_data_share sanitization "
    "(emails, phones, long IDs, card-like numbers). No raw secrets/PII intended. "
    "Deterministic engine remains source of truth; dataset is for explicit operator-approved training/eval only."
)


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _dataset_manifest_path(jsonl_path: Path) -> Path:
    name = jsonl_path.name
    if name.endswith(".jsonl"):
        name = name[:-6]
    return jsonl_path.with_name(name + ".manifest.json")


def _iter_sanitized_dataset_records(pkg: dict[str, Any]) -> list[dict[str, Any]]:
    data = pkg.get("data") if isinstance(pkg.get("data"), dict) else {}
    created_at = str(pkg.get("created_at") or _now_iso())
    prov_base = {
        "package_type": pkg.get("package_type"),
        "package_version": pkg.get("version"),
        "package_sha256": pkg.get("sha256"),
        "bundle_id": pkg.get("bundle_id"),
        "app": pkg.get("app"),
    }
    rows: list[dict[str, Any]] = []

    def add(kind: str, source: str, record: dict[str, Any], idx: int) -> None:
        rec = dict(record) if isinstance(record, dict) else {"value": record}
        rec["_dataset_kind"] = kind
        rec["_source"] = source
        rec["_provenance"] = {**prov_base, "source": source, "kind": kind, "index": idx, "created_at": created_at}
        rec["_sanitized"] = True
        rows.append(rec)

    for i, r in enumerate(data.get("feedback") or []):
        if isinstance(r, dict):
            add("feedback", "assistant_nlu.feedback", r, i)
    for i, r in enumerate(data.get("intent_seed") or []):
        if isinstance(r, dict):
            add("intent_seed", "assistant_nlu.intents_seed", r, i)
    for i, r in enumerate(data.get("persona_examples") or []):
        if isinstance(r, dict):
            add("persona", "co_camp.persona_examples", r, i)
    for i, r in enumerate(data.get("business_history") or []):
        if isinstance(r, dict):
            add("business_history", "datasets.curated.business_history", r, i)
    for i, r in enumerate(data.get("app_operations_knowledge") or []):
        if isinstance(r, dict):
            add("ops_knowledge", "datasets.curated.app_operations_knowledge", r, i)
    return rows


def build_sanitized_dataset(*, actor: str = "assistant_training") -> dict[str, Any]:
    """Build a versioned sanitized JSONL dataset + manifest in data/datasets/processed.

    Explicit operator action only. Reuses training_data_share sanitization.
    """
    from . import training_data_share

    pkg = training_data_share.build_training_share_package()
    records = _iter_sanitized_dataset_records(pkg)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dataset_id = f"sanitized-dataset-{ts}"
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    jsonl_path = PROCESSED_DIR / f"{dataset_id}.jsonl"
    manifest_path = PROCESSED_DIR / f"{dataset_id}.manifest.json"

    with jsonl_path.open("w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")

    sha256 = _sha256_file(jsonl_path)
    size_bytes = jsonl_path.stat().st_size
    def _rel(p: Path) -> str:
        try:
            return str(p.relative_to(PROJECT_ROOT))
        except Exception:
            return str(p)
    manifest = {
        "id": dataset_id,
        "version": 1,
        "created_at": _now_iso(),
        "actor": str(actor or "assistant_training"),
        "kind": "sanitized_training_dataset",
        "format": "jsonl",
        "path": _rel(jsonl_path),
        "manifest_path": _rel(manifest_path),
        "jsonl_path": _rel(jsonl_path),
        "bytes": size_bytes,
        "size_bytes": size_bytes,
        "sha256": sha256,
        "fingerprint": sha256,
        "record_count": len(records),
        "counts": pkg.get("counts") or {},
        "provenance": {
            "source_package": "training_data_share.build_training_share_package",
            "package_type": pkg.get("package_type"),
            "package_version": pkg.get("version"),
            "package_sha256": pkg.get("sha256"),
            "bundle_id": pkg.get("bundle_id"),
            "app": pkg.get("app"),
        },
        "redaction_note": DATASET_REDACTION_NOTE,
        "pii_secrets_redacted": True,
        "no_silent_upload": True,
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # best-effort job/audit tracking
    try:
        from . import model_ops
        job = model_ops.create_job(
            "dataset_build",
            model_id="",
            dataset_ref=manifest["path"],
            dataset_fingerprint=sha256,
            config={"kind": "sanitized", "dataset_id": dataset_id},
            actor=str(actor or "assistant_training"),
        )
        model_ops.update_job(int(job["id"]), status="success", artifact_path=manifest["path"], log_path=manifest["manifest_path"], metrics_json={"bytes": size_bytes, "record_count": len(records), "counts": manifest["counts"]})
    except Exception:
        pass

    return {"ok": True, "dataset": manifest}


def list_sanitized_datasets(limit: int = 50) -> list[dict[str, Any]]:
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    items: list[dict[str, Any]] = []
    for mp in sorted(PROCESSED_DIR.glob("sanitized-dataset-*.manifest.json"), reverse=True):
        try:
            m = json.loads(mp.read_text(encoding="utf-8", errors="ignore"))
        except Exception:
            continue
        if not isinstance(m, dict):
            continue
        # normalize/refresh size if file exists
        p = PROJECT_ROOT / str(m.get("jsonl_path") or m.get("path") or "")
        if p.exists():
            try:
                m["bytes"] = p.stat().st_size
                m["size_bytes"] = m["bytes"]
            except Exception:
                pass
        items.append(m)
        if len(items) >= max(1, min(int(limit or 50), 200)):
            break
    return items


def get_sanitized_dataset(dataset_id: str) -> dict[str, Any] | None:
    did = str(dataset_id or "").strip()
    if not did:
        return None
    # prevent path traversal
    if "/" in did or "\\" in did or ".." in did:
        return None
    mp = PROCESSED_DIR / f"{did}.manifest.json"
    if not mp.exists():
        # allow passing full id without prefix? no, be strict
        return None
    try:
        m = json.loads(mp.read_text(encoding="utf-8", errors="ignore"))
        return m if isinstance(m, dict) else None
    except Exception:
        return None
