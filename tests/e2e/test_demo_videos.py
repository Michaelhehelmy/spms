"""tests/e2e/test_demo_videos.py — demo videos (silent, with captions) (app issue #42).

Records 20–40s videos of app actions with caption overlays; videos are saved
to ``dist/demo-videos/<name>.webm`` via the ``record_video`` helper.
"""
from __future__ import annotations

from playwright.sync_api import expect

from conftest import TEST_PASSWORD, _fill_create_form, caption, record_video


# ── Setup & dashboard ────────────────────────────────────────────────────────


def test_demo_setup_wizard_video(e2e_server, page, setup_app):
    base = e2e_server.base_url
    caption(page, f"1. Open the browser and go to the app at {base} — the Setup Wizard")
    page.goto(base + "/setup")
    page.wait_for_load_state("networkidle")
    caption(page, "2. Type the display name (Acadia Camp)")
    page.fill('input[name="display_name"]', "Acadia Camp")
    page.wait_for_timeout(2_500)
    caption(page, "3. Save — the app installs branding and starts")
    page.evaluate("() => { const el = document.getElementById('demo-caption'); if (el) el.remove(); }")
    page.wait_for_timeout(500)
    page.evaluate('document.querySelector(\'form[action="/setup"] button[type="submit"]\').click()')
    page.wait_for_url(lambda u: u == base + "/", timeout=20000)
    page.wait_for_load_state("networkidle")
    caption(page, "4. Redirected to the dashboard — the app is ready")
    page.wait_for_timeout(2_500)
    record_video(page, "01_setup_wizard")
    page.wait_for_timeout(2_500)
    record_video(page, "01_setup_wizard")


def test_demo_unlock_video(e2e_server, page):
    base = e2e_server.base_url
    caption(page, f"1. Open the browser and go to {base}/unlock")
    page.goto(base + "/unlock")
    page.wait_for_load_state("networkidle")
    caption(page, "1. Enter the super password here to unlock actions")
    page.fill('input[name="password"]', TEST_PASSWORD)
    caption(page, "2. After unlocking you can use protected actions (settings, refunds, ...)")
    page.wait_for_timeout(2_000)
    record_video(page, "02_unlock")


def test_demo_lock_session_video(e2e_server, page, setup_app, unlock):
    base = e2e_server.base_url
    caption(page, f"1. Open the browser and go to {base}/setup")
    setup_app("Acadia Camp")
    unlock()
    page.goto(base + "/")
    caption(page, "1. The Lock session button is in the top-right")
    page.get_by_role("button", name="Lock session").click()
    page.wait_for_load_state("networkidle")
    caption(page, "2. Locked — actions now redirect to /unlock")
    record_video(page, "03_lock_session")


def test_demo_dashboard_video(e2e_server, page, setup_app, unlock):
    base = e2e_server.base_url
    caption(page, f"1. Open the browser and go to {base}/setup")
    setup_app("Acadia Camp")
    unlock()
    page.goto(base + "/")
    caption(page, "1. Dashboard: arrivals, departures, in-house, financial snapshot")
    page.wait_for_load_state("networkidle")
    record_video(page, "04_dashboard")


def test_demo_dashboard_day_filter_video(e2e_server, page, setup_app, unlock):
    base = e2e_server.base_url
    caption(page, f"1. Open the browser and go to {base}/setup")
    setup_app("Acadia Camp")
    unlock()
    page.goto(base + "/")
    caption(page, "1. Use the date filter to view another ops day")
    page.fill('input[name="day"]', "2026-11-23")
    page.get_by_role("button", name="View").click()
    page.wait_for_load_state("networkidle")
    record_video(page, "05_dashboard_day_filter")


# ── Guests ──────────────────────────────────────────────────────────────────


def test_demo_guest_search_video(e2e_server, page, setup_app, unlock):
    base = e2e_server.base_url
    caption(page, f"1. Open the browser and go to {base}/setup")
    setup_app("Acadia Camp")
    unlock()
    page.goto(base + "/guests?tab=directory")
    caption(page, "1. Search by name, phone or email in the guests directory")
    page.fill('input[name="q"]', "Alice")
    page.get_by_role("button", name="Search").click()
    page.wait_for_load_state("networkidle")
    record_video(page, "06_guest_search")


