"""Auto-pull of the Co-Camp assistant models from the models repo on startup.

The assistant models (the fine-tuned SetFit intent router and the bundled GGUF
"talking" model) live in a separate repository (default:
``https://github.com/Michaelhehelmy/spms-co-camp-models``).  On web-server
startup the app downloads the files listed in the repo's ``manifest.json``
into its user-writable data dir (``DATA_DIR/assistant_models/``), verifies each
file's sha256 against the manifest, and then points the assistant plug-ins at
the downloaded copies:

- ``assistant_local_model_path`` + ``ASSISTANT_LOCAL_MODEL_PATH`` → the GGUF
  (``manifest["env"]["gguf"]`` when present, default ``ASSISTANT_LOCAL_MODEL_PATH``).
- ``assistant_setfit_model_dir`` + ``ASSISTANT_SETFIT_MODEL_DIR`` → the SetFit
  router dir (``manifest["env"]["setfit_router"]`` default).
- ``assistant_sklearn_model_path`` + ``ASSISTANT_SKLEARN_MODEL`` → the sklearn
  router path (``manifest["env"]["sklearn_router"]`` default).

Behavior is controlled by settings (see ``SETTINGS_CATALOG`` in
``app_core/services/_seed_data.py``):

- ``assistant_models_repo``      — models repo URL (default the other repo).
- ``assistant_models_auto_pull`` — set to ``false`` to disable auto-pull.

Everything is best-effort and never blocks startup: fetch/download failures
are logged and the app continues (the assistant falls back to its normal
deterministic behavior).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .. import services
from ..paths import DATA_DIR

logger = logging.getLogger(__name__)

DEFAULT_REPO_URL = "https://github.com/Michaelhehelmy/spms-co-camp-models"
MANIFEST_NAME = "manifest.json"
DEST_DIR = DATA_DIR / "assistant_models"
_FETCH_TIMEOUT = 15
_CHUNK = 1 << 20
_FALSE_VALUES = ("0", "false", "no", "off", "disabled")

__all__ = [
    "DEFAULT_REPO_URL",
    "DEST_DIR",
    "pull_models_on_startup",
    "start_pull_on_startup",
]


def _setting(key: str, default: str = "") -> str:
    try:
        return (services.get_setting(key, default) or default).strip()
    except Exception:
        return default


def _is_disabled() -> bool:
    return _setting("assistant_models_auto_pull", "true").lower() in _FALSE_VALUES


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(_CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


def _fetch(url: str) -> bytes:
    parsed = urlparse(url)
    if parsed.scheme not in ("https", "http") or not parsed.netloc:
        raise ValueError(f"Unsupported model URL scheme: {parsed.scheme!r}")
    with urllib.request.urlopen(url, timeout=_FETCH_TIMEOUT) as resp:  # nosec B310 - scheme validated to https/http above; nosemgrep: python.lang.security.audit.dynamic-urllib-use-detected.dynamic-urllib-use-detected
        return resp.read()


def _validate_rel(rel: str) -> str:
    p = (rel or "").strip().lstrip("/")
    if not p or any(part in ("", "..", ".") for part in Path(p).parts):
        raise ValueError(f"unsafe path in manifest: {rel!r}")
    return p


def _model_targets(manifest: dict[str, Any]) -> dict[str, str]:
    """Resolve the model artifacts from the manifest.

    Returns ``{name: relative path}`` for names ``gguf``, ``setfit_router``,
    ``sklearn_router``: prefers the manifest's explicit keys, then falls back
    to matching files in the manifest's ``files`` list.
    """
    targets: dict[str, str] = {}
    for key in ("gguf", "setfit_router", "sklearn_router"):
        if manifest.get(key):
            targets[key] = _validate_rel(str(manifest[key]))
    for entry in manifest.get("files") or []:
        rel = (entry or {}).get("path") or ""
        if not rel:
            continue
        if "gguf" not in targets and rel.lower().endswith(".gguf"):
            targets["gguf"] = _validate_rel(rel)
        if "setfit_router" not in targets and "assistant_intent_setfit" in rel:
            idx = rel.find("assistant_intent_setfit")
            targets["setfit_router"] = _validate_rel(rel[: idx + len("assistant_intent_setfit")])
        if "sklearn_router" not in targets and "assistant_intent_sklearn" in rel:
            targets["sklearn_router"] = _validate_rel(rel)
    return targets


def _apply_model_paths(manifest: dict[str, Any], targets: dict[str, str], dest_root: Path) -> None:
    """Point the assistant plug-ins at the pulled models (settings + env)."""
    env_names = manifest.get("env") or {}

    def _apply(name: str, setting_key: str, default_env: str) -> None:
        rel = targets.get(name)
        if not rel:
            return
        path = dest_root / rel
        env_key = env_names.get(name) or default_env
        try:
            os.environ[env_key] = str(path)
        except Exception:
            logger.debug("assistant models: could not set env %s", env_key, exc_info=True)
        try:
            services.set_setting(setting_key, str(path))
        except Exception:
            logger.debug("assistant models: set_setting(%s) failed", setting_key, exc_info=True)

    _apply("gguf", "assistant_local_model_path", "ASSISTANT_LOCAL_MODEL_PATH")
    _apply("setfit_router", "assistant_setfit_model_dir", "ASSISTANT_SETFIT_MODEL_DIR")
    _apply("sklearn_router", "assistant_sklearn_model_path", "ASSISTANT_SKLEARN_MODEL")


def pull_models_on_startup(repo_url: str | None = None) -> dict:
    """Download the Co-Camp models listed in the repo's manifest into
    ``DATA_DIR/assistant_models/`` and point the assistant at them.

    Returns a summary dict: ``{"repo", "downloaded", "skipped", "failed",
    "applied"}``.  Never raises; all failures are logged.
    """
    if _is_test_env():
        return {"repo": repo_url or "", "downloaded": [], "skipped": [], "failed": [], "applied": False, "skipped_reason": "test_env"}
    summary: dict[str, Any] = {"repo": "", "downloaded": [], "skipped": [], "failed": [], "applied": False}
    if _is_disabled():
        logger.info("assistant models: auto-pull disabled (assistant_models_auto_pull=false)")
        return summary
    repo = (repo_url or _setting("assistant_models_repo", DEFAULT_REPO_URL)).rstrip("/")
    summary["repo"] = repo
    manifest_url = f"{repo}/raw/main/{MANIFEST_NAME}"
    try:
        manifest = json.loads(_fetch(manifest_url).decode("utf-8"))
    except Exception as exc:
        logger.info("assistant models: could not fetch manifest from %s: %s", manifest_url, exc)
        return summary
    if not isinstance(manifest, dict):
        logger.warning("assistant models: manifest from %s is not a JSON object", manifest_url)
        return summary
    files = manifest.get("files") or []
    if not files:
        logger.info("assistant models: manifest from %s lists no files", manifest_url)
        return summary
    dest_root = DEST_DIR
    targets = _model_targets(manifest)
    for entry in files:
        entry = entry or {}
        rel = entry.get("path") or ""
        if not rel:
            continue
        expected = (entry.get("sha256") or "").strip().lower()
        try:
            rel = _validate_rel(rel)
        except ValueError as exc:
            summary["failed"].append(rel)
            logger.warning("assistant models: %s", exc)
            continue
        dest = dest_root / rel
        url = f"{repo}/raw/main/{rel}"
        try:
            if dest.exists() and expected and _sha256(dest).lower() == expected:
                summary["skipped"].append(rel)
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            data = _fetch(url)
            if expected:
                digest = hashlib.sha256(data).hexdigest()
                if digest != expected:
                    raise ValueError(
                        f"checksum mismatch for {rel} from {url}: expected {expected[:12]}…, got {digest[:12]}…"
                    )
            dest.write_bytes(data)
            summary["downloaded"].append(rel)
        except Exception as exc:
            summary["failed"].append(rel)
            logger.warning("assistant models: download failed for %s: %s", rel, exc)
    if summary["downloaded"] or summary["skipped"]:
        try:
            _apply_model_paths(manifest, targets, dest_root)
            summary["applied"] = True
        except Exception:
            logger.exception("assistant models: failed to apply pulled model paths")
    logger.info(
        "assistant models: repo=%s downloaded=%d skipped(up-to-date)=%d failed=%d",
        repo,
        len(summary["downloaded"]),
        len(summary["skipped"]),
        len(summary["failed"]),
    )
    return summary


def _is_test_env() -> bool:
    import sys

    return bool(
        os.environ.get("PYTEST_CURRENT_TEST")
        or os.environ.get("SPMS_DISABLE_MODEL_PULL")
        or "pytest" in sys.modules
    )


def start_pull_on_startup() -> threading.Thread | None:
    """Start ``pull_models_on_startup`` in a daemon thread (best-effort, never blocks)."""
    if _is_test_env():
        logger.debug("assistant models: skipping auto-pull in test environment")
        return None

    def _run() -> None:
        try:
            pull_models_on_startup()
        except Exception:
            logger.debug("assistant models: startup pull failed", exc_info=True)

    t = threading.Thread(target=_run, daemon=True, name="spms-assistant-model-pull")
    t.start()
    return t
