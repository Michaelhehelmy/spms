"""Combined demo videos (silent, captioned) — SPMS.

6 videos covering related actions in business flow. All except Video 1 start at `/`.
See docs/DEMO_VIDEOS.md for the plan.
"""
from __future__ import annotations

import os
import pytest

pytest.importorskip("playwright")

pytestmark = pytest.mark.skipif(
    os.environ.get("E2E_DEMO", "").lower() not in ("1", "true", "yes", "on", "demo"),
    reason="Demo video recording; set E2E_DEMO=1",
)

from playwright.sync_api import expect

from conftest import (
    TEST_PASSWORD,
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


def _prep_dashboard(page, base, setup_app, unlock):
    """Setup app, unlock, land on dashboard with cursor/modal-hide ready."""
    setup_app("Acadia Camp")
    unlock()
    page.goto(base + "/", wait_until="domcontentloaded")
    page.add_style_tag(content="#update-modal-backdrop,.modal-backdrop{display:none!important}")
    hide_update_modal(page)
    demo_install_cursor(page)
    page.wait_for_timeout(1200)


def _nav(page, href: str, label: str):
    caption(page, f"Navigate: {label}", duration=1.0)
    sel = f'a.nav-link[href="{href}"]'
    demo_move(page, sel)
    page.locator(sel).first.click()
    page.wait_for_load_state("domcontentloaded")
    page.add_style_tag(content="#update-modal-backdrop,.modal-backdrop{display:none!important}")
    hide_update_modal(page)
    demo_install_cursor(page)
    page.wait_for_timeout(600)


def _click_btn(page, name: str, *, exact: bool = False):
    loc = page.get_by_role("button", name=name, exact=exact) if exact else page.get_by_role("button", name=name)
    if loc.count() > 1:
        loc = loc.first
    loc.scroll_into_view_if_needed()
    box = loc.bounding_box()
    if box:
        page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2, steps=15)
    loc.click()
    page.wait_for_timeout(250)


def _click_link(page, name: str, *, exact: bool = False):
    loc = page.get_by_role("link", name=name, exact=exact) if exact else page.get_by_role("link", name=name)
    if loc.count() > 1:
        loc = loc.first
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


def _select_overlay(page, selector: str, value: str, label: str):
    """Show a visual dropdown overlay for native select (OS dropdown not captured in video)."""
    demo_move(page, selector)
    page.locator(selector).click()
    page.evaluate(
        """({selector, value, label}) => {
            const sel = document.querySelector(selector);
            const r = sel.getBoundingClientRect();
            const overlay = document.createElement('div');
            overlay.id = 'demo-select-overlay';
            Object.assign(overlay.style, {
                position: 'fixed', left: r.left + 'px', top: (r.bottom + 4) + 'px',
                width: Math.max(r.width, 220) + 'px', background: '#fff', color: '#111',
                border: '1px solid #bbb', borderRadius: '6px',
                boxShadow: '0 8px 24px rgba(0,0,0,.18)', zIndex: '2147483647',
                font: '14px/1.4 sans-serif', overflow: 'hidden',
            });
            const opts = Array.from(sel.options).map(o => [o.value, o.textContent.trim()]);
            opts.forEach(([val, text]) => {
                const item = document.createElement('div');
                item.textContent = text;
                Object.assign(item.style, { padding: '8px 12px', cursor: 'pointer' });
                if (val === value) item.style.background = '#e8f0fe';
                overlay.appendChild(item);
            });
            document.body.appendChild(overlay);
        }""",
        {"selector": selector, "value": value, "label": label},
    )
    page.wait_for_timeout(700)
    box = page.locator(selector).bounding_box()
    if box:
        # Click near the chosen option (first match for simplicity)
        options = page.locator(f'{selector} option')
        idx = 0
        for i in range(options.count()):
            if options.nth(i).get_attribute("value") == value:
                idx = i
                break
        page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] + 20 + idx * 34, steps=15)
        page.wait_for_timeout(250)
        page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] + 20 + idx * 34)
    page.select_option(selector, value)
    page.evaluate("() => { const el = document.getElementById('demo-select-overlay'); if (el) el.remove(); }")
    page.wait_for_timeout(500)


# ── Video 1 — Setup, Access & Dashboard Orientation ─────────────────────────