def test_demo_guest_portfolio_video(e2e_server, page, setup_app, unlock, seed_guest):
    base = e2e_server.base_url
    caption(page, f"1. Open the browser and go to {base}/setup")
    setup_app("Acadia Camp")
    unlock()
    seed_guest("Alice Example")
    page.goto(base + "/guests?tab=directory")
    page.fill('input[name="q"]', "Alice")
    page.get_by_role("button", name="Search").click()
    page.wait_for_load_state("networkidle")
    caption(page, "1. Open the guest portfolio")
    page.get_by_role("link", name="Open portfolio").click()
    page.wait_for_load_state("networkidle")
    caption(page, "2. 360° view: profile, trips, POS/activity, payments, invoices")
    record_video(page, "07_guest_portfolio")


def test_demo_guest_edit_profile_video(e2e_server, page, setup_app, unlock, seed_guest):
    base = e2e_server.base_url
    setup_app("Acadia Camp")
    unlock()
    gid = seed_guest("Bob Example")
    page.goto(base + f"/guests/{gid}")
    page.wait_for_load_state("networkidle")
    caption(page, "1. Edit profile (unlock + super password)")
    form = page.locator(f'form[action="/guests/{gid}/update"]')
    form.locator('input[name="name"]').fill("Bob Edited")
    form.locator('input[name="notes"]').fill("Acadia demo edit")
    form.locator('input[type="password"]').fill(TEST_PASSWORD)
    form.get_by_role("button", name="Update profile").click()
    page.wait_for_load_state("networkidle")
    page.wait_for_url(lambda u: "/guests/" in u, timeout=20000)
    record_video(page, "08_guest_edit_profile")


# ── Reservations ────────────────────────────────────────────────────────────


def _open_new_reservation_detail(page, base, guest_name):
    _fill_create_form(page, base, guest_name)
    page.get_by_role("button", name="Create reservation").click()
    page.wait_for_url(lambda u: "/reservations" in u)
    page.wait_for_load_state("networkidle")
    page.locator('a[href^="/reservations/"]:not([href$="/reservations/groups"])').first.click()
    page.wait_for_load_state("networkidle")


def test_demo_reservation_create_video(e2e_server, page, setup_app, unlock):
    base = e2e_server.base_url
    caption(page, f"1. Open the browser and go to {base}/setup")
    setup_app("Acadia Camp")
    unlock()
    page.goto(base + "/reservations?tab=create")
    caption(page, "1. Guest, room, dates and nightly rate → Create reservation")
    _fill_create_form(page, base, "Acadia Create Guest")
    page.get_by_role("button", name="Create reservation").click()
    page.wait_for_url(lambda u: "/reservations" in u)
    page.wait_for_load_state("networkidle")
    record_video(page, "09_reservation_create")


def test_demo_reservation_detail_folio_video(e2e_server, page, setup_app, unlock):
    base = e2e_server.base_url
    caption(page, f"1. Open the browser and go to {base}/setup")
    setup_app("Acadia Camp")
    unlock()
    _open_new_reservation_detail(page, base, "Folio Guest")
    caption(page, "1. Reservation detail: folio, payments, POS, invoices")
    page.wait_for_load_state("networkidle")
    record_video(page, "10_reservation_detail_folio")


def test_demo_reservation_pricing_quote_video(e2e_server, page, setup_app, unlock):
    base = e2e_server.base_url
    caption(page, f"1. Open the browser and go to {base}/setup")
    setup_app("Acadia Camp")
    unlock()
    page.goto(base + "/reservations?tab=create")
    page.fill('input[name="guest_name"]', "Quote Guest")
    page.select_option("select[name=room_id]", index=0)
    page.fill("input[name=check_in]", "2026-11-22")
    page.fill("input[name=check_out]", "2026-11-23")
    page.fill('input[name="rate"]', "120")
    caption(page, "1. Get pricing quote — suggested rate, nights and totals from room/rules")
    page.get_by_role("button", name="Get pricing quote").click()
    page.wait_for_load_state("networkidle")
    expect(page.get_by_role("heading", name="Pricing quote (suggested)")).to_be_visible()
    record_video(page, "11_reservation_pricing_quote")


