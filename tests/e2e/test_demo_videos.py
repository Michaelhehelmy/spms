"""tests/e2e/test_demo_videos.py — demo videos (silent, with captions) (app issue #42).

Records 20–40s videos of app actions with caption overlays; videos are saved
to ``dist/demo-videos/<name>.webm`` via the ``record_video`` helper.
"""
from __future__ import annotations

from playwright.sync_api import expect

from conftest import (
    TEST_PASSWORD,
    _fill_create_form,
    caption,
    demo_click,
    demo_install_cursor,
    demo_move,
    demo_select,
    demo_type,
    hide_update_modal,
    record_video,
)


# ── Helpers ──────────────────────────────────────────────────────────────────


def _prep(page, base, e2e_server, setup_app, unlock, *, start_path="/"):
    """Common demo prep: setup, unlock, start at dashboard with cursor."""
    setup_app("Acadia Camp")
    unlock()
    page.goto(base + start_path, wait_until="domcontentloaded")
    page.add_style_tag(content="#update-modal-backdrop,.modal-backdrop{display:none!important}")
    hide_update_modal(page)
    demo_install_cursor(page)
    page.wait_for_timeout(1200)


def _nav(page, href: str, label: str):
    """Navigate via sidebar click (human action)."""
    caption(page, f"Navigate: {label}", duration=1.0)
    sel = f'a.nav-link[href="{href}"]'
    demo_move(page, sel)
    page.locator(sel).first.click()
    page.wait_for_load_state("domcontentloaded")
    page.add_style_tag(content="#update-modal-backdrop,.modal-backdrop{display:none!important}")
    hide_update_modal(page)
    demo_install_cursor(page)
    page.wait_for_timeout(600)


def _click_btn(page, name: str):
    btn = page.get_by_role("button", name=name)
    btn.scroll_into_view_if_needed()
    box = btn.bounding_box()
    if box:
        page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2, steps=15)
    btn.click()
    page.wait_for_timeout(250)


def _click_role(page, role: str, name: str):
    exact = page.get_by_role(role, name=name, exact=True)
    if exact.count() == 1:
        loc = exact
    else:
        loc = page.get_by_role(role, name=name).first
    loc.scroll_into_view_if_needed()
    box = loc.bounding_box()
    if box:
        page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2, steps=15)
    loc.click()
    page.wait_for_timeout(250)


def _type_loc(page, loc, text: str, delay: int = 55):
    loc.scroll_into_view_if_needed()
    box = loc.bounding_box()
    if box:
        page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2, steps=15)
    loc.click()
    page.wait_for_timeout(120)
    t = (loc.get_attribute("type") or "").lower()
    if t in {"date", "datetime-local", "time", "number"}:
        loc.fill(text)
    else:
        loc.fill("")
        page.keyboard.type(text, delay=delay)
    page.wait_for_timeout(200)


def _end(page, name: str, endpoint: str):
    caption(page, f"Result: {endpoint}", duration=1.5)
    page.wait_for_timeout(1200)
    record_video(page, name, trim_start=1.5, speed=0.85)


# ── Video 1 — Setup wizard ───────────────────────────────────────────────────


