"""Structured, bounded, sanitized assistant session memory (V2).

Stores small continuity state per session/user: resolved entities, last intent,
pending task hints. No secrets/PII beyond policy; values are sanitized and capped.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

from .. import db, services

_SENSITIVE_RE = re.compile(r"(?i)(password|secret|token|csrf|api[_-]?key|authorization|cookie|session)")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.replace(microsecond=0).isoformat()


def _enabled() -> bool:
    try:
        return str(services.get_setting("assistant_session_memory_enabled", "true")).lower() == "true"
    except Exception:
        return True


def _ttl_minutes() -> int:
    try:
        return max(5, min(int(services.get_setting("assistant_session_memory_ttl_minutes", "120") or 120), 24 * 60))
    except Exception:
        return 120


def _sanitize(value: Any, key: str = "", depth: int = 0) -> Any:
    if depth > 4:
        return "<max_depth>"
    if _SENSITIVE_RE.search(str(key or "")):
        return "<redacted>"
    if isinstance(value, dict):
        out = {}
        for k, v in list(value.items())[:40]:
            out[str(k)[:80]] = _sanitize(v, str(k), depth + 1)
        return out
    if isinstance(value, list):
        return [_sanitize(v, key, depth + 1) for v in value[:30]]
    if isinstance(value, str):
        v = value.strip()
        if len(v) > 300:
            v = v[:297] + "..."
        if _SENSITIVE_RE.search(v):
            return "<redacted>"
        return v
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return str(value)[:300]


def _session_id(ui_context: Mapping[str, Any] | None) -> str:
    ctx = dict(ui_context or {})
    sid = str(ctx.get("session_id") or ctx.get("conversation_id") or ctx.get("sid") or "").strip()
    return sid[:120]


def load_for_chat(ui_context: Mapping[str, Any] | None = None, history: list[dict] | None = None) -> dict[str, Any]:
    if not _enabled():
        return {}
    sid = _session_id(ui_context)
    if not sid:
        return {}
    try:
        with db.connect() as conn:
            row = conn.execute(
                "SELECT memory_json, expires_at FROM assistant_session_memory WHERE session_id=?",
                (sid,),
            ).fetchone()
        if not row:
            return {}
        exp = str(row["expires_at"] or "")
        if exp:
            try:
                if datetime.fromisoformat(exp.replace("Z", "+00:00")) < _now():
                    clear_session(sid)
                    return {}
            except Exception:
                pass
        mem = json.loads(row["memory_json"] or "{}")
        if not isinstance(mem, dict):
            return {}
        # return small context for slot hydration
        slots = {}
        for k in ("reservation_id", "guest_id", "room_id", "activity_id", "date_start", "date_end"):
            if mem.get("last_" + k) is not None:
                slots[k] = mem.get("last_" + k)
        return {"memory": mem, "slots": slots}
    except Exception:
        return {}


def update_after_chat(message: str, result: Mapping[str, Any] | None, ui_context: Mapping[str, Any] | None = None, history: list[dict] | None = None) -> None:
    if not _enabled():
        return
    sid = _session_id(ui_context)
    if not sid:
        return
    res = dict(result or {})
    slots = dict(res.get("slots") or {})
    try:
        existing = {}
        with db.connect() as conn:
            row = conn.execute("SELECT memory_json FROM assistant_session_memory WHERE session_id=?", (sid,)).fetchone()
            if row:
                existing = json.loads(row["memory_json"] or "{}")
                if not isinstance(existing, dict):
                    existing = {}
        mem = dict(existing)
        mem["last_intent"] = str(res.get("intent") or mem.get("last_intent") or "")[:120]
        mem["last_message_preview"] = _sanitize(message, "message") if isinstance(message, str) else ""
        mem["last_updated_at"] = _iso(_now())
        for k in ("reservation_id", "guest_id", "room_id", "activity_id", "date_start", "date_end"):
            v = slots.get(k)
            if v is not None and v != "":
                mem["last_" + k] = _sanitize(v, k)
        if res.get("resolved_guest_id"):
            mem["last_guest_id"] = _sanitize(res.get("resolved_guest_id"), "guest_id")
        if isinstance(res.get("proposed_action"), dict):
            pa = res["proposed_action"]
            mem["last_proposed_action"] = {
                "action_type": _sanitize(pa.get("action_type"), "action_type"),
                "status": _sanitize(pa.get("status"), "status"),
                "summary": _sanitize(pa.get("summary"), "summary"),
            }
        # cap memory size
        mem = _sanitize(mem)
        raw = json.dumps(mem, ensure_ascii=False, default=str)
        if len(raw) > 12000:
            # trim heavy keys
            for k in ["last_message_preview", "last_proposed_action"]:
                mem.pop(k, None)
            raw = json.dumps(mem, ensure_ascii=False, default=str)[:12000]
            mem = json.loads(raw) if raw.startswith("{") else {"trimmed": True}
        expires = _iso(_now() + timedelta(minutes=_ttl_minutes()))
        with db.connect() as conn:
            conn.execute(
                """
                INSERT INTO assistant_session_memory(session_id, actor_user_id, memory_json, updated_at, expires_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    actor_user_id=excluded.actor_user_id,
                    memory_json=excluded.memory_json,
                    updated_at=excluded.updated_at,
                    expires_at=excluded.expires_at
                """,
                (
                    sid,
                    (ui_context or {}).get("actor_user_id"),
                    json.dumps(mem, ensure_ascii=False, default=str),
                    _iso(_now()),
                    expires,
                ),
            )
            conn.commit()
    except Exception:
        return


def clear_session(session_id: str) -> None:
    sid = str(session_id or "").strip()[:120]
    if not sid:
        return
    try:
        with db.connect() as conn:
            conn.execute("DELETE FROM assistant_session_memory WHERE session_id=?", (sid,))
            conn.commit()
    except Exception:
        pass
