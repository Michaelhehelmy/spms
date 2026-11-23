"""tests/e2e/test_pos_activities.py — POS Activities tab (app issue #42).

Covers: the Activities tab renders the register-activity forms and lists
registered activities.
"""
from __future__ import annotations

import pytest

pytest.importorskip("playwright")
from playwright.sync_api import expect


def test_pos_activities_tab_renders(e2e_server, page, setup_app, unlock):
    base = e2e_server.base_url
    setup_app("E2E Property")
    unlock()
    page.goto(base + "/pos?tab=activities")
    expect(page.get_by_role("heading", name="POS / Inventory")).to_be_visible()
    expect(page.get_by_role("link", name="Activities")).to_be_visible()
    expect(page.get_by_role("heading", name="Register new activity / trip")).to_be_visible()
    expect(page.get_by_role("heading", name="Registered activities")).to_be_visible()
    expect(page.get_by_role("button", name="Register activity")).to_be_visible()
