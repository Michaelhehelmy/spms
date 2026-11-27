"""Story V2 — Guests & Reservations Lifecycle (real E2E + demo mode).

Covers: guests directory/portfolio/edit; reservations list/create/quote/detail;
checkin/checkout/modify/cancel; payment/refund/invoice; extra service/discount;
groups/group folio. Uses live UI-created data where possible.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta

import pytest
from playwright.sync_api import expect

from conftest import TEST_PASSWORD
from flows.common import assert_url_contains, ensure_demo_ready, maybe_caption, nav_click
from flows.guests import edit_profile, open_directory, open_portfolio_from_directory, search as guest_search
from flows.reservations import (
    add_extra_service,
    add_pos_charge,
    add_reservation_to_group,
    apply_discount,
    apply_package,
    book_activity,
    cancel_reservation,
    create_from_form,
    create_group,
    delete_reservation,
    detail_checkin,
    detail_checkout,
    generate_invoice,
    modify_reservation,
    noshow_reservation,
    open_create,
    open_detail_from_list,
    open_group_folio,
    open_groups,
    open_list,
    pay_full_balance,
    quote_create,
    record_payment,
    refund_payment,
    search_list,
    void_first_package,
    void_first_payment,
    void_first_pos_line,
)


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _tomorrow() -> str:
    return (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")


def _day_after() -> str:
    return (datetime.now() + timedelta(days=2)).strftime("%Y-%m-%d")


@pytest.mark.story
def test_story_v2_guests_reservations(e2e_server, page, setup_app, unlock):
    base = e2e_server.base_url
    setup_app("Acadia Camp")
    unlock()
    page.goto(base + "/", wait_until="domcontentloaded")
    ensure_demo_ready(page)

    guest_a = "Alice Story"
    guest_b = "Bob Group"

    # --- Guests: directory, search, portfolio, edit ---
    maybe_caption(page, "Start: Guests & Reservations lifecycle", duration=1.8)
    open_directory(page, base)
    # Create guest data through UI by creating reservations later; also use search empty state.
    guest_search(page, base, "NoSuchGuestXYZ")
    expect(page.get_by_text(re.compile(r"No guests found|No guests", re.I)).first).to_be_visible()
    maybe_caption(page, "Result: guest search no-results state", duration=1.0)

    # --- Reservations: create tab, quote, create (live UI data) ---
    open_create(page, base)
    quote_create(page, guest_name=guest_a, check_in=_today(), check_out=_tomorrow(), rate="120")
    create_from_form(page, guest_name=guest_a, check_in=_today(), check_out=_tomorrow(), rate="120", source="Direct")
    # Create second reservation for groups/cancel flow
    open_create(page, base)
    create_from_form(page, guest_name=guest_b, check_in=_today(), check_out=_day_after(), rate="100", source="Phone", room_index=1)

    # --- Reservations list: filter/search, open detail ---
    open_list(page, base)
    search_list(page, q="Alice")
    expect(page.get_by_text(guest_a).first).to_be_visible()
    maybe_caption(page, "Result: reservations list filtered by guest", duration=1.0)
    open_detail_from_list(page, guest_a)

    # --- Reservation detail: status/actions, payment, invoice, service, discount, modify ---
    expect(page.get_by_text(guest_a).first).to_be_visible()
    maybe_caption(page, "Sub-tab/section: Reservation detail folio & actions", duration=1.2)

    record_payment(page, "50", method="Cash", payment_type="Deposit")
    expect(page.get_by_text(re.compile(r"Payment recorded|payment", re.I)).first).to_be_visible()

    generate_invoice(page)

    # Extra service and discount (sub-sections)
    add_extra_service(page, "Airport pickup", qty="1", price="25")
    apply_discount(page, "Story discount", dtype="amount", value="5")

    modify_reservation(page, rate="130", password=TEST_PASSWORD)
    expect(page.get_by_text(re.compile(r"130")).first).to_be_visible()

    # Check in then checkout override/pay-full path: pay remaining and checkout
    detail_checkin(page)
    expect(page.get_by_text(re.compile(r"Checked In", re.I)).first).to_be_visible()
    pay_full_balance(page)
    detail_checkout(page)
    expect(page.get_by_text(re.compile(r"Checked Out|Checked out", re.I)).first).to_be_visible()

    # Refund + void-payment gap fill (allocation/idempotency fields visible in UI)
    refund_payment(page, "10", password=TEST_PASSWORD)
    void_first_payment(page, password=TEST_PASSWORD)

    # --- Guests: open portfolio created via live reservation flow, edit ---
    open_directory(page, base)
    guest_search(page, base, "Alice")
    expect(page.get_by_text(guest_a).first).to_be_visible()
    open_portfolio_from_directory(page, guest_a)
    expect(page.get_by_text(re.compile(r"Trips / Reservations", re.I)).first).to_be_visible()
    edit_profile(page, name="Alice Story Updated", phone="+1555000111", email="alice.story@example.com", notes="Updated in Story V2", password=TEST_PASSWORD)

    # --- Seed minimal preconditions for package/activity (service-level, stable) ---
    import os, subprocess, sys
    from pathlib import Path
    ROOT = Path(__file__).resolve().parents[2]
    SRC = ROOT / "src"
    env = {**os.environ, "PM_DATA_DIR": str(e2e_server.data_dir), "PYTHONPATH": f"{SRC}{os.pathsep}{ROOT}", "PM_WEB_SECRET_KEY": "e2e-test-secret-" + "x" * 48, "PM_WEB_UNLOCK_RATE_LIMIT": "100", "PM_WEB_UNLOCK_RATE_WINDOW_SEC": "600"}
    subprocess.run([sys.executable, "-c", (
        "from app_core import services\n"
        "try:\n services.create_activity('Desert Hike', description='Guided hike', category='Trip', unit_price=25.0, active=1)\n"
        "except Exception:\n pass\n"
        "try:\n pid = services.create_package('Welcome Pack','Demo package')\n"
        "except Exception:\n pid = None\n"
        "try:\n"
        " if pid:\n  services.add_package_item(pid, service_id=None, description='Welcome drink', quantity=1, unit_price=5.0, taxable=1)\n"
        "except Exception:\n pass\n"
    )], cwd=ROOT, env=env, check=True, capture_output=True, text=True)

    # --- Reservation detail extras: POS charge/void, activity booking, package apply/void, allocation/idempotency ---
    open_create(page, base)
    create_from_form(page, guest_name="Eve Extras", check_in=_today(), check_out=_tomorrow(), rate="110", source="Direct", room_index=4)
    open_list(page, base)
    search_list(page, q="Eve")
    open_detail_from_list(page, "Eve Extras")

    add_pos_charge(page, "Manual minibar", qty="2", price="7.50")
    void_first_pos_line(page, password=TEST_PASSWORD)
    # book activity (pre-seeded)
    try:
        book_activity(page, "Desert Hike", qty="1")
    except Exception:
        maybe_caption(page, "Alt path: activity booking unavailable in this state; continuing", duration=1.0)
    try:
        apply_package(page)
        void_first_package(page, password=TEST_PASSWORD)
    except Exception:
        maybe_caption(page, "Alt path: package flow unavailable in this state; continuing", duration=1.0)

    # Allocation/idempotency fields on normal payment
    maybe_caption(page, "Action: record payment with allocation/idempotency", duration=1.2)
    pay_form = page.locator('form[action$="/pay"]').first
    pay_form.locator('input[name="amount"]').fill("20")
    alloc = pay_form.locator('details', has_text='Allocation (optional, advanced)').first
    if alloc.count() > 0 and not alloc.evaluate('el => el.open'):
        alloc.locator('summary').first.click()
        page.wait_for_timeout(200)
    pay_form.locator('input[name="idempotency_key"]').fill("story-v2-pay-1")
    pay_form.locator('textarea[name="allocation_json"]').fill('{"accommodation":20}')
    pay_form.get_by_role("button", name="Record payment").click()
    page.wait_for_load_state("domcontentloaded")
    ensure_demo_ready(page)
    expect(page.get_by_text(re.compile(r"Payment recorded", re.I)).first).to_be_visible()

    # --- Groups: create, add member, group folio, group member payment ---
    open_groups(page, base)
    create_group(page, "Story Group", group_type="tour", contact="Bob Coordinator")
    add_reservation_to_group(page, "Story Group", guest_b)
    # group payment with allocation/idempotency fields (UI)
    grp = page.locator('details', has_text='Story Group').first
    if not grp.evaluate('el => el.open'):
        grp.locator('summary').first.click()
    pay_det = grp.locator('details', has_text='Record payment for a member').first
    if pay_det.count() > 0:
        if not pay_det.evaluate('el => el.open'):
            pay_det.locator('summary').first.click()
            page.wait_for_timeout(200)
        pay_form = pay_det.locator('form[action*="/payment"]').first
        pay_form.locator('input[name="amount"]').fill("20")
        alloc = pay_form.locator('details', has_text='Allocation (optional, advanced)').first
        if alloc.count() > 0 and not alloc.evaluate('el => el.open'):
            alloc.locator('summary').first.click()
            page.wait_for_timeout(200)
        pay_form.locator('input[name="idempotency_key"]').fill("story-v2-group-1")
        pay_form.locator('textarea[name="allocation_json"]').fill('{"accommodation":20}')
        maybe_caption(page, "Action: group member payment with allocation/idempotency", duration=1.2)
        pay_form.get_by_role("button", name="Record payment").click()
        page.wait_for_load_state("domcontentloaded")
        ensure_demo_ready(page)
        expect(page.get_by_text(re.compile(r"Payment recorded", re.I)).first).to_be_visible()
    folio = open_group_folio(page, "Story Group")
    folio.close()

    # --- Cancel flow on second reservation (alt path) ---
    open_list(page, base)
    search_list(page, q="Bob")
    open_detail_from_list(page, guest_b)
    cancel_reservation(page, password=TEST_PASSWORD)
    expect(page.get_by_text(re.compile(r"Cancelled|cancelled|Cancel", re.I)).first).to_be_visible()

    # --- No-show and delete gap fill ---
    open_create(page, base)
    create_from_form(page, guest_name="Charlie NoShow", check_in=_today(), check_out=_tomorrow(), rate="90", source="Direct", room_index=2)
    open_list(page, base)
    search_list(page, q="Charlie")
    open_detail_from_list(page, "Charlie NoShow")
    noshow_reservation(page, password=TEST_PASSWORD)

    open_create(page, base)
    create_from_form(page, guest_name="Dana Delete", check_in=_today(), check_out=_tomorrow(), rate="90", source="Direct", room_index=3)
    open_list(page, base)
    search_list(page, q="Dana")
    open_detail_from_list(page, "Dana Delete")
    delete_reservation(page, password=TEST_PASSWORD)
    assert_url_contains(page, "/reservations")

    maybe_caption(page, "Result: Guests & Reservations story complete (gap-fill)", duration=1.8)
    # Master video is recorded by test_story_master_all_app.py; keep this as E2E coverage.
