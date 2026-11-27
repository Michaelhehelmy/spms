"""Support/report flows."""
from __future__ import annotations

import re

from playwright.sync_api import expect

from .common import ensure_demo_ready, maybe_caption, nav_click, type_into


def open_page(page, base: str):
    nav_click(page, "/support/report", "Report issue")
    expect(page).to_have_url(re.compile(r"/support/report"))
    maybe_caption(page, "Sub-tab: Support report form", duration=1.0)


def generate_report(page, *, title: str = "Story demo report", steps: str = "1. Open app\n2. Observe issue", expected: str = "Should work", actual: str = "Demo report"):
    maybe_caption(page, "Action: fill support report form", duration=1.2)
    page.locator('#f-title').fill(title)
    page.locator('#f-steps').fill(steps)
    page.locator('#f-expected').fill(expected)
    page.locator('#f-actual').fill(actual)
    page.locator('#btn-generate').click()
    page.wait_for_timeout(500)
    page.wait_for_load_state("domcontentloaded")
    ensure_demo_ready(page)
    expect(page.locator('#report-preview')).not_to_have_value("")
