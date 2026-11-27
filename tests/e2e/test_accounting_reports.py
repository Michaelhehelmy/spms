"""tests/e2e/test_accounting_reports.py — accounting + reports (app issue #42).

Covers: accounting page loads; record expense, record payment, open shift +
record shift movement via the UI; run P&L report from the Reports page.
"""
from __future__ import annotations

import pytest

import re
from datetime import datetime, timedelta

pytest.importorskip("playwright")
from playwright.sync_api import expect


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _tomorrow() -> str:
    return (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")


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
    expect(page.get_by_text("Report generated")).to_be_visible(timeout=15000)


def test_accounting_refund_flow(e2e_server, page, setup_app, unlock, password):
    base = e2e_server.base_url
    setup_app("E2E Property")
    unlock()
    # Create a reservation and record a payment so there is a balance to refund.
    page.goto(base + "/reservations?tab=create")
    page.fill('input[name="guest_name"]', "Refund Guest")
    page.select_option("select[name=room_id]", index=0)
    page.fill("input[name=check_in]", _today())
    page.fill("input[name=check_out]", _tomorrow())
    page.fill('input[name="rate"]', "100")
    page.get_by_role("button", name="Create reservation").click()
    page.wait_for_url(lambda u: "/reservations" in u)
    page.wait_for_load_state("networkidle", timeout=15000)
    detail_link = page.locator('a[href^="/reservations/"]:not([href$="/reservations/groups"])').first
    rid = int(detail_link.get_attribute("href").split("/reservations/")[-1])
    detail_link.click()
    page.wait_for_load_state("networkidle", timeout=15000)
    assert page.url == f"{base}/reservations/{rid}"
    page.fill('#pay_amount', "40.00")
    page.get_by_role("button", name="Record payment").click()
    page.wait_for_load_state("networkidle", timeout=15000)
    # Refund 10 via the accounting page.
    page.goto(base + "/accounting?tab=payments")
    form = page.locator('form[action="/accounting/refund"]')
    form.locator('input[name="reservation_id"]').fill(str(rid))
    form.locator('input[name="amount"]').fill("10.00")
    form.locator('input[type="password"]').fill(password)
    page.get_by_role("button", name="Refund").click()
    page.wait_for_load_state("networkidle", timeout=15000)
    expect(page.get_by_text("Refund recorded")).to_be_visible()


def test_accounting_void_expense(e2e_server, page, setup_app, unlock, seed_expense_category, password):
    base = e2e_server.base_url
    setup_app("E2E Property")
    unlock()
    seed_expense_category("E2E Expense")
    page.goto(base + "/accounting?tab=expenses")
    page.fill('input[name="param"]', "E2E Expense Void")
    page.fill('input[name="amount"]', "10.00")
    page.select_option('select[name="cat_id"]', index=0)
    page.get_by_role("button", name="Record expense").click()
    page.wait_for_load_state("networkidle", timeout=15000)
    expect(page.get_by_text("Expense recorded")).to_be_visible()
    # Void the recorded expense.
    form = page.locator('form[action^="/accounting/expense/"][action$="/void"]').first
    form.locator('input[name="password"]').fill(password)
    form.get_by_role("button", name="Void").click()
    page.wait_for_load_state("networkidle", timeout=15000)
    expect(page.get_by_text("Expense voided").first).to_be_visible()


def test_accounting_run_night_audit(e2e_server, page, setup_app, unlock):
    base = e2e_server.base_url
    setup_app("E2E Property")
    unlock()
    page.goto(base + "/accounting?tab=night_audit")
    page.get_by_role("button", name="Run & record snapshot").click()
    page.wait_for_load_state("networkidle", timeout=15000)
    expect(page.get_by_text("Night audit snapshot recorded (advisory)")).to_be_visible()


def test_accounting_ledger_tab(e2e_server, page, setup_app, unlock):
    base = e2e_server.base_url
    setup_app("E2E Property")
    unlock()
    page.goto(base + "/accounting?tab=ledger")
    expect(page.get_by_role("heading", name="Recent ledger")).to_be_visible()