def test_demo_setup_wizard_video(e2e_server, page):
    base = e2e_server.base_url
    page.add_init_script("""
        (() => {
            const css = '#update-modal-backdrop,.modal-backdrop{display:none!important}';
            const add = () => {
                if (!document.getElementById('demo-hide-modal-style')) {
                    const s = document.createElement('style');
                    s.id = 'demo-hide-modal-style';
                    s.textContent = css;
                    (document.head || document.documentElement).appendChild(s);
                }
            };
            if (document.head) add(); else document.addEventListener('DOMContentLoaded', add, {once:true});
        })();
    """)
    page.goto(base + "/setup", wait_until="domcontentloaded")
    hide_update_modal(page)
    demo_install_cursor(page)
    page.add_style_tag(content="#update-modal-backdrop,.modal-backdrop{display:none!important}")
    page.wait_for_selector('form[action="/setup"]', state="visible", timeout=15000)
    hide_update_modal(page)
    demo_install_cursor(page)
    page.wait_for_timeout(2_500)

    caption(page, f"Start: {base}/setup — Setup Wizard", duration=2.0)
    caption(page, "Action: fill display name, tagline, loading animation", duration=1.2)
    demo_type(page, 'input[name="display_name"]', "Acadia Camp", delay=70)
    demo_type(page, 'input[name="tagline"]', "Desert comfort, thoughtfully hosted.", delay=55)

    demo_move(page, 'select[name="animation"]')
    page.locator('select[name="animation"]').click()
    page.evaluate(
        """() => {
            const sel = document.querySelector('select[name="animation"]');
            const r = sel.getBoundingClientRect();
            const overlay = document.createElement('div');
            overlay.id = 'demo-select-overlay';
            Object.assign(overlay.style, {
                position: 'fixed', left: r.left + 'px', top: (r.bottom + 4) + 'px',
                width: r.width + 'px', background: '#fff', color: '#111',
                border: '1px solid #bbb', borderRadius: '6px',
                boxShadow: '0 8px 24px rgba(0,0,0,.18)', zIndex: '2147483647',
                font: '14px/1.4 sans-serif', overflow: 'hidden',
            });
            const opts = [['reveal','Reveal letters'],['typewriter','Typewriter'],['wave','Wave'],['pulse','Pulse'],['none','No animation']];
            opts.forEach(([val, label]) => {
                const item = document.createElement('div');
                item.textContent = label;
                item.dataset.val = val;
                Object.assign(item.style, { padding: '8px 12px', cursor: 'pointer' });
                if (val === 'reveal') item.style.background = '#e8f0fe';
                overlay.appendChild(item);
            });
            document.body.appendChild(overlay);
        }"""
    )
    page.wait_for_timeout(700)
    box = page.locator('select[name="animation"]').bounding_box()
    if box:
        page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] + 20, steps=15)
        page.wait_for_timeout(250)
        page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] + 20)
    page.select_option('select[name="animation"]', "reveal")
    page.evaluate("() => { const el = document.getElementById('demo-select-overlay'); if (el) el.remove(); }")
    page.wait_for_timeout(500)

    caption(page, "Action: Save setup", duration=1.2)
    page.evaluate("() => { const el = document.getElementById('demo-caption'); if (el) el.remove(); }")
    page.wait_for_timeout(200)
    demo_move(page, 'form[action="/setup"] button[type="submit"]')
    page.evaluate('document.querySelector(\'form[action="/setup"] button[type="submit"]\').click()')
    page.wait_for_url(lambda u: u.rstrip("/") == base, timeout=20000)
    page.wait_for_load_state("domcontentloaded")
    page.add_style_tag(content="#update-modal-backdrop,.modal-backdrop{display:none!important}")
    hide_update_modal(page)
    page.wait_for_timeout(1500)

    caption(page, "Result: branding saved, dashboard ready at /", duration=2.0)
    page.wait_for_timeout(1500)
    record_video(page, "01_setup_wizard", trim_start=6.0, speed=0.85)


# ── Video 2 — Unlock ─────────────────────────────────────────────────────────


def test_demo_unlock_video(e2e_server, page, setup_app):
    base = e2e_server.base_url
    setup_app("Acadia Camp")
    # Start at dashboard (locked) - protected action will redirect to unlock
    page.goto(base + "/", wait_until="domcontentloaded")
    page.add_style_tag(content="#update-modal-backdrop,.modal-backdrop{display:none!important}")
    hide_update_modal(page)
    demo_install_cursor(page)
    page.wait_for_timeout(1200)
    caption(page, "Start: / dashboard (locked)", duration=1.5)
    caption(page, "Action: open Settings (protected) → unlock", duration=1.2)
    _nav(page, "/settings", "Settings / Branding")
    page.wait_for_load_state("domcontentloaded")
    hide_update_modal(page)
    demo_install_cursor(page)
    # If redirected to unlock, type password
    if "/unlock" in page.url:
        caption(page, "Action: enter super password and unlock", duration=1.2)
        demo_type(page, 'input[name="password"]', "e2e-pass-123", delay=70)
        _click_btn(page, "Unlock")
        page.wait_for_load_state("domcontentloaded")
        hide_update_modal(page)
    _end(page, "02_unlock", "endpoint: unlocked, access granted")


# ── Video 3 — Lock session ───────────────────────────────────────────────────


def test_demo_lock_session_video(e2e_server, page, setup_app, unlock):
    base = e2e_server.base_url
    _prep(page, base, e2e_server, setup_app, unlock)
    caption(page, "Start: / dashboard (unlocked)", duration=1.5)
    caption(page, "Action: click Lock session in top-right", duration=1.2)
    _click_btn(page, "Lock session")
    page.wait_for_load_state("domcontentloaded")
    hide_update_modal(page)
    _end(page, "03_lock_session", "endpoint: session locked, protected actions redirect to /unlock")


# ── Video 4 — Dashboard ──────────────────────────────────────────────────────


def test_demo_dashboard_video(e2e_server, page, setup_app, unlock):
    base = e2e_server.base_url
    _prep(page, base, e2e_server, setup_app, unlock)
    caption(page, "Start: / dashboard", duration=1.5)
    caption(page, "Action: review arrivals, departures, in-house, financial snapshot", duration=1.8)
    page.wait_for_timeout(1500)
    page.mouse.wheel(0, 400)
    page.wait_for_timeout(1000)
    page.mouse.wheel(0, -400)
    page.wait_for_timeout(800)
    _end(page, "04_dashboard", "endpoint: dashboard overview /")


