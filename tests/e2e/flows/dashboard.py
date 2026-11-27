"""Dashboard flows."""
from __future__ import annotations

from playwright.sync_api import expect

from .common import click_button, ensure_demo_ready, maybe_caption, nav_click, type_into


def overview(page, base: str):
    nav_click(page, "/", "Dashboard")
    expect(page).to_have_url(base + "/")
    expect(page.get_by_text("Front Desk / Today Ops").first).to_be_visible()
    maybe_caption(page, "Start: dashboard overview", duration=1.2)


def filter_day(page, base: str, day: str):
    maybe_caption(page, f"Action: filter dashboard day {day}", duration=1.0)
    type_into(page, 'input[name="day"]', day, delay=60)
    click_button(page, "View")
    page.wait_for_load_state("domcontentloaded")
    ensure_demo_ready(page)
    expect(page.locator('input[name="day"]')).to_have_value(day)
    maybe_caption(page, "Result: dashboard filtered", duration=1.0)
