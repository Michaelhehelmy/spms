"""tests/e2e/test_reports_extended.py — reports: analytics export, invoices list (app issue #42).

Covers: analytics export from the Reports page, and the Reports "Invoices"
list showing a generated reservation invoice.
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


def test_reports_analytics_export_flow(e2e_server, page, setup_app, unlock):
    base = e2e_server.base_url
    setup_app("E2E Property")
    unlock()
    page.goto(base + "/reports?tab=generate")
    page.get_by_role("button", name="Export (JSON/TXT/CSV as configured)").click()
    page.wait_for_load_state("networkidle", timeout=15000)
    expect(page.get_by_text(re.compile(r"Analytics export created:"))).to_be_visible()


def test_reports_exports_list_shows_invoice(e2e_server, page, setup_app, unlock):
    base = e2e_server.base_url
    setup_app("E2E Property")
    unlock()
    # Create a reservation and generate its invoice on the detail page.
    page.goto(base + "/reservations?tab=create")
    page.fill('input[name="guest_name"]', "Reports Guest")
    page.select_option("select[name=room_id]", index=0)
    page.fill("input[name=check_in]", _today())
    page.fill("input[name=check_out]", _tomorrow())
    page.fill('input[name="rate"]', "100")
    page.get_by_role("button", name="Create reservation").click()
    page.wait_for_url(lambda u: "/reservations" in u)
    page.wait_for_load_state("networkidle", timeout=15000)
    page.locator('a[href^="/reservations/"]:not([href$="/reservations/groups"])').first.click()
    page.wait_for_load_state("networkidle", timeout=15000)
    invoice_responses: list = []
    page.on("response", lambda r: invoice_responses.append(r) if r.url.startswith(base + "/files/invoice/") else None)
    page.get_by_role("button", name="Generate invoice").click()
    page.wait_for_load_state("networkidle", timeout=15000)
    assert invoice_responses and invoice_responses[0].status == 200
    invoice_name = invoice_responses[0].url.split("/files/invoice/")[-1]
    # The invoice is listed on the Reports page.
    page.goto(base + "/reports")
    expect(page.get_by_text(invoice_name).first).to_be_visible()
