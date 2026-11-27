"""Opt-in sanitized training-data sharing (app -> landing page -> GitHub).

Default OFF. When explicitly enabled by the user, the app may auto-upload a
sanitized training-data package monthly when online. No raw PII/secrets should
be included; the package is intended for model retraining only.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import threading
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .. import services
from ..paths import DATA_DIR, PROJECT_ROOT

logger = logging.getLogger(__name__)

DEFAULT_UPLOAD_URL = "https://spms-landing.pages.dev/api/training-data"
DEFAULT_REPO = "Michaelhehelmy/spms-training-inbox"
DEFAULT_MIN_BYTES = 1_048_576
SHARE_STATE_PATH = DATA_DIR / "assistant_training_share_state.json"
_FETCH_TIMEOUT = 20
_FALSE_VALUES = ("0", "false", "no", "off", "disabled")

EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)
PHONE_RE = re.compile(r"\b(?:\+?\d[\d\s().-]{7,}\d)\b")
LONG_ID_RE = re.compile(r"\b(?:guest|reservation|booking|folio|invoice|payment|group|room|item|approval)\s*#?\s*(\d{3,})\b", re.I)
CC_RE = re.compile(r"\b(?:\d[ -]*?){13,16}\b")


def _setting(key: str, default: str = "") -> str:
    try:
        return (services.get_setting(key, default) or default).strip()
    except Exception:
        return default


def _is_test_env() -> bool:
    import sys

    return bool(
        os.environ.get("PYTEST_CURRENT_TEST")
        or os.environ.get("SPMS_DISABLE_TRAINING_SHARE")
        or "pytest" in sys.modules
    )


def _enabled() -> bool:
    a = _setting("app_data_contribution_enabled", "false").lower() not in _FALSE_VALUES
    b = _setting("assistant_training_share_enabled", "false").lower() not in _FALSE_VALUES
    return bool(a or b)


def _min_bytes() -> int:
    try:
        return max(1, int(_setting("assistant_training_share_min_bytes", str(DEFAULT_MIN_BYTES))))
    except Exception:
        return DEFAULT_MIN_BYTES


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


def _redact_text(text: str) -> str:
    if not text:
        return ""
    s = str(text)
    s = EMAIL_RE.sub("[REDACTED_EMAIL]", s)
    s = CC_RE.sub("[REDACTED_NUMBER]", s)
    s = PHONE_RE.sub("[REDACTED_PHONE]", s)
    s = LONG_ID_RE.sub(lambda m: f"{m.group(0).split()[0]} #[REDACTED_ID]", s)
    return s


def _sanitize_feedback(rows: list[dict]) -> list[dict]:
    out = []
    for r in rows:
        msg = _redact_text(r.get("message") or "")
        ans = _redact_text(r.get("expected_answer") or r.get("corrected_answer") or r.get("answer_preview") or "")
        note = _redact_text(r.get("user_note") or "")
        # keep training-useful fields only
        out.append({
            "created_at": r.get("created_at"),
            "message": msg,
            "predicted_intent": r.get("predicted_intent") or "",
            "corrected_intent": r.get("corrected_intent") or "",
            "rating": int(r.get("rating") or 0),
            "expected_answer": ans,
            "user_note": note,
            "source": r.get("source") or "",
            "status": r.get("status") or "",
            "sanitized": True,
        })
    return out


def build_training_share_package() -> dict[str, Any]:
    """Build a sanitized training-data package for maintainer review/retraining."""
    bundle_id = "spms_default"
    assistant_name = "Co-Camp"
    try:
        from .bundles import get_active_bundle

        b = get_active_bundle()
        bundle_id = b.id
        assistant_name = b.name or assistant_name
    except Exception:
        pass
    feedback = _sanitize_feedback(_load_jsonl(PROJECT_ROOT / "data" / "assistant_nlu" / "feedback.jsonl"))
    intent_seed = _load_jsonl(PROJECT_ROOT / "data" / "assistant_nlu" / "intents_seed.jsonl")
    persona = _load_jsonl(PROJECT_ROOT / "co-camp" / "co_camp" / "data" / "persona_examples.jsonl")
    curated_history = _load_jsonl(PROJECT_ROOT / "data" / "datasets" / "curated" / "business_history.jsonl")
    curated_ops = _load_jsonl(PROJECT_ROOT / "data" / "datasets" / "curated" / "app_operations_knowledge.jsonl")
    manifest = {}
    mp = PROJECT_ROOT / "data" / "datasets" / "manifest.json"
    if mp.exists():
        try:
            manifest = json.loads(mp.read_text(encoding="utf-8"))
        except Exception:
            manifest = {}

    # sanitize intent/persona text lightly
    def _sanitize_text_rows(rows):
        out = []
        for r in rows:
            rr = dict(r)
            if "text" in rr:
                rr["text"] = _redact_text(rr.get("text") or "")
            if "target_answer" in rr:
                rr["target_answer"] = _redact_text(rr.get("target_answer") or "")
            if "question" in rr:
                rr["question"] = _redact_text(rr.get("question") or "")
            if "answer" in rr:
                rr["answer"] = _redact_text(rr.get("answer") or "")
            out.append(rr)
        return out

    package = {
        "package_type": "spms_training_data_share",
        "version": 1,
        "created_at": _now_iso(),
        "app": "SPMS",
        "assistant": assistant_name,
        "bundle_id": bundle_id,
        "consent": {
            "opt_in": True,
            "setting": "assistant_training_share_enabled",
            "notice": "Sanitized training data only; no raw PII/secrets intended. User explicitly opted in.",
        },
        "counts": {
            "feedback": len(feedback),
            "intent_seed": len(intent_seed),
            "persona": len(persona),
            "business_history": len(curated_history),
            "ops_knowledge": len(curated_ops),
        },
        "data": {
            "feedback": feedback,
            "intent_seed": _sanitize_text_rows(intent_seed),
            "persona_examples": _sanitize_text_rows(persona),
            "business_history": _sanitize_text_rows(curated_history),
            "app_operations_knowledge": _sanitize_text_rows(curated_ops),
            "dataset_manifest": manifest,
        },
    }
    raw = json.dumps(package, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    package["size_bytes"] = len(raw)
    package["sha256"] = hashlib.sha256(raw).hexdigest()
    return package


def package_size_bytes() -> int:
    pkg = build_training_share_package()
    return int(pkg.get("size_bytes") or 0)


def _load_state() -> dict:
    if not SHARE_STATE_PATH.exists():
        return {}
    try:
        return json.loads(SHARE_STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_state(state: dict) -> None:
    SHARE_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    SHARE_STATE_PATH.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _last_upload_at() -> datetime | None:
    for src in (_setting("assistant_training_share_last_upload_at", ""), _load_state().get("last_upload_at", "")):
        if not src:
            continue
        try:
            return datetime.fromisoformat(str(src).replace("Z", "+00:00"))
        except Exception:
            pass
    return None


def should_upload_now() -> tuple[bool, str]:
    if not _enabled():
        return False, "disabled"
    pkg_size = package_size_bytes()
    if pkg_size < _min_bytes():
        return False, f"below_min_size:{pkg_size}<{_min_bytes()}"
    last = _last_upload_at()
    if last is not None:
        age = datetime.now(timezone.utc) - last.astimezone(timezone.utc)
        if age < timedelta(days=30):
            return False, f"recent_upload:{age.days}d"
    return True, "ok"


def upload_training_package() -> dict[str, Any]:
    """Upload sanitized package to configured landing-page endpoint."""
    if not _enabled():
        return {"ok": False, "error": "disabled"}
    url = _setting("assistant_training_share_upload_url", DEFAULT_UPLOAD_URL) or DEFAULT_UPLOAD_URL
    parsed = urlparse(url)
    if parsed.scheme not in ("https", "http") or not parsed.netloc:
        return {"ok": False, "error": "invalid_upload_url"}

    pkg = build_training_share_package()
    size = int(pkg.get("size_bytes") or 0)
    min_bytes = _min_bytes()
    if size < min_bytes:
        return {"ok": False, "error": "below_min_size", "size_bytes": size, "min_bytes": min_bytes}

    body = json.dumps(pkg, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("User-Agent", "spms-training-share/1")
    req.add_header("X-SPMS-Training-Share", "1")
    try:
        with urllib.request.urlopen(req, timeout=_FETCH_TIMEOUT) as resp:  # nosec B310 - scheme validated above
            raw = resp.read().decode("utf-8", errors="ignore")
            data = json.loads(raw) if raw else {}
            ok = bool(resp.status >= 200 and resp.status < 300 and data.get("ok", True))
    except Exception as e:
        data = {"ok": False, "error": str(e)}
        ok = False

    state = _load_state()
    state.update({
        "last_attempt_at": _now_iso(),
        "last_upload_at": _now_iso() if ok else state.get("last_upload_at", ""),
        "last_status": "ok" if ok else f"error:{data.get('error','upload_failed')}",
        "last_response": data,
        "last_size_bytes": size,
        "last_sha256": pkg.get("sha256"),
    })
    _save_state(state)
    try:
        services.set_setting("assistant_training_share_last_upload_at", state.get("last_upload_at", ""))
        services.set_setting("assistant_training_share_last_status", state.get("last_status", ""))
    except Exception:
        logger.debug("training share: failed to persist status settings", exc_info=True)
    return {"ok": ok, "size_bytes": size, "response": data, "url": url}


def maybe_upload_monthly() -> dict[str, Any]:
    ok, reason = should_upload_now()
    if not ok:
        return {"ok": False, "skipped": reason}
    return upload_training_package()


def start_monthly_upload_on_startup() -> threading.Thread | None:
    if _is_test_env():
        return None

    def _run() -> None:
        try:
            # small delay so startup/network settle
            time.sleep(5)
            res = maybe_upload_monthly()
            logger.info("training share startup check: %s", res.get("skipped") or res.get("ok"))
        except Exception:
            logger.debug("training share startup check failed", exc_info=True)

    t = threading.Thread(target=_run, daemon=True, name="spms-training-share")
    t.start()
    return t
