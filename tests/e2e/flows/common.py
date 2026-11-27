"""Common demo-aware UI helpers for E2E story flows."""
from __future__ import annotations

import re

from playwright.sync_api import expect

from conftest import (
    TEST_PASSWORD,
    caption as _caption,
    demo_click as _demo_click,
    demo_install_cursor,
    demo_move as _demo_move,
    demo_select as _demo_select,
    demo_type as _demo_type,
    hide_update_modal,
)


def demo_mode(page) -> bool:
    return bool(getattr(page, "_demo_mode", False) or getattr(page, "_demo_video", None))


def maybe_caption(page, text: str, duration: float = 1.8) -> None:
    if demo_mode(page):
        _caption(page, text, duration=duration)


def ensure_demo_ready(page) -> None:
    if not demo_mode(page):
        return
    page.add_style_tag(content="#update-modal-backdrop,.modal-backdrop{display:none!important}")
    hide_update_modal(page)
    demo_install_cursor(page)
    # Let UI settle so demo video doesn't jump before response renders.
    page.wait_for_timeout(500)


def goto(page, base: str, path: str) -> None:
    page.goto(base + path, wait_until="domcontentloaded")
    ensure_demo_ready(page)


def nav_click(page, href: str, label: str) -> None:
    maybe_caption(page, f"Navigate: {label}", duration=1.0)
    sel = f'a.nav-link[href="{href}"]'
    loc = page.locator(sel).first
    if demo_mode(page):
        _demo_move(page, sel)
    loc.click()
    page.wait_for_load_state("domcontentloaded")
    ensure_demo_ready(page)


def click_role(page, role: str, name: str, *, exact: bool = False) -> None:
    loc = page.get_by_role(role, name=name, exact=exact)
    if loc.count() > 1 and not exact:
        exact_loc = page.get_by_role(role, name=name, exact=True)
        loc = exact_loc if exact_loc.count() == 1 else loc.first
    else:
        loc = loc.first
    loc.scroll_into_view_if_needed()
    if demo_mode(page):
        box = loc.bounding_box()
        if box:
            page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2, steps=15)
    loc.click()
    page.wait_for_timeout(250 if demo_mode(page) else 50)


def click_button(page, name: str, *, exact: bool = False) -> None:
    click_role(page, "button", name, exact=exact)


def click_link(page, name: str, *, exact: bool = False) -> None:
    click_role(page, "link", name, exact=exact)


def type_into(page, selector: str, text: str, delay: int = 55) -> None:
    loc = page.locator(selector).first
    loc.scroll_into_view_if_needed()
    if demo_mode(page):
        _demo_type(page, selector, text, delay=delay)
        return
    loc.fill(text)


def type_loc(page, loc, text: str, delay: int = 55) -> None:
    loc.scroll_into_view_if_needed()
    if demo_mode(page):
        box = loc.bounding_box()
        if box:
            page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2, steps=15)
        loc.click()
        page.wait_for_timeout(120)
        t = (loc.get_attribute("type") or "").lower()
        if t in {"date", "datetime-local", "time", "number"}:
            loc.fill(text)
        else:
            loc.fill("")
            page.keyboard.type(text, delay=delay)
        page.wait_for_timeout(200)
    else:
        loc.fill(text)


def select_option(page, selector: str, value=None, *, index=None, label=None) -> None:
    loc = page.locator(selector).first
    if demo_mode(page):
        _demo_move(page, selector)
    if value is not None:
        loc.select_option(value)
    elif index is not None:
        loc.select_option(index=index)
    elif label is not None:
        loc.select_option(label=label)
    if demo_mode(page):
        page.wait_for_timeout(250)


def assert_flash(page, text: str) -> None:
    expect(page.get_by_text(text).first).to_be_visible()


def assert_url_contains(page, fragment: str) -> None:
    expect(page).to_have_url(re.compile(re.escape(fragment)))


def set_date(page, selector: str, value: str) -> None:
    loc = page.locator(selector).first
    loc.scroll_into_view_if_needed()
    if demo_mode(page):
        from conftest import demo_move
        demo_move(page, selector)
    loc.fill(value)
    if demo_mode(page):
        page.wait_for_timeout(250)


def select_overlay(page, selector: str, value: str) -> None:
    """Demo-friendly visual select: shows overlay then sets value."""
    loc = page.locator(selector).first
    loc.scroll_into_view_if_needed()
    if not demo_mode(page):
        loc.select_option(value)
        return
    from conftest import demo_move
    demo_move(page, selector)
    loc.click()
    page.evaluate(
        """({selector, value}) => {
            const sel = document.querySelector(selector);
            if (!sel) return;
            const r = sel.getBoundingClientRect();
            const old = document.getElementById('demo-select-overlay');
            if (old) old.remove();
            const overlay = document.createElement('div');
            overlay.id = 'demo-select-overlay';
            Object.assign(overlay.style, {
                position: 'fixed', left: r.left + 'px', top: (r.bottom + 4) + 'px',
                width: Math.max(r.width, 220) + 'px', background: '#fff', color: '#111',
                border: '1px solid #bbb', borderRadius: '6px',
                boxShadow: '0 8px 24px rgba(0,0,0,.18)', zIndex: '2147483647',
                font: '14px/1.4 sans-serif', overflow: 'hidden',
            });
            Array.from(sel.options).forEach(o => {
                const item = document.createElement('div');
                item.textContent = o.textContent.trim();
                Object.assign(item.style, { padding: '8px 12px', cursor: 'pointer' });
                if (o.value === value) item.style.background = '#e8f0fe';
                overlay.appendChild(item);
            });
            document.body.appendChild(overlay);
        }""",
        {"selector": selector, "value": value},
    )
    page.wait_for_timeout(700)
    box = loc.bounding_box()
    if box:
        options = loc.locator('option')
        idx = 0
        for i in range(options.count()):
            if options.nth(i).get_attribute('value') == value:
                idx = i
                break
        page.mouse.move(box['x'] + box['width']/2, box['y'] + box['height'] + 20 + idx*34, steps=15)
        page.wait_for_timeout(250)
        page.mouse.click(box['x'] + box['width']/2, box['y'] + box['height'] + 20 + idx*34)
    loc.select_option(value)
    page.evaluate("() => { const el = document.getElementById('demo-select-overlay'); if (el) el.remove(); }")
    page.wait_for_timeout(400)