def test_demo_reservation_checkin_video(e2e_server, page, setup_app, unlock):
    base = e2e_server.base_url
    caption(page, f"1. Open the browser and go to {base}/setup")
    setup_app("Acadia Camp")
    unlock()
    _open_new_reservation_detail(page, base, "Checkin Guest")
    caption(page, "1. Mark the reservation as Checked In")
    page.get_by_role("button", name="Check in").click()
    page.wait_for_load_state("networkidle")
    record_video(page, "12_reservation_checkin")


def test_demo_reservation_groups_create_video(e2e_server, page, setup_app, unlock):
    base = e2e_server.base_url
    caption(page, f"1. Open the browser and go to {base}/setup")
    setup_app("Acadia Camp")
    unlock()
    page.goto(base + "/reservations/groups")
    caption(page, "1. Create a reservation group (bookings share folio/charges)")
    page.fill('input[name="name"]', "Acadia Demo Group")
    page.fill('input[name="contact_name"]', "Demo Travel")
    page.get_by_role("button", name="Create group").click()
    page.wait_for_load_state("networkidle")
    record_video(page, "13_reservation_groups_create")


def test_demo_reservation_groups_add_video(e2e_server, page, setup_app, unlock):
    base = e2e_server.base_url
    caption(page, f"1. Open the browser and go to {base}/setup")
    setup_app("Acadia Camp")
    unlock()
    _open_new_reservation_detail(page, base, "Grouped Guest")
    page.goto(base + "/reservations/groups")
    page.fill('input[name="name"]', "Acadia Add Group")
    page.get_by_role("button", name="Create group").click()
    page.wait_for_load_state("networkidle")
    caption(page, "1. Add the reservation to the group")
    page.select_option('select[name="group_id"]', index=0)
    page.select_option('select[name="reservation_id"]', index=0)
    page.get_by_role("button", name="Add to group").click()
    page.wait_for_load_state("networkidle")
    record_video(page, "14_reservation_groups_add")


def test_demo_group_folio_video(e2e_server, page, setup_app, unlock):
    base = e2e_server.base_url
    caption(page, f"1. Open the browser and go to {base}/setup")
    setup_app("Acadia Camp")
    unlock()
    _open_new_reservation_detail(page, base, "Folio Group Guest")
    page.goto(base + "/reservations/groups")
    page.fill('input[name="name"]', "Acadia Folio Group")
    page.get_by_role("button", name="Create group").click()
    page.wait_for_load_state("networkidle")
    caption(page, "1. Open the group folio/report (aggregated charges, payments, status)")
    page.locator('a[href^="/reservations/groups/"][href$="/folio"]').first.click()
    page.wait_for_load_state("networkidle")
    record_video(page, "15_group_folio")


# ── POS / Inventory ─────────────────────────────────────────────────────────


def test_demo_pos_inventory_tab_video(e2e_server, page, setup_app, unlock):
    base = e2e_server.base_url
    caption(page, f"1. Open the browser and go to {base}/setup")
    setup_app("Acadia Camp")
    unlock()
    page.goto(base + "/pos?tab=inventory")
    caption(page, "1. POS / Inventory: search items, manage stock, batches")
    page.wait_for_load_state("networkidle")
    record_video(page, "16_pos_inventory_tab")


def test_demo_pos_batches_tab_video(e2e_server, page, setup_app, unlock):
    base = e2e_server.base_url
    caption(page, f"1. Open the browser and go to {base}/setup")
    setup_app("Acadia Camp")
    unlock()
    page.goto(base + "/pos?tab=batches")
    caption(page, "1. Batches & traceability: lot codes, received/expiry dates")
    page.wait_for_load_state("networkidle")
    record_video(page, "17_pos_batches_tab")


def test_demo_pos_history_tab_video(e2e_server, page, setup_app, unlock):
    base = e2e_server.base_url
    caption(page, f"1. Open the browser and go to {base}/setup")
    setup_app("Acadia Camp")
    unlock()
    page.goto(base + "/pos?tab=history")
    caption(page, "1. POS history: past walk-in sales and receipts")
    page.wait_for_load_state("networkidle")
    record_video(page, "18_pos_history_tab")


