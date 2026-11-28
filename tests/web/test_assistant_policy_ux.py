from __future__ import annotations

import time

from tests.web.conftest import get_csrf, set_session


def _patch_base(monkeypatch):
    import ui.web.routes.assistant as ar

    monkeypatch.setattr(
        ar.assistant,
        "get_llm_config",
        lambda: {
            "provider": "auto",
            "response_mode": "talking",
            "local_available": False,
            "enabled": False,
            "external": False,
        },
    )
    monkeypatch.setattr(ar.assistant, "INTENT_LABELS", {"capabilities_help": "Help"}, raising=False)
    monkeypatch.setattr(ar.services, "get_setting", lambda k, d=None: "true" if k == "assistant_require_unlock" else d)
    return ar


def test_assistant_ask_json_includes_policy_and_denied_proposal_not_pending(client, monkeypatch):
    ar = _patch_base(monkeypatch)

    def fake_chat(msg, history=None, ui_context=None):
        return {
            "ok": False,
            "answer": "Action blocked by policy: deny rule.",
            "intent": "propose_record_payment",
            "confidence": 0.9,
            "tools_used": ["validate_entities"],
            "source": "policy_deny",
            "ui_actions": [],
            "proposed_action": {
                "status": "denied",
                "action_type": "propose_record_payment",
                "summary": "Record payment",
                "errors": ["Policy denied: no payments"],
                "policy": {
                    "effect": "deny",
                    "matched_rule_id": "deny-payments",
                    "reason": "no payments",
                    "requires_confirmation": True,
                    "sensitive": True,
                },
                "prechecks": {"ok": False, "errors": ["Policy denied: no payments"], "warnings": [], "checks": [], "resolved": {}, "preview": {}},
            },
            "policy": {
                "effect": "deny",
                "matched_rule_id": "deny-payments",
                "reason": "no payments",
                "requires_confirmation": True,
                "sensitive": True,
            },
        }

    monkeypatch.setattr(ar.assistant, "chat", fake_chat)
    token = set_session(client, unlocked=True)
    r = client.post(
        "/assistant/ask",
        data={"csrf": token, "message": "record payment"},
        headers={"Accept": "application/json"},
    )
    assert r.status_code == 200
    j = r.json()
    assert j["ok"] is False
    assert j.get("policy", {}).get("effect") == "deny"
    assert j.get("policy", {}).get("matched_rule_id") == "deny-payments"
    # Denied proposal must not be persisted as a pending executable action.
    assert j.get("pending_action") is None
    assert j.get("proposed_action") is None


def test_assistant_pending_action_html_shows_policy_and_hides_confirm_on_deny(client, monkeypatch):
    ar = _patch_base(monkeypatch)
    pending = {
        "id": "act-deny",
        "type": "propose_record_payment",
        "summary": "Record payment",
        "resolved": {"reservation": {"id": 1}},
        "preview": {"amount": 10},
        "prechecks": {"ok": True, "errors": [], "warnings": [], "checks": []},
        "policy": {
            "effect": "deny",
            "matched_rule_id": "deny-payments",
            "reason": "Payments blocked by property policy",
            "requires_confirmation": True,
        },
        "expires_at_ts": int(time.time()) + 600,
        "expires_at": "2099-01-01T00:00:00Z",
    }
    token = set_session(client, unlocked=True, extra={ar.PENDING_ACTION_SESSION_KEY: dict(pending), "assistant_history": []})
    page = client.get("/assistant")
    csrf = get_csrf(page.text)
    r = client.post(
        "/assistant/ask",
        data={"csrf": csrf, "message": ""},
        headers={"HX-Request": "true"},
    )
    assert r.status_code == 200
    html = r.text
    assert "Policy decision:" in html
    assert "DENY" in html.upper()
    assert "deny-payments" in html
    assert "Payments blocked by property policy" in html
    assert "Confirmation required:" in html
    assert "Resolved details" in html
    # confirm button should not be rendered for denied actions
    assert "Confirm action" not in html
    assert "Action blocked by policy" in html


def test_assistant_confirm_refuses_denied_pending_action(client, monkeypatch):
    ar = _patch_base(monkeypatch)
    pending = {
        "id": "act-deny-2",
        "type": "propose_record_payment",
        "summary": "Record payment",
        "args": {"reservation_id": 1, "amount": 10, "method": "Cash"},
        "resolved": {},
        "preview": {},
        "prechecks": {"ok": True},
        "policy": {
            "effect": "deny",
            "matched_rule_id": "deny-payments",
            "reason": "Payments blocked",
            "requires_confirmation": True,
        },
        "expires_at_ts": int(time.time()) + 600,
    }
    token = set_session(client, unlocked=True, extra={ar.PENDING_ACTION_SESSION_KEY: dict(pending), "assistant_history": []})
    called = {"exec": False}

    def should_not_exec(*args, **kwargs):
        called["exec"] = True
        return {"ok": True}

    monkeypatch.setattr(ar, "execute_pending_action", should_not_exec)
    page = client.get("/assistant")
    csrf = get_csrf(page.text)
    r = client.post(
        "/assistant/action/confirm",
        data={"csrf": csrf, "action_id": "act-deny-2"},
        headers={"Accept": "application/json"},
    )
    assert r.status_code == 200
    j = r.json()
    assert j["ok"] is False
    assert "denied by policy" in (j.get("error") or j.get("answer") or "").lower()
    assert j.get("policy", {}).get("effect") == "deny"
    assert called["exec"] is False


def test_assistant_pending_action_html_shows_ask_confirmation(client, monkeypatch):
    ar = _patch_base(monkeypatch)
    pending = {
        "id": "act-ask",
        "type": "propose_add_pos_item",
        "summary": "Add POS item",
        "resolved": {"reservation": {"id": 2}, "item": {"id": 5}},
        "preview": {"qty": 1},
        "prechecks": {"ok": True, "errors": [], "warnings": [], "checks": []},
        "policy": {
            "effect": "ask",
            "matched_rule_id": "safety-ask-sensitive-writes",
            "reason": "Sensitive/write actions require explicit confirmation.",
            "requires_confirmation": True,
        },
        "expires_at_ts": int(time.time()) + 600,
        "expires_at": "2099-01-01T00:00:00Z",
    }
    token = set_session(client, unlocked=True, extra={ar.PENDING_ACTION_SESSION_KEY: dict(pending), "assistant_history": []})
    page = client.get("/assistant")
    csrf = get_csrf(page.text)
    r = client.post(
        "/assistant/ask",
        data={"csrf": csrf, "message": ""},
        headers={"HX-Request": "true"},
    )
    assert r.status_code == 200
    html = r.text
    assert "Policy decision:" in html
    assert "ASK" in html.upper()
    assert "safety-ask-sensitive-writes" in html
    assert "Confirmation required" in html
    assert "Resolved details" in html
    assert "Confirm action" in html
