"""tests/e2e/test_accounting_reports.py — accounting + reports (app issue #42).

Covers: accounting page loads; record expense, record payment, open shift +
record shift movement via the UI; run P&L report from the Reports page.
"""
from __future__ import annotations

import re

from playwright.sync_api import expect


def test_accounting_page_loads(e2e_server, page, setup_app, unlock):
    base = e2e_server.base_url
    setup_app("E2E Property")
    unlock()
    page.goto(base + "/accounting?tab=overview")
    expect(page.get_by_text("Quick actions").first).to_be_visible()
    page.goto(base + "/accounting?tab=expenses")
    expect(page.get_by_text("Record expense").first).to_be_visible()
    expect(page.get_by_text("Recent expenses").first).to_be_visible()
    page.goto(base + "/accounting?tab=payments")
    expect(page.get_by_text("Record payment").first).to_be_visible()


def test_accounting_record_expense(e2e_server, page, setup_app, unlock, seed_expense_category):
    base = e2e_server.base_url
    setup_app("E2E Property")
    unlock()
    seed_expense_category("E2E Expense")
    page.goto(base + "/accounting?tab=expenses")
    page.fill('input[name="param"]', "E2E Expense Item")
    page.fill('input[name="amount"]', "12.50")
    page.select_option('select[name="cat_id"]', index=0)
    page.get_by_role("button", name="Record expense").click()
    expect(page.get_by_text("Expense recorded")).to_be_visible()


def test_accounting_record_payment(e2e_server, page, setup_app, unlock):
    base = e2e_server.base_url
    setup_app("E2E Property")
    unlock()
    page.goto(base + "/accounting?tab=payments")
    page.fill('input[name="amount"]', "7.50")
    page.get_by_role("button", name="Record payment").click()
    expect(page.get_by_text("Payment recorded")).to_be_visible()


def test_accounting_open_shift_and_record_movement(e2e_server, page, setup_app, unlock):
    base = e2e_server.base_url
    setup_app("E2E Property")
    unlock()
    page.goto(base + "/accounting?tab=shifts")
    r = page.request.post(base + "/accounting/shifts/open", form={"csrf": page.locator('input[name="csrf"]').first.input_value()})
    assert r.status in (200, 303, 302)
    page.goto(base + "/accounting?tab=shifts")
    expect(page.get_by_role("button", name="Record movement")).to_be_visible()
    page.fill('input[name="amount"]', "50.00")
    page.get_by_role("button", name="Record movement").click()
    expect(page.get_by_text("Cash movement recorded")).to_be_visible()


def test_reports_generate_pl(e2e_server, page, setup_app, unlock):
    base = e2e_server.base_url
    setup_app("E2E Property")
    unlock()
    page.goto(base + "/reports?tab=generate")
    expect(page.get_by_text("Run report").first).to_be_visible()
    page.select_option('select[name="kind"]', "pl")
    page.get_by_role("button", name="Generate").click()
    page.wait_for_load_state("networkidle")
    expect(page.get_by_text("Report generated")).to_be_visible()
