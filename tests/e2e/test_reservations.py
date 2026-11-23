"""tests/e2e/test_reservations.py — reservations create/detail/folio flows (app issue #42).

Covers: create reservation via UI form, reservation detail page + folio,
check-in/check-out buttons, record payment, and the "Get pricing quote" flow.
"""
from __future__ import annotations

from datetime import datetime, timedelta

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
    page.wait_for_load_state("networkidle")
    expect(page.get_by_text("Alice Example").first).to_be_visible()


def test_reservation_detail_page_loads(e2e_server, page, setup_app, unlock):
    base = e2e_server.base_url
    setup_app("E2E Property")
    unlock()
    _fill_create_form(page, base, "Bob Detail Guest")
    page.get_by_role("button", name="Create reservation").click()
    page.wait_for_url(lambda u: "/reservations" in u)
    page.wait_for_load_state("networkidle")
    # Open the reservation detail page via the list row link.
    page.locator('a[href^="/reservations/"]:not([href$="/reservations/groups"])').first.click()
    page.wait_for_load_state("networkidle")
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
    page.wait_for_load_state("networkidle")
    page.fill('#pay_amount', "42.00")
    page.get_by_role("button", name="Record payment").click()
    page.wait_for_load_state("networkidle")
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
    page.wait_for_load_state("networkidle")
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
    page.wait_for_load_state("networkidle")
    page.locator('a[href^="/reservations/"]:not([href$="/reservations/groups"])').first.click()
    page.wait_for_load_state("networkidle")
    assert "/reservations/" in page.url and page.url != f"{base}/reservations?tab=list"
    expect(page.get_by_role("button", name="Check in")).to_be_visible()
    page.get_by_role("button", name="Check in").click()
    page.wait_for_load_state("networkidle")
    expect(page.get_by_text("Checked in").first).to_be_visible()
    expect(page.get_by_role("button", name="Check out")).to_be_visible()
