"""Reports flows."""
from __future__ import annotations

import re

from playwright.sync_api import expect

from .common import assert_url_contains, click_link, ensure_demo_ready, maybe_caption, nav_click


def open_tab(page, base: str, tab: str, label: str):
    nav_click(page, "/reports", "Reports & Analytics")
    subtab = page.locator(f'.subtabs a[href*="tab={tab}"]').first
    expect(subtab).to_be_visible()
    subtab.click()
    page.wait_for_load_state("domcontentloaded")
    ensure_demo_ready(page)
    assert_url_contains(page, f"tab={tab}")
    maybe_caption(page, f"Sub-tab: Reports {label}", duration=1.0)


def generate_report(page, kind: str = "pl"):
    maybe_caption(page, f"Action: generate report '{kind}'", duration=1.2)
    form = page.locator('form[action="/reports/run"]').first
    form.locator('select[name="kind"]').select_option(kind)
    form.get_by_role("button", name="Generate").click()
    page.wait_for_load_state("domcontentloaded")
    ensure_demo_ready(page)
    expect(page.get_by_text(re.compile(r"Report generated|Report:", re.I)).first).to_be_visible()
