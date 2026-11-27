"""tests/e2e/test_reservations.py — reservations create/detail/folio flows (app issue #42).

Covers: create reservation via UI form, reservation detail page + folio,
check-in/check-out buttons, record payment, and the "Get pricing quote" flow.
"""
from __future__ import annotations

import pytest

from datetime import datetime, timedelta
import re

pytest.importorskip("playwright")
from playwright.sync_api import expect


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _tomorrow() -> str:
    return (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")


def _fill_create_form(page, base, guest_name: str):
    page.goto(base + "/reservations?tab=create")
    expect(page.get_by_role("button", name="Create reservation")).to_be_visible()
    page.fill('input[name="guest_name"]', guest_name)
    page.select_option("select[name=room_id]", index=0)
    page.fill("input[name=check_in]", _today())
    page.fill("input[name=check_out]", _tomorrow())
    page.fill('input[name="rate"]', "100")


def test_create_reservation_flow(e2e_server, page, setup_app, unlock):
    base = e2e_server.base_url
    setup_app("E2E Property")
    unlock()
    _fill_create_form(page, base, "Alice Example")
    page.get_by_role("button", name="Create reservation").click()
    page.wait_for_url(lambda u: "/reservations" in u)
    page.wait_for_load_state("networkidle", timeout=15000)
    expect(page.get_by_text("Alice Example").first).to_be_visible()


def test_reservation_detail_page_loads(e2e_server, page, setup_app, unlock):
    base = e2e_server.base_url
    setup_app("E2E Property")
    unlock()
    _fill_create_form(page, base, "Bob Detail Guest")
    page.get_by_role("button", name="Create reservation").click()
    page.wait_for_url(lambda u: "/reservations" in u)
    page.wait_for_load_state("networkidle", timeout=15000)
    # Open the reservation detail page via the list row link.
    page.locator('a[href^="/reservations/"]:not([href$="/reservations/groups"])').first.click()
    page.wait_for_load_state("networkidle", timeout=15000)
    assert "/reservations/" in page.url and page.url != f"{base}/reservations?tab=list"
    expect(page.get_by_role("heading", name="Reservation #")).to_be_visible()
    expect(page.get_by_role("heading", name="Folio", exact=True)).to_be_visible()
    expect(page.get_by_role("button", name="Check in")).to_be_visible()
    expect(page.get_by_role("button", name="Check out")).to_be_visible()
    expect(page.get_by_role("button", name="Record payment")).to_be_visible()


def test_record_payment_via_ui(e2e_server, page, setup_app, unlock):
    base = e2e_server.base_url
    setup_app("E2E Property")
    unlock()
    _fill_create_form(page, base, "Carol Payer Guest")
    page.get_by_role("button", name="Create reservation").click()
    page.wait_for_url(lambda u: "/reservations" in u)
    page.locator('a[href^="/reservations/"]:not([href$="/reservations/groups"])').first.click()
    page.wait_for_load_state("networkidle", timeout=15000)
    page.fill('#pay_amount', "42.00")
    page.get_by_role("button", name="Record payment").click()
    page.wait_for_load_state("networkidle", timeout=15000)
    expect(page.get_by_text("Payment recorded", exact=False).first).to_be_visible()
    assert "/reservations/" in page.url


def test_get_pricing_quote_flow(e2e_server, page, setup_app, unlock):
    base = e2e_server.base_url
    setup_app("E2E Property")
    unlock()
    page.goto(base + "/reservations?tab=create")
    page.fill('input[name="guest_name"]', "Quote Guest")
    page.select_option("select[name=room_id]", index=0)
    page.fill("input[name=check_in]", _today())
    page.fill("input[name=check_out]", _tomorrow())
    page.fill('input[name="rate"]', "120")
    page.get_by_role("button", name="Get pricing quote").click()
    page.wait_for_load_state("networkidle", timeout=15000)
    assert "quote=1" in page.url
    expect(page.get_by_role("heading", name="Pricing quote (suggested)")).to_be_visible()
    expect(page.get_by_text("Suggested nightly").first).to_be_visible()


def test_checkin_checkout_via_detail(e2e_server, page, setup_app, unlock):
    base = e2e_server.base_url
    setup_app("E2E Property")
    unlock()
    _fill_create_form(page, base, "Checkin Guest")
    page.get_by_role("button", name="Create reservation").click()
    page.wait_for_url(lambda u: "/reservations" in u)
    page.wait_for_load_state("networkidle", timeout=15000)
    page.locator('a[href^="/reservations/"]:not([href$="/reservations/groups"])').first.click()
    page.wait_for_load_state("networkidle", timeout=15000)
    assert "/reservations/" in page.url and page.url != f"{base}/reservations?tab=list"
    expect(page.get_by_role("button", name="Check in")).to_be_visible()
    page.get_by_role("button", name="Check in").click()
    page.wait_for_load_state("networkidle", timeout=15000)
    expect(page.get_by_text("Checked in").first).to_be_visible()
    expect(page.get_by_role("button", name="Check out")).to_be_visible()


def _open_new_reservation(page, base, guest_name):
    _fill_create_form(page, base, guest_name)
    page.get_by_role("button", name="Create reservation").click()
    page.wait_for_url(lambda u: "/reservations" in u)
    page.wait_for_load_state("networkidle", timeout=15000)
    detail_link = page.locator('a[href^="/reservations/"]:not([href$="/reservations/groups"])').first
    rid = int(detail_link.get_attribute("href").split("/reservations/")[-1])
    detail_link.click()
    page.wait_for_load_state("networkidle", timeout=15000)
    assert "/reservations/" in page.url
    return rid


def test_groups_create_flow(e2e_server, page, setup_app, unlock):
    base = e2e_server.base_url
    setup_app("E2E Property")
    unlock()
    page.goto(base + "/reservations/groups")
    expect(page.get_by_role("heading", name="Reservation Groups")).to_be_visible()
    expect(page.get_by_role("heading", name="Create group")).to_be_visible()
    page.fill('input[name="name"]', "E2E Group Alpha")
    page.get_by_role("button", name="Create group").click()
    page.wait_for_load_state("networkidle", timeout=15000)
    expect(page.get_by_text(re.compile(r"Group #\d+ created"))).to_be_visible()


def test_group_add_reservation_flow(e2e_server, page, setup_app, unlock):
    base = e2e_server.base_url
    setup_app("E2E Property")
    unlock()
    rid = _open_new_reservation(page, base, "Grouped Guest")
    # Create the group.
    page.goto(base + "/reservations/groups")
    page.fill('input[name="name"]', "E2E Group Beta")
    page.get_by_role("button", name="Create group").click()
    page.wait_for_load_state("networkidle", timeout=15000)
    # Add the reservation to the group via the add form.
    page.select_option('select[name="group_id"]', index=0)
    page.select_option('select[name="reservation_id"]', value=str(rid))
    page.get_by_role("button", name="Add to group").click()
    page.wait_for_load_state("networkidle", timeout=15000)
    expect(page.get_by_text("Reservation added to group")).to_be_visible()


def test_invoice_generation_via_detail(e2e_server, page, setup_app, unlock):
    base = e2e_server.base_url
    setup_app("E2E Property")
    unlock()
    _open_new_reservation(page, base, "Invoice Guest")
    expect(page.get_by_role("button", name="Generate invoice")).to_be_visible()
    invoice_responses: list = []
    page.on("response", lambda r: invoice_responses.append(r) if r.url.startswith(base + "/files/invoice/") else None)
    page.get_by_role("button", name="Generate invoice").click()
    page.wait_for_load_state("networkidle", timeout=15000)
    assert invoice_responses and invoice_responses[0].status == 200