# ── Video 5 — Dashboard day filter ───────────────────────────────────────────


def test_demo_dashboard_day_filter_video(e2e_server, page, setup_app, unlock):
    base = e2e_server.base_url
    _prep(page, base, e2e_server, setup_app, unlock)
    caption(page, "Start: / dashboard", duration=1.5)
    caption(page, "Action: change ops day and click View", duration=1.2)
    demo_type(page, 'input[name="day"]', "2026-11-23", delay=60)
    _click_btn(page, "View")
    page.wait_for_load_state("domcontentloaded")
    hide_update_modal(page)
    _end(page, "05_dashboard_day_filter", "endpoint: dashboard filtered by day")


# ── Video 6 — Guest search ───────────────────────────────────────────────────


def test_demo_guest_search_video(e2e_server, page, setup_app, unlock):
    base = e2e_server.base_url
    _prep(page, base, e2e_server, setup_app, unlock)
    caption(page, "Start: / dashboard", duration=1.2)
    _nav(page, "/guests", "Guests")
    caption(page, "Action: search guest by name", duration=1.2)
    demo_type(page, 'input[name="q"]', "Alice", delay=70)
    _click_btn(page, "Search")
    page.wait_for_load_state("domcontentloaded")
    hide_update_modal(page)
    _end(page, "06_guest_search", "endpoint: guests directory search results")


# ── Video 7 — Guest portfolio ────────────────────────────────────────────────


def test_demo_guest_portfolio_video(e2e_server, page, setup_app, unlock, seed_guest):
    base = e2e_server.base_url
    _prep(page, base, e2e_server, setup_app, unlock)
    seed_guest("Alice Example")
    caption(page, "Start: / dashboard", duration=1.2)
    _nav(page, "/guests", "Guests")
    caption(page, "Action: search and open guest portfolio", duration=1.2)
    demo_type(page, 'input[name="q"]', "Alice", delay=70)
    _click_btn(page, "Search")
    page.wait_for_load_state("domcontentloaded")
    hide_update_modal(page)
    _click_role(page, "link", "Open portfolio")
    page.wait_for_load_state("domcontentloaded")
    hide_update_modal(page)
    caption(page, "Result: 360° profile, trips, POS, payments, invoices", duration=1.8)
    page.wait_for_timeout(1200)
    record_video(page, "07_guest_portfolio", trim_start=1.5, speed=0.85)


# ── Video 8 — Guest edit profile ─────────────────────────────────────────────


def test_demo_guest_edit_profile_video(e2e_server, page, setup_app, unlock, seed_guest):
    base = e2e_server.base_url
    _prep(page, base, e2e_server, setup_app, unlock)
    gid = seed_guest("Bob Example")
    caption(page, "Start: / dashboard", duration=1.2)
    _nav(page, "/guests", "Guests")
    page.goto(base + f"/guests/{gid}", wait_until="domcontentloaded")
    hide_update_modal(page)
    demo_install_cursor(page)
    page.wait_for_timeout(800)
    caption(page, "Action: edit profile and enter super password", duration=1.2)
    form = page.locator(f'form[action="/guests/{gid}/update"]')
    _type_loc(page, form.locator('input[name="name"]'), "Bob Edited")
    _type_loc(page, form.locator('textarea[name="notes"]'), "Acadia demo edit")
    _type_loc(page, form.locator('input[type="password"]'), "e2e-pass-123")
    _btn = form.get_by_role("button", name="Update profile")
    _btn.scroll_into_view_if_needed()
    box = _btn.bounding_box()
    if box:
        page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2, steps=15)
    _btn.click()
    page.wait_for_load_state("domcontentloaded")
    hide_update_modal(page)
    _end(page, "08_guest_edit_profile", "endpoint: guest profile updated")


# ── Reservations ─────────────────────────────────────────────────────────────


def _demo_create_reservation(page, base, guest_name="Acadia Create Guest"):
    _nav(page, "/reservations", "Reservations")
    _click_role(page, "link", "Create")
    page.wait_for_load_state("domcontentloaded")
    hide_update_modal(page)
    caption(page, "Action: fill guest, room, dates, rate", duration=1.2)
    demo_type(page, 'input[name="guest_name"]', guest_name, delay=55)
    page.locator("select[name=room_id]").select_option(index=0)
    demo_type(page, "input[name=check_in]", "2026-11-22", delay=55)
    demo_type(page, "input[name=check_out]", "2026-11-23", delay=55)
    demo_type(page, 'input[name="rate"]', "120", delay=55)
    _click_btn(page, "Create reservation")
    page.wait_for_url(lambda u: "/reservations" in u)
    page.wait_for_load_state("domcontentloaded")
    hide_update_modal(page)