def test_demo_pos_add_to_reservation_video(e2e_server, page, setup_app, unlock):
    base = e2e_server.base_url
    caption(page, f"1. Open the browser and go to {base}/setup")
    setup_app("Acadia Camp")
    unlock()
    page.goto(base + "/reservations?tab=create")
    page.fill('input[name="guest_name"]', "POS Guest")
    page.select_option("select[name=room_id]", index=0)
    page.fill("input[name=check_in]", "2026-11-22")
    page.fill("input[name=check_out]", "2026-11-23")
    page.fill('input[name="rate"]', "100")
    page.get_by_role("button", name="Create reservation").click()
    page.wait_for_url(lambda u: "/reservations" in u)
    page.wait_for_load_state("networkidle")
    page.goto(base + "/pos?tab=sell")
    caption(page, "1. Add a POS item directly to a reservation folio")
    form = page.locator('form[action="/pos/add"]')
    form.locator('input[name="desc"]').fill("Acadia Demo Service")
    form.locator('input[name="qty"]').fill("2")
    form.locator('input[name="price"]').fill("25")
    page.get_by_role("button", name="Add to reservation").click()
    page.wait_for_load_state("networkidle")
    expect(page.get_by_text("POS item added to reservation").first).to_be_visible()
    record_video(page, "19_pos_add_to_reservation")


# ── Housekeeping ─────────────────────────────────────────────────────────────


def test_demo_housekeeping_task_video(e2e_server, page, setup_app, unlock):
    base = e2e_server.base_url
    caption(page, f"1. Open the browser and go to {base}/setup")
    setup_app("Acadia Camp")
    unlock()
    page.goto(base + "/housekeeping")
    caption(page, "1. Create a housekeeping task (room, type, priority)")
    page.locator('details summary:has-text("Create task")').click()
    form = page.locator('form[action="/housekeeping/tasks/create"]')
    form.locator("select[name='room_id']").select_option(index=0)
    form.locator('input[name="task_type"]').fill("cleaning")
    form.locator('input[name="assignee"]').fill("Acadia Staff")
    form.get_by_role("button", name="Create task").click()
    page.wait_for_load_state("networkidle")
    record_video(page, "20_housekeeping_task")


# ── Accounting & Reports ─────────────────────────────────────────────────────


def test_demo_accounting_expense_video(e2e_server, page, setup_app, unlock, seed_expense_category):
    base = e2e_server.base_url
    caption(page, f"1. Open the browser and go to {base}/setup")
    setup_app("Acadia Camp")
    unlock()
    seed_expense_category("Acadia Expense")
    page.goto(base + "/accounting?tab=expenses")
    caption(page, "1. Record an operational expense")
    page.fill('input[name="param"]', "Acadia Demo Expense")
    page.fill('input[name="amount"]', "85.00")
    page.select_option('select[name="cat_id"]', index=0)
    page.get_by_role("button", name="Record expense").click()
    page.wait_for_load_state("networkidle")
    expect(page.get_by_text("Expense recorded")).to_be_visible()
    record_video(page, "21_accounting_expense")


def test_demo_accounting_void_expense_video(e2e_server, page, setup_app, unlock, seed_expense_category):
    base = e2e_server.base_url
    caption(page, f"1. Open the browser and go to {base}/setup")
    setup_app("Acadia Camp")
    unlock()
    seed_expense_category("Acadia Expense")
    page.goto(base + "/accounting?tab=expenses")
    page.fill('input[name="param"]', "Acadia Voidable Expense")
    page.fill('input[name="amount"]', "10.00")
    page.select_option('select[name="cat_id"]', index=0)
    page.get_by_role("button", name="Record expense").click()
    page.wait_for_load_state("networkidle")
    caption(page, "1. Void an expense (audited reversal, requires password)")
    form = page.locator('form[action^="/accounting/expense/"][action$="/void"]').first
    form.locator('input[name="password"]').fill(TEST_PASSWORD)
    form.get_by_role("button", name="Void").click()
    page.wait_for_load_state("networkidle")
    expect(page.get_by_text("Expense voided").first).to_be_visible()
    record_video(page, "22_accounting_void_expense")


