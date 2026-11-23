"""tests/e2e/test_csrf.py — CSRF protection (app issue #42).

Covers: tampered CSRF token → 400; missing CSRF token → 400.
"""
from __future__ import annotations

import pytest

pytest.importorskip("playwright")
from playwright.sync_api import expect


def _responses_for(page, url):
    responses = []
    page.on("response", lambda r: responses.append(r) if r.url == url else None)
    return responses


def test_csrf_tampered_token_rejected(e2e_server, page, setup_app):
    base = e2e_server.base_url
    setup_app("E2E Property")
    page.goto(base + "/unlock")
    page.evaluate(
        "() => { const el = document.querySelector('form[action=\"/unlock\"] input[name=\"csrf\"]');"
        " if (el) el.value = 'tampered-token-value'; }"
    )
    page.fill('input[name="password"]', "e2e-pass-123")
    responses = _responses_for(page, base + "/unlock")
    page.get_by_role("button", name="Unlock").click()
    page.wait_for_load_state("networkidle")
    assert any(r.status == 400 for r in responses)


def test_csrf_missing_token_rejected(e2e_server, page, setup_app):
    base = e2e_server.base_url
    setup_app("E2E Property")
    page.goto(base + "/unlock")
    expect(page.locator('input[name="password"]')).to_be_visible()
    page.evaluate(
        "() => { const el = document.querySelector('form[action=\"/unlock\"] input[name=\"csrf\"]');"
        " if (el) el.remove(); }"
    )
    page.fill('input[name="password"]', "e2e-pass-123")
    responses = _responses_for(page, base + "/unlock")
    page.get_by_role("button", name="Unlock").click()
    page.wait_for_load_state("networkidle")
    assert any(r.status == 400 for r in responses)