def _demo_open_res_detail(page, base, guest_name):
    _demo_create_reservation(page, base, guest_name)
    caption(page, "Action: open reservation detail", duration=1.0)
    loc = page.locator('a[href^="/reservations/"]:not([href$="/reservations/groups"])').first
    loc.scroll_into_view_if_needed()
    box = loc.bounding_box()
    if box:
        page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2, steps=15)
    loc.click()
    page.wait_for_load_state("domcontentloaded")
    hide_update_modal(page)


def test_demo_reservation_create_video(e2e_server, page, setup_app, unlock):
    base = e2e_server.base_url
    _prep(page, base, e2e_server, setup_app, unlock)
    caption(page, "Start: / dashboard", duration=1.2)
    _demo_create_reservation(page, base, "Acadia Create Guest")
    _end(page, "09_reservation_create", "endpoint: reservation created")


def test_demo_reservation_detail_folio_video(e2e_server, page, setup_app, unlock):
    base = e2e_server.base_url
    _prep(page, base, e2e_server, setup_app, unlock)
    caption(page, "Start: / dashboard", duration=1.2)
    _demo_open_res_detail(page, base, "Folio Guest")
    caption(page, "Result: folio, payments, POS, invoices visible", duration=1.5)
    page.wait_for_timeout(1000)
    record_video(page, "10_reservation_detail_folio", trim_start=1.5, speed=0.85)


def test_demo_reservation_pricing_quote_video(e2e_server, page, setup_app, unlock):
    base = e2e_server.base_url
    _prep(page, base, e2e_server, setup_app, unlock)
    caption(page, "Start: / dashboard", duration=1.2)
    _nav(page, "/reservations", "Reservations")
    _click_role(page, "link", "Create")
    page.wait_for_load_state("domcontentloaded")
    hide_update_modal(page)
    caption(page, "Action: fill quote inputs and get pricing quote", duration=1.2)
    demo_type(page, 'input[name="guest_name"]', "Quote Guest", delay=55)
    page.locator("select[name=room_id]").select_option(index=0)
    demo_type(page, "input[name=check_in]", "2026-11-22", delay=55)
    demo_type(page, "input[name=check_out]", "2026-11-23", delay=55)
    demo_type(page, 'input[name="rate"]', "120", delay=55)
    _click_btn(page, "Get pricing quote")
    page.wait_for_load_state("domcontentloaded")
    hide_update_modal(page)
    expect(page.get_by_role("heading", name="Pricing quote (suggested)")).to_be_visible()
    _end(page, "11_reservation_pricing_quote", "endpoint: pricing quote shown")


def test_demo_reservation_checkin_video(e2e_server, page, setup_app, unlock):
    base = e2e_server.base_url
    _prep(page, base, e2e_server, setup_app, unlock)
    caption(page, "Start: / dashboard", duration=1.2)
    _demo_open_res_detail(page, base, "Checkin Guest")
    caption(page, "Action: click Check in", duration=1.2)
    _click_btn(page, "Check in")
    page.wait_for_load_state("domcontentloaded")
    hide_update_modal(page)
    _end(page, "12_reservation_checkin", "endpoint: reservation checked in")


def test_demo_reservation_groups_create_video(e2e_server, page, setup_app, unlock):
    base = e2e_server.base_url
    _prep(page, base, e2e_server, setup_app, unlock)
    caption(page, "Start: / dashboard", duration=1.2)
    _nav(page, "/reservations", "Reservations")
    caption(page, "Action: open Groups and create group", duration=1.2)
    _click_role(page, "link", "Groups")
    page.wait_for_load_state("domcontentloaded")
    hide_update_modal(page)
    demo_type(page, 'input[name="name"]', "Acadia Demo Group", delay=55)
    demo_type(page, 'input[name="contact_name"]', "Demo Travel", delay=55)
    _click_btn(page, "Create group")
    page.wait_for_load_state("domcontentloaded")
    hide_update_modal(page)
    _end(page, "13_reservation_groups_create", "endpoint: reservation group created")


def test_demo_reservation_groups_add_video(e2e_server, page, setup_app, unlock):
    base = e2e_server.base_url
    _prep(page, base, e2e_server, setup_app, unlock)
    caption(page, "Start: / dashboard", duration=1.2)
    _demo_open_res_detail(page, base, "Grouped Guest")
    _nav(page, "/reservations", "Reservations")
    _click_role(page, "link", "Groups")
    page.wait_for_load_state("domcontentloaded")
    hide_update_modal(page)
    demo_type(page, 'input[name="name"]', "Acadia Add Group", delay=55)
    _click_btn(page, "Create group")
    page.wait_for_load_state("domcontentloaded")
    hide_update_modal(page)
    caption(page, "Action: add reservation to group", duration=1.2)
    page.select_option('select[name="group_id"]', index=0)
    page.select_option('select[name="reservation_id"]', index=0)
    _click_btn(page, "Add to group")
    page.wait_for_load_state("domcontentloaded")
    hide_update_modal(page)
    _end(page, "14_reservation_groups_add", "endpoint: reservation added to group")


