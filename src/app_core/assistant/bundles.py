"""Assistant brain/model bundle discovery and resolution.

A bundle is a selectable assistant package: persona/brain config + optional
model artifacts (SetFit/sklearn/GGUF) + training metadata. SPMS ships with a
default bundle and can load Co-Camp or other local/pulled bundles.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .. import services
from ..paths import DATA_DIR, PROJECT_ROOT

logger = logging.getLogger(__name__)

BUNDLE_SCHEMA_VERSION = 1
BUNDLES_DIR = DATA_DIR / "assistant_bundles"
PULLED_MODELS_DIR = DATA_DIR / "assistant_models"
DEFAULT_BUNDLE_ID = "spms_default"
COCAMP_BUNDLE_ID = "cocamp"
COCAMP_REPO_DEFAULT = "https://github.com/Michaelhehelmy/spms-co-camp-models"


@dataclass
class Bundle:
    id: str
    name: str
    version: str = "0.0.0"
    description: str = ""
    source: str = "builtin"  # builtin|local|pulled|package
    root: Path | None = None
    manifest_path: Path | None = None
    manifest: dict[str, Any] = field(default_factory=dict)
    brain_path: Path | None = None
    gguf_path: Path | None = None
    setfit_dir: Path | None = None
    sklearn_path: Path | None = None
    repo_url: str = ""
    capabilities: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "source": self.source,
            "root": str(self.root) if self.root else "",
            "manifest_path": str(self.manifest_path) if self.manifest_path else "",
            "brain_path": str(self.brain_path) if self.brain_path else "",
            "gguf_path": str(self.gguf_path) if self.gguf_path else "",
            "setfit_dir": str(self.setfit_dir) if self.setfit_dir else "",
            "sklearn_path": str(self.sklearn_path) if self.sklearn_path else "",
            "repo_url": self.repo_url,
            "capabilities": self.capabilities,
        }


def _safe_read_json(path: Path) -> dict[str, Any] | None:
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
        return obj if isinstance(obj, dict) else None
    except Exception:
        return None


def _validate_rel(rel: str) -> str:
    p = (rel or "").strip().lstrip("/")
    if not p or any(part in ("", "..") for part in Path(p).parts):
        raise ValueError(f"unsafe relative path: {rel!r}")
    return p


def _resolve_path(root: Path, rel: str | None) -> Path | None:
    if not rel:
        return None
    try:
        return (root / _validate_rel(str(rel))).resolve()
    except Exception:
        return None


def load_manifest(path: Path) -> dict[str, Any] | None:
    data = _safe_read_json(path)
    if not data:
        return None
    # Accept legacy Co-Camp models repo manifest (files/gguf/env) by normalizing.
    if "bundle_id" not in data and ("files" in data or "gguf" in data or "setfit_router" in data):
        data = normalize_legacy_cocamp_manifest(data)
    return data


def normalize_legacy_cocamp_manifest(data: dict[str, Any]) -> dict[str, Any]:
    files = data.get("files") or []
    gguf = data.get("gguf")
    setfit = data.get("setfit_router")
    sklearn = data.get("sklearn_router")
    for entry in files:
        rel = str((entry or {}).get("path") or "")
        if not gguf and rel.lower().endswith(".gguf"):
            gguf = rel
        if not setfit and "assistant_intent_setfit" in rel:
            idx = rel.find("assistant_intent_setfit")
            setfit = rel[: idx + len("assistant_intent_setfit")]
        if not sklearn and "assistant_intent_sklearn" in rel:
            sklearn = rel
    return {
        "schema_version": 1,
        "bundle_id": COCAMP_BUNDLE_ID,
        "name": "Co-Camp",
        "version": str(data.get("version") or "0.0.0"),
        "description": "Co-Camp assistant models bundle",
        "repo_url": data.get("repo") or data.get("repo_url") or COCAMP_REPO_DEFAULT,
        "models": {
            "intent_router": {"setfit_dir": setfit, "sklearn_joblib": sklearn},
            "gguf": {"path": gguf},
        },
        "legacy_files": files,
        "legacy_env": data.get("env") or {},
        "capabilities": {"local_nlu": True, "local_gguf_rephrase": bool(gguf)},
    }


def bundle_from_manifest(manifest: dict[str, Any], *, root: Path, manifest_path: Path | None = None, source: str = "local") -> Bundle:
    bid = str(manifest.get("bundle_id") or manifest.get("id") or "").strip() or "unknown"
    name = str(manifest.get("display_name") or manifest.get("name") or bid).strip()
    models = manifest.get("models") or {}
    intent = models.get("intent_router") or {}
    gguf = models.get("gguf") or {}
    brain = manifest.get("brain") or {}
    brain_path = _resolve_path(root, brain.get("path")) if isinstance(brain, dict) else None
    setfit_dir = _resolve_path(root, intent.get("setfit_dir"))
    sklearn_path = _resolve_path(root, intent.get("sklearn_joblib") or intent.get("sklearn_path"))
    gguf_path = _resolve_path(root, gguf.get("path"))
    return Bundle(
        id=bid,
        name=name,
        version=str(manifest.get("version") or "0.0.0"),
        description=str(manifest.get("description") or ""),
        source=source,
        root=root,
        manifest_path=manifest_path,
        manifest=manifest,
        brain_path=brain_path,
        gguf_path=gguf_path,
        setfit_dir=setfit_dir,
        sklearn_path=sklearn_path,
        repo_url=str(manifest.get("repo_url") or manifest.get("repo") or ""),
        capabilities=manifest.get("capabilities") if isinstance(manifest.get("capabilities"), dict) else {},
    )


def _builtin_default_bundle() -> Bundle:
    from .brain import BRAIN_PATH

    return Bundle(
        id=DEFAULT_BUNDLE_ID,
        name="SPMS Default",
        version="1.0.0",
        description="Built-in SPMS assistant brain and local model defaults.",
        source="builtin",
        root=PROJECT_ROOT,
        brain_path=BRAIN_PATH,
        repo_url="",
        capabilities={"deterministic_tools": True, "local_nlu": True, "local_gguf_rephrase": True},
    )


def _candidate_manifest_paths() -> list[tuple[Path, str]]:
    candidates: list[tuple[Path, str]] = []
    # local dev co-camp bundle
    candidates.append((PROJECT_ROOT / "co-camp" / "brain_bundle" / "manifest.json", "local"))
    candidates.append((PROJECT_ROOT / "co-camp" / "manifest.json", "local"))
    # pulled bundles
    if PULLED_MODELS_DIR.exists():
        for p in PULLED_MODELS_DIR.glob("*/manifest.json"):
            candidates.append((p, "pulled"))
        # legacy flat pulled Co-Camp manifest
        legacy = PULLED_MODELS_DIR / "manifest.json"
        if legacy.exists():
            candidates.append((legacy, "pulled"))
    # installed bundle dirs
    if BUNDLES_DIR.exists():
        for p in BUNDLES_DIR.glob("*/manifest.json"):
            candidates.append((p, "installed"))
    return candidates


def discover_bundles() -> dict[str, Bundle]:
    bundles: dict[str, Bundle] = {DEFAULT_BUNDLE_ID: _builtin_default_bundle()}
    for mp, source in _candidate_manifest_paths():
        try:
            if not mp.exists():
                continue
            manifest = load_manifest(mp)
            if not manifest:
                continue
            root = mp.parent
            b = bundle_from_manifest(manifest, root=root, manifest_path=mp, source=source)
            # legacy flat Co-Camp pulled files live directly under assistant_models/
            if mp == PULLED_MODELS_DIR / "manifest.json" and b.id == COCAMP_BUNDLE_ID:
                b.root = PULLED_MODELS_DIR
                b = bundle_from_manifest(manifest, root=PULLED_MODELS_DIR, manifest_path=mp, source="pulled")
            # don't override richer local bundle with legacy pulled manifest unless missing
            existing = bundles.get(b.id)
            if existing is None or (existing.source == "pulled" and source == "local"):
                bundles[b.id] = b
        except Exception:
            logger.debug("assistant bundles: failed to load %s", mp, exc_info=True)

    # if co-camp package exists but no manifest, expose it as discoverable local bundle
    if COCAMP_BUNDLE_ID not in bundles:
        co_camp_dir = PROJECT_ROOT / "co-camp"
        if co_camp_dir.exists():
            bundles[COCAMP_BUNDLE_ID] = Bundle(
                id=COCAMP_BUNDLE_ID,
                name="Co-Camp",
                version="0.1.0",
                description="Co-Camp SPMS assistant bundle (local package detected).",
                source="local",
                root=co_camp_dir,
                brain_path=None,
                setfit_dir=co_camp_dir / "models" / "assistant_intent_setfit",
                sklearn_path=co_camp_dir / "models" / "assistant_intent_sklearn.joblib",
                gguf_path=co_camp_dir / "model" / "SmolLM2-135M-Instruct-Q4_K_M.gguf",
                repo_url=COCAMP_REPO_DEFAULT,
                capabilities={"local_nlu": True, "local_gguf_rephrase": True},
            )
    return bundles


def _setting(key: str, default: str = "") -> str:
    try:
        return (services.get_setting(key, default) or default).strip()
    except Exception:
        return default


def get_active_bundle_id() -> str:
    bid = _setting("assistant_active_bundle", DEFAULT_BUNDLE_ID) or DEFAULT_BUNDLE_ID
    bid = bid.strip().lower().replace("-", "_")
    aliases = {"default": DEFAULT_BUNDLE_ID, "spms": DEFAULT_BUNDLE_ID, "co_camp": COCAMP_BUNDLE_ID, "cocamp": COCAMP_BUNDLE_ID}
    return aliases.get(bid, bid)


def get_active_bundle() -> Bundle:
    bundles = discover_bundles()
    bid = get_active_bundle_id()
    b = bundles.get(bid)
    if b:
        return b
    logger.warning("assistant bundles: active bundle %s not found; falling back to default", bid)
    return bundles[DEFAULT_BUNDLE_ID]


def resolve_bundle_paths(bundle: Bundle | None = None) -> dict[str, str]:
    b = bundle or get_active_bundle()
    # explicit settings/env override active bundle artifacts
    env_gguf = (os.environ.get("ASSISTANT_LOCAL_MODEL_PATH") or "").strip()
    env_setfit = (os.environ.get("ASSISTANT_SETFIT_MODEL_DIR") or "").strip()
    env_sklearn = (os.environ.get("ASSISTANT_SKLEARN_MODEL") or "").strip()
    set_gguf = _setting("assistant_local_model_path", "")
    set_setfit = _setting("assistant_setfit_model_dir", "")
    set_sklearn = _setting("assistant_sklearn_model_path", "")
    return {
        "bundle_id": b.id,
        "brain_path": str(b.brain_path) if b.brain_path and Path(b.brain_path).exists() else "",
        "gguf_path": env_gguf or set_gguf or (str(b.gguf_path) if b.gguf_path and Path(b.gguf_path).exists() else ""),
        "setfit_dir": env_setfit or set_setfit or (str(b.setfit_dir) if b.setfit_dir and Path(b.setfit_dir).exists() else ""),
        "sklearn_path": env_sklearn or set_sklearn or (str(b.sklearn_path) if b.sklearn_path and Path(b.sklearn_path).exists() else ""),
    }


def list_bundles() -> list[dict[str, Any]]:
    active = get_active_bundle_id()
    out = []
    for b in discover_bundles().values():
        d = b.to_dict()
        d["active"] = b.id == active
        d["resolved"] = resolve_bundle_paths(b)
        out.append(d)
    out.sort(key=lambda x: (0 if x["id"] == DEFAULT_BUNDLE_ID else 1, x["name"]))
    return out