def test_demo_v1_setup_access_dashboard(e2e_server_fresh, page):
    base = e2e_server_fresh.base_url

    # --- Setup wizard ---
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
    page.add_style_tag(content="#update-modal-backdrop,.modal-backdrop{display:none!important}")
    page.wait_for_selector('form[action="/setup"]', state="visible", timeout=15000)
    hide_update_modal(page)
    demo_install_cursor(page)
    page.wait_for_timeout(2000)

    caption(page, "Start: /setup — first-run Setup Wizard", duration=2.0)
    caption(page, "Action: fill property branding fields", duration=1.2)
    demo_type(page, 'input[name="display_name"]', "Acadia Camp", delay=70)
    demo_type(page, 'input[name="tagline"]', "Desert comfort, thoughtfully hosted.", delay=55)
    _select_overlay(page, 'select[name="animation"]', "reveal", "Reveal letters")

    caption(page, "Action: save setup", duration=1.2)
    page.evaluate("() => { const el = document.getElementById('demo-caption'); if (el) el.remove(); }")
    page.wait_for_timeout(200)
    demo_move(page, 'form[action="/setup"] button[type="submit"]')
    page.evaluate('document.querySelector(\'form[action="/setup"] button[type="submit"]\').click()')
    page.wait_for_url(lambda u: u.rstrip("/") == base, timeout=20000)
    page.wait_for_load_state("domcontentloaded")
    page.add_style_tag(content="#update-modal-backdrop,.modal-backdrop{display:none!important}")
    hide_update_modal(page)
    demo_install_cursor(page)
    page.wait_for_timeout(1200)
    caption(page, "Result: branding saved, redirected to dashboard /", duration=1.8)

    # --- First-run super password creation + Lock / Unlock ---
    caption(page, "Action: first-run secure setup — create super password", duration=1.8)
    unlock_link = page.locator('a[href="/unlock"]').first
    unlock_link.scroll_into_view_if_needed()
    box = unlock_link.bounding_box()
    if box:
        page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2, steps=15)
    unlock_link.click()
    page.wait_for_load_state("domcontentloaded")
    page.add_style_tag(content="#update-modal-backdrop,.modal-backdrop{display:none!important}")
    hide_update_modal(page)
    demo_install_cursor(page)
    page.wait_for_timeout(600)

    if page.locator('input[name="confirm_password"]').count() > 0:
        caption(page, "Action: create and confirm super password", duration=1.5)
        demo_type(page, 'input[name="password"]', TEST_PASSWORD, delay=70)
        demo_type(page, 'input[name="confirm_password"]', TEST_PASSWORD, delay=70)
        _click_btn(page, "Create password & unlock")
    else:
        caption(page, "Action: enter super password", duration=1.2)
        demo_type(page, 'input[name="password"]', TEST_PASSWORD, delay=70)
        _click_btn(page, "Unlock")
    page.wait_for_load_state("domcontentloaded")
    page.add_style_tag(content="#update-modal-backdrop,.modal-backdrop{display:none!important}")
    hide_update_modal(page)
    demo_install_cursor(page)
    page.wait_for_timeout(800)
    caption(page, "Result: super password created; session unlocked", duration=1.5)

    caption(page, "Action: lock session from top-right", duration=1.2)
    if "/unlock" in page.url or page.locator('form[action="/lock"]').count() == 0:
        _nav(page, "/", "Dashboard")
    lock_btn = page.get_by_role("button", name="Lock session")
    if lock_btn.count() > 0:
        lock_btn.first.scroll_into_view_if_needed()
        box = lock_btn.first.bounding_box()
        if box:
            page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2, steps=15)
        lock_btn.first.click()
        page.wait_for_load_state("domcontentloaded")
        page.add_style_tag(content="#update-modal-backdrop,.modal-backdrop{display:none!important}")
        hide_update_modal(page)
        demo_install_cursor(page)
        page.wait_for_timeout(800)
    caption(page, "Result: session locked; protected actions require unlock", duration=1.5)

    caption(page, "Action: unlock again to continue", duration=1.2)
    unlock_link = page.locator('a[href="/unlock"]').first
    if unlock_link.count() > 0:
        unlock_link.scroll_into_view_if_needed()
        box = unlock_link.bounding_box()
        if box:
            page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2, steps=15)
        unlock_link.click()
        page.wait_for_load_state("domcontentloaded")
        page.add_style_tag(content="#update-modal-backdrop,.modal-backdrop{display:none!important}")
        hide_update_modal(page)
        demo_install_cursor(page)
    if page.locator('input[name="password"]').count() > 0:
        demo_type(page, 'input[name="password"]', TEST_PASSWORD, delay=70)
        _click_btn(page, "Unlock")
        page.wait_for_load_state("domcontentloaded")
        page.add_style_tag(content="#update-modal-backdrop,.modal-backdrop{display:none!important}")
        hide_update_modal(page)
        demo_install_cursor(page)
    caption(page, "Result: unlocked; ready for dashboard overview", duration=1.2)

    # --- Dashboard orientation ---
    _nav(page, "/", "Dashboard")
    caption(page, "Start section: Dashboard / ops overview", duration=1.5)
    caption(page, "Action: review occupancy, arrivals, departures, exceptions", duration=1.8)
    page.mouse.wheel(0, 350)
    page.wait_for_timeout(900)
    page.mouse.wheel(0, -350)
    page.wait_for_timeout(700)

    caption(page, "Action: filter ops day", duration=1.2)
    demo_type(page, 'input[name="day"]', "2026-11-23", delay=60)
    _click_btn(page, "View")
    page.wait_for_load_state("domcontentloaded")
    page.add_style_tag(content="#update-modal-backdrop,.modal-backdrop{display:none!important}")
    hide_update_modal(page)
    demo_install_cursor(page)
    page.wait_for_timeout(1200)

    caption(page, "Result: dashboard filtered by selected ops day", duration=1.5)

    # --- App overview: navigate all main tabs ---
    caption(page, "Action: overview — navigate all main app tabs", duration=1.8)
    for href, label in [
        ("/reservations", "Reservations"),
        ("/guests", "Guests"),
        ("/housekeeping", "Housekeeping"),
        ("/pos", "POS / Inventory"),
        ("/accounting", "Accounting"),
        ("/reports", "Reports & Analytics"),
        ("/settings", "Settings / Branding"),
        ("/support/report", "Report issue"),
    ]:
        _nav(page, href, label)
        page.wait_for_timeout(900)

    _nav(page, "/", "Dashboard")
    caption(page, "Result: full app overview complete; endpoint /", duration=2.0)
    page.wait_for_timeout(1500)
    record_video(page, "01_setup_access_dashboard", trim_start=1.5, speed=0.85)
