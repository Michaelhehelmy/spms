"""Accounting flows."""
from __future__ import annotations

import re

from playwright.sync_api import expect

from conftest import TEST_PASSWORD
from .common import assert_url_contains, click_link, ensure_demo_ready, maybe_caption, nav_click


def open_tab(page, base: str, tab: str, label: str):
    nav_click(page, "/accounting", "Accounting")
    subtab = page.locator(f'.subtabs a[href*="tab={tab}"]').first
    expect(subtab).to_be_visible()
    subtab.click()
    page.wait_for_load_state("domcontentloaded")
    ensure_demo_ready(page)
    assert_url_contains(page, f"tab={tab}")
    maybe_caption(page, f"Sub-tab: Accounting {label}", duration=1.0)


def record_expense(page, *, param: str = "Story supplies", amount: str = "35.00", vat: str = "0"):
    maybe_caption(page, "Action: record expense", duration=1.2)
    form = page.locator('form[action="/accounting/expense"]').first
    # pick first category
    form.locator('input[name="param"]').fill(param)
    form.locator('input[name="amount"]').fill(amount)
    form.locator('input[name="vat"]').fill(vat)
    form.get_by_role("button", name="Record expense").click()
    page.wait_for_load_state("domcontentloaded")
    ensure_demo_ready(page)
    expect(page.get_by_text("Expense recorded").first).to_be_visible()


def record_walkin_payment(page, *, amount: str = "20.00", method: str = "Cash"):
    maybe_caption(page, "Action: record walk-in payment", duration=1.2)
    form = page.locator('form[action="/accounting/payment"]').first
    form.locator('input[name="amount"]').fill(amount)
    form.locator('select[name="method"]').select_option(method)
    form.get_by_role("button", name="Record payment").click()
    page.wait_for_load_state("domcontentloaded")
    ensure_demo_ready(page)
    expect(page.get_by_text("Payment recorded").first).to_be_visible()


def open_shift(page, *, name: str = "Story Shift", opening_float: str = "100"):
    maybe_caption(page, "Action: open cash shift", duration=1.2)
    form = page.locator('form[action="/accounting/shifts/open"]').first
    form.locator('input[name="name"]').fill(name)
    form.locator('input[name="opening_float"]').fill(opening_float)
    form.get_by_role("button", name="Open shift").click()
    page.wait_for_load_state("domcontentloaded")
    ensure_demo_ready(page)
    expect(page.get_by_text("Cash shift opened").first).to_be_visible()


def run_night_audit(page):
    maybe_caption(page, "Action: run advisory night audit snapshot", duration=1.2)
    form = page.locator('form[action="/accounting/night-audit/run"]').first
    form.get_by_role("button", name="Run & record snapshot").click()
    page.wait_for_load_state("domcontentloaded")
    ensure_demo_ready(page)
    expect(page.get_by_text(re.compile(r"Night audit snapshot recorded", re.I)).first).to_be_visible()
