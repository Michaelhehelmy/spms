"""tests/e2e/test_pwa_a11y.py — PWA + accessibility smoke (app issue #42).

Covers: manifest + icon assets present; no console/page errors on key app
pages (allowlisting the known-benign service-worker scope warning); mobile
viewport smoke on key pages.
"""
from __future__ import annotations

import pytest

pytest.importorskip("playwright")
from playwright.sync_api import expect

KEY_PAGES = ["/", "/reservations", "/guests", "/housekeeping", "/accounting", "/pos", "/reports", "/settings", "/assistant", "/support/report"]


def test_manifest_and_icons_present(e2e_server, page, setup_app, unlock):
    base = e2e_server.base_url
    r = page.goto(base + "/static/manifest.webmanifest")
    assert r is not None and r.status == 200
    manifest = r.json()
    assert manifest["name"]
    r = page.goto(base + "/static/icons/icon-192.png")
    assert r is not None and r.status == 200
    assert r.headers.get("content-type", "").startswith("image/")
    r = page.goto(base + "/static/icons/apple-touch-icon.png")
    assert r is not None and r.status == 200
    assert r.headers.get("content-type", "").startswith("image/")


def test_no_console_errors_on_key_pages(e2e_server, page, setup_app, unlock):
    base = e2e_server.base_url
    for path in KEY_PAGES:
        page.goto(base + path)
        page.wait_for_load_state("networkidle", timeout=15000)
        errors = [e for e in page._console_errors if "Service Worker script" not in e]
        assert errors == [], f"console errors on {path}: {errors[:3]}"


def test_mobile_viewport_key_pages(e2e_server, browser):
    base = e2e_server.base_url
    ctx = browser.new_context(viewport={"width": 390, "height": 844})
    page = ctx.new_page()
    try:
        page.goto(base + "/setup")
        page.fill('input[name="display_name"]', "E2E Property")
        page.select_option('select[name="animation"]', "reveal")
        page.click('button[type="submit"]:not(.ghost)')
        page.wait_for_url(lambda url: url == base + "/")
        page.goto(base + "/unlock")
        page.fill('input[name="password"]', "e2e-pass-123")
        page.click('button[type="submit"]:not(.ghost)')
        page.wait_for_url(lambda url: url == base + "/")
        for path in ["/guests", "/reservations", "/pos", "/assistant"]:
            page.goto(base + path)
            page.wait_for_load_state("networkidle", timeout=15000)
            expect(page.locator("nav.sidebar a.nav-link").first).to_be_visible()
    finally:
        ctx.close()


def test_keyboard_navigation_reaches_nav(e2e_server, page, setup_app, unlock):
    base = e2e_server.base_url
    setup_app("E2E Property")
    unlock()
    page.goto(base + "/")
    seen: list[str] = []
    for _ in range(15):
        page.keyboard.press("Tab")
        seen.append(page.evaluate("document.activeElement ? (document.activeElement.textContent || '') : ''"))
    assert any("Dashboard" in text for text in seen)
