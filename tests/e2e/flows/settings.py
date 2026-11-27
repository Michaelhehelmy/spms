"""Settings flows."""
from __future__ import annotations

import re

from playwright.sync_api import expect

from .common import assert_url_contains, click_link, ensure_demo_ready, maybe_caption, nav_click


def open_tab(page, base: str, tab: str, label: str):
    nav_click(page, "/settings", "Settings / Branding")
    subtab = page.locator(f'.subtabs a[href*="tab={tab}"]').first
    expect(subtab).to_be_visible()
    subtab.click()
    page.wait_for_load_state("domcontentloaded")
    ensure_demo_ready(page)
    assert_url_contains(page, f"tab={tab}")
    maybe_caption(page, f"Sub-tab: Settings {label}", duration=1.0)
