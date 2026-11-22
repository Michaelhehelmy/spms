"""tests/e2e/test_cross_browser.py — cross-browser smoke (app issue #42).

Chromium smoke is the suite's primary target; Firefox/WebKit smoke runs when
the browser is installed locally (optionally installed on CI/local: see
`playwright install firefox webkit`).
"""
from __future__ import annotations

import pytest
from playwright.sync_api import expect

BROWSERS = ["chromium", "firefox", "webkit"]


def _setup_unlock(page, e2e_server):
    base = e2e_server.base_url
    page.goto(base + "/setup")
    page.fill('input[name="display_name"]', "E2E Property")
    page.select_option('select[name="animation"]', "reveal")
    page.click('button[type="submit"]')
    page.wait_for_url(lambda url: url == base + "/")
    page.goto(base + "/unlock")
    page.fill('input[name="password"]', "e2e-pass-123")
    page.click('button[type="submit"]')
    page.wait_for_url(lambda url: url == base + "/")


@pytest.mark.parametrize("browser_name", BROWSERS)
def test_pages_load_in_browser(e2e_server, playwright, browser_name):
    browser_cls = getattr(playwright, browser_name)
    try:
        browser = browser_cls.launch(headless=True)
    except Exception:
        pytest.skip(f"{browser_name} not installed")
    base = e2e_server.base_url
    ctx = browser.new_context()
    page = ctx.new_page()
    try:
        _setup_unlock(page, e2e_server)
        for path in ["/", "/guests", "/reservations", "/pos"]:
            page.goto(base + path)
            page.wait_for_load_state("networkidle")
            expect(page.get_by_role("link", name="Dashboard")).to_be_visible()
    finally:
        ctx.close()
        browser.close()
