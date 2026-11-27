"""tests/e2e/test_assistant.py — Manager Assistant (app issue #42).

Covers: assistant page loads (conversation + ask form + clear chat), and the
/assistant/ask route through the browser session (JSON request via the
context session).
"""
from __future__ import annotations

import pytest

pytest.importorskip("playwright")
from playwright.sync_api import expect


def test_assistant_page_loads(e2e_server, page, setup_app, unlock):
    base = e2e_server.base_url
    setup_app("E2E Property")
    unlock()
    page.goto(base + "/assistant")
    expect(page.get_by_role("heading", name="Manager Assistant")).to_be_visible()
    expect(page.get_by_role("button", name="Send message")).to_be_visible()
    expect(page.get_by_role("button", name="Clear chat")).to_be_visible()
    expect(page.locator("#assistant-messages")).to_be_visible()


def test_assistant_ask_route_via_session(e2e_server, page, setup_app, unlock):
    base = e2e_server.base_url
    setup_app("E2E Property")
    unlock()
    page.goto(base + "/assistant")
    resp = page.request.post(
        base + "/assistant/ask",
        form={"message": "Who owes money?", "csrf": page.locator('input[name="csrf"]').first.input_value()},
        headers={"Accept": "application/json"},
    )
    assert resp.status == 200
    body = resp.json()
    assert body.get("ok") is True


def test_assistant_send_message_via_ui(e2e_server, page, setup_app, unlock):
    base = e2e_server.base_url
    setup_app("E2E Property")
    unlock()
    page.goto(base + "/assistant")
    page.fill('textarea[name="message"]', "Who owes money?")
    page.get_by_role("button", name="Send message").click()
    page.wait_for_load_state("networkidle", timeout=15000)
    assert page.url == base + "/assistant"
    expect(page.get_by_role("button", name="Send message")).to_be_visible()
    # Clear chat via the guarded route.
    r = page.request.post(base + "/assistant/clear", form={"csrf": page.locator('input[name="csrf"]').first.input_value()})
    assert r.status in (200, 303, 302)