def test_demo_group_folio_video(e2e_server, page, setup_app, unlock):
    base = e2e_server.base_url
    _prep(page, base, e2e_server, setup_app, unlock)
    caption(page, "Start: / dashboard", duration=1.2)
    _demo_open_res_detail(page, base, "Folio Group Guest")
    _nav(page, "/reservations", "Reservations")
    _click_role(page, "link", "Groups")
    page.wait_for_load_state("domcontentloaded")
    hide_update_modal(page)
    demo_type(page, 'input[name="name"]', "Acadia Folio Group", delay=55)
    _click_btn(page, "Create group")
    page.wait_for_load_state("domcontentloaded")
    hide_update_modal(page)
    caption(page, "Action: open group folio", duration=1.2)
    loc = page.locator('a[href^="/reservations/groups/"][href$="/folio"]').first
    loc.scroll_into_view_if_needed()
    box = loc.bounding_box()
    if box:
        page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2, steps=15)
    loc.click()
    page.wait_for_load_state("domcontentloaded")
    hide_update_modal(page)
    _end(page, "15_group_folio", "endpoint: group folio/report")


# ── POS / Inventory ──────────────────────────────────────────────────────────


def test_demo_pos_inventory_tab_video(e2e_server, page, setup_app, unlock):
    base = e2e_server.base_url
    _prep(page, base, e2e_server, setup_app, unlock)
    caption(page, "Start: / dashboard", duration=1.2)
    _nav(page, "/pos", "POS / Inventory")
    caption(page, "Action: review inventory tab", duration=1.2)
    page.wait_for_load_state("domcontentloaded")
    _end(page, "16_pos_inventory_tab", "endpoint: /pos?tab=inventory")


def test_demo_pos_batches_tab_video(e2e_server, page, setup_app, unlock):
    base = e2e_server.base_url
    _prep(page, base, e2e_server, setup_app, unlock)
    caption(page, "Start: / dashboard", duration=1.2)
    _nav(page, "/pos", "POS / Inventory")
    caption(page, "Action: open Batches tab", duration=1.2)
    _click_role(page, "link", "Batches")
    page.wait_for_load_state("domcontentloaded")
    hide_update_modal(page)
    _end(page, "17_pos_batches_tab", "endpoint: /pos?tab=batches")


def test_demo_pos_history_tab_video(e2e_server, page, setup_app, unlock):
    base = e2e_server.base_url
    _prep(page, base, e2e_server, setup_app, unlock)
    caption(page, "Start: / dashboard", duration=1.2)
    _nav(page, "/pos", "POS / Inventory")
    caption(page, "Action: open History tab", duration=1.2)
    _click_role(page, "link", "History")
    page.wait_for_load_state("domcontentloaded")
    hide_update_modal(page)
    _end(page, "18_pos_history_tab", "endpoint: /pos?tab=history")


def test_demo_pos_add_to_reservation_video(e2e_server, page, setup_app, unlock):
    base = e2e_server.base_url
    _prep(page, base, e2e_server, setup_app, unlock)
    caption(page, "Start: / dashboard", duration=1.2)
    _demo_create_reservation(page, base, "POS Guest")
    _nav(page, "/pos", "POS / Inventory")
    caption(page, "Action: add POS item to reservation folio", duration=1.2)
    form = page.locator('form[action="/pos/add"]')
    form.locator('select[name="reservation_id"]').select_option(index=1)
    _type_loc(page, form.locator('input[name="desc"]'), "Acadia Demo Service")
    _type_loc(page, form.locator('input[name="qty"]'), "2")
    _type_loc(page, form.locator('input[name="price"]'), "25")
    _click_btn(page, "Add to reservation")
    page.wait_for_load_state("domcontentloaded")
    hide_update_modal(page)
    expect(page.get_by_text("POS item added to reservation").first).to_be_visible()
    _end(page, "19_pos_add_to_reservation", "endpoint: POS item added to reservation")


# ── Housekeeping ─────────────────────────────────────────────────────────────


