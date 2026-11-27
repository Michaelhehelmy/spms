"""Story V3 — POS/Inventory/Housekeeping (real E2E + demo mode)."""
from __future__ import annotations

import re

import pytest

pytest.importorskip("playwright")

from playwright.sync_api import expect

from conftest import TEST_PASSWORD
from flows.common import ensure_demo_ready, maybe_caption, nav_click
from flows.housekeeping import (
    create_room_block,
    create_task,
    filter_tasks,
    generate_dirty_tasks,
    open_page as open_housekeeping,
    resolve_first_block,
    update_first_task_status,
)
from flows.pos import (
    activity_create,
    batches_receive,
    inventory_add_item,
    open_tab as open_pos_tab,
    sell_add_custom_to_cart,
    sell_complete_walkin,
)


@pytest.mark.story
def test_story_v3_pos_housekeeping(e2e_server, page, setup_app, unlock):
    base = e2e_server.base_url
    setup_app("Acadia Camp")
    unlock()
    page.goto(base + "/", wait_until="domcontentloaded")
    ensure_demo_ready(page)

    # --- POS: Sell tab ---
    maybe_caption(page, "Start: POS / Inventory & Housekeeping story", duration=1.8)
    open_pos_tab(page, base, "sell", "Sell")
    expect(page.get_by_role("heading", name="Barcode scan / lookup (item or batch/lot)").first).to_be_visible()
    sell_add_custom_to_cart(page, "Story Walk-in Coffee", qty="2", price="4.50")
    expect(page.get_by_text("Walk-in cart (1 items)").first).to_be_visible()
    sell_complete_walkin(page, base)

    # --- POS: Inventory tab ---
    open_pos_tab(page, base, "inventory", "Inventory")
    inventory_add_item(page, name="Story Water Bottle", category="Drinks", unit="bottle", stock="10", cost="1.00", selling="3.00", password=TEST_PASSWORD)
    # find item id for later batch/restock
    row = page.locator("tr", has_text="Story Water Bottle").first
    expect(row).to_be_visible()
    item_id = row.locator("td").nth(0).inner_text().strip()

    # restock (sub-action)
    form = page.locator('form[action="/inventory/restock"]').first
    form.locator('input[name="item_id"]').fill(item_id)
    form.locator('input[name="qty"]').fill("5")
    form.locator('input[name="unit_cost"]').fill("1.00")
    form.locator('input[name="password"]').fill(TEST_PASSWORD)
    maybe_caption(page, "Action: restock inventory item", duration=1.2)
    form.get_by_role("button", name="Restock").click()
    page.wait_for_load_state("domcontentloaded")
    ensure_demo_ready(page)
    expect(page.get_by_text(re.compile(r"Batch received|restocked", re.I)).first).to_be_visible()

    # --- POS: Batches tab ---
    open_pos_tab(page, base, "batches", "Batches & Traceability")
    batches_receive(page, item_id=item_id, qty="4", unit_cost="1.00", supplier="Story Supplier", password=TEST_PASSWORD)
    expect(page.get_by_text(re.compile(r"Story Water Bottle")).first).to_be_visible()

    # --- POS: Meals & Recipes tab ---
    open_pos_tab(page, base, "meals", "Meals & Recipes")
    expect(page.get_by_role("heading", name="Registered Meals").first).to_be_visible()
    maybe_caption(page, "Sub-tab: Meals & Recipes visible (recipe/meal management)", duration=1.2)

    # --- POS: Activities tab ---
    open_pos_tab(page, base, "activities", "Activities")
    activity_create(page, name="Story Desert Tour", category="Trip", price="45.00", description="Guided tour")
    expect(page.get_by_text("Story Desert Tour").first).to_be_visible()

    # --- POS: History tab ---
    open_pos_tab(page, base, "history", "History")
    expect(page.get_by_role("heading", name="Recent walk-in POS lines (no reservation)").first).to_be_visible()
    expect(page.get_by_text(re.compile(r"Story Walk-in Coffee|Walk-in")).first).to_be_visible()
    maybe_caption(page, "Result: walk-in sale visible in POS history", duration=1.2)

    # --- Housekeeping ---
    open_housekeeping(page, base)
    generate_dirty_tasks(page)
    create_task(page, assignee="Alex HK", task_type="cleaning", priority="high", notes="Story housekeeping task")
    update_first_task_status(page, "in_progress")
    filter_tasks(page, "in_progress")
    expect(page.locator("td", has_text="in_progress").first).to_be_visible()
    filter_tasks(page, "")  # reset

    create_room_block(page, password=TEST_PASSWORD)
    resolve_first_block(page, password=TEST_PASSWORD)

    maybe_caption(page, "Result: POS/Inventory/Housekeeping story complete", duration=1.8)
    # Master video is recorded by test_story_master_all_app.py; keep this as E2E coverage.
