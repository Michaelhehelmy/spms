"""tests/e2e/test_settings_admin.py — settings admin: branding, backup, rooms (app issue #42).

Covers: apply branding via the Settings/Branding form, Backup now, and adding a
room via the Rooms & Plans tab.
"""
from __future__ import annotations

import re

from playwright.sync_api import expect


def test_settings_apply_branding(e2e_server, page, setup_app, unlock):
    base = e2e_server.base_url
    setup_app("E2E Property")
    unlock()
    page.goto(base + "/settings?tab=general")
    form = page.locator('form[action="/settings/branding"]')
    form.locator('input[name="display_name"]').fill("E2E Branding Name")
    form.locator('input[name="tagline"]').fill("E2E branding tagline")
    form.get_by_role("button", name="Apply branding").click()
    page.wait_for_load_state("networkidle")
    expect(page.get_by_text("Branding updated")).to_be_visible()
    expect(page.get_by_role("heading", name="E2E Branding Name")).to_be_visible()


def test_settings_backup_now(e2e_server, page, setup_app, unlock):
    base = e2e_server.base_url
    setup_app("E2E Property")
    unlock()
    page.goto(base + "/settings?tab=general")
    page.get_by_role("button", name="Backup now").click()
    page.wait_for_load_state("networkidle")
    flash = page.locator(".flash.success").first
    expect(flash).to_be_visible()
    assert flash.inner_text().startswith("Backup:")


def test_settings_rooms_add_room(e2e_server, page, setup_app, unlock):
    base = e2e_server.base_url
    setup_app("E2E Property")
    unlock()
    page.goto(base + "/settings?tab=rooms")
    page.fill('input[name="room_number"]', "E2E Room 77")
    page.fill('input[name="room_type"]', "Standard Room")
    page.get_by_role("button", name="Add room").click()
    page.wait_for_load_state("networkidle")
    expect(page.get_by_text(re.compile(r"Room added \(#\d+\)"))).to_be_visible()


def test_settings_rate_plans_add(e2e_server, page, setup_app, unlock, password):
    base = e2e_server.base_url
    setup_app("E2E Property")
    unlock()
    page.goto(base + "/settings/rate-plans")
    form = page.locator('form[action="/settings/rate-plans/add"]')
    form.locator('input[name="name"]').fill("E2E Plan")
    form.locator('input[name="modifier"]').fill("5")
    form.locator('input[name="password"]').fill(password)
    form.get_by_role("button", name="Add").click()
    page.wait_for_load_state("networkidle")
    expect(page.get_by_text("E2E Plan").first).to_be_visible()
    expect(page.get_by_text("+5.00 EGP").first).to_be_visible()
