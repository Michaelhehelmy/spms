"""tests/e2e/test_housekeeping_blocks.py — housekeeping room blocks (app issue #42).

Covers: create a room block (OOO/OOS) via the UI (opens the details form),
then resolve the active block.
"""
from __future__ import annotations

import pytest

from datetime import datetime, timedelta

pytest.importorskip("playwright")
from playwright.sync_api import expect


def _fill_create_block_form(page, password):
    form = page.locator('form[action="/housekeeping/blocks/create"]')
    form.locator("select[name='room_id']").select_option(index=0)
    form.locator('input[name="start_date"]').fill(datetime.now().strftime("%Y-%m-%d"))
    form.locator('input[name="end_date"]').fill((datetime.now() + timedelta(days=2)).strftime("%Y-%m-%d"))
    form.locator('input[name="reason"]').fill("E2E block reason")
    form.locator('input[name="password"]').fill(password)
    form.get_by_role("button", name="Create block").click()


def test_housekeeping_create_room_block(e2e_server, page, setup_app, unlock, password):
    base = e2e_server.base_url
    setup_app("E2E Property")
    unlock()
    page.goto(base + "/housekeeping")
    page.get_by_text("Create room block").click()  # opens the details form
    _fill_create_block_form(page, password)
    page.wait_for_load_state("networkidle", timeout=15000)
    expect(page.get_by_text("Room block created")).to_be_visible()


def test_housekeeping_resolve_block_flow(e2e_server, page, setup_app, unlock, password):
    base = e2e_server.base_url
    setup_app("E2E Property")
    unlock()
    page.goto(base + "/housekeeping")
    page.get_by_text("Create room block").click()
    _fill_create_block_form(page, password)
    page.wait_for_load_state("networkidle", timeout=15000)
    expect(page.get_by_text("Room block created")).to_be_visible()
    # Resolve the active block (requires password).
    page.goto(base + "/housekeeping")
    rform = page.locator('form[action^="/housekeeping/blocks/"][action$="/resolve"]').first
    rform.locator('input[name="password"]').fill(password)
    rform.get_by_role("button", name="Resolve").click()
    page.wait_for_load_state("networkidle", timeout=15000)
    expect(page.get_by_text("Room block resolved").first).to_be_visible()
