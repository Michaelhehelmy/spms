"""On-demand assistant playbooks/skills (V2/V3).

Loads task-specific playbooks only when relevant. Sources (on-demand, small):
- Built-in deterministic playbooks
- Brain skills (agent_brain.json skills)
- Optional brain manifest `playbooks` key
- Optional data/assistant_knowledge/playbooks.json

No silent writes; deterministic guides grounded in SPMS routes/actions.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from .common import DATA_DIR, _norm_text

logger = logging.getLogger(__name__)

PLAYBOOKS_PATH = DATA_DIR / "assistant_knowledge" / "playbooks.json"

_BUILTIN_PLAYBOOKS = [
    {
        "id": "checkin_checkout",
        "title": "Check-in / Check-out flow",
        "keywords": ["check in", "check out", "arrival", "departure"],
        "steps": [
            "Open Reservations and locate the reservation by guest name or reservation ID.",
            "Verify room readiness/housekeeping status before check-in.",
            "For check-out, review folio balance, record payment if needed, then complete checkout.",
            "All write actions require explicit confirmation in assistant UI.",
        ],
        "routes": ["/reservations", "/housekeeping"],
    },
    {
        "id": "walkin_sale",
        "title": "Walk-in POS sale",
        "keywords": ["walk in", "counter sale", "pos sale", "sell item"],
        "steps": [
            "Identify item(s) by name/SKU/barcode/ID and quantity.",
            "Confirm payment method and total before execution.",
            "Assistant will propose action; you must explicitly confirm before it executes.",
        ],
        "routes": ["/pos"],
        "actions": ["propose_complete_walkin_sale"],
    },
    {
        "id": "record_payment",
        "title": "Record reservation payment",
        "keywords": ["record payment", "take payment", "receive payment", "pay balance"],
        "steps": [
            "Identify reservation ID, amount, and payment method.",
            "Assistant validates reservation/balance impact and proposes action.",
            "Explicit confirmation required before execution.",
        ],
        "routes": ["/reservations", "/accounting"],
        "actions": ["propose_record_payment"],
    },
    {
        "id": "issue_report",
        "title": "Report issue / diagnostics",
        "keywords": ["bug", "issue", "error", "report problem", "diagnostic"],
        "steps": [
            "Open Report issue page to generate sanitized diagnostics.",
            "Review redacted report; optionally share if data contribution is enabled.",
            "No secrets/PII should be included; report is sanitized by default.",
        ],
        "routes": ["/support/report", "/settings"],
    },
]


def _as_str_list(v: Any) -> list[str]:
    if isinstance(v, str):
        v = [v]
    if not isinstance(v, list):
        return []
    out = []
    for x in v:
        s = str(x or "").strip()
        if s:
            out.append(s)
    return out


def normalize_playbook(raw: Any, *, source: str = "") -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    pid = str(raw.get("id") or raw.get("playbook_id") or "").strip()
    title = str(raw.get("title") or raw.get("name") or pid).strip()
    if not pid and not title:
        return None
    if not pid:
        pid = _norm_text(title).replace(" ", "_")[:64] or "playbook"
    steps = _as_str_list(raw.get("steps") or raw.get("checklist") or raw.get("procedure"))
    if not steps:
        desc = str(raw.get("description") or "").strip()
        if desc:
            steps = [desc]
    pb = {
        "id": pid,
        "title": title or pid,
        "description": str(raw.get("description") or "").strip(),
        "keywords": _as_str_list(raw.get("keywords") or raw.get("triggers") or []),
        "steps": steps,
        "routes": _as_str_list(raw.get("routes") or []),
        "actions": _as_str_list(raw.get("actions") or []),
        "tags": _as_str_list(raw.get("tags") or []),
        "enabled": bool(raw.get("enabled", True)),
        "source": str(raw.get("source") or source or "").strip(),
    }
    # keep small deterministic metadata if present
    for k in ("intent", "module", "version"):
        if raw.get(k) is not None:
            pb[k] = str(raw.get(k))
    return pb


def validate_playbook(pb: Any) -> list[str]:
    errs: list[str] = []
    if not isinstance(pb, dict):
        return ["playbook must be an object"]
    if not str(pb.get("id") or "").strip():
        errs.append("id is required")
    if not str(pb.get("title") or pb.get("name") or "").strip():
        errs.append("title/name is required")
    for k in ("keywords", "steps", "routes", "actions", "tags"):
        if k in pb and not isinstance(pb.get(k), list):
            errs.append(f"{k} must be a list")
    if "enabled" in pb and not isinstance(pb.get("enabled"), bool):
        errs.append("enabled must be boolean")
    return errs


def _load_json_file(path: Path) -> Any:
    try:
        if not path.exists() or not path.is_file():
            return None
        return json.loads(path.read_text(encoding="utf-8", errors="ignore"))
    except Exception:
        logger.debug("playbooks: failed to load %s", path, exc_info=True)
        return None


def _playbooks_from_brain() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    try:
        from .brain import load_brain

        b = load_brain()
        data = b.data if hasattr(b, "data") else {}
        # explicit playbooks key in brain manifest
        for raw in (data.get("playbooks") or []):
            pb = normalize_playbook(raw, source="brain_manifest")
            if pb and pb.get("enabled", True):
                out.append(pb)
        # skills as playbooks (legacy/compatible)
        for s in (data.get("skills") or []):
            if not isinstance(s, dict):
                continue
            raw = {
                "id": f"brain:{s.get('id')}",
                "title": s.get("name") or s.get("id"),
                "description": s.get("description") or "",
                "keywords": [str(s.get("name") or ""), str(s.get("id") or ""), str(s.get("description") or "")],
                "steps": s.get("steps") or s.get("checklist") or [s.get("description") or ""],
                "routes": s.get("routes") or [],
                "actions": s.get("actions") or [],
                "tags": s.get("tags") or [],
                "enabled": bool(s.get("enabled", True)),
                "source": "brain_skill",
            }
            pb = normalize_playbook(raw, source="brain_skill")
            if pb and pb.get("enabled", True):
                out.append(pb)
    except Exception:
        logger.debug("playbooks: brain load failed", exc_info=True)
    return out


def load_playbooks_file(path: Path | None = None) -> list[dict[str, Any]]:
    """Load playbooks from data/assistant_knowledge/playbooks.json on demand."""
    p = path or PLAYBOOKS_PATH
    obj = _load_json_file(p)
    if obj is None:
        return []
    items = obj.get("playbooks") if isinstance(obj, dict) else obj
    if not isinstance(items, list):
        return []
    out: list[dict[str, Any]] = []
    for raw in items:
        pb = normalize_playbook(raw, source="playbooks_file")
        if not pb or not pb.get("enabled", True):
            continue
        errs = validate_playbook(pb)
        if errs:
            logger.debug("playbooks: skipping invalid playbook %s: %s", pb.get("id"), errs)
            continue
        out.append(pb)
    return out


def list_playbooks(*, include_disabled: bool = False) -> list[dict[str, Any]]:
    items = [normalize_playbook(dict(p), source="builtin") for p in _BUILTIN_PLAYBOOKS]
    items.extend(_playbooks_from_brain())
    items.extend(load_playbooks_file())
    # dedupe by id, first wins (builtins highest priority)
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for p in items:
        if not isinstance(p, dict):
            continue
        if not include_disabled and not p.get("enabled", True):
            continue
        pid = str(p.get("id") or "").strip()
        if not pid or pid in seen:
            continue
        seen.add(pid)
        out.append(p)
    return out


def find_relevant(message: str = "", intent: str = "", limit: int = 3) -> list[dict[str, Any]]:
    t = _norm_text(message)
    it = _norm_text(intent)
    scored = []
    for p in list_playbooks():
        score = 0.0
        for kw in p.get("keywords", []):
            k = _norm_text(kw)
            if k and k in t:
                score += 2.0 if " " in k else 1.0
        for kw in [p.get("title"), p.get("id"), p.get("module"), p.get("intent")]:
            k = _norm_text(str(kw or ""))
            if k and k in t:
                score += 1.5
        for tag in p.get("tags", []):
            k = _norm_text(tag)
            if k and k in t:
                score += 0.75
        if it:
            if any(it in _norm_text(str(a)) for a in p.get("actions", [])):
                score += 1.5
            if it == _norm_text(str(p.get("intent") or "")):
                score += 2.0
        if score > 0:
            scored.append({**p, "score": round(score, 3)})
    scored.sort(key=lambda x: (-float(x.get("score") or 0), str(x.get("id"))))
    return scored[: max(1, min(int(limit or 3), 10))]


def get_playbook(playbook_id: str) -> dict[str, Any] | None:
    pid = str(playbook_id or "").strip()
    if not pid:
        return None
    for p in list_playbooks(include_disabled=True):
        if str(p.get("id")) == pid:
            return p
    return None
