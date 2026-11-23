"""tests/e2e/test_settings_users.py — users & roles admin (app issue #42).

Covers: users page loads, add user via the UI form (requires super password).
"""
from __future__ import annotations

from playwright.sync_api import expect


def test_users_page_loads(e2e_server, page, setup_app, unlock):
    base = e2e_server.base_url
    setup_app("E2E Property")
    unlock()
    page.goto(base + "/settings/users")
    expect(page.get_by_role("heading", name="Users & Roles (RBAC groundwork)")).to_be_visible()
    expect(page.get_by_role("heading", name="Add user")).to_be_visible()
    expect(page.get_by_role("heading", name="Current session identity")).to_be_visible()


def test_users_add_user_flow(e2e_server, page, setup_app, unlock, password):
    base = e2e_server.base_url
    setup_app("E2E Property")
    unlock()
    page.goto(base + "/settings/users")
    form = page.locator('form[action="/settings/users/add"]')
    form.locator('input[name="username"]').fill("e2euser1")
    form.locator('input[name="display_name"]').fill("E2E User One")
    form.locator('input[name="new_password"]').fill("somepassword123")
    form.locator('input[name="password"]').fill(password)
    form.get_by_role("button", name="Create user").click()
    page.wait_for_load_state("networkidle")
    expect(page.get_by_text("User created").first).to_be_visible()
