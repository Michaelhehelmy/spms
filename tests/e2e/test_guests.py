"""tests/e2e/test_guests.py — guests directory/portfolio/edit (app issue #42).

Covers: guest search, guest 360 portfolio open, guest profile edit via UI.
"""
from __future__ import annotations

import pytest
from playwright.sync_api import expect


def test_guest_search_and_no_results(e2e_server, page, setup_app, unlock):
    base = e2e_server.base_url
    setup_app("E2E Property")
    unlock()
    page.goto(base + "/guests?tab=directory")
    expect(page.get_by_role("button", name="Search")).to_be_visible()
    page.fill('input[name="q"]', "NoSuchGuestName")
    page.get_by_role("button", name="Search").click()
    page.wait_for_load_state("networkidle")
    expect(page.get_by_text("No guests found")).to_be_visible()


def test_guest_search_and_open_portfolio(e2e_server, page, setup_app, unlock, seed_guest):
    base = e2e_server.base_url
    setup_app("E2E Property")
    unlock()
    gid = seed_guest("Alice Example", phone="+1234567890", email="alice@example.com")
    page.goto(base + "/guests?tab=directory")
    page.fill('input[name="q"]', "Alice")
    page.get_by_role("button", name="Search").click()
    page.wait_for_load_state("networkidle")
    expect(page.get_by_text("Alice Example").first).to_be_visible()
    page.get_by_role("link", name="Open portfolio").click()
    page.wait_for_load_state("networkidle")
    assert page.url == f"{base}/guests/{gid}"
    expect(page.get_by_text("360° view")).to_be_visible()
    expect(page.get_by_text("Alice Example").first).to_be_visible()


def test_guest_edit_profile_via_ui(e2e_server, page, setup_app, unlock, seed_guest, password):
    base = e2e_server.base_url
    setup_app("E2E Property")
    unlock()
    gid = seed_guest("Bob Example", phone="+1999887766", email="bob@example.com")
    page.goto(base + f"/guests/{gid}")
    expect(page.get_by_text("Bob Example").first).to_be_visible()
    page.fill('input[name="name"]', "Bob Edited")
    page.fill('input[name="phone"]', "+1234567890")
    page.fill('input[name="email"]', "bob.edited@example.com")
    page.fill('textarea[name="notes"]', "E2E edited notes")
    page.fill('input[type="password"]', password)
    page.get_by_role("button", name="Update profile").click()
    page.wait_for_load_state("networkidle")
    expect(page.get_by_text("Guest updated")).to_be_visible()
    expect(page.locator('input[name="name"]')).to_have_value("Bob Edited")
