"""Guest flows."""
from __future__ import annotations

import re

from playwright.sync_api import expect

from conftest import TEST_PASSWORD
from .common import (
    assert_url_contains,
    click_button,
    click_link,
    ensure_demo_ready,
    maybe_caption,
    nav_click,
    type_into,
)


def open_directory(page, base: str):
    nav_click(page, "/guests", "Guests")
    assert_url_contains(page, "/guests")
    expect(page.get_by_role("button", name="Search")).to_be_visible()
    maybe_caption(page, "Sub-tab: Guests directory", duration=1.0)


def search(page, base: str, query: str):
    open_directory(page, base)
    maybe_caption(page, f"Action: search guests for '{query}'", duration=1.2)
    type_into(page, 'input[name="q"]', query)
    click_button(page, "Search")
    page.wait_for_load_state("domcontentloaded")
    ensure_demo_ready(page)
    expect(page.locator('input[name="q"]')).to_have_value(query)


def open_portfolio_from_directory(page, name: str):
    maybe_caption(page, f"Action: open portfolio for {name}", duration=1.2)
    row = page.locator("tr", has_text=name).first
    expect(row).to_be_visible()
    row.get_by_role("link", name="Open portfolio").click()
    page.wait_for_load_state("domcontentloaded")
    ensure_demo_ready(page)
    assert_url_contains(page, "/guests/")
    expect(page.get_by_role("heading", name=re.compile(r"Guest portfolio")).first).to_be_visible()
    expect(page.get_by_text(name).first).to_be_visible()


def edit_profile(page, *, name: str, phone: str, email: str, notes: str, password: str = TEST_PASSWORD):
    maybe_caption(page, "Action: edit guest profile (super password required)", duration=1.5)
    form = page.locator('form[action*="/update"]').first
    expect(form).to_be_visible()
    type_into(page, 'input[name="name"]', name)
    type_into(page, 'input[name="phone"]', phone)
    type_into(page, 'input[name="email"]', email)
    form.locator('textarea[name="notes"]').fill(notes)
    type_into(page, 'input[name="password"]', password)
    form.get_by_role("button", name="Update profile").click()
    page.wait_for_load_state("domcontentloaded")
    ensure_demo_ready(page)
    expect(page.get_by_text("Guest updated").first).to_be_visible()
    expect(page.get_by_text(name).first).to_be_visible()