def test_demo_accounting_payment_video(e2e_server, page, setup_app, unlock):
    base = e2e_server.base_url
    caption(page, f"1. Open the browser and go to {base}/setup")
    setup_app("Acadia Camp")
    unlock()
    page.goto(base + "/accounting?tab=payments")
    caption(page, "1. Record a payment (walk-in or reservation)")
    page.fill('input[name="amount"]', "75.00")
    page.get_by_role("button", name="Record payment").click()
    page.wait_for_load_state("networkidle")
    expect(page.get_by_text("Payment recorded")).to_be_visible()
    record_video(page, "23_accounting_payment")


def test_demo_accounting_shift_video(e2e_server, page, setup_app, unlock):
    base = e2e_server.base_url
    caption(page, f"1. Open the browser and go to {base}/setup")
    setup_app("Acadia Camp")
    unlock()
    page.goto(base + "/accounting?tab=shifts")
    caption(page, "1. Open a cash shift")
    page.get_by_role("button", name="Open shift").click()
    page.wait_for_load_state("networkidle")
    caption(page, "2. Record a shift movement")
    page.fill('input[name="amount"]', "200.00")
    page.get_by_role("button", name="Record movement").click()
    page.wait_for_load_state("networkidle")
    expect(page.get_by_text("Cash movement recorded")).to_be_visible()
    record_video(page, "24_accounting_shift")


def test_demo_accounting_night_audit_video(e2e_server, page, setup_app, unlock):
    base = e2e_server.base_url
    caption(page, f"1. Open the browser and go to {base}/setup")
    setup_app("Acadia Camp")
    unlock()
    page.goto(base + "/accounting?tab=night_audit")
    caption(page, "1. Run an advisory night-audit snapshot")
    page.get_by_role("button", name="Run & record snapshot").click()
    page.wait_for_load_state("networkidle")
    expect(page.get_by_text("Night audit snapshot recorded (advisory)")).to_be_visible()
    record_video(page, "25_accounting_night_audit")


def test_demo_accounting_ledger_video(e2e_server, page, setup_app, unlock):
    base = e2e_server.base_url
    caption(page, f"1. Open the browser and go to {base}/setup")
    setup_app("Acadia Camp")
    unlock()
    page.goto(base + "/accounting?tab=ledger")
    caption(page, "1. Ledger: recent real-data entries")
    page.wait_for_load_state("networkidle")
    record_video(page, "26_accounting_ledger")


def test_demo_reports_pl_video(e2e_server, page, setup_app, unlock):
    base = e2e_server.base_url
    caption(page, f"1. Open the browser and go to {base}/setup")
    setup_app("Acadia Camp")
    unlock()
    page.goto(base + "/reports?tab=generate")
    caption(page, "1. Run a report — P&L")
    page.select_option('select[name="kind"]', "pl")
    page.get_by_role("button", name="Generate").click()
    page.wait_for_load_state("networkidle")
    expect(page.get_by_text("Report generated")).to_be_visible()
    record_video(page, "27_reports_pl")


def test_demo_reports_analytics_export_video(e2e_server, page, setup_app, unlock):
    base = e2e_server.base_url
    caption(page, f"1. Open the browser and go to {base}/setup")
    setup_app("Acadia Camp")
    unlock()
    page.goto(base + "/reports?tab=generate")
    caption(page, "1. Analytics export (saved to the Downloads tab)")
    page.get_by_role("button", name="Export (JSON/TXT/CSV as configured)").click()
    page.wait_for_load_state("networkidle")
    expect(page.get_by_text("Analytics export created:").first).to_be_visible()
    record_video(page, "28_reports_analytics_export")


# ── Assistant & Settings & Support ──────────────────────────────────────────


def test_demo_assistant_ask_video(e2e_server, page, setup_app, unlock):
    base = e2e_server.base_url
    caption(page, f"1. Open the browser and go to {base}/setup")
    setup_app("Acadia Camp")
    unlock()
    page.goto(base + "/assistant")
    caption(page, "1. Ask the Manager Assistant (grounded in real app data)")
    page.fill('textarea[name="message"]', "Who owes money?")
    page.get_by_role("button", name="Send message").click()
    page.wait_for_load_state("networkidle")
    record_video(page, "29_assistant_ask")


