from __future__ import annotations

import logging

import json
import os
import time
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import Response

from app_core import assistant, services
from app_core.assistant import training as assistant_training
from app_core.assistant.actions import create_proposal, execute_pending_action
from ui.web import deps
from ui.web.rendering import render
from ui.web.route_utils import flash_redirect, guarded_unlock_redirect, htmx_partial_or_redirect

logger = logging.getLogger(__name__)


def _json_safe_value(value, _depth=0):
    """Return a JSON-safe sanitized copy (drops exception/trace-like objects)."""
    if _depth > 8:
        return str(value)  # pragma: no cover
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, BaseException):  # pragma: no cover
        return "internal_error"
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            try:
                key = str(k)
            except Exception:  # pragma: no cover
                continue
            # avoid leaking traceback/exception internals by key names
            if key in {"__traceback__", "tb", "traceback", "exception", "exc_info"}:
                continue
            out[key] = _json_safe_value(v, _depth + 1)
        return out
    if isinstance(value, (list, tuple, set)):
        return [_json_safe_value(v, _depth + 1) for v in list(value)[:200]]
    # fallback: string form, but avoid repr of exception objects
    try:
        if value.__class__.__module__ in ("traceback", "types") and value.__class__.__name__ in (
            "TracebackType",
            "FrameType",
            "CodeType",
        ):
            return "internal_error"
    except Exception:  # pragma: no cover
        pass
    return str(value)


router = APIRouter()

PENDING_ACTION_SESSION_KEY = "assistant_pending_action"
PENDING_ACTION_TTL_SECONDS = 600


def _now_ts() -> int:
    return int(time.time())


def _iso_utc(ts: int | None = None) -> str:
    return datetime.fromtimestamp(ts if ts is not None else _now_ts(), tz=timezone.utc).isoformat()


