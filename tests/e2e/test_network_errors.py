"""tests/e2e/test_network_errors.py — network/error states (app issue #42).

Covers: a UI-driven error state shows a friendly flash (POS add-to-cart
rejects a negative price server-side), and an unknown route returns a 404.
"""
from __future__ import annotations

import pytest

pytest.importorskip("playwright")
from playwright.sync_api import expect


def test_invalid_price_shows_friendly_error_flash(e2e_server, page, setup_app, unlock):
    base = e2e_server.base_url
    setup_app("E2E Property")
    unlock()
    page.goto(base + "/pos?tab=sell")
    form = page.locator('.panel:has(h3:has-text("Add custom item to walk-in cart")) form[action="/pos/cart/add"]')
    form.locator('input[name="desc"]').fill("E2E Error Item")
    form.locator('input[name="qty"]').fill("1")
    form.locator('input[name="price"]').fill("-5")
    form.get_by_role("button", name="Add to cart").click()
    page.wait_for_load_state("networkidle", timeout=15000)
    expect(page.get_by_text("Price cannot be negative.")).to_be_visible()


def test_unknown_route_returns_404(e2e_server, page, setup_app, unlock):
    base = e2e_server.base_url
    setup_app("E2E Property")
    unlock()
    resp = page.goto(base + "/no-such-page")
    assert resp is not None and resp.status == 404
