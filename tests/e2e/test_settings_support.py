"""tests/e2e/test_settings_support.py — settings + support pages (app issue #42).

Covers: settings general page loads, saving settings via the guarded form,
and the support report page (issue report form + preview).
"""
from __future__ import annotations

import pytest

import re

pytest.importorskip("playwright")
from playwright.sync_api import expect


def test_settings_general_page_loads(e2e_server, page, setup_app, unlock):
    base = e2e_server.base_url
    setup_app("E2E Property")
    unlock()
    page.goto(base + "/settings?tab=general")
    expect(page.get_by_text("Save settings").first).to_be_visible()


def test_settings_save_via_ui(e2e_server, page, setup_app, unlock, password):
    base = e2e_server.base_url
    setup_app("E2E Property")
    unlock()
    page.goto(base + "/settings?tab=general")
    page.locator('form[action="/settings/save"]').locator('input[name="password"]').fill(password)
    page.get_by_role("button", name="Save settings").click()
    page.wait_for_load_state("networkidle")
    expect(page.get_by_text(re.compile(r"Saved \d+ settings"))).to_be_visible()


def test_support_report_page_loads(e2e_server, page, setup_app, unlock):
    base = e2e_server.base_url
    setup_app("E2E Property")
    unlock()
    page.goto(base + "/support/report")
    expect(page.get_by_role("heading", name="Report an issue")).to_be_visible()
    expect(page.locator("#btn-generate")).to_be_visible()
    expect(page.locator("#report-preview")).to_be_visible()
