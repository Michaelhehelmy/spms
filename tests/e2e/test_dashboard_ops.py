"""tests/e2e/test_dashboard_ops.py — dashboard ops sections + day filter (app issue #42).

Covers: dashboard renders the Arrivals / Departures / In-house sections, and
the day filter (?day=) on the dashboard.
"""
from __future__ import annotations

import pytest

import re

pytest.importorskip("playwright")
from playwright.sync_api import expect


def test_dashboard_ops_sections(e2e_server, page, setup_app, unlock):
    base = e2e_server.base_url
    setup_app("E2E Property")
    unlock()
    page.goto(base + "/")
    expect(page.get_by_role("heading", name=re.compile(r"Arrivals \(\d*\)"))).to_be_visible()
    expect(page.get_by_role("heading", name=re.compile(r"Departures \(\d*\)"))).to_be_visible()
    expect(page.get_by_role("heading", name=re.compile(r"Stayovers \(\d*\)"))).to_be_visible()


def test_dashboard_day_filter(e2e_server, page, setup_app, unlock):
    base = e2e_server.base_url
    setup_app("E2E Property")
    unlock()
    page.goto(base + "/")
    page.fill('input[name="day"]', "2026-11-23")
    page.get_by_role("button", name="View").click()
    page.wait_for_load_state("networkidle")
    assert "day=" in page.url
