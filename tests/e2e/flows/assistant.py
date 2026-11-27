"""Assistant flows."""
from __future__ import annotations

import re

from playwright.sync_api import expect

from .common import ensure_demo_ready, maybe_caption, nav_click, type_into


def ask(page, question: str):
    nav_click(page, "/assistant", "Manager Assistant")
    maybe_caption(page, "Action: ask assistant", duration=1.2)
    type_into(page, 'textarea[name="message"]', question)
    page.get_by_role("button", name="Send message").click()
    # Wait for HTMX response to render and typewriter animation to complete.
    page.wait_for_timeout(800)
    try:
        page.wait_for_function(
            """() => {
                const msgs = document.querySelector('#assistant-messages');
                if (!msgs) return false;
                const typing = msgs.querySelectorAll('.assistant-content.typing');
                if (typing.length > 0) return false;
                const bodies = msgs.querySelectorAll('.msg-row.assistant .msg-body');
                if (!bodies.length) return false;
                const last = bodies[bodies.length - 1];
                const txt = (last.textContent || '').trim();
                return txt.length >= 10;
            }""",
            timeout=15000,
        )
    except Exception:
        # Fallback: if animation detection was flaky, proceed once response text exists.
        try:
            page.wait_for_function(
                """() => {
                    const bodies = document.querySelectorAll('#assistant-messages .msg-row.assistant .msg-body');
                    if (!bodies.length) return false;
                    return (bodies[bodies.length - 1].textContent || '').trim().length >= 10;
                }""",
                timeout=15000,
            )
        except Exception:
            pass
    page.wait_for_load_state("domcontentloaded")
    ensure_demo_ready(page)
    expect(page.locator("#assistant-messages")).to_contain_text(re.compile(r".{10,}", re.S))
    # Brief read pause; keep demo moving.
    page.wait_for_timeout(1800 if getattr(page, "_demo_mode", False) else 300)
