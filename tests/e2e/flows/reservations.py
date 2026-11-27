"""Reservation flows."""
from __future__ import annotations

import re
from datetime import datetime, timedelta

from playwright.sync_api import expect

from conftest import TEST_PASSWORD
from .common import (
    assert_url_contains,
    click_button,
    click_link,
    ensure_demo_ready,
    maybe_caption,
    nav_click,
    select_option,
    set_date,
    type_into,
)


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _tomorrow() -> str:
    return (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")


def open_list(page, base: str):
    nav_click(page, "/reservations", "Reservations")
    click_link(page, "List")
    page.wait_for_load_state("domcontentloaded")
    ensure_demo_ready(page)
    assert_url_contains(page, "/reservations")
    expect(page.locator('.subtabs a.active', has_text='List').first).to_be_visible()
    maybe_caption(page, "Sub-tab: Reservations list", duration=1.0)


def open_create(page, base: str):
    nav_click(page, "/reservations", "Reservations")
    click_link(page, "Create")
    page.wait_for_load_state("domcontentloaded")
    ensure_demo_ready(page)
    assert_url_contains(page, "tab=create")
    expect(page.locator('input[name="guest_name"]')).to_be_visible()
    maybe_caption(page, "Sub-tab: Reservations create", duration=1.0)


def quote_create(page, *, guest_name: str, check_in: str | None = None, check_out: str | None = None, rate: str = "120", room_index: int = 0):
    maybe_caption(page, "Action: get pricing quote on create form", duration=1.5)
    type_into(page, 'input[name="guest_name"]', guest_name)
    select_option(page, 'select[name="room_id"]', index=room_index)
    set_date(page, 'input[name="check_in"]', check_in or _today())
    set_date(page, 'input[name="check_out"]', check_out or _tomorrow())
    type_into(page, 'input[name="rate"]', rate)
    form = page.locator('form[action="/reservations/create"]').first
    form.get_by_role("button", name="Get pricing quote").click()
    page.wait_for_load_state("domcontentloaded")
    ensure_demo_ready(page)
    expect(page.get_by_text("Pricing quote (suggested)").first).to_be_visible()
    expect(page.locator('input[name="guest_name"]')).to_have_value(guest_name)


def create_from_form(page, *, guest_name: str, check_in: str | None = None, check_out: str | None = None, rate: str = "120", source: str = "Direct", room_index: int = 0):
    maybe_caption(page, f"Action: create reservation for {guest_name}", duration=1.5)
    form = page.locator('form[action="/reservations/create"]').first
    form.locator('input[name="guest_name"]').fill(guest_name)
    select_option(page, 'select[name="room_id"]', index=room_index)
    set_date(page, 'input[name="check_in"]', check_in or _today())
    set_date(page, 'input[name="check_out"]', check_out or _tomorrow())
    type_into(page, 'input[name="rate"]', rate)
    type_into(page, 'input[name="source"]', source)
    form.get_by_role("button", name="Create reservation").click()
    page.wait_for_load_state("domcontentloaded")
    ensure_demo_ready(page)
    expect(page.get_by_text(re.compile(r"Reservation #\d+ created")).first).to_be_visible()


def search_list(page, q: str = "", source: str = "", segment: str = ""):
    maybe_caption(page, "Action: search/filter reservations list", duration=1.2)
    if q:
        type_into(page, 'input[name="q"]', q)
    if source:
        type_into(page, 'input[name="source"]', source)
    if segment:
        type_into(page, 'input[name="segment"]', segment)
    click_button(page, "Search")
    page.wait_for_load_state("domcontentloaded")
    ensure_demo_ready(page)


def open_detail_from_list(page, guest_name: str):
    maybe_caption(page, f"Action: open reservation detail for {guest_name}", duration=1.2)
    row = page.locator("tr", has_text=guest_name).first
    expect(row).to_be_visible()
    row.locator('a[href*="/reservations/"]').first.click()
    page.wait_for_load_state("domcontentloaded")
    ensure_demo_ready(page)
    assert_url_contains(page, "/reservations/")
    expect(page.get_by_role("heading", name=re.compile(r"Reservation #\d+")).first).to_be_visible()


def detail_checkin(page):
    maybe_caption(page, "Action: check in reservation", duration=1.0)
    page.locator('form[action$="/checkin"]').first.get_by_role("button", name="Check in").click()
    page.wait_for_load_state("domcontentloaded")
    ensure_demo_ready(page)
    expect(page.get_by_text("Checked in").first).to_be_visible()


def detail_checkout(page):
    maybe_caption(page, "Action: check out reservation", duration=1.0)
    page.locator('form[action$="/checkout"]').first.get_by_role("button", name="Check out").click()
    page.wait_for_load_state("domcontentloaded")
    ensure_demo_ready(page)
    expect(page.get_by_text(re.compile(r"Checked out|Unpaid balance")).first).to_be_visible()


def record_payment(page, amount: str, *, method: str = "Cash", payment_type: str = "Payment"):
    maybe_caption(page, f"Action: record {payment_type.lower()} {amount}", duration=1.2)
    pay_form = page.locator('form[action$="/pay"]').first
    pay_form.locator('input[name="amount"]').fill(amount)
    pay_form.locator('select[name="method"]').select_option(method)
    pay_form.locator('select[name="payment_type"]').select_option(payment_type)
    pay_form.get_by_role("button", name="Record payment").click()
    page.wait_for_load_state("domcontentloaded")
    ensure_demo_ready(page)
    expect(page.get_by_text(re.compile(r"Payment recorded|payment", re.I)).first).to_be_visible()


def pay_full_balance(page):
    maybe_caption(page, "Action: pay full balance", duration=1.2)
    pay_form = page.locator('form[action$="/pay"]').first
    full_btn = pay_form.get_by_role("button", name="Pay full balance")
    if full_btn.count() > 0:
        full_btn.first.click()
        page.wait_for_timeout(200)
    pay_form.get_by_role("button", name="Record payment").click()
    page.wait_for_load_state("domcontentloaded")
    ensure_demo_ready(page)
    expect(page.get_by_text(re.compile(r"Payment recorded|payment", re.I)).first).to_be_visible()


def generate_invoice(page):
    maybe_caption(page, "Action: generate invoice", duration=1.2)
    page.locator('form[action$="/invoice"]').first.get_by_role("button", name="Generate invoice").click()
    page.wait_for_load_state("domcontentloaded")
    ensure_demo_ready(page)
    expect(page.get_by_text(re.compile(r"Invoice|generated", re.I)).first).to_be_visible()


def add_extra_service(page, description: str, qty: str = "1", price: str = "25"):
    maybe_caption(page, "Action: add extra service", duration=1.2)
    panel = page.locator('#services')
    panel.locator('summary', has_text='Add extra service').click()
    page.wait_for_timeout(200)
    form = panel.locator('form[action$="/services/add"]').first
    form.locator('input[name="description"]').fill(description)
    form.locator('input[name="quantity"]').fill(qty)
    form.locator('input[name="unit_price"]').fill(price)
    form.get_by_role("button", name="Add service").click()
    page.wait_for_load_state("domcontentloaded")
    ensure_demo_ready(page)
    expect(page.get_by_text(re.compile(r"Service added|added", re.I)).first).to_be_visible()


def apply_discount(page, description: str, dtype: str = "amount", value: str = "10"):
    maybe_caption(page, "Action: apply discount", duration=1.2)
    panel = page.locator('#discounts')
    panel.locator('summary', has_text='Apply discount / voucher').click()
    page.wait_for_timeout(200)
    form = panel.locator('form[action$="/discounts/apply"]').first
    form.locator('select[name="discount_type"]').select_option(dtype)
    form.locator('input[name="value"]').fill(value)
    form.locator('input[name="description"]').fill(description)
    form.get_by_role("button", name="Apply discount").click()
    page.wait_for_load_state("domcontentloaded")
    ensure_demo_ready(page)
    expect(page.get_by_text(re.compile(r"Discount applied|applied", re.I)).first).to_be_visible()


def open_groups(page, base: str):
    nav_click(page, "/reservations", "Reservations")
    click_link(page, "Groups")
    page.wait_for_load_state("domcontentloaded")
    ensure_demo_ready(page)
    assert_url_contains(page, "/reservations/groups")
    expect(page.get_by_role("heading", name="Reservation Groups").first).to_be_visible()
    maybe_caption(page, "Sub-tab: Reservation groups", duration=1.0)


def create_group(page, name: str, group_type: str = "group", contact: str = "Coordinator"):
    maybe_caption(page, f"Action: create reservation group '{name}'", duration=1.2)
    form = page.locator('form[action="/reservations/groups/create"]').first
    form.locator('input[name="name"]').fill(name)
    form.locator('input[name="group_type"]').fill(group_type)
    form.locator('input[name="contact_name"]').fill(contact)
    form.get_by_role("button", name="Create group").click()
    page.wait_for_load_state("domcontentloaded")
    ensure_demo_ready(page)
    expect(page.get_by_text(re.compile(r"Group #\d+ created")).first).to_be_visible()


def add_reservation_to_group(page, group_name: str, guest_name: str):
    maybe_caption(page, f"Action: add {guest_name} to group {group_name}", duration=1.2)
    form = page.locator('#add-group-form').first
    grp_sel = form.locator('select[name="group_id"]')
    grp_options = grp_sel.locator('option')
    grp_target = None
    for i in range(grp_options.count()):
        txt = grp_options.nth(i).inner_text()
        if group_name in txt:
            grp_target = grp_options.nth(i).get_attribute('value')
            break
    if grp_target:
        grp_sel.select_option(grp_target)
    # select reservation by guest name in option label
    res_sel = form.locator('select[name="reservation_id"]')
    options = res_sel.locator('option')
    target = None
    for i in range(options.count()):
        txt = options.nth(i).inner_text()
        if guest_name in txt:
            target = options.nth(i).get_attribute('value')
            break
    if target:
        res_sel.select_option(target)
    form.get_by_role("button", name="Add to group").click()
    page.wait_for_load_state("domcontentloaded")
    ensure_demo_ready(page)
    expect(page.get_by_text("Reservation added to group").first).to_be_visible()


def open_group_folio(page, group_name: str):
    maybe_caption(page, f"Action: open group folio for {group_name}", duration=1.2)
    details = page.locator('details', has_text=group_name).first
    expect(details).to_be_visible()
    if not details.evaluate('el => el.open'):
        details.locator('summary').first.click()
        page.wait_for_timeout(200)
    with page.expect_popup() as pop:
        details.get_by_role("link", name="View group folio/report").first.click()
    folio_page = pop.value
    folio_page.wait_for_load_state("domcontentloaded")
    expect(folio_page.get_by_text(re.compile(r"Group Folio|group", re.I)).first).to_be_visible()
    maybe_caption(page, "Result: group folio/report opened", duration=1.0)
    return folio_page


def modify_reservation(page, *, rate: str = "150", password: str = TEST_PASSWORD):
    maybe_caption(page, "Action: modify reservation rate/details", duration=1.2)
    form = page.locator('form[action$="/modify"]').first
    details = form.locator('xpath=ancestor::details[1]')
    if details.count() > 0 and not details.evaluate('el => el.open'):
        details.locator('summary').first.click()
        page.wait_for_timeout(200)
    form.locator('input[name="rate"]').fill(rate)
    pw = form.locator('input[name="password"]')
    if pw.count() > 0:
        pw.fill(password)
    form.get_by_role("button", name="Modify", exact=True).click()
    page.wait_for_load_state("domcontentloaded")
    ensure_demo_ready(page)
    expect(page.get_by_text(re.compile(r"Reservation modified", re.I)).first).to_be_visible()


def cancel_reservation(page, password: str = TEST_PASSWORD):
    maybe_caption(page, "Action: cancel reservation (policy/password as required)", duration=1.2)
    details = page.locator('details', has_text='Cancel / No-show / Delete').first
    if not details.evaluate('el => el.open'):
        details.locator('summary').first.click()
        page.wait_for_timeout(200)
    form = details.locator('form[action$="/cancel"]').first
    pw = form.locator('input[name="password"]')
    if pw.count() > 0:
        pw.fill(password)
    form.get_by_role("button", name="Cancel", exact=True).click()
    page.wait_for_load_state("domcontentloaded")
    ensure_demo_ready(page)
    expect(page.get_by_text(re.compile(r"Cancelled", re.I)).first).to_be_visible()


def refund_payment(page, amount: str, password: str = TEST_PASSWORD):
    maybe_caption(page, f"Action: refund {amount} (super password)", duration=1.2)
    details = page.locator('details', has_text='Refund (password)').first
    if not details.evaluate('el => el.open'):
        details.locator('summary').first.click()
        page.wait_for_timeout(200)
    form = details.locator('form[action$="/refund"]').first
    form.locator('input[name="amount"]').fill(amount)
    form.locator('input[name="password"]').fill(password)
    form.get_by_role("button", name="Refund", exact=True).click()
    page.wait_for_load_state("domcontentloaded")
    ensure_demo_ready(page)
    expect(page.get_by_text(re.compile(r"Refund recorded|refund", re.I)).first).to_be_visible()


def noshow_reservation(page, password: str = TEST_PASSWORD):
    maybe_caption(page, "Action: mark reservation no-show", duration=1.2)
    details = page.locator('details', has_text='Cancel / No-show / Delete').first
    if not details.evaluate('el => el.open'):
        details.locator('summary').first.click()
        page.wait_for_timeout(200)
    form = details.locator('form[action$="/noshow"]').first
    pw = form.locator('input[name="password"]')
    if pw.count() > 0:
        pw.fill(password)
    form.get_by_role("button", name="No-show", exact=True).click()
    page.wait_for_load_state("domcontentloaded")
    ensure_demo_ready(page)
    expect(page.get_by_text(re.compile(r"Marked no-show|no-show", re.I)).first).to_be_visible()


def delete_reservation(page, password: str = TEST_PASSWORD):
    maybe_caption(page, "Action: delete reservation (if permitted)", duration=1.2)
    details = page.locator('details', has_text='Cancel / No-show / Delete').first
    if not details.evaluate('el => el.open'):
        details.locator('summary').first.click()
        page.wait_for_timeout(200)
    form = details.locator('form[action$="/delete"]').first
    pw = form.locator('input[name="password"]')
    if pw.count() > 0:
        pw.fill(password)
    form.get_by_role("button", name="Delete", exact=True).click()
    page.wait_for_load_state("domcontentloaded")
    ensure_demo_ready(page)
    expect(page.get_by_text(re.compile(r"Deleted", re.I)).first).to_be_visible()


def void_first_payment(page, password: str = TEST_PASSWORD):
    maybe_caption(page, "Action: void a payment/refund line (super password)", duration=1.2)
    form = page.locator('form[action*="/payments/"][action$="/void"]').first
    expect(form).to_be_visible()
    form.locator('input[name="password"]').fill(password)
    form.get_by_role("button", name="Void", exact=True).click()
    page.wait_for_load_state("domcontentloaded")
    ensure_demo_ready(page)
    expect(page.get_by_text(re.compile(r"Payment/refund voided|voided", re.I)).first).to_be_visible()


def add_pos_charge(page, desc: str, qty: str = "1", price: str = "15.00"):
    maybe_caption(page, f"Action: add POS charge '{desc}'", duration=1.2)
    panel = page.locator('details', has_text='Add POS / inventory charge').first
    if not panel.evaluate('el => el.open'):
        panel.locator('summary').first.click()
        page.wait_for_timeout(200)
    form = panel.locator('form[action="/pos/add"]').first
    form.locator('input[name="desc"]').fill(desc)
    form.locator('input[name="qty"]').fill(qty)
    form.locator('input[name="price"]').fill(price)
    form.get_by_role("button", name="Add POS charge").click()
    page.wait_for_load_state("domcontentloaded")
    ensure_demo_ready(page)
    expect(page.get_by_text(re.compile(r"POS charge added|added", re.I)).first).to_be_visible()
    expect(page.get_by_text(desc).first).to_be_visible()


def void_first_pos_line(page, password: str = TEST_PASSWORD):
    maybe_caption(page, "Action: void POS/charge line (super password)", duration=1.2)
    form = page.locator('form[action^="/pos/void/"]').first
    expect(form).to_be_visible()
    form.locator('input[name="password"]').fill(password)
    form.get_by_role("button", name="Void", exact=True).click()
    page.wait_for_load_state("domcontentloaded")
    ensure_demo_ready(page)
    expect(page.get_by_text(re.compile(r"voided|Voided", re.I)).first).to_be_visible()


def book_activity(page, activity_name: str, qty: str = "1"):
    maybe_caption(page, f"Action: book activity '{activity_name}'", duration=1.2)
    panel = page.locator('details', has_text='Book activity / trip (registered)').first
    if not panel.evaluate('el => el.open'):
        panel.locator('summary').first.click()
        page.wait_for_timeout(200)
    form = panel.locator('form[action$="/book-activity"]').first
    sel = form.locator('select[name="activity_id"]')
    options = sel.locator('option')
    target = None
    for i in range(options.count()):
        txt = options.nth(i).inner_text()
        if activity_name in txt:
            target = options.nth(i).get_attribute('value')
            break
    if target:
        sel.select_option(target)
    form.locator('input[name="qty"]').fill(qty)
    form.get_by_role("button", name=re.compile(r"Book / order activity", re.I)).click()
    page.wait_for_load_state("domcontentloaded")
    ensure_demo_ready(page)
    expect(page.get_by_text(re.compile(r"Activity booked|booked", re.I)).first).to_be_visible()


def apply_package(page, package_name: str = None):
    maybe_caption(page, "Action: apply package to reservation", duration=1.2)
    panel = page.locator('#packages')
    panel.locator('summary', has_text='Apply package').click()
    page.wait_for_timeout(200)
    form = panel.locator('form[action$="/packages/apply"]').first
    if package_name:
        sel = form.locator('select[name="package_id"]')
        opts = sel.locator('option')
        for i in range(opts.count()):
            if package_name in opts.nth(i).inner_text():
                sel.select_option(opts.nth(i).get_attribute('value'))
                break
    form.get_by_role("button", name="Apply package").click()
    page.wait_for_load_state("domcontentloaded")
    ensure_demo_ready(page)
    expect(page.get_by_text(re.compile(r"Package applied", re.I)).first).to_be_visible()


def void_first_package(page, password: str = TEST_PASSWORD):
    maybe_caption(page, "Action: void applied package", duration=1.2)
    form = page.locator('form[action*="/packages/"][action$="/void"]').first
    expect(form).to_be_visible()
    form.locator('input[name="password"]').fill(password)
    form.get_by_role("button", name="Void", exact=True).click()
    page.wait_for_load_state("domcontentloaded")
    ensure_demo_ready(page)
    expect(page.get_by_text(re.compile(r"Applied package voided|voided", re.I)).first).to_be_visible()
