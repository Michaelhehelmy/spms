"""tests/e2e/test_pos_inventory.py — POS sell + inventory (app issue #42).

Covers: POS sell page loads, adding a custom item to the walk-in cart,
clearing the cart, and searching the inventory list on the POS page.
"""
from __future__ import annotations

from playwright.sync_api import expect


def test_pos_sell_page_loads(e2e_server, page, setup_app, unlock):
    base = e2e_server.base_url
    setup_app("E2E Property")
    unlock()
    page.goto(base + "/pos?tab=sell")
    expect(page.get_by_role("heading", name="POS / Inventory")).to_be_visible()
    expect(page.get_by_role("heading", name="Barcode scan / lookup (item or batch/lot)")).to_be_visible()
    expect(page.get_by_role("heading", name="Add custom item to walk-in cart")).to_be_visible()
    expect(page.get_by_text("Walk-in cart (0 items)")).to_be_visible()
    expect(page.get_by_role("button", name="Search")).to_be_visible()


def test_pos_add_custom_item_to_cart(e2e_server, page, setup_app, unlock):
    base = e2e_server.base_url
    setup_app("E2E Property")
    unlock()
    page.goto(base + "/pos?tab=sell")
    form = page.locator('form[action="/pos/cart/add"]:has-text("Add to cart")')
    form.locator('input[name="desc"]').fill("E2E Pos Item")
    form.locator('input[name="qty"]').fill("2")
    form.locator('input[name="price"]').fill("15.50")
    form.get_by_role("button", name="Add to cart").click()
    page.wait_for_load_state("networkidle")
    expect(page.get_by_text("E2E Pos Item").first).to_be_visible()
    expect(page.get_by_text("Walk-in cart (1 items)")).to_be_visible()


def test_pos_clear_cart(e2e_server, page, setup_app, unlock):
    base = e2e_server.base_url
    setup_app("E2E Property")
    unlock()
    page.goto(base + "/pos?tab=sell")
    form = page.locator('form[action="/pos/cart/add"]:has-text("Add to cart")')
    form.locator('input[name="desc"]').fill("E2E Temp Item")
    form.locator('input[name="qty"]').fill("1")
    form.locator('input[name="price"]').fill("3.25")
    form.get_by_role("button", name="Add to cart").click()
    page.wait_for_load_state("networkidle")
    expect(page.get_by_text("Walk-in cart (1 items)")).to_be_visible()
    page.get_by_role("button", name="Clear cart").click()
    page.wait_for_load_state("networkidle")
    expect(page.get_by_text("Cart is empty").first).to_be_visible()


def test_pos_inventory_search(e2e_server, page, setup_app, unlock, seed_inventory):
    base = e2e_server.base_url
    setup_app("E2E Property")
    unlock()
    seed_inventory("E2E Supplies Item", selling_price=9.99, stock_qty=3)
    page.goto(base + "/pos?tab=sell")
    page.fill('input[name="q"]', "E2E Supplies")
    page.get_by_role("button", name="Search").click()
    page.wait_for_load_state("networkidle")
    expect(page.locator("td:has-text('E2E Supplies Item')").first).to_be_visible()
