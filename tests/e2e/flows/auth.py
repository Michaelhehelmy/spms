"""Auth/setup flows with assertions."""
from __future__ import annotations

from playwright.sync_api import expect

from conftest import TEST_PASSWORD
from .common import click_button, ensure_demo_ready, goto, maybe_caption, nav_click, type_into, select_overlay


def setup_wizard(page, base: str, *, name="Acadia Camp", tagline="Desert comfort, thoughtfully hosted.", animation="reveal"):
    maybe_caption(page, "Start: /setup — first-run Setup Wizard", duration=1.8)
    goto(page, base, "/setup")
    page.wait_for_selector('form[action="/setup"]', state="visible", timeout=15000)
    ensure_demo_ready(page)
    type_into(page, 'input[name="display_name"]', name, delay=70)
    type_into(page, 'input[name="tagline"]', tagline, delay=55)
    select_overlay(page, 'select[name="animation"]', animation)
    maybe_caption(page, "Action: save setup", duration=1.0)
    if getattr(page, "_demo_mode", False):
        page.evaluate("() => { const el = document.getElementById('demo-caption'); if (el) el.remove(); }")
        page.wait_for_timeout(200)
        page.locator('form[action="/setup"] button[type="submit"]').scroll_into_view_if_needed()
        box = page.locator('form[action="/setup"] button[type="submit"]').bounding_box()
        if box:
            page.mouse.move(box['x']+box['width']/2, box['y']+box['height']/2, steps=15)
        page.evaluate('document.querySelector(\'form[action="/setup"] button[type="submit"]\').click()')
    else:
        page.locator('form[action="/setup"] button[type="submit"]').click()
    page.wait_for_url(lambda u: u.rstrip("/") == base, timeout=20000)
    page.wait_for_load_state("domcontentloaded")
    ensure_demo_ready(page)
    expect(page).to_have_url(base + "/")
    maybe_caption(page, "Result: setup saved, redirected to dashboard", duration=1.5)


def create_super_password(page, base: str, password: str = TEST_PASSWORD):
    maybe_caption(page, "Action: first-run create super password", duration=1.5)
    unlock_link = page.locator('a[href="/unlock"]').first
    if unlock_link.count() == 0:
        goto(page, base, "/unlock")
    else:
        unlock_link.scroll_into_view_if_needed()
        if getattr(page, "_demo_mode", False):
            box = unlock_link.bounding_box()
            if box:
                page.mouse.move(box['x']+box['width']/2, box['y']+box['height']/2, steps=15)
        unlock_link.click()
        page.wait_for_load_state("domcontentloaded")
        ensure_demo_ready(page)
    expect(page.locator('input[name="password"]')).to_be_visible()
    if page.locator('input[name="confirm_password"]').count() > 0:
        type_into(page, 'input[name="password"]', password, delay=70)
        type_into(page, 'input[name="confirm_password"]', password, delay=70)
        click_button(page, "Create password & unlock")
    else:
        type_into(page, 'input[name="password"]', password, delay=70)
        click_button(page, "Unlock")
    page.wait_for_load_state("domcontentloaded")
    ensure_demo_ready(page)
    expect(page.locator('form[action="/lock"]')).to_be_visible()
    maybe_caption(page, "Result: super password created/unlocked", duration=1.2)


def unlock(page, base: str, password: str = TEST_PASSWORD):
    goto(page, base, "/unlock")
    if page.locator('input[name="confirm_password"]').count() > 0:
        return create_super_password(page, base, password=password)
    type_into(page, 'input[name="password"]', password, delay=70)
    click_button(page, "Unlock")
    page.wait_for_load_state("domcontentloaded")
    ensure_demo_ready(page)
    expect(page.locator('form[action="/lock"]')).to_be_visible()


def lock(page, base: str):
    maybe_caption(page, "Action: lock session", duration=1.0)
    if page.locator('form[action="/lock"]').count() == 0:
        nav_click(page, "/", "Dashboard")
    click_button(page, "Lock session")
    page.wait_for_load_state("domcontentloaded")
    ensure_demo_ready(page)
    expect(page.locator('a[href="/unlock"]').first).to_be_visible()
    maybe_caption(page, "Result: session locked", duration=1.0)