def test_demo_housekeeping_task_video(e2e_server, page, setup_app, unlock):
    base = e2e_server.base_url
    _prep(page, base, e2e_server, setup_app, unlock)
    caption(page, "Start: / dashboard", duration=1.2)
    _nav(page, "/housekeeping", "Housekeeping")
    caption(page, "Action: create housekeeping task", duration=1.2)
    page.locator('details summary:has-text("Create task")').click()
    page.wait_for_timeout(400)
    form = page.locator('form[action="/housekeeping/tasks/create"]')
    form.locator("select[name='room_id']").select_option(index=0)
    _type_loc(page, form.locator('input[name="task_type"]'), "cleaning")
    _type_loc(page, form.locator('input[name="assignee"]'), "Acadia Staff")
    btn = form.get_by_role("button", name="Create task")
    btn.scroll_into_view_if_needed()
    box = btn.bounding_box()
    if box:
        page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2, steps=15)
    btn.click()
    page.wait_for_load_state("domcontentloaded")
    hide_update_modal(page)
    _end(page, "20_housekeeping_task", "endpoint: housekeeping task created")


# ── Accounting ───────────────────────────────────────────────────────────────


def test_demo_accounting_expense_video(e2e_server, page, setup_app, unlock, seed_expense_category):
    base = e2e_server.base_url
    _prep(page, base, e2e_server, setup_app, unlock)
    seed_expense_category("Acadia Expense")
    caption(page, "Start: / dashboard", duration=1.2)
    _nav(page, "/accounting", "Accounting")
    _click_role(page, "link", "Expenses")
    page.wait_for_load_state("domcontentloaded")
    hide_update_modal(page)
    caption(page, "Action: record an expense", duration=1.2)
    demo_type(page, 'input[name="param"]', "Acadia Demo Expense", delay=55)
    demo_type(page, 'input[name="amount"]', "85.00", delay=55)
    page.select_option('select[name="cat_id"]', index=0)
    _click_btn(page, "Record expense")
    page.wait_for_load_state("domcontentloaded")
    hide_update_modal(page)
    expect(page.get_by_text("Expense recorded")).to_be_visible()
    _end(page, "21_accounting_expense", "endpoint: expense recorded")


def test_demo_accounting_void_expense_video(e2e_server, page, setup_app, unlock, seed_expense_category):
    base = e2e_server.base_url
    _prep(page, base, e2e_server, setup_app, unlock)
    seed_expense_category("Acadia Expense")
    caption(page, "Start: / dashboard", duration=1.2)
    _nav(page, "/accounting", "Accounting")
    _click_role(page, "link", "Expenses")
    page.wait_for_load_state("domcontentloaded")
    hide_update_modal(page)
    demo_type(page, 'input[name="param"]', "Acadia Voidable Expense", delay=55)
    demo_type(page, 'input[name="amount"]', "10.00", delay=55)
    page.select_option('select[name="cat_id"]', index=0)
    _click_btn(page, "Record expense")
    page.wait_for_load_state("domcontentloaded")
    hide_update_modal(page)
    caption(page, "Action: void the expense (audited reversal)", duration=1.2)
    form = page.locator('form[action^="/accounting/expense/"][action$="/void"]').first
    _type_loc(page, form.locator('input[name="password"]'), "e2e-pass-123")
    btn = form.get_by_role("button", name="Void")
    btn.scroll_into_view_if_needed()
    box = btn.bounding_box()
    if box:
        page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2, steps=15)
    btn.click()
    page.wait_for_load_state("domcontentloaded")
    hide_update_modal(page)
    expect(page.get_by_text("Expense voided").first).to_be_visible()
    _end(page, "22_accounting_void_expense", "endpoint: expense voided")


def test_demo_accounting_payment_video(e2e_server, page, setup_app, unlock):
    base = e2e_server.base_url
    _prep(page, base, e2e_server, setup_app, unlock)
    caption(page, "Start: / dashboard", duration=1.2)
    _nav(page, "/accounting", "Accounting")
    _click_role(page, "link", "Payments")
    page.wait_for_load_state("domcontentloaded")
    hide_update_modal(page)
    caption(page, "Action: record a payment", duration=1.2)
    demo_type(page, 'input[name="amount"]', "75.00", delay=55)
    _click_btn(page, "Record payment")
    page.wait_for_load_state("domcontentloaded")
    hide_update_modal(page)
    expect(page.get_by_text("Payment recorded")).to_be_visible()
    _end(page, "23_accounting_payment", "endpoint: payment recorded")


def test_demo_accounting_shift_video(e2e_server, page, setup_app, unlock):
    base = e2e_server.base_url
    _prep(page, base, e2e_server, setup_app, unlock)
    caption(page, "Start: / dashboard", duration=1.2)
    _nav(page, "/accounting", "Accounting")
    _click_role(page, "link", "Shifts")
    page.wait_for_load_state("domcontentloaded")
    hide_update_modal(page)
    caption(page, "Action: open shift and record movement", duration=1.2)
    _click_btn(page, "Open shift")
    page.wait_for_load_state("domcontentloaded")
    hide_update_modal(page)
    demo_type(page, 'input[name="amount"]', "200.00", delay=55)
    _click_btn(page, "Record movement")
    page.wait_for_load_state("domcontentloaded")
    hide_update_modal(page)
    expect(page.get_by_text("Cash movement recorded")).to_be_visible()
    _end(page, "24_accounting_shift", "endpoint: shift opened, movement recorded")


