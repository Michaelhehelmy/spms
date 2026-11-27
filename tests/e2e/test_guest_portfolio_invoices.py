"""tests/e2e/test_guest_portfolio_invoices.py — guest portfolio invoices (app issue #42).

Covers: the guest portfolio (360° view) lists saved invoice files per stay.
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


def test_portfolio_shows_invoice_files(e2e_server, page, setup_app, unlock, seed_guest):
    base = e2e_server.base_url
    setup_app("E2E Property")
    unlock()
    gid = seed_guest("Portfolio Guest")
    # Create a reservation for the guest and generate its invoice.
    page.goto(base + "/reservations?tab=create")
    page.fill('input[name="guest_name"]', "Portfolio Guest")
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
    invoice_name = re.sub(r"[^\w.-]", "_", invoice_responses[0].url.split("/files/invoice/")[-1])
    # The invoice is listed in the guest's portfolio Invoices section.
    page.goto(base + f"/guests/{gid}")
    expect(page.get_by_text("Invoices").first).to_be_visible()
    expect(page.get_by_text(invoice_name).first).to_be_visible()
