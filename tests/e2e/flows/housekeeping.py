"""Housekeeping flows."""
from __future__ import annotations

import re
from datetime import datetime, timedelta

from playwright.sync_api import expect

from conftest import TEST_PASSWORD
from .common import assert_url_contains, ensure_demo_ready, maybe_caption, nav_click


def open_page(page, base: str):
    nav_click(page, "/housekeeping", "Housekeeping")
    assert_url_contains(page, "/housekeeping")
    expect(page.get_by_role("heading", name="Housekeeping").first).to_be_visible()
    maybe_caption(page, "Sub-tab: Housekeeping tasks & blocks", duration=1.0)


def create_task(page, *, assignee: str = "E2E Staff", task_type: str = "cleaning", priority: str = "high", notes: str = "Story task"):
    maybe_caption(page, "Action: create housekeeping task", duration=1.2)
    page.locator('details summary:has-text("Create task")').click()
    page.wait_for_timeout(200)
    form = page.locator('form[action="/housekeeping/tasks/create"]').first
    form.locator('select[name="room_id"]').select_option(index=0)
    form.locator('input[name="task_type"]').fill(task_type)
    form.locator('select[name="priority"]').select_option(priority)
    form.locator('input[name="assignee"]').fill(assignee)
    form.locator('textarea[name="notes"]').fill(notes)
    form.get_by_role("button", name="Create task").click()
    page.wait_for_load_state("domcontentloaded")
    ensure_demo_ready(page)
    expect(page.get_by_text("Housekeeping task created").first).to_be_visible()


def update_first_task_status(page, status: str = "in_progress"):
    maybe_caption(page, f"Action: update first task status to {status}", duration=1.2)
    form = page.locator('form[action*="/housekeeping/tasks/"][action$="/status"]').first
    form.locator('select[name="status"]').select_option(status)
    form.get_by_role("button", name="Update status").click()
    page.wait_for_load_state("domcontentloaded")
    ensure_demo_ready(page)
    expect(page.get_by_text("Task updated").first).to_be_visible()


def filter_tasks(page, status: str = ""):
    maybe_caption(page, f"Action: filter housekeeping tasks status={status or 'all'}", duration=1.0)
    form = page.locator('form[method="get"]').filter(has=page.locator('select[name="status"]')).first
    form.locator('select[name="status"]').select_option(status)
    form.get_by_role("button", name="Filter").click()
    page.wait_for_load_state("domcontentloaded")
    ensure_demo_ready(page)


def generate_dirty_tasks(page):
    maybe_caption(page, "Action: generate tasks for dirty rooms", duration=1.2)
    page.locator('form[action="/housekeeping/tasks/generate"]').get_by_role("button", name="Generate tasks for dirty rooms").click()
    page.wait_for_load_state("domcontentloaded")
    ensure_demo_ready(page)
    expect(page.get_by_text(re.compile(r"Generated \d+ task\(s\) for dirty rooms")).first).to_be_visible()


def create_room_block(page, password: str = TEST_PASSWORD):
    maybe_caption(page, "Action: create room block (OOO/OOS)", duration=1.2)
    page.get_by_text("Create room block", exact=False).first.click()
    page.wait_for_timeout(200)
    form = page.locator('form[action="/housekeeping/blocks/create"]').first
    form.locator('select[name="room_id"]').select_option(index=0)
    form.locator('input[name="start_date"]').fill(datetime.now().strftime("%Y-%m-%d"))
    form.locator('input[name="end_date"]').fill((datetime.now() + timedelta(days=2)).strftime("%Y-%m-%d"))
    form.locator('input[name="reason"]').fill("E2E Story block")
    form.locator('input[name="password"]').fill(password)
    form.get_by_role("button", name="Create block").click()
    page.wait_for_load_state("domcontentloaded")
    ensure_demo_ready(page)
    expect(page.get_by_text("Room block created").first).to_be_visible()


def resolve_first_block(page, password: str = TEST_PASSWORD):
    maybe_caption(page, "Action: resolve active room block", duration=1.2)
    form = page.locator('form[action^="/housekeeping/blocks/"][action$="/resolve"]').first
    form.locator('input[name="password"]').fill(password)
    form.get_by_role("button", name="Resolve").click()
    page.wait_for_load_state("domcontentloaded")
    ensure_demo_ready(page)
    expect(page.get_by_text("Room block resolved").first).to_be_visible()