def _parse_body_fields(form, payload: dict[str, Any] | None, *keys: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k in keys:
        v = None
        if payload and k in payload:
            v = payload.get(k)
        elif form is not None:
            try:
                v = form.get(k)
            except Exception:  # pragma: no cover
                v = None
        if v is not None:
            out[k] = v
    return out


async def _get_request_data(request: Request):
    form = None
    payload = None
    ct = (request.headers.get("content-type") or "").lower()
    try:
        if "application/json" in ct:
            payload = await request.json()  # pragma: no cover
            if not isinstance(payload, dict):  # pragma: no cover
                payload = {}  # pragma: no cover
        else:
            form = await deps.get_form(request)
    except Exception:  # pragma: no cover
        try:
            form = await deps.get_form(request)
        except Exception:  # pragma: no cover
            form = None
            payload = payload if isinstance(payload, dict) else {}
    return form, (payload or {})


def _normalize_pending_action(proposed: dict[str, Any] | None, ui_context: Any = None) -> dict[str, Any] | None:
    if not isinstance(proposed, dict):
        return None
    action = dict(proposed)
    # Never normalize/store denied policy results as pending executable actions.
    pol = action.get("policy") if isinstance(action.get("policy"), dict) else {}
    if str(action.get("status") or "").lower() == "denied" or str(pol.get("effect") or "").lower() == "deny":
        return None
    # Ensure proposal shape/id if caller only provided a raw action hint
    if not action.get("id") or not action.get("type"):
        try:
            # If this already looks like a proposal result, don't re-create from it.
            if action.get("action_type") and action.get("prechecks"):
                action = dict(action)
                action.setdefault("type", action.get("action_type"))
                action.setdefault("id", action.get("action_id") or "")
            else:
                action = create_proposal(action)
        except Exception:
            # best-effort fallback normalization
            action = dict(action)
    created = _now_ts()
    action.setdefault("created_at", _iso_utc(created))
    try:
        exp = int(action.get("expires_at_ts") or 0)
    except Exception:  # pragma: no cover
        exp = 0
    if exp <= 0:
        exp = created + PENDING_ACTION_TTL_SECONDS
    action["expires_at_ts"] = exp
    action["expires_at"] = _iso_utc(exp)
    action["ui_context"] = ui_context or action.get("ui_context") or {}
    action.setdefault("args", {})
    action.setdefault("resolved", {})
    action.setdefault("preview", {})
    action.setdefault(
        "summary", action.get("title") or action.get("description") or action.get("type") or "Proposed action"
    )
    pol2 = action.get("policy") if isinstance(action.get("policy"), dict) else {}
    action["requires_confirmation"] = bool(pol2.get("requires_confirmation", action.get("requires_confirmation", True)))
    if pol2.get("effect") == "deny":
        # should not happen due to earlier guard, but defense-in-depth
        return None
    return action


def set_pending_action(
    request: Request, proposed: dict[str, Any] | None, ui_context: Any = None
) -> dict[str, Any] | None:
    action = _normalize_pending_action(proposed, ui_context=ui_context)
    sess = deps.get_session(request)
    if action:
        sess[PENDING_ACTION_SESSION_KEY] = action
    else:
        sess.pop(PENDING_ACTION_SESSION_KEY, None)  # pragma: no cover
    return action


def get_pending_action(request: Request, *, clear_if_expired: bool = True) -> dict[str, Any] | None:
    sess = deps.get_session(request)
    action = sess.get(PENDING_ACTION_SESSION_KEY)
    if not isinstance(action, dict):
        return None
    try:
        exp = int(action.get("expires_at_ts") or 0)
    except Exception:  # pragma: no cover
        exp = 0
    if exp and _now_ts() > exp:
        if clear_if_expired:
            sess.pop(PENDING_ACTION_SESSION_KEY, None)
        return None
    return action


def clear_pending_action(request: Request) -> None:
    deps.get_session(request).pop(PENDING_ACTION_SESSION_KEY, None)


def _assistant_history_context(hist: list[dict[str, Any]], *, limit: int = 20) -> list[dict[str, Any]]:
    return [h for h in hist[-limit:] if h.get("role") in ("user", "assistant")]


def _assistant_allowed(request: Request) -> bool:
    try:
        req = services.get_setting("assistant_require_unlock", "true") == "true"
    except Exception:
        req = True
    return (not req) or deps.is_unlocked(request)


def _show_assistant_debug() -> bool:
    return os.environ.get("SPMS_ASSISTANT_DEBUG", "").lower() in ("1", "true", "yes") or os.environ.get(
        "ASSISTANT_DEBUG_META", ""
    ).lower() in ("1", "true", "yes")


def _messages_ctx(request: Request, **extra: Any) -> dict[str, Any]:
    ctx = {
        "request": request,
        "history": _history(request)[-20:],
        "pending_action": get_pending_action(request),
        "csrf_token": deps.csrf_token(request),
        "intents": assistant.INTENT_LABELS,
        "show_assistant_debug": _show_assistant_debug(),
    }
    ctx.update(extra)
    return ctx


def _history(request: Request):
    sess = deps.get_session(request)
    hist = sess.get("assistant_history")
    if not isinstance(hist, list):
        hist = []
    return hist


@router.get("/assistant")
def assistant_page(request: Request):
    pending = get_pending_action(request)
    playbooks_ctx = []
    try:
        from app_core.assistant import playbooks as assistant_playbooks
        playbooks_ctx = assistant_playbooks.list_playbooks()[:20]
    except Exception:
        playbooks_ctx = []
    ctx = {
        "title": "Manager Assistant",
        "history": _history(request)[-20:],
        "pending_action": pending,
        "assistant_locked": not _assistant_allowed(request),
        "llm": assistant.get_llm_config(),
        "intents": assistant.INTENT_LABELS,
        "show_assistant_debug": _show_assistant_debug(),
        "playbooks": playbooks_ctx,
        **_training_context(request),
    }
    return render(request, "assistant/index.html", ctx)


@router.post("/assistant/ask")
async def assistant_ask(request: Request):
    form = await deps.get_form(request)
    want_json = (
        (request.headers.get("accept", "").find("application/json") >= 0)
        or (request.headers.get("x-requested-with") == "assistant-widget")
        or (str(form.get("widget") or "") == "1")
    )

    if not _assistant_allowed(request):
        if want_json:
            return Response(
                content=json.dumps(
                    {
                        "ok": False,
                        "error": "Unlock required to use Manager Assistant (sensitive data).",
                        "ui_actions": [{"type": "navigate", "url": "/unlock?next=/assistant"}],
                    },
                    separators=(",", ":"),
                ),
                media_type="application/json",
            )
        return guarded_unlock_redirect(
            request, "/unlock?next=/assistant", "Unlock required to use Manager Assistant (sensitive data)."
        )

    message = (form.get("message") or "").strip()
    ui_context = None
    raw_ctx = form.get("ui_context")
    if raw_ctx:
        try:
            ui_context = json.loads(raw_ctx) if isinstance(raw_ctx, str) else raw_ctx
        except Exception:  # pragma: no cover
            ui_context = None

    hist = _history(request)
    result = {
        "ok": True,
        "answer": "",
        "intent": "capabilities_help",
        "confidence": 0.0,
        "tools_used": [],
        "source": "none",
        "ui_actions": [],
    }
    pending_action = get_pending_action(request)
    if message:
        hist.append({"role": "user", "content": message, "ui_context": ui_context or {}})
        history_for_chat = _assistant_history_context(hist[:-1])
        chat_ctx = dict(ui_context or {})
        if pending_action and "pending_action" not in chat_ctx:
            chat_ctx["pending_action"] = pending_action
        # V1/V2 context for policy/memory
        try:
            sess = deps.get_session(request)
            if sess.get("assistant_session_id"):
                chat_ctx.setdefault("session_id", sess.get("assistant_session_id"))
            else:
                import secrets as _sec
                sess["assistant_session_id"] = _sec.token_urlsafe(16)
                chat_ctx.setdefault("session_id", sess.get("assistant_session_id"))
            chat_ctx.setdefault("unlocked", bool(deps.is_unlocked(request)))
            try:
                actor = deps.current_actor(request)
                chat_ctx.setdefault("actor", actor.get("actor"))
                chat_ctx.setdefault("actor_user_id", actor.get("actor_user_id"))
                chat_ctx.setdefault("actor_role", actor.get("actor_role"))
            except Exception:
                pass
        except Exception:
            pass
        try:
            result = assistant.chat(message, history=history_for_chat, ui_context=chat_ctx)
        except TypeError:
            # backward compat if chat signature not yet updated
            try:
                result = assistant.chat(message, history=history_for_chat)
            except Exception:
                logger.exception("assistant_ask_failed")
                if want_json:
                    return Response(
                        content=json.dumps(
                            {
                                "ok": False,
                                "answer": "Sorry, the assistant encountered an error while processing your request. Please try again.",
                                "intent": "error",
                                "confidence": 0.0,
                                "tools_used": [],
                                "source": "error",
                                "slots": {},
                                "ui_actions": [],
                            },
                            separators=(",", ":"),
                        ),
                        media_type="application/json",
                    )
                result = {  # pragma: no cover
                    "ok": False,
                    "answer": "Sorry, the assistant encountered an error while processing your request. Please try again.",
                    "intent": "error",
                    "confidence": 0.0,
                    "tools_used": [],
                    "source": "error",
                    "ui_actions": [],
                }
        except Exception:
            logger.exception("assistant_ask_failed")
            if want_json:
                return Response(
                    content=json.dumps(
                        {
                            "ok": False,
                            "answer": "Sorry, the assistant encountered an error while processing your request. Please try again.",
                            "intent": "error",
                            "confidence": 0.0,
                            "tools_used": [],
                            "source": "error",
                            "slots": {},
                            "ui_actions": [],
                        },
                        separators=(",", ":"),
                    ),
                    media_type="application/json",
                )
            result = {  # pragma: no cover
                "ok": False,
                "answer": "Sorry, the assistant encountered an error while processing your request. Please try again.",
                "intent": "error",
                "confidence": 0.0,
                "tools_used": [],
                "source": "error",
                "ui_actions": [],
            }

        if not isinstance(result, dict):
            result = {
                "ok": True,
                "answer": str(result),
                "intent": "unknown",
                "confidence": 0.0,
                "tools_used": [],
                "source": "unknown",
                "ui_actions": [],
            }
        result.setdefault("ui_actions", [])

        proposed = result.get("proposed_action")
        if proposed:
            pol = proposed.get("policy") if isinstance(proposed, dict) else None
            denied = isinstance(proposed, dict) and (
                str(proposed.get("status") or "").lower() == "denied"
                or (isinstance(pol, dict) and str(pol.get("effect") or "").lower() == "deny")
            )
            if denied:
                # Never persist denied actions as pending confirmable actions.
                result["proposed_action"] = None
                result["policy"] = pol if isinstance(pol, dict) else result.get("policy")
                pending_action = get_pending_action(request)
            else:
                pending_action = set_pending_action(
                    request, proposed if isinstance(proposed, dict) else {"raw": proposed}, ui_context=ui_context
                )
                result["proposed_action"] = pending_action
        else:
            # keep any existing pending action unless explicitly replaced; ask flow doesn't clear by itself
            pending_action = get_pending_action(request)

        answer = result.get("answer") or ""
        meta = f"[source={result.get('source')} intent={result.get('intent')} conf={result.get('confidence')} tools={','.join(result.get('tools_used') or []) or '-'}]"
        hist.append(
            {
                "role": "assistant",
                "content": answer,
                "meta": meta,
                "intent": result.get("intent"),
                "confidence": result.get("confidence"),
                "tools_used": result.get("tools_used") or [],
                "slots": result.get("slots") or {},
                "source": result.get("source"),
                "user_message": message,
                "ui_actions": result.get("ui_actions") or [],
                "proposed_action": result.get("proposed_action") or None,
            }
        )
        deps.get_session(request)["assistant_history"] = hist[-40:]
    else:
        pending_action = get_pending_action(request)

    if want_json:
        # Error responses: return fixed safe payload to avoid any exception/trace exposure.
        if not bool(result.get("ok", True)) and str(result.get("source") or "") == "error":
            return Response(  # pragma: no cover
                content=json.dumps(
                    {
                        "ok": False,
                        "answer": "Sorry, the assistant encountered an error while processing your request. Please try again.",
                        "intent": "error",
                        "confidence": 0.0,
                        "tools_used": [],
                        "source": "error",
                        "slots": {},
                        "ui_actions": [],
                    },
                    separators=(",", ":"),
                ),
                media_type="application/json",
            )

        # Return only sanitized, JSON-safe fields (no exception/trace data).
        safe_slots = _json_safe_value(result.get("slots") if isinstance(result.get("slots"), dict) else {})
        safe_ui_actions = _json_safe_value(
            result.get("ui_actions") if isinstance(result.get("ui_actions"), list) else []
        )
        payload = {
            "ok": bool(result.get("ok", True)),
            "answer": str(result.get("answer") or ""),
            "intent": str(result.get("intent") or ""),
            "confidence": _json_safe_value(result.get("confidence")),
            "tools_used": [str(x) for x in (result.get("tools_used") or []) if isinstance(x, (str, int, float, bool))],
            "source": str(result.get("source") or ""),
            "slots": safe_slots,
            "ui_actions": safe_ui_actions,
        }
        pol = result.get("policy")
        if isinstance(pol, dict):
            payload["policy"] = _json_safe_value(pol)
        if "needs_confirmation" in result:
            payload["needs_confirmation"] = bool(result.get("needs_confirmation"))
        pa = result.get("proposed_action") or pending_action
        if isinstance(pa, dict):
            safe_pa = _json_safe_value(pa)
            if isinstance(safe_pa, dict):
                payload["proposed_action"] = safe_pa
                payload["pending_action"] = safe_pa
        else:
            cur = get_pending_action(request)
            if isinstance(cur, dict):
                safe_cur = _json_safe_value(cur)  # pragma: no cover
                if isinstance(safe_cur, dict):  # pragma: no cover
                    payload["pending_action"] = safe_cur  # pragma: no cover
        # Final JSON serialization to ensure a clean, non-tainted response body.
        try:
            clean_body = json.dumps(payload, default=lambda _o: "internal_error", separators=(",", ":"))
            # Validate serialized form is parseable JSON
            json.loads(clean_body)
        except Exception:  # pragma: no cover
            clean_body = json.dumps(
                {
                    "ok": False,
                    "answer": "Sorry, the assistant encountered an error while processing your request. Please try again.",
                    "intent": "error",
                    "confidence": 0.0,
                    "tools_used": [],
                    "source": "error",
                    "slots": {},
                    "ui_actions": [],
                },
                separators=(",", ":"),
            )
        return Response(
            content=clean_body, media_type="application/json"
        )  # codeql[py/stack-trace-exposure] sanitized JSON body

    shown = _history(request)[-20:]
    animate_index = None
    if message and shown:
        for i in range(len(shown) - 1, -1, -1):
            if shown[i].get("role") == "assistant":
                animate_index = i
                break
    ctx = {
        "request": request,
        "history": shown,
        "pending_action": get_pending_action(request),
        "csrf_token": deps.csrf_token(request),
        "intents": assistant.INTENT_LABELS,
        "show_assistant_debug": _show_assistant_debug(),
        "animate_index": animate_index,
    }
    return htmx_partial_or_redirect(
        request, partial_template="assistant/_messages.html", partial_context=ctx, redirect_url="/assistant"
    )


@router.post("/assistant/feedback")
async def assistant_feedback(request: Request):
    form = await deps.get_form(request)
    if not _assistant_allowed(request):
        return guarded_unlock_redirect(request, "/assistant", "Unlock required.")
    idx = form.get("msg_index")
    rating = int(form.get("rating") or 0)
    corrected_intent = (form.get("corrected_intent") or "").strip()
    user_note = (form.get("user_note") or "").strip()
    corrected_slots_raw = (form.get("corrected_slots_json") or "").strip()
    hist = _history(request)
    msg = None
    try:
        i = int(idx)
        if 0 <= i < len(hist):
            msg = hist[i]
    except Exception:
        msg = None
    # fallback: last assistant
    if msg is None or msg.get("role") != "assistant":
        for m in reversed(hist):
            if m.get("role") == "assistant":
                msg = m
                break
    if msg and msg.get("role") == "assistant":
        try:
            corrected_slots = json.loads(corrected_slots_raw) if corrected_slots_raw else {}
            if not isinstance(corrected_slots, dict):
                corrected_slots = {}
        except Exception:
            corrected_slots = {}
        assistant.record_feedback(
            message=msg.get("user_message") or "",
            predicted_intent=msg.get("intent") or "",
            corrected_intent=corrected_intent,
            rating=rating,
            confidence=msg.get("confidence"),
            slots=msg.get("slots") or {},
            corrected_slots=corrected_slots,
            tools_used=msg.get("tools_used") or [],
            answer=msg.get("content") or "",
            user_note=user_note,
            source=msg.get("source") or "",
            status="new" if (corrected_intent or rating != 0) else "new",
        )
        msg["feedback"] = {"rating": rating, "corrected_intent": corrected_intent, "note": user_note}
        deps.get_session(request)["assistant_history"] = hist[-40:]
        deps.add_flash(
            request,
            "Feedback saved. Corrections are used to improve routing over time (instant exemplar memory + retraining dataset).",
            "success",
        )
    else:
        deps.add_flash(request, "Could not find assistant message to rate.", "error")

    ctx = {
        "request": request,
        "history": _history(request)[-20:],
        "csrf_token": deps.csrf_token(request),
        "intents": assistant.INTENT_LABELS,
        "show_assistant_debug": _show_assistant_debug(),
    }
    return htmx_partial_or_redirect(
        request, partial_template="assistant/_messages.html", partial_context=ctx, redirect_url="/assistant"
    )


@router.post("/assistant/action/confirm")
async def assistant_action_confirm(request: Request):
    form, payload = await _get_request_data(request)
    want_json = (
        (request.headers.get("accept", "").find("application/json") >= 0)
        or (request.headers.get("x-requested-with") == "assistant-widget")
        or (str((payload or {}).get("widget") or (form.get("widget") if form is not None else "") or "") == "1")
    )

    if not _assistant_allowed(request):
        if want_json:
            return {
                "ok": False,
                "error": "Unlock required to confirm assistant actions.",
                "ui_actions": [{"type": "navigate", "url": "/unlock?next=/assistant"}],
            }
        return guarded_unlock_redirect(
            request, "/unlock?next=/assistant", "Unlock required to confirm assistant actions."
        )

    fields = _parse_body_fields(form, payload, "action_id", "password", "proof", "proof_password")
    action_id = str(fields.get("action_id") or "").strip()
    pending = get_pending_action(request)
    if not pending:
        if want_json:
            return {"ok": False, "error": "No pending assistant action (it may have expired).", "pending_action": None}
        deps.add_flash(request, "No pending assistant action (it may have expired).", "error")
        ctx = {
            "request": request,
            "history": _history(request)[-20:],
            "pending_action": None,
            "csrf_token": deps.csrf_token(request),
            "intents": assistant.INTENT_LABELS,
        "show_assistant_debug": _show_assistant_debug(),
        }
        return htmx_partial_or_redirect(
            request, partial_template="assistant/_messages.html", partial_context=ctx, redirect_url="/assistant"
        )

    if not action_id or str(pending.get("id") or "") != action_id:
        if want_json:
            return {
                "ok": False,
                "error": "Pending action does not match (stale or replaced). Please review and try again.",
                "pending_action": pending,
            }
        deps.add_flash(
            request, "Pending action does not match (stale or replaced). Please review and try again.", "error"
        )
        ctx = {
            "request": request,
            "history": _history(request)[-20:],
            "pending_action": pending,
            "csrf_token": deps.csrf_token(request),
            "intents": assistant.INTENT_LABELS,
        "show_assistant_debug": _show_assistant_debug(),
        }
        return htmx_partial_or_redirect(
            request, partial_template="assistant/_messages.html", partial_context=ctx, redirect_url="/assistant"
        )

    pol = pending.get("policy") if isinstance(pending.get("policy"), dict) else {}
    if str(pol.get("effect") or "").lower() == "deny":
        msg = f"Action denied by policy: {pol.get('reason') or 'denied'}"
        if want_json:
            return {
                "ok": False,
                "error": msg,
                "answer": msg,
                "policy": pol,
                "pending_action": pending,
                "ui_actions": [],
            }
        deps.add_flash(request, msg, "error")
        ctx = {
            "request": request,
            "history": _history(request)[-20:],
            "pending_action": pending,
            "csrf_token": deps.csrf_token(request),
            "intents": assistant.INTENT_LABELS,
            "show_assistant_debug": _show_assistant_debug(),
        }
        return htmx_partial_or_redirect(
            request, partial_template="assistant/_messages.html", partial_context=ctx, redirect_url="/assistant"
        )

    # Best-effort proof resolution: prefer explicit password, else session sentinel when unlocked.
    proof = fields.get("proof") or fields.get("proof_password") or None
    if proof is None and form is not None:
        try:
            proof = deps.service_password(request, form, allow_session_sentinel=True)
        except Exception:
            proof = fields.get("password") or None
    if proof is None:
        proof = fields.get("password") or None

    hist = _history(request)
    exec_result = None
    try:
        exec_result = execute_pending_action(pending, request=request, password=proof, proof=proof)
        if not isinstance(exec_result, dict):
            exec_result = {"ok": True, "answer": str(exec_result), "ui_actions": []}
    except Exception:
        logger.exception("assistant_action_confirm_failed")
        exec_result = {
            "ok": False,
            "answer": "Failed to execute action due to an internal error. Please try again or check logs.",
            "error": "internal_error",
            "ui_actions": [],
            "terminal": True,
        }

    ok = bool(exec_result.get("ok", False))
    terminal_failure = bool(exec_result.get("terminal")) or not ok
    # Clear on success or terminal failure; keep pending for retryable failures if explicitly marked non-terminal
    if ok or terminal_failure:
        clear_pending_action(request)
        pending_after = get_pending_action(request)
    else:
        pending_after = get_pending_action(request)  # pragma: no cover

    answer = exec_result.get("answer") or ("Action completed." if ok else "Action failed.")
    meta = f"[action={pending.get('type')} status={'ok' if ok else 'failed'}]"
    hist.append(
        {
            "role": "assistant",
            "content": answer,
            "meta": meta,
            "intent": "action_confirm",
            "confidence": 1.0,
            "tools_used": exec_result.get("tools_used") or ["assistant_action_confirm"],
            "slots": {"action_id": action_id, "action_type": pending.get("type")},
            "source": "assistant_action",
            "user_message": f"[confirm action] {pending.get('summary') or pending.get('type') or action_id}",
            "ui_actions": exec_result.get("ui_actions") or [],
            "action_result": exec_result,
            "proposed_action": None,
        }
    )
    deps.get_session(request)["assistant_history"] = hist[-40:]

    if want_json:
        exec_policy = (exec_result or {}).get("policy") if isinstance((exec_result or {}).get("policy"), dict) else None
        safe_exec = {
            "ok": bool((exec_result or {}).get("ok", False)),
            "answer": str((exec_result or {}).get("answer") or answer),
            "status": str((exec_result or {}).get("status") or ("ok" if ok else "failed")),
            "tools_used": [
                str(x) for x in ((exec_result or {}).get("tools_used") or []) if isinstance(x, (str, int, float))
            ],
            "ui_actions": (exec_result or {}).get("ui_actions")
            if isinstance((exec_result or {}).get("ui_actions"), list)
            else [],
        }
        if exec_policy:
            safe_exec["policy"] = _json_safe_value(exec_policy)
        if not ok and (exec_result or {}).get("error"):
            safe_exec["error"] = "internal_error"
        resp = {
            "ok": ok,
            "answer": str(answer),
            "result": safe_exec,
            "ui_actions": safe_exec["ui_actions"],
            "pending_action": pending_after if isinstance(pending_after, dict) else None,
            "proposed_action": None,
        }
        if exec_policy:
            resp["policy"] = _json_safe_value(exec_policy)
        return resp

    shown = _history(request)[-20:]
    animate_index = len(shown) - 1 if shown else None
    ctx = {
        "request": request,
        "history": shown,
        "pending_action": pending_after,
        "csrf_token": deps.csrf_token(request),
        "intents": assistant.INTENT_LABELS,
        "show_assistant_debug": _show_assistant_debug(),
        "animate_index": animate_index,
    }
    if ok:
        deps.add_flash(request, answer if len(answer) < 180 else "Action completed.", "success")
    else:
        deps.add_flash(request, answer if len(answer) < 180 else "Action failed.", "error")
    return htmx_partial_or_redirect(
        request, partial_template="assistant/_messages.html", partial_context=ctx, redirect_url="/assistant"
    )


@router.post("/assistant/action/cancel")
async def assistant_action_cancel(request: Request):
    form, payload = await _get_request_data(request)
    want_json = (
        (request.headers.get("accept", "").find("application/json") >= 0)
        or (request.headers.get("x-requested-with") == "assistant-widget")
        or (str((payload or {}).get("widget") or (form.get("widget") if form is not None else "") or "") == "1")
    )

    if not _assistant_allowed(request):
        if want_json:
            return {
                "ok": False,
                "error": "Unlock required to manage assistant actions.",
                "ui_actions": [{"type": "navigate", "url": "/unlock?next=/assistant"}],
            }
        return guarded_unlock_redirect(
            request, "/unlock?next=/assistant", "Unlock required to manage assistant actions."
        )

    fields = _parse_body_fields(form, payload, "action_id")
    action_id = str(fields.get("action_id") or "").strip()
    pending = get_pending_action(request)
    if pending and action_id and str(pending.get("id") or "") != action_id:
        # stale id: don't clear current pending, report mismatch
        if want_json:
            return {
                "ok": False,
                "error": "Pending action does not match; nothing cancelled.",
                "pending_action": pending,
            }
        deps.add_flash(request, "Pending action does not match; nothing cancelled.", "error")
        ctx = {
            "request": request,
            "history": _history(request)[-20:],
            "pending_action": pending,
            "csrf_token": deps.csrf_token(request),
            "intents": assistant.INTENT_LABELS,
        "show_assistant_debug": _show_assistant_debug(),
        }
        return htmx_partial_or_redirect(
            request, partial_template="assistant/_messages.html", partial_context=ctx, redirect_url="/assistant"
        )

    if pending:
        clear_pending_action(request)
        hist = _history(request)
        hist.append(
            {
                "role": "assistant",
                "content": f"Cancelled proposed action: {pending.get('summary') or pending.get('type') or 'action'}.",
                "meta": "[action=cancelled]",
                "intent": "action_cancel",
                "confidence": 1.0,
                "tools_used": ["assistant_action_cancel"],
                "slots": {"action_id": str(pending.get("id") or action_id)},
                "source": "assistant_action",
                "user_message": f"[cancel action] {pending.get('summary') or pending.get('type') or ''}",
                "ui_actions": [],
                "proposed_action": None,
            }
        )
        deps.get_session(request)["assistant_history"] = hist[-40:]
        msg = "Proposed action cancelled."
    else:
        msg = "No pending action to cancel."

    if want_json:
        return {"ok": True, "answer": msg, "pending_action": None, "proposed_action": None, "ui_actions": []}

    deps.add_flash(request, msg, "info" if pending else "warning")
    shown = _history(request)[-20:]
    animate_index = len(shown) - 1 if shown and pending else None
    ctx = {
        "request": request,
        "history": shown,
        "pending_action": None,
        "csrf_token": deps.csrf_token(request),
        "intents": assistant.INTENT_LABELS,
        "show_assistant_debug": _show_assistant_debug(),
        "animate_index": animate_index,
    }
    return htmx_partial_or_redirect(
        request, partial_template="assistant/_messages.html", partial_context=ctx, redirect_url="/assistant"
    )


@router.post("/assistant/clear")
async def assistant_clear(request: Request):
    form = await deps.get_form(request)
    deps.get_session(request)["assistant_history"] = []
    clear_pending_action(request)
    ctx = {
        "request": request,
        "history": [],
        "pending_action": None,
        "csrf_token": deps.csrf_token(request),
        "intents": assistant.INTENT_LABELS,
        "show_assistant_debug": _show_assistant_debug(),
    }
    return htmx_partial_or_redirect(
        request, partial_template="assistant/_messages.html", partial_context=ctx, redirect_url="/assistant"
    )


# ── Training / dataset selection ────────────────────────────────────────────

def _training_context(request: Request) -> dict[str, Any]:
    sources = assistant_training.list_sources()
    runs = assistant_training.training_runs()[-10:]
    runs.reverse()
    training_share = {}
    try:
        from app_core.assistant import training_data_share as tds
        pkg_size = tds.package_size_bytes()
        min_bytes = int(services.get_setting("assistant_training_share_min_bytes", "1048576") or "1048576")
        enabled = services.get_setting("assistant_training_share_enabled", "false") == "true"
        ok, reason = tds.should_upload_now()
        training_share = {
            "enabled": enabled,
            "package_size_bytes": pkg_size,
            "package_size_mb": round(pkg_size / (1024 * 1024), 2),
            "min_bytes": min_bytes,
            "ready": pkg_size >= min_bytes,
            "should_upload_now": ok,
            "reason": reason,
            "last_upload_at": services.get_setting("assistant_training_share_last_upload_at", ""),
            "last_status": services.get_setting("assistant_training_share_last_status", ""),
        }
    except Exception:
        training_share = {}
    training_datasets = []
    try:
        training_datasets = assistant_training.list_sanitized_datasets(limit=10)
    except Exception:
        training_datasets = []
    return {
        "training_sources": sources,
        "training_runs": runs,
        "training_datasets": training_datasets,
        "training_backends": [
            {"id": "sklearn", "label": "Intent classifier (sklearn, fast, on-device)"},
            {"id": "setfit", "label": "Intent classifier (SetFit, heavier)"},
            {"id": "llm_lora", "label": "SmolLM2-360M LoRA fine-tune (GPU recommended, prepares dataset)"},
        ],
        "default_model": "SmolLM2-360M-Instruct",
        "training_share": training_share,
    }


@router.get("/assistant/training/sources")
def assistant_training_sources(request: Request):
    if not _assistant_allowed(request):
        return Response(content=json.dumps({"ok": False, "error": "unlock_required"}), media_type="application/json", status_code=403)
    return {"ok": True, **_training_context(request)}


@router.post("/assistant/training/estimate")
async def assistant_training_estimate(request: Request):
    if not _assistant_allowed(request):
        return Response(content=json.dumps({"ok": False, "error": "unlock_required"}), media_type="application/json", status_code=403)
    form, payload = await _get_request_data(request)
    fields = _parse_body_fields(form, payload, "backend", "model", "sources")
    backend = str(fields.get("backend") or "sklearn")
    model = str(fields.get("model") or "SmolLM2-360M-Instruct")
    raw_sources = fields.get("sources")
    if isinstance(raw_sources, str):
        try:
            source_ids = json.loads(raw_sources)
        except Exception:
            source_ids = [s.strip() for s in raw_sources.split(",") if s.strip()]
    elif isinstance(raw_sources, list):
        source_ids = [str(s) for s in raw_sources]
    else:
        # also accept repeated form fields
        try:
            if hasattr(form, "getlist"):
                source_ids = [str(s) for s in form.getlist("sources")]  # type: ignore
            else:
                source_ids = []  # pragma: no cover
        except Exception:
            source_ids = []  # pragma: no cover
    est = assistant_training.estimate_training(source_ids, backend=backend, model=model)
    return est


@router.post("/assistant/training/start")
async def assistant_training_start(request: Request):
    form, payload = await _get_request_data(request)
    want_json = (
        (request.headers.get("accept", "").find("application/json") >= 0)
        or (request.headers.get("x-requested-with") == "assistant-widget")
        or (str((form.get("format") if form else "") or "") == "json")
    )
    if not _assistant_allowed(request):
        return Response(content=json.dumps({"ok": False, "error": "unlock_required"}), media_type="application/json", status_code=403)
    fields = _parse_body_fields(form, payload, "backend", "model", "sources", "csrf")
    csrf = str(fields.get("csrf") or (form.get("csrf") if form else "") or request.headers.get("X-CSRF-Token") or "")
    try:
        deps.verify_csrf(request, csrf)
    except Exception:  # pragma: no cover - middleware enforces CSRF first
        if want_json:  # pragma: no cover
            return Response(content=json.dumps({"ok": False, "error": "csrf"}), media_type="application/json", status_code=403)  # pragma: no cover
        return guarded_unlock_redirect(request, fallback="/assistant")  # pragma: no cover
    backend = str(fields.get("backend") or "sklearn")
    model = str(fields.get("model") or "SmolLM2-360M-Instruct")
    raw_sources = fields.get("sources")
    if isinstance(raw_sources, str):
        try:
            source_ids = json.loads(raw_sources)
        except Exception:
            source_ids = [s.strip() for s in raw_sources.split(",") if s.strip()]
    elif isinstance(raw_sources, list):
        source_ids = [str(s) for s in raw_sources]
    else:
        try:
            source_ids = [str(s) for s in form.getlist("sources")] if hasattr(form, "getlist") else []  # pragma: no cover
        except Exception:
            source_ids = []  # pragma: no cover
    res = assistant_training.start_training(source_ids, backend=backend, model=model)
    if want_json:
        return res
    if res.get("ok"):
        deps.add_flash(request, f"Training {res.get('run',{}).get('status')}: {backend}", "success")
    else:
        deps.add_flash(request, res.get("message") or res.get("error") or "Training failed", "error")
    return flash_redirect(request, "/assistant")


# ---- Smart Agent V1/V2/V3 endpoints (issue #77) ----

@router.get("/assistant/smart/status")
async def assistant_smart_status(request: Request):
    if not _assistant_allowed(request):
        return Response(content=json.dumps({"ok": False, "error": "unlock_required"}), media_type="application/json", status_code=403)
    try:
        from app_core.assistant import model_ops, policy, business_map, playbooks
        cat = model_ops.get_catalog()
        return _json_safe_value({
            "ok": True,
            "smart_enabled": str(services.get_setting("assistant_smart_enabled", "false")).lower() == "true",
            "active_model": str(services.get_setting("assistant_smart_model", "") or ""),
            "catalog": cat,
            "policy_audit_enabled": str(services.get_setting("assistant_policy_audit_enabled", "true")).lower() == "true",
            "memory_enabled": str(services.get_setting("assistant_session_memory_enabled", "true")).lower() == "true",
            "playbooks_enabled": str(services.get_setting("assistant_playbooks_enabled", "true")).lower() == "true",
            "eval_gate_enabled": str(services.get_setting("assistant_eval_gate_enabled", "true")).lower() == "true",
            "business_map": business_map.get_map(),
            "playbooks": playbooks.list_playbooks(),
        })
    except Exception as e:
        logger.exception("assistant_smart_status_failed")
        return Response(content=json.dumps({"ok": False, "error": "status_failed"}), media_type="application/json", status_code=500)


@router.get("/assistant/playbooks")
async def assistant_playbooks(request: Request, q: str = "", intent: str = "", relevant: bool = False, limit: int = 10):
    if not _assistant_allowed(request):
        return Response(content=json.dumps({"ok": False, "error": "unlock_required"}), media_type="application/json", status_code=403)
    try:
        from app_core.assistant import playbooks
        lim = max(1, min(int(limit or 10), 50))
        if relevant or (q or intent):
            items = playbooks.find_relevant(message=q, intent=intent, limit=lim)
        else:
            items = playbooks.list_playbooks()[:lim]
        return _json_safe_value({"ok": True, "playbooks": items, "count": len(items)})
    except Exception:
        logger.exception("assistant_playbooks_failed")
        return Response(content=json.dumps({"ok": False, "error": "playbooks_failed"}), media_type="application/json", status_code=500)


@router.get("/assistant/policy/audit")
async def assistant_policy_audit(request: Request, limit: int = 100):
    if not _assistant_allowed(request):
        return Response(content=json.dumps({"ok": False, "error": "unlock_required"}), media_type="application/json", status_code=403)
    try:
        from app_core.assistant import policy
        return _json_safe_value({"ok": True, "items": policy.list_policy_audit(limit=limit)})
    except Exception:
        logger.exception("assistant_policy_audit_failed")
        return Response(content=json.dumps({"ok": False, "error": "audit_failed"}), media_type="application/json", status_code=500)


@router.get("/assistant/models/catalog")
async def assistant_models_catalog(request: Request):
    if not _assistant_allowed(request):
        return Response(content=json.dumps({"ok": False, "error": "unlock_required"}), media_type="application/json", status_code=403)
    try:
        from app_core.assistant import model_ops
        return _json_safe_value({"ok": True, "catalog": model_ops.get_catalog(), "jobs": model_ops.list_jobs(limit=20)})
    except Exception:
        logger.exception("assistant_models_catalog_failed")
        return Response(content=json.dumps({"ok": False, "error": "catalog_failed"}), media_type="application/json", status_code=500)


@router.post("/assistant/models/select")
async def assistant_models_select(request: Request):
    if not _assistant_allowed(request):
        return Response(content=json.dumps({"ok": False, "error": "unlock_required"}), media_type="application/json", status_code=403)
    form = await request.form()
    try:
        deps.verify_csrf(request, str(form.get("csrf") or request.headers.get("X-CSRF-Token") or ""))
    except Exception:
        return Response(content=json.dumps({"ok": False, "error": "csrf"}), media_type="application/json", status_code=403)
    try:
        from app_core.assistant import model_ops
        actor = deps.current_actor(request).get("actor") if hasattr(deps, "current_actor") else "manager"
        res = model_ops.select_model(str(form.get("model_id") or ""), actor=str(actor or "manager"))
        return _json_safe_value(res)
    except Exception:
        logger.exception("assistant_models_select_failed")
        return Response(content=json.dumps({"ok": False, "error": "select_failed"}), media_type="application/json", status_code=500)


@router.post("/assistant/models/eval")
async def assistant_models_eval(request: Request):
    if not _assistant_allowed(request):
        return Response(content=json.dumps({"ok": False, "error": "unlock_required"}), media_type="application/json", status_code=403)
    form = await request.form()
    try:
        deps.verify_csrf(request, str(form.get("csrf") or request.headers.get("X-CSRF-Token") or ""))
    except Exception:
        return Response(content=json.dumps({"ok": False, "error": "csrf"}), media_type="application/json", status_code=403)
    try:
        from app_core.assistant import model_ops
        actor = deps.current_actor(request).get("actor") if hasattr(deps, "current_actor") else "manager"
        res = model_ops.run_eval(str(form.get("model_id") or ""), dataset_ref=str(form.get("dataset_ref") or ""), actor=str(actor or "manager"))
        return _json_safe_value({"ok": True, "eval": res})
    except Exception:
        logger.exception("assistant_models_eval_failed")
        return Response(content=json.dumps({"ok": False, "error": "eval_failed"}), media_type="application/json", status_code=500)


@router.post("/assistant/models/rollback")
async def assistant_models_rollback(request: Request):
    if not _assistant_allowed(request):
        return Response(content=json.dumps({"ok": False, "error": "unlock_required"}), media_type="application/json", status_code=403)
    form = await request.form()
    try:
        deps.verify_csrf(request, str(form.get("csrf") or request.headers.get("X-CSRF-Token") or ""))
    except Exception:
        return Response(content=json.dumps({"ok": False, "error": "csrf"}), media_type="application/json", status_code=403)
    try:
        from app_core.assistant import model_ops
        actor = deps.current_actor(request).get("actor") if hasattr(deps, "current_actor") else "manager"
        return _json_safe_value(model_ops.rollback_model(actor=str(actor or "manager")))
    except Exception:
        logger.exception("assistant_models_rollback_failed")
        return Response(content=json.dumps({"ok": False, "error": "rollback_failed"}), media_type="application/json", status_code=500)


@router.get("/assistant/policy/effective")
async def assistant_policy_effective(request: Request):
    if not _assistant_allowed(request):
        return Response(content=json.dumps({"ok": False, "error": "unlock_required"}), media_type="application/json", status_code=403)
    try:
        from app_core.assistant import policy
        return _json_safe_value(policy.effective_policy_summary())
    except Exception:
        logger.exception("assistant_policy_effective_failed")
        return Response(content=json.dumps({"ok": False, "error": "policy_failed"}), media_type="application/json", status_code=500)


@router.post("/assistant/policy/validate")
async def assistant_policy_validate(request: Request):
    if not _assistant_allowed(request):
        return Response(content=json.dumps({"ok": False, "error": "unlock_required"}), media_type="application/json", status_code=403)
    form = await request.form()
    try:
        deps.verify_csrf(request, str(form.get("csrf") or request.headers.get("X-CSRF-Token") or ""))
    except Exception:
        return Response(content=json.dumps({"ok": False, "error": "csrf"}), media_type="application/json", status_code=403)
    try:
        from app_core.assistant import policy
        res = policy.validate_policy_config(
            action_policy_json=str(form.get("assistant_action_policy_json") if form.get("assistant_action_policy_json") is not None else services.get_setting("assistant_action_policy_json", "[]")),
            property_rules=str(form.get("assistant_property_rules") if form.get("assistant_property_rules") is not None else services.get_setting("assistant_property_rules", "")),
        )
        return _json_safe_value(res)
    except Exception:
        logger.exception("assistant_policy_validate_failed")
        return Response(content=json.dumps({"ok": False, "error": "validate_failed"}), media_type="application/json", status_code=500)


@router.post("/assistant/models/upsert")
async def assistant_models_upsert(request: Request):
    if not _assistant_allowed(request):
        return Response(content=json.dumps({"ok": False, "error": "unlock_required"}), media_type="application/json", status_code=403)
    form = await request.form()
    try:
        deps.verify_csrf(request, str(form.get("csrf") or request.headers.get("X-CSRF-Token") or ""))
    except Exception:
        return Response(content=json.dumps({"ok": False, "error": "csrf"}), media_type="application/json", status_code=403)
    try:
        from app_core.assistant import model_ops
        actor = deps.current_actor(request).get("actor") if hasattr(deps, "current_actor") else "manager"
        model = {
            "id": str(form.get("id") or form.get("model_id") or "").strip(),
            "name": str(form.get("name") or form.get("id") or "").strip(),
            "provider": str(form.get("provider") or "local_gguf").strip(),
            "size": str(form.get("size") or "").strip(),
            "method": str(form.get("method") or "").strip(),
            "path": str(form.get("path") or "").strip(),
            "checksum": str(form.get("checksum") or "").strip(),
            "enabled": str(form.get("enabled") or "true").lower() == "true",
        }
        return _json_safe_value(model_ops.upsert_catalog_model(model, actor=str(actor or "manager")))
    except Exception:
        logger.exception("assistant_models_upsert_failed")
        return Response(content=json.dumps({"ok": False, "error": "upsert_failed"}), media_type="application/json", status_code=500)


@router.post("/assistant/models/delete")
async def assistant_models_delete(request: Request):
    if not _assistant_allowed(request):
        return Response(content=json.dumps({"ok": False, "error": "unlock_required"}), media_type="application/json", status_code=403)
    form = await request.form()
    try:
        deps.verify_csrf(request, str(form.get("csrf") or request.headers.get("X-CSRF-Token") or ""))
    except Exception:
        return Response(content=json.dumps({"ok": False, "error": "csrf"}), media_type="application/json", status_code=403)
    try:
        from app_core.assistant import model_ops
        actor = deps.current_actor(request).get("actor") if hasattr(deps, "current_actor") else "manager"
        return _json_safe_value(model_ops.delete_catalog_model(str(form.get("model_id") or ""), actor=str(actor or "manager"), delete_file=str(form.get("delete_file") or "false").lower()=="true"))
    except Exception:
        logger.exception("assistant_models_delete_failed")
        return Response(content=json.dumps({"ok": False, "error": "delete_failed"}), media_type="application/json", status_code=500)


@router.post("/assistant/models/verify")
async def assistant_models_verify(request: Request):
    if not _assistant_allowed(request):
        return Response(content=json.dumps({"ok": False, "error": "unlock_required"}), media_type="application/json", status_code=403)
    form = await request.form()
    try:
        deps.verify_csrf(request, str(form.get("csrf") or request.headers.get("X-CSRF-Token") or ""))
    except Exception:
        return Response(content=json.dumps({"ok": False, "error": "csrf"}), media_type="application/json", status_code=403)
    try:
        from app_core.assistant import model_ops
        actor = deps.current_actor(request).get("actor") if hasattr(deps, "current_actor") else "manager"
        return _json_safe_value(model_ops.verify_catalog_model(str(form.get("model_id") or ""), actor=str(actor or "manager")))
    except Exception:
        logger.exception("assistant_models_verify_failed")
        return Response(content=json.dumps({"ok": False, "error": "verify_failed"}), media_type="application/json", status_code=500)


@router.post("/assistant/models/install")
async def assistant_models_install(request: Request):
    if not _assistant_allowed(request):
        return Response(content=json.dumps({"ok": False, "error": "unlock_required"}), media_type="application/json", status_code=403)
    form = await request.form()
    try:
        deps.verify_csrf(request, str(form.get("csrf") or request.headers.get("X-CSRF-Token") or ""))
    except Exception:
        return Response(content=json.dumps({"ok": False, "error": "csrf"}), media_type="application/json", status_code=403)
    try:
        from app_core.assistant import model_ops
        actor = deps.current_actor(request).get("actor") if hasattr(deps, "current_actor") else "manager"
        model_id = str(form.get("id") or form.get("model_id") or "").strip()
        url = str(form.get("url") or form.get("source_url") or "").strip()
        checksum = str(form.get("checksum") or "").strip()
        path = str(form.get("path") or "").strip()
        name = str(form.get("name") or model_id).strip()
        provider = str(form.get("provider") or "local_gguf").strip()
        method = str(form.get("method") or "gguf/local").strip()
        size = str(form.get("size") or "").strip()
        filename = str(form.get("filename") or "").strip()
        if url:
            res = model_ops.start_model_download_job(
                model_id=model_id,
                url=url,
                checksum=checksum,
                actor=str(actor or "manager"),
                filename=filename,
                name=name,
                provider=provider,
                method=method,
                size=size,
            )
            return _json_safe_value(res)
        # register by local/approved path
        res = model_ops.upsert_catalog_model(
            {
                "id": model_id,
                "name": name,
                "provider": provider,
                "method": method,
                "size": size,
                "path": path,
                "checksum": checksum,
                "source_url": "",
                "enabled": str(form.get("enabled") or "true").lower() == "true",
            },
            actor=str(actor or "manager"),
        )
        if res.get("ok") and path:
            # best-effort verification for explicit operator action
            try:
                v = model_ops.verify_catalog_model(model_id, actor=str(actor or "manager"))
                res["verification"] = v
            except Exception:
                pass
        return _json_safe_value(res)
    except Exception:
        logger.exception("assistant_models_install_failed")
        return Response(content=json.dumps({"ok": False, "error": "install_failed"}), media_type="application/json", status_code=500)


@router.post("/assistant/models/pull-bundle")
async def assistant_models_pull_bundle(request: Request):
    if not _assistant_allowed(request):
        return Response(content=json.dumps({"ok": False, "error": "unlock_required"}), media_type="application/json", status_code=403)
    form = await request.form()
    try:
        deps.verify_csrf(request, str(form.get("csrf") or request.headers.get("X-CSRF-Token") or ""))
    except Exception:
        return Response(content=json.dumps({"ok": False, "error": "csrf"}), media_type="application/json", status_code=403)
    try:
        from app_core.assistant import model_pull, bundles
        bid = bundles.get_active_bundle_id()
        res = model_pull.pull_bundle_on_startup(bundle_id=bid)
        return _json_safe_value({"ok": True, "bundle_id": bid, "result": res})
    except Exception:
        logger.exception("assistant_models_pull_bundle_failed")
        return Response(content=json.dumps({"ok": False, "error": "pull_failed"}), media_type="application/json", status_code=500)


@router.post("/assistant/training/build-dataset")
async def assistant_training_build_dataset(request: Request):
    if not _assistant_allowed(request):
        return Response(content=json.dumps({"ok": False, "error": "unlock_required"}), media_type="application/json", status_code=403)
    form = await request.form()
    try:
        deps.verify_csrf(request, str(form.get("csrf") or request.headers.get("X-CSRF-Token") or ""))
    except Exception:
        return Response(content=json.dumps({"ok": False, "error": "csrf"}), media_type="application/json", status_code=403)
    try:
        from app_core.assistant import training as at
        actor = "assistant_training"
        try:
            actor = str((deps.current_actor(request) or {}).get("actor") or actor) if hasattr(deps, "current_actor") else actor
        except Exception:
            pass
        res = at.build_sanitized_dataset(actor=actor)
        return _json_safe_value(res)
    except Exception:
        logger.exception("assistant_training_build_dataset_failed")
        return Response(content=json.dumps({"ok": False, "error": "dataset_build_failed"}), media_type="application/json", status_code=500)


@router.get("/assistant/training/datasets")
async def assistant_training_datasets(request: Request, limit: int = 50):
    if not _assistant_allowed(request):
        return Response(content=json.dumps({"ok": False, "error": "unlock_required"}), media_type="application/json", status_code=403)
    try:
        from app_core.assistant import training as at
        items = at.list_sanitized_datasets(limit=limit)
        return _json_safe_value({"ok": True, "datasets": items, "count": len(items)})
    except Exception:
        logger.exception("assistant_training_datasets_failed")
        return Response(content=json.dumps({"ok": False, "error": "datasets_failed"}), media_type="application/json", status_code=500)


@router.get("/assistant/training/datasets/{dataset_id}")
async def assistant_training_dataset_get(request: Request, dataset_id: str):
    if not _assistant_allowed(request):
        return Response(content=json.dumps({"ok": False, "error": "unlock_required"}), media_type="application/json", status_code=403)
    try:
        from app_core.assistant import training as at
        ds = at.get_sanitized_dataset(dataset_id)
        if not ds:
            return Response(content=json.dumps({"ok": False, "error": "not_found"}), media_type="application/json", status_code=404)
        return _json_safe_value({"ok": True, "dataset": ds})
    except Exception:
        logger.exception("assistant_training_dataset_get_failed")
        return Response(content=json.dumps({"ok": False, "error": "dataset_get_failed"}), media_type="application/json", status_code=500)


@router.get("/assistant/models/jobs")
async def assistant_models_jobs(request: Request, limit: int = 50):
    if not _assistant_allowed(request):
        return Response(content=json.dumps({"ok": False, "error": "unlock_required"}), media_type="application/json", status_code=403)
    try:
        from app_core.assistant import model_ops
        return _json_safe_value({"ok": True, "jobs": model_ops.list_jobs(limit=limit)})
    except Exception:
        logger.exception("assistant_models_jobs_failed")
        return Response(content=json.dumps({"ok": False, "error": "jobs_failed"}), media_type="application/json", status_code=500)


@router.get("/assistant/models/jobs/{job_id}")
async def assistant_models_job_get(request: Request, job_id: int):
    if not _assistant_allowed(request):
        return Response(content=json.dumps({"ok": False, "error": "unlock_required"}), media_type="application/json", status_code=403)
    try:
        from app_core.assistant import model_ops
        job = model_ops.get_job(int(job_id))
        if not job:
            return Response(content=json.dumps({"ok": False, "error": "not_found"}), media_type="application/json", status_code=404)
        return _json_safe_value({"ok": True, "job": job})
    except Exception:
        logger.exception("assistant_models_job_get_failed")
        return Response(content=json.dumps({"ok": False, "error": "job_get_failed"}), media_type="application/json", status_code=500)


@router.post("/assistant/models/jobs/{job_id}/cancel")
async def assistant_models_job_cancel(request: Request, job_id: int):
    if not _assistant_allowed(request):
        return Response(content=json.dumps({"ok": False, "error": "unlock_required"}), media_type="application/json", status_code=403)
    form = await request.form()
    try:
        deps.verify_csrf(request, str(form.get("csrf") or request.headers.get("X-CSRF-Token") or ""))
    except Exception:
        return Response(content=json.dumps({"ok": False, "error": "csrf"}), media_type="application/json", status_code=403)
    try:
        from app_core.assistant import model_ops
        actor = "manager"
        try:
            actor = str((deps.current_actor(request) or {}).get("actor") or actor) if hasattr(deps, "current_actor") else actor
        except Exception:
            pass
        res = model_ops.cancel_job(int(job_id), actor=actor, reason=str(form.get("reason") or ""))
        return _json_safe_value(res)
    except Exception:
        logger.exception("assistant_models_job_cancel_failed")
        return Response(content=json.dumps({"ok": False, "error": "job_cancel_failed"}), media_type="application/json", status_code=500)


@router.post("/assistant/models/jobs/{job_id}/fail")
async def assistant_models_job_fail(request: Request, job_id: int):
    if not _assistant_allowed(request):
        return Response(content=json.dumps({"ok": False, "error": "unlock_required"}), media_type="application/json", status_code=403)
    form = await request.form()
    try:
        deps.verify_csrf(request, str(form.get("csrf") or request.headers.get("X-CSRF-Token") or ""))
    except Exception:
        return Response(content=json.dumps({"ok": False, "error": "csrf"}), media_type="application/json", status_code=403)
    try:
        from app_core.assistant import model_ops
        actor = "manager"
        try:
            actor = str((deps.current_actor(request) or {}).get("actor") or actor) if hasattr(deps, "current_actor") else actor
        except Exception:
            pass
        res = model_ops.mark_job_failed(int(job_id), actor=actor, reason=str(form.get("reason") or ""))
        return _json_safe_value(res)
    except Exception:
        logger.exception("assistant_models_job_fail_failed")
        return Response(content=json.dumps({"ok": False, "error": "job_fail_failed"}), media_type="application/json", status_code=500)


@router.post("/assistant/models/pull-bundle-job")
async def assistant_models_pull_bundle_job(request: Request):
    if not _assistant_allowed(request):
        return Response(content=json.dumps({"ok": False, "error": "unlock_required"}), media_type="application/json", status_code=403)
    form = await request.form()
    try:
        deps.verify_csrf(request, str(form.get("csrf") or request.headers.get("X-CSRF-Token") or ""))
    except Exception:
        return Response(content=json.dumps({"ok": False, "error": "csrf"}), media_type="application/json", status_code=403)
    try:
        from app_core.assistant import model_ops
        actor = deps.current_actor(request).get("actor") if hasattr(deps, "current_actor") else "manager"
        return _json_safe_value(model_ops.start_bundle_pull_job(actor=str(actor or "manager")))
    except Exception:
        logger.exception("assistant_models_pull_bundle_job_failed")
        return Response(content=json.dumps({"ok": False, "error": "pull_job_failed"}), media_type="application/json", status_code=500)