def test_demo_settings_general_save_video(e2e_server, page, setup_app, unlock, password):
    base = e2e_server.base_url
    caption(page, f"1. Open the browser and go to {base}/setup")
    setup_app("Acadia Camp")
    unlock()
    page.goto(base + "/settings?tab=general")
    caption(page, "1. Save settings (requires unlock + super password)")
    page.locator('form[action="/settings/save"]').locator('input[name="password"]').fill(password)
    page.get_by_role("button", name="Save settings").click()
    page.wait_for_load_state("networkidle")
    expect(page.get_by_text("Saved").first).to_be_visible()
    record_video(page, "30_settings_general_save")


def test_demo_settings_branding_video(e2e_server, page, setup_app, unlock):
    base = e2e_server.base_url
    caption(page, f"1. Open the browser and go to {base}/setup")
    setup_app("Acadia Camp")
    unlock()
    page.goto(base + "/settings?tab=general")
    caption(page, "1. Apply branding to the app display name")
    form = page.locator('form[action="/settings/branding"]')
    form.locator('input[name="display_name"]').fill("Acadia Camp Renamed")
    page.get_by_role("button", name="Apply branding").click()
    page.wait_for_load_state("networkidle")
    expect(page.get_by_text("Branding updated")).to_be_visible()
    record_video(page, "31_settings_branding")


def test_demo_settings_rooms_video(e2e_server, page, setup_app, unlock):
    base = e2e_server.base_url
    caption(page, f"1. Open the browser and go to {base}/setup")
    setup_app("Acadia Camp")
    unlock()
    page.goto(base + "/settings?tab=rooms")
    caption(page, "1. Add a new room (number + type)")
    page.fill('input[name="room_number"]', "Acadia Video Room")
    page.fill('input[name="room_type"]', "Standard Room")
    page.get_by_role("button", name="Add room").click()
    page.wait_for_load_state("networkidle")
    record_video(page, "32_settings_rooms")


def test_demo_settings_rate_plans_video(e2e_server, page, setup_app, unlock, password):
    base = e2e_server.base_url
    caption(page, f"1. Open the browser and go to {base}/setup")
    setup_app("Acadia Camp")
    unlock()
    page.goto(base + "/settings/rate-plans")
    caption(page, "1. Add a rate plan (modifier applied to stays)")
    form = page.locator('form[action="/settings/rate-plans/add"]')
    form.locator('input[name="name"]').fill("Acadia Video Plan")
    form.locator('input[name="modifier"]').fill("3")
    form.locator('input[name="password"]').fill(password)
    page.get_by_role("button", name="Add").click()
    page.wait_for_load_state("networkidle")
    expect(page.get_by_text("Acadia Video Plan").first).to_be_visible()
    record_video(page, "33_settings_rate_plans")


def test_demo_settings_users_video(e2e_server, page, setup_app, unlock, password):
    base = e2e_server.base_url
    caption(page, f"1. Open the browser and go to {base}/setup")
    setup_app("Acadia Camp")
    unlock()
    page.goto(base + "/settings/users")
    caption(page, "1. Create a user in the RBAC room page")
    form = page.locator('form[action="/settings/users/add"]')
    form.locator('input[name="username"]').fill("e2evideo1")
    form.locator('input[name="display_name"]').fill("Acadia Video User")
    form.locator('input[name="password"]').fill(password)
    page.get_by_role("button", name="Create user").click()
    page.wait_for_load_state("networkidle")
    expect(page.get_by_text("User created").first).to_be_visible()
    record_video(page, "34_settings_users")


def test_demo_settings_health_video(e2e_server, page, setup_app, unlock):
    base = e2e_server.base_url
    caption(page, f"1. Open the browser and go to {base}/setup")
    setup_app("Acadia Camp")
    unlock()
    page.goto(base + "/settings/health")
    caption(page, "1. Data health check page")
    page.wait_for_load_state("networkidle")
    record_video(page, "35_settings_health")


def test_demo_support_report_video(e2e_server, page, setup_app, unlock):
    base = e2e_server.base_url
    caption(page, f"1. Open the browser and go to {base}/setup")
    setup_app("Acadia Camp")
    unlock()
    page.goto(base + "/support/report")
    caption(page, "1. Report an issue — privacy-safe diagnostics preview")
    page.wait_for_load_state("networkidle")
    record_video(page, "36_support_report")