def test_demo_accounting_night_audit_video(e2e_server, page, setup_app, unlock):
    base = e2e_server.base_url
    _prep(page, base, e2e_server, setup_app, unlock)
    caption(page, "Start: / dashboard", duration=1.2)
    _nav(page, "/accounting", "Accounting")
    _click_role(page, "link", "Night audit")
    page.wait_for_load_state("domcontentloaded")
    hide_update_modal(page)
    caption(page, "Action: run night-audit snapshot", duration=1.2)
    _click_btn(page, "Run & record snapshot")
    page.wait_for_load_state("domcontentloaded")
    hide_update_modal(page)
    expect(page.get_by_text("Night audit snapshot recorded (advisory)")).to_be_visible()
    _end(page, "25_accounting_night_audit", "endpoint: night audit snapshot recorded")


def test_demo_accounting_ledger_video(e2e_server, page, setup_app, unlock):
    base = e2e_server.base_url
    _prep(page, base, e2e_server, setup_app, unlock)
    caption(page, "Start: / dashboard", duration=1.2)
    _nav(page, "/accounting", "Accounting")
    _click_role(page, "link", "Ledger")
    page.wait_for_load_state("domcontentloaded")
    hide_update_modal(page)
    caption(page, "Action: review ledger entries", duration=1.2)
    page.wait_for_timeout(1200)
    _end(page, "26_accounting_ledger", "endpoint: accounting ledger")


# ── Reports ──────────────────────────────────────────────────────────────────


def test_demo_reports_pl_video(e2e_server, page, setup_app, unlock):
    base = e2e_server.base_url
    _prep(page, base, e2e_server, setup_app, unlock)
    caption(page, "Start: / dashboard", duration=1.2)
    _nav(page, "/reports", "Reports & Analytics")
    caption(page, "Action: generate P&L report", duration=1.2)
    page.select_option('select[name="kind"]', "pl")
    _click_btn(page, "Generate")
    page.wait_for_load_state("domcontentloaded")
    hide_update_modal(page)
    expect(page.get_by_text("Report generated")).to_be_visible()
    _end(page, "27_reports_pl", "endpoint: P&L report generated")


def test_demo_reports_analytics_export_video(e2e_server, page, setup_app, unlock):
    base = e2e_server.base_url
    _prep(page, base, e2e_server, setup_app, unlock)
    caption(page, "Start: / dashboard", duration=1.2)
    _nav(page, "/reports", "Reports & Analytics")
    caption(page, "Action: export analytics", duration=1.2)
    _click_btn(page, "Export (JSON/TXT/CSV as configured)")
    page.wait_for_load_state("domcontentloaded")
    hide_update_modal(page)
    expect(page.get_by_text("Analytics export created:").first).to_be_visible()
    _end(page, "28_reports_analytics_export", "endpoint: analytics export created")


# ── Assistant ────────────────────────────────────────────────────────────────


def test_demo_assistant_ask_video(e2e_server, page, setup_app, unlock):
    base = e2e_server.base_url
    _prep(page, base, e2e_server, setup_app, unlock)
    caption(page, "Start: / dashboard", duration=1.2)
    _nav(page, "/assistant", "Manager Assistant")
    caption(page, "Action: ask a grounded question", duration=1.2)
    demo_type(page, 'textarea[name="message"]', "Who owes money?", delay=55)
    _click_btn(page, "Send message")
    page.wait_for_load_state("domcontentloaded")
    hide_update_modal(page)
    _end(page, "29_assistant_ask", "endpoint: assistant response shown")


# ── Settings / Support ───────────────────────────────────────────────────────


def test_demo_settings_general_save_video(e2e_server, page, setup_app, unlock, password):
    base = e2e_server.base_url
    _prep(page, base, e2e_server, setup_app, unlock)
    caption(page, "Start: / dashboard", duration=1.2)
    _nav(page, "/settings", "Settings / Branding")
    caption(page, "Action: save settings with super password", duration=1.2)
    form = page.locator('form[action="/settings/save"]')
    _type_loc(page, form.locator('input[name="password"]'), password)
    _click_btn(page, "Save settings")
    page.wait_for_load_state("domcontentloaded")
    hide_update_modal(page)
    expect(page.get_by_text("Saved").first).to_be_visible()
    _end(page, "30_settings_general_save", "endpoint: settings saved")


