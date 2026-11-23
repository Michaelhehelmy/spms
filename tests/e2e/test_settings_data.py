"""tests/e2e/test_settings_data.py — settings Seed & Data tab (app issue #42).

Covers: data tab loads, inventory CSV export (current + template), and seed
config JSON export via the Settings page.
"""
from __future__ import annotations

from playwright.sync_api import expect


def test_settings_data_tab_loads(e2e_server, page, setup_app, unlock):
    base = e2e_server.base_url
    setup_app("E2E Property")
    unlock()
    page.goto(base + "/settings?tab=data")
    expect(page.get_by_role("heading", name="First-time seed / master data")).to_be_visible()
    expect(page.get_by_role("heading", name="Guarded demo data preset")).to_be_visible()
    expect(page.get_by_role("heading", name="Reset settings to defaults")).to_be_visible()


def _post_response_303(page, base, url):
    responses = []
    page.on("response", lambda r: responses.append(r) if r.url == url else None)
    return responses


def test_settings_export_inventory_csv(e2e_server, page, setup_app, unlock):
    base = e2e_server.base_url
    setup_app("E2E Property")
    unlock()
    page.goto(base + "/settings?tab=data")
    responses = _post_response_303(page, base, base + "/settings/seed/export-inventory-csv")
    page.get_by_role("button", name="Export current inventory CSV").click()
    page.wait_for_load_state("networkidle")
    redirects = [r for r in responses if r.status == 303]
    assert redirects and redirects[0].headers.get("location", "").startswith("/files/export/")


def test_settings_download_inventory_csv_template(e2e_server, page, setup_app, unlock):
    base = e2e_server.base_url
    setup_app("E2E Property")
    unlock()
    page.goto(base + "/settings?tab=data")
    responses = _post_response_303(page, base, base + "/settings/seed/export-inventory-csv")
    page.get_by_role("button", name="Download inventory CSV template").click()
    page.wait_for_load_state("networkidle")
    redirects = [r for r in responses if r.status == 303]
    assert redirects and redirects[0].headers.get("location", "").startswith("/files/export/")


def test_settings_export_seed_config_json(e2e_server, page, setup_app, unlock):
    base = e2e_server.base_url
    setup_app("E2E Property")
    unlock()
    page.goto(base + "/settings?tab=data")
    responses = _post_response_303(page, base, base + "/settings/seed/export")
    page.get_by_role("button", name="Export seed config JSON (download)").click()
    page.wait_for_load_state("networkidle")
    redirects = [r for r in responses if r.status == 303]
    assert redirects and redirects[0].headers.get("location", "").startswith("/files/export/")
