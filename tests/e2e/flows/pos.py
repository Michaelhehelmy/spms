"""POS/Inventory flows."""
from __future__ import annotations

import re

from playwright.sync_api import expect

from conftest import TEST_PASSWORD
from .common import (
    assert_url_contains,
    click_link,
    ensure_demo_ready,
    maybe_caption,
    nav_click,
    type_into,
)


def open_tab(page, base: str, tab: str, label: str):
    nav_click(page, "/pos", "POS / Inventory")
    subtab = page.locator(f'.subtabs a[href*="tab={tab}"]').first
    expect(subtab).to_be_visible()
    subtab.click()
    page.wait_for_load_state("domcontentloaded")
    ensure_demo_ready(page)
    assert_url_contains(page, f"tab={tab}")
    maybe_caption(page, f"Sub-tab: POS {label}", duration=1.0)


def sell_add_custom_to_cart(page, desc: str, qty: str = "1", price: str = "10.00"):
    maybe_caption(page, f"Action: add '{desc}' to walk-in cart", duration=1.2)
    form = page.locator('form[action="/pos/cart/add"]').filter(has_text="Add to cart").first
    form.locator('input[name="desc"]').fill(desc)
    form.locator('input[name="qty"]').fill(qty)
    form.locator('input[name="price"]').fill(price)
    form.get_by_role("button", name="Add to cart").click()
    page.wait_for_load_state("domcontentloaded")
    ensure_demo_ready(page)
    expect(page.get_by_text(desc).first).to_be_visible()


def sell_complete_walkin(page, base: str):
    maybe_caption(page, "Action: complete walk-in sale & get receipt", duration=1.2)
    with page.expect_response(lambda r: "/pos/walkin" in r.url or "/files/invoice/" in r.url, timeout=15000):
        page.get_by_role("button", name="Complete walk-in sale & get receipt").click()
    page.wait_for_load_state("domcontentloaded")
    page.wait_for_timeout(500)
    # Success may redirect to receipt file or show flash on POS page.
    if "/files/invoice/" in page.url:
        maybe_caption(page, "Result: walk-in sale receipt generated", duration=1.2)
        page.goto(base + "/pos?tab=sell", wait_until="domcontentloaded")
        ensure_demo_ready(page)
        return
    ensure_demo_ready(page)
    if page.get_by_text(re.compile(r"Walk-in sale completed", re.I)).count() == 0:
        # fallback: navigate to sell and check cart cleared / flash in session
        page.goto(base + "/pos?tab=sell", wait_until="domcontentloaded")
        ensure_demo_ready(page)
    expect(page.get_by_text(re.compile(r"Walk-in sale completed|Cart is empty|Walk-in cart \(0 items\)", re.I)).first).to_be_visible()


def inventory_add_item(page, *, name: str, category: str = "Supplies", unit: str = "pcs", stock: str = "10", cost: str = "2", selling: str = "5", password: str = TEST_PASSWORD):
    maybe_caption(page, f"Action: add inventory item '{name}'", duration=1.2)
    form = page.locator('form[action="/inventory/add"]').first
    form.locator('input[name="name"]').fill(name)
    form.locator('input[name="category"]').fill(category)
    form.locator('input[name="unit"]').fill(unit)
    form.locator('input[name="stock"]').fill(stock)
    form.locator('input[name="unit_cost"]').fill(cost)
    form.locator('input[name="selling_price"]').fill(selling)
    form.locator('input[name="password"]').fill(password)
    form.get_by_role("button", name="Add item").click()
    page.wait_for_load_state("domcontentloaded")
    ensure_demo_ready(page)
    expect(page.get_by_text("Inventory item added").first).to_be_visible()


def inventory_restock(page, *, item_id: str, qty: str = "5", unit_cost: str = "2", password: str = TEST_PASSWORD):
    maybe_caption(page, f"Action: restock inventory item #{item_id}", duration=1.2)
    form = page.locator('form[action="/inventory/restock"]').first
    form.locator('input[name="item_id"]').fill(item_id)
    form.locator('input[name="qty"]').fill(qty)
    form.locator('input[name="unit_cost"]').fill(unit_cost)
    form.locator('input[name="password"]').fill(password)
    form.get_by_role("button", name="Restock").click()
    page.wait_for_load_state("domcontentloaded")
    ensure_demo_ready(page)
    expect(page.get_by_text(re.compile(r"Batch received|restocked", re.I)).first).to_be_visible()


def batches_receive(page, *, item_id: str, qty: str = "3", unit_cost: str = "2", supplier: str = "E2E Supplier", password: str = TEST_PASSWORD):
    maybe_caption(page, f"Action: receive batch for item #{item_id}", duration=1.2)
    form = page.locator('form[action="/inventory/batch/receive"]').first
    form.locator('input[name="item_id"]').fill(item_id)
    form.locator('input[name="qty"]').fill(qty)
    form.locator('input[name="unit_cost"]').fill(unit_cost)
    form.locator('input[name="supplier"]').fill(supplier)
    # uncheck print label to avoid printer side effects in CI
    cb = form.locator('input[name="print_label"]')
    if cb.count() > 0 and cb.is_checked():
        cb.uncheck()
    form.locator('input[name="password"]').fill(password)
    form.get_by_role("button", name="Receive batch").click()
    page.wait_for_load_state("domcontentloaded")
    ensure_demo_ready(page)
    expect(page.get_by_text(re.compile(r"Batch received", re.I)).first).to_be_visible()


def activity_create(page, *, name: str, category: str = "Trip", price: str = "30", description: str = "Story activity"):
    maybe_caption(page, f"Action: register activity '{name}'", duration=1.2)
    form = page.locator('form[action="/activities/create"]').first
    form.locator('input[name="name"]').fill(name)
    form.locator('textarea[name="description"]').fill(description)
    form.locator('input[name="category"]').fill(category)
    form.locator('input[name="unit_price"]').fill(price)
    form.get_by_role("button", name="Register activity").click()
    page.wait_for_load_state("domcontentloaded")
    ensure_demo_ready(page)
    expect(page.get_by_text(re.compile(r"Activity/trip registered|registered", re.I)).first).to_be_visible()
