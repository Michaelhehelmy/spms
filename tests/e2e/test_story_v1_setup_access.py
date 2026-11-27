"""Story V1 — Setup, Access & Dashboard Orientation (real E2E + demo mode).

Run normally: assertions only. Run with E2E_DEMO=1 or @pytest.mark.demo: captions/video.
"""
from __future__ import annotations

import re

import pytest
from playwright.sync_api import expect

from conftest import is_demo_mode
from flows.auth import create_super_password, lock, setup_wizard
from flows.common import maybe_caption, nav_click
from flows.dashboard import filter_day, overview


@pytest.mark.story
def test_story_v1_setup_access_dashboard(e2e_server_fresh, page):
    base = e2e_server_fresh.base_url

    # --- Setup ---
    setup_wizard(page, base)
    expect(page.get_by_text("Acadia Camp").first).to_be_visible()

    # --- First-run super password + lock/unlock cycle ---
    create_super_password(page, base)
    lock(page, base)
    create_super_password(page, base)  # unlock again (password already set -> normal unlock path)

    # --- Dashboard ---
    overview(page, base)
    filter_day(page, base, "2026-11-23")

    # --- Sub-tab/nav overview (main areas) ---
    maybe_caption(page, "Action: overview — navigate main app tabs", duration=1.5)
    for href, label, expected in [
        ("/reservations", "Reservations", "/reservations"),
        ("/guests", "Guests", "/guests"),
        ("/housekeeping", "Housekeeping", "/housekeeping"),
        ("/pos", "POS / Inventory", "/pos"),
        ("/accounting", "Accounting", "/accounting"),
        ("/reports", "Reports & Analytics", "/reports"),
        ("/settings", "Settings / Branding", "/settings"),
        ("/support/report", "Report issue", "/support/report"),
    ]:
        nav_click(page, href, label)
        expect(page).to_have_url(re.compile(re.escape(expected)))

    nav_click(page, "/", "Dashboard")
    maybe_caption(page, "Result: setup/access/dashboard story complete; endpoint /", duration=1.8)

    # Master video is recorded by test_story_master_all_app.py; keep this as E2E coverage.
