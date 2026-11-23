"""tests/e2e/test_housekeeping.py — housekeeping page, tasks (app issue #42).

Covers: housekeeping page loads, creating a housekeeping task via the UI,
and generating tasks for dirty rooms.
"""
from __future__ import annotations

import pytest

pytest.importorskip("playwright")
from playwright.sync_api import expect
import re


def test_housekeeping_page_loads(e2e_server, page, setup_app, unlock):
    base = e2e_server.base_url
    setup_app("E2E Property")
    unlock()
    page.goto(base + "/housekeeping")
    expect(page.get_by_role("heading", name="Housekeeping")).to_be_visible()
    expect(page.get_by_role("heading", name="Tasks")).to_be_visible()
    expect(page.get_by_role("button", name="Generate tasks for dirty rooms")).to_be_visible()


def test_housekeeping_create_task(e2e_server, page, setup_app, unlock):
    base = e2e_server.base_url
    setup_app("E2E Property")
    unlock()
    page.goto(base + "/housekeeping")
    page.locator('details summary:has-text("Create task")').click()  # opens the form
    page.select_option('select[name="room_id"]', index=0)
    page.fill('input[name="task_type"]', "cleaning")
    page.select_option('select[name="priority"]', "high")
    page.fill('input[name="assignee"]', "E2E Staff")
    page.fill('textarea[name="notes"]', "E2E notes")
    page.get_by_role("button", name="Create task").click()
    page.wait_for_load_state("networkidle")
    expect(page.get_by_text("Housekeeping task created")).to_be_visible()
    expect(page.get_by_text("E2E Staff").first).to_be_visible()


def test_housekeeping_generate_tasks(e2e_server, page, setup_app, unlock):
    base = e2e_server.base_url
    setup_app("E2E Property")
    unlock()
    page.goto(base + "/housekeeping")
    page.get_by_role("button", name="Generate tasks for dirty rooms").click()
    page.wait_for_load_state("networkidle")
    expect(page.get_by_text(re.compile(r"Generated \d+ task\(s\) for dirty rooms"))).to_be_visible()
