"""Master all-in-one SPMS demo/E2E story (single video).

Covers the full app in one continuous flow: setup/access, dashboard, guests,
reservations, POS/inventory, housekeeping, accounting, reports, assistant,
settings/admin, and support. Records one demo video when E2E_DEMO=1 or story demo mode.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from playwright.sync_api import expect

from conftest import DEMO_DIR, TEST_PASSWORD, record_video
from flows.auth import create_super_password, lock, setup_wizard
from flows.common import assert_url_contains, ensure_demo_ready, maybe_caption, nav_click
from flows.dashboard import filter_day, overview
from flows.guests import edit_profile, open_directory, open_portfolio_from_directory, search as guest_search
from flows.housekeeping import (
    create_room_block,
    create_task,
    filter_tasks,
    generate_dirty_tasks,
    open_page as open_housekeeping,
    resolve_first_block,
    update_first_task_status,
)
from flows.pos import (
    activity_create,
    batches_receive,
    inventory_add_item,
    open_tab as open_pos_tab,
    sell_add_custom_to_cart,
    sell_complete_walkin,
)
from flows.reservations import (
    add_extra_service,
    add_pos_charge,
    add_reservation_to_group,
    apply_discount,
    book_activity,
    cancel_reservation,
    create_from_form,
    create_group,
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
    search_list,
    void_first_pos_line,
)
from flows.accounting import open_tab as open_acct_tab, record_expense, record_walkin_payment, open_shift, run_night_audit
from flows.reports import open_tab as open_reports_tab, generate_report
from flows.assistant import ask as assistant_ask
from flows.settings import open_tab as open_settings_tab
from flows.support import generate_report as support_generate_report, open_page as open_support


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _tomorrow() -> str:
    return (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")


@pytest.mark.story
def test_story_master_all_app(e2e_server_fresh, page):
    base = e2e_server_fresh.base_url
    import time as _time
    t0 = _time.monotonic()
    chapters: list[tuple[float, str]] = []
    trim_start, speed = 1.0, 0.9

    def mark(label: str) -> None:
        chapters.append((max(0.0, (_time.monotonic() - t0 - trim_start) * speed), label))

    # ── 1) Setup / Access / Dashboard ───────────────────────────────────────
    mark("Setup, Access & Dashboard")
    maybe_caption(page, "Chapter 1 — Setup, Access & Dashboard: first-run setup, secure unlock, and daily operations overview.", duration=2.8)
    setup_wizard(page, base)
    maybe_caption(page, "Security: create the Super Password to protect sensitive actions (payments, voids, refunds, settings).", duration=2.5)
    create_super_password(page, base)
    lock(page, base)
    create_super_password(page, base)
    maybe_caption(page, "Dashboard shows today's ops: occupancy, arrivals, departures, exceptions. Filter by business day for review.", duration=2.5)
    overview(page, base)
    filter_day(page, base, _today())

    # ── 2) Guests & Reservations ────────────────────────────────────────────
    mark("Guests & Reservations")
    maybe_caption(page, "Chapter 2 — Guests & Reservations: search guests, create/quote bookings, manage folio, payments, invoice, groups.", duration=2.8)
    guest_name = "Alice Master"
    guest_b = "Bob Master"

    maybe_caption(page, "Guests directory: search by name/phone/email; open 360° portfolio with stays, POS, payments, invoices.", duration=2.5)
    open_directory(page, base)
    guest_search(page, base, "NoSuchGuestXYZ")
    expect(page.get_by_text(re.compile(r"No guests found|No guests", re.I)).first).to_be_visible()

    maybe_caption(page, "Reservations: get pricing quote, then create reservation from real rooms/rates/availability.", duration=2.5)
    open_create(page, base)
    quote_create(page, guest_name=guest_name, check_in=_today(), check_out=_tomorrow(), rate="120")
    create_from_form(page, guest_name=guest_name, check_in=_today(), check_out=_tomorrow(), rate="120", source="Direct")
    open_create(page, base)
    create_from_form(page, guest_name=guest_b, check_in=_today(), check_out=_tomorrow(), rate="100", source="Phone", room_index=1)

    open_list(page, base)
    search_list(page, q="Alice")
    open_detail_from_list(page, guest_name)

    maybe_caption(page, "Reservation detail: record deposit/payment, generate invoice, add services/discounts, modify stay.", duration=2.5)
    record_payment(page, "50", method="Cash", payment_type="Deposit")
    generate_invoice(page)
    add_extra_service(page, "Airport pickup", qty="1", price="25")
    apply_discount(page, "Story discount", dtype="amount", value="5")
    modify_reservation(page, rate="130", password=TEST_PASSWORD)
    maybe_caption(page, "Front desk flow: check in guest, collect remaining balance, then check out.", duration=2.5)
    detail_checkin(page)
    pay_full_balance(page)
    detail_checkout(page)

    maybe_caption(page, "Guest 360 portfolio: full history and profile edit (super password protected).", duration=2.5)
    open_directory(page, base)
    guest_search(page, base, "Alice")
    open_portfolio_from_directory(page, guest_name)
    edit_profile(page, name="Alice Master Updated", phone="+1555000111", email="alice.master@example.com", notes="Updated in master story", password=TEST_PASSWORD)

    maybe_caption(page, "Reservation Groups: group bookings, add members, and open group folio/report.", duration=2.5)
    open_groups(page, base)
    create_group(page, "Master Group", group_type="tour", contact="Coordinator")
    add_reservation_to_group(page, "Master Group", guest_b)
    folio = open_group_folio(page, "Master Group")
    folio.close()

    # ── 3) POS / Inventory / Housekeeping ──────────────────────────────────
    mark("POS, Inventory & Housekeeping")
    maybe_caption(page, "Chapter 3 — POS, Inventory & Housekeeping: sell walk-ins, manage stock/batches, activities, and room readiness.", duration=2.8)
    maybe_caption(page, "POS Sell: add items to walk-in cart and complete sale with receipt; can also charge reservations.", duration=2.3)
    open_pos_tab(page, base, "sell", "Sell")
    sell_add_custom_to_cart(page, "Master Walk-in Coffee", qty="2", price="4.50")
    sell_complete_walkin(page, base)

    maybe_caption(page, "Inventory: create items (SKU/barcode/pricing/stock); restock records received batches for traceability.", duration=2.3)
    open_pos_tab(page, base, "inventory", "Inventory")
    inventory_add_item(page, name="Master Water Bottle", category="Drinks", unit="bottle", stock="10", cost="1.00", selling="3.00", password=TEST_PASSWORD)
    row = page.locator("tr", has_text="Master Water Bottle").first
    item_id = row.locator("td").nth(0).inner_text().strip()

    maybe_caption(page, "Batches & Traceability: receive lots with received/expiry/cost; FEFO and lot traceability for sales.", duration=2.3)
    open_pos_tab(page, base, "batches", "Batches & Traceability")
    batches_receive(page, item_id=item_id, qty="4", unit_cost="1.00", supplier="Master Supplier", password=TEST_PASSWORD)

    open_pos_tab(page, base, "meals", "Meals & Recipes")
    expect(page.get_by_role("heading", name="Registered Meals").first).to_be_visible()
    maybe_caption(page, "Meals & Recipes: register meals and ingredient auto-deduction recipes for POS orders.", duration=2.2)

    open_pos_tab(page, base, "activities", "Activities")
    activity_create(page, name="Master Desert Tour", category="Trip", price="45.00", description="Guided tour")
    maybe_caption(page, "Activities: register bookable trips/experiences; book from reservation to post to folio/invoice.", duration=2.2)

    open_pos_tab(page, base, "history", "History")
    expect(page.get_by_role("heading", name="Recent walk-in POS lines (no reservation)").first).to_be_visible()
    maybe_caption(page, "POS History: review walk-in sales/lines; void with password when needed (audited).", duration=2.0)

    maybe_caption(page, "Housekeeping: generate/manage cleaning tasks, update status, and block rooms (OOO/OOS) with dates.", duration=2.3)
    open_housekeeping(page, base)
    generate_dirty_tasks(page)
    create_task(page, assignee="Alex HK", task_type="cleaning", priority="high", notes="Master housekeeping task")
    update_first_task_status(page, "in_progress")
    filter_tasks(page, "in_progress")
    filter_tasks(page, "")
    create_room_block(page, password=TEST_PASSWORD)
    resolve_first_block(page, password=TEST_PASSWORD)

    # ── 4) Accounting / Reports / Assistant ────────────────────────────────
    mark("Accounting, Reports & Assistant")
    maybe_caption(page, "Chapter 4 — Accounting, Reports & Assistant: ledger-grounded finance, exports, and grounded AI help.", duration=2.8)
    open_acct_tab(page, base, "overview", "Overview")
    expect(page.get_by_text("Billed revenue").first).to_be_visible()
    maybe_caption(page, "Accounting Overview: billed revenue, expenses/COGS, net profit, A/R from real ledger data.", duration=2.2)
    open_acct_tab(page, base, "expenses", "Expenses")
    record_expense(page, param="Master supplies", amount="35.00")
    maybe_caption(page, "Expenses: record/void operational costs; void requires unlock+super password and is audited.", duration=2.2)
    open_acct_tab(page, base, "payments", "Payments & Refunds")
    record_walkin_payment(page, amount="20.00", method="Cash")
    maybe_caption(page, "Payments & Refunds: record reservation/walk-in payments; refunds require super password and are audited.", duration=2.2)
    open_acct_tab(page, base, "shifts", "Cash Shifts")
    open_shift(page, name="Master Shift", opening_float="100")
    maybe_caption(page, "Cash Shifts: open/close shifts, record movements, reconcile expected vs counted cash.", duration=2.2)
    open_acct_tab(page, base, "night_audit", "Night Audit")
    run_night_audit(page)
    maybe_caption(page, "Night Audit: advisory snapshot of ops/ledger state and exceptions for a business date.", duration=2.2)
    open_acct_tab(page, base, "ledger", "Ledger")
    expect(page.get_by_role("heading", name="Recent ledger").first).to_be_visible()

    maybe_caption(page, "Reports: generate P&L/cash/VAT/ops reports from real data; export presets saved to Downloads.", duration=2.2)
    open_reports_tab(page, base, "generate", "Generate")
    generate_report(page, "pl")
    nav_click(page, "/reports", "Reports & Analytics")
    open_reports_tab(page, base, "downloads", "Downloads")
    expect(page.get_by_role("heading", name="Exports").first).to_be_visible()

    maybe_caption(page, "Assistant: grounded read-only answers from real app data; wait for response before next action.", duration=2.2)
    assistant_ask(page, "What can you do?")

    # ── 5) Settings / Admin / Support ──────────────────────────────────────
    mark("Settings, Admin & Support")
    maybe_caption(page, "Chapter 5 — Settings, Admin & Support: configuration, master data, governance, health, and issue reporting.", duration=2.8)
    maybe_caption(page, "Settings tabs: General branding/backup, Seed & Data import/export, Rooms & Plans, Updates & Health.", duration=2.2)
    for tab, label in [("general", "General"), ("data", "Seed & Data"), ("rooms", "Rooms & Plans"), ("updates", "Updates & Health")]:
        open_settings_tab(page, base, tab, label)
        assert_url_contains(page, f"tab={tab}")

    # Admin pages
    for href, label, marker in [
        ("/settings/rate-plans", "Rate Plans — manage plans/rules used by reservation pricing.", "Rate Plans"),
        ("/settings/users", "Users / RBAC — roles, permissions, and user access control.", "Users"),
        ("/settings/packages", "Packages — bundles of services/items applied to reservations.", "Packages"),
        ("/settings/vouchers", "Vouchers — discount/voucher rules for reservations/folio.", "Vouchers"),
        ("/settings/service-catalog", "Service Catalog — extra services available on reservation folios.", "Service"),
        ("/settings/approvals", "Approvals — request/review/execute sensitive workflow approvals.", "Approvals"),
        ("/settings/health", "Health — system checks and diagnostics for operations.", "Health"),
    ]:
        page.goto(base + href, wait_until="domcontentloaded")
        ensure_demo_ready(page)
        maybe_caption(page, f"Admin: {label}", duration=1.8)
        assert_url_contains(page, href)

    maybe_caption(page, "Support: generate privacy-safe issue report with diagnostics; download/share for maintainer.", duration=2.2)
    open_support(page, base)
    support_generate_report(page, title="Master demo report", steps="1. Open app\n2. Review flow", expected="Report generated", actual="Master story completed")

    # ── Wrap up ────────────────────────────────────────────────────────────
    mark("Wrap-up & Summary")
    overview(page, base)
    maybe_caption(page, "Result: full SPMS app demo complete (single video)", duration=2.5)

    # Write YouTube chapter timestamps (adjusted for trim/speed).
    try:
        DEMO_DIR.mkdir(parents=True, exist_ok=True)
        lines = []
        for sec, label in chapters:
            m, s = divmod(int(sec), 60)
            h, m = divmod(m, 60)
            ts = f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"
            lines.append(f"{ts} {label}")
        (DEMO_DIR / "00_spms_full_app_demo.chapters.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    except Exception:
        pass

    if getattr(page, "_demo_mode", False):
        record_video(page, "00_spms_full_app_demo", trim_start=1.0, speed=0.9)