def test_demo_settings_branding_video(e2e_server, page, setup_app, unlock):
    base = e2e_server.base_url
    _prep(page, base, e2e_server, setup_app, unlock)
    caption(page, "Start: / dashboard", duration=1.2)
    _nav(page, "/settings", "Settings / Branding")
    caption(page, "Action: apply branding display name", duration=1.2)
    form = page.locator('form[action="/settings/branding"]')
    _type_loc(page, form.locator('input[name="display_name"]'), "Acadia Camp Renamed")
    _click_btn(page, "Apply branding")
    page.wait_for_load_state("domcontentloaded")
    hide_update_modal(page)
    expect(page.get_by_text("Branding updated")).to_be_visible()
    _end(page, "31_settings_branding", "endpoint: branding updated")


def test_demo_settings_rooms_video(e2e_server, page, setup_app, unlock):
    base = e2e_server.base_url
    _prep(page, base, e2e_server, setup_app, unlock)
    caption(page, "Start: / dashboard", duration=1.2)
    _nav(page, "/settings", "Settings / Branding")
    _click_role(page, "link", "Rooms")
    page.wait_for_load_state("domcontentloaded")
    hide_update_modal(page)
    caption(page, "Action: add a room", duration=1.2)
    demo_type(page, 'input[name="room_number"]', "Acadia Video Room", delay=55)
    demo_type(page, 'input[name="room_type"]', "Standard Room", delay=55)
    _click_btn(page, "Add room")
    page.wait_for_load_state("domcontentloaded")
    hide_update_modal(page)
    _end(page, "32_settings_rooms", "endpoint: room added")


def test_demo_settings_rate_plans_video(e2e_server, page, setup_app, unlock, password):
    base = e2e_server.base_url
    _prep(page, base, e2e_server, setup_app, unlock)
    caption(page, "Start: / dashboard", duration=1.2)
    _nav(page, "/settings", "Settings / Branding")
    page.goto(base + "/settings/rate-plans", wait_until="domcontentloaded")
    hide_update_modal(page)
    demo_install_cursor(page)
    caption(page, "Action: add rate plan", duration=1.2)
    form = page.locator('form[action="/settings/rate-plans/add"]')
    _type_loc(page, form.locator('input[name="name"]'), "Acadia Video Plan")
    _type_loc(page, form.locator('input[name="modifier"]'), "3")
    _type_loc(page, form.locator('input[name="password"]'), password)
    _click_btn(page, "Add")
    page.wait_for_load_state("domcontentloaded")
    hide_update_modal(page)
    expect(page.get_by_text("Acadia Video Plan").first).to_be_visible()
    _end(page, "33_settings_rate_plans", "endpoint: rate plan added")


def test_demo_settings_users_video(e2e_server, page, setup_app, unlock, password):
    base = e2e_server.base_url
    _prep(page, base, e2e_server, setup_app, unlock)
    caption(page, "Start: / dashboard", duration=1.2)
    _nav(page, "/settings", "Settings / Branding")
    page.goto(base + "/settings/users", wait_until="domcontentloaded")
    hide_update_modal(page)
    demo_install_cursor(page)
    caption(page, "Action: create user", duration=1.2)
    form = page.locator('form[action="/settings/users/add"]')
    _type_loc(page, form.locator('input[name="username"]'), "e2evideo1")
    _type_loc(page, form.locator('input[name="display_name"]'), "Acadia Video User")
    _type_loc(page, form.locator('input[name="password"]'), password)
    _click_btn(page, "Create user")
    page.wait_for_load_state("domcontentloaded")
    hide_update_modal(page)
    expect(page.get_by_text("User created").first).to_be_visible()
    _end(page, "34_settings_users", "endpoint: user created")


def test_demo_settings_health_video(e2e_server, page, setup_app, unlock):
    base = e2e_server.base_url
    _prep(page, base, e2e_server, setup_app, unlock)
    caption(page, "Start: / dashboard", duration=1.2)
    _nav(page, "/settings", "Settings / Branding")
    page.goto(base + "/settings/health", wait_until="domcontentloaded")
    hide_update_modal(page)
    demo_install_cursor(page)
    caption(page, "Action: view data health checks", duration=1.2)
    page.wait_for_timeout(1200)
    _end(page, "35_settings_health", "endpoint: settings/health")


def test_demo_support_report_video(e2e_server, page, setup_app, unlock):
    base = e2e_server.base_url
    _prep(page, base, e2e_server, setup_app, unlock)
    caption(page, "Start: / dashboard", duration=1.2)
    _nav(page, "/support/report", "Report issue")
    caption(page, "Action: review privacy-safe diagnostics preview", duration=1.2)
    page.wait_for_timeout(1200)
    _end(page, "36_support_report", "endpoint: support/report")
