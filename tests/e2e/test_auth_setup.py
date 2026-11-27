"""tests/e2e/test_auth_setup.py — setup wizard + unlock/lock/security guards (app issue #42).

Covers: setup wizard flow, unlock success/wrong password, lock, sensitive-action
guard (unlock redirect), and session expiry on inactivity.
"""
from __future__ import annotations

import sqlite3

import pytest
pytest.importorskip("playwright")
from playwright.sync_api import expect


def test_setup_wizard_completes_and_redirects(e2e_server, page, setup_app):
    base = e2e_server.base_url
    page.goto(base + "/setup")
    expect(page.locator('input[name="display_name"]')).to_be_visible()
    setup_app("E2E Property")
    expect(page.get_by_text("Front Desk / Today Ops")).to_be_visible()
    # Wizard is now configured: /setup redirects to /.
    page.goto(base + "/setup")
    page.wait_for_url(lambda url: url == f"{base}/")


def test_setup_wizard_requires_display_name(e2e_server, page):
    page.goto(e2e_server.base_url + "/setup")
    page.click('button[type="submit"]:not(.ghost)')
    page.wait_for_load_state("networkidle", timeout=15000)
    assert page.url == f"{e2e_server.base_url}/setup"


def test_unlock_wrong_password_shows_flash(e2e_server, page, setup_app):
    base = e2e_server.base_url
    setup_app("E2E Property")
    page.goto(base + "/unlock")
    page.fill('input[name="password"]', "definitely-wrong")
    page.click('button[type="submit"]:not(.ghost)')
    page.wait_for_load_state("networkidle", timeout=15000)
    expect(page.get_by_text("Invalid super password")).to_be_visible()


def test_unlock_success_shows_lock_button(e2e_server, page, setup_app, unlock, password):
    base = e2e_server.base_url
    setup_app("E2E Property")
    page.goto(base + "/unlock")
    page.fill('input[name="password"]', password)
    page.click('button[type="submit"]:not(.ghost)')
    page.wait_for_url(lambda url: url == f"{base}/")
    expect(page.get_by_text("🔒 Lock session")).to_be_visible()


def test_lock_button_locks_session(e2e_server, page, setup_app, unlock):
    base = e2e_server.base_url
    setup_app("E2E Property")
    unlock()
    expect(page.get_by_text("🔒 Lock session")).to_be_visible()
    page.get_by_role("button", name="Lock session").click()
    page.wait_for_load_state("networkidle", timeout=15000)
    expect(page.get_by_text("🔓 Unlock protected actions")).to_be_visible()


def test_sensitive_action_blocked_when_locked(e2e_server, page, setup_app):
    base = e2e_server.base_url
    setup_app("E2E Property")  # locked: setup done, no unlock yet
    page.goto(base + "/settings?tab=general")
    page.get_by_role("button", name="Save settings").click()
    page.wait_for_load_state("networkidle", timeout=15000)
    assert "/unlock" in page.url


@pytest.mark.timeout(150)
def test_session_expires_after_idle(e2e_server, page, setup_app, unlock):
    base = e2e_server.base_url
    setup_app("E2E Property")
    unlock()
    expect(page.get_by_text("🔒 Lock session")).to_be_visible()
    # The app slides activity on requests; with a 1-minute (minimum) session
    # timeout and >60s of no traffic, the next request re-locks the browser.
    conn = sqlite3.connect(e2e_server.data_dir / "property_manager.db")
    conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('session_timeout_min', '1')")
    conn.commit()
    conn.close()
    page.wait_for_timeout(65_000)
    page.goto(base + "/")
    page.wait_for_load_state("networkidle", timeout=15000)
    expect(page.get_by_text("🔓 Unlock protected actions")).to_be_visible()
