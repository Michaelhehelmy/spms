"""Playwright E2E harness for SPMS (app issue #42: comprehensive Playwright E2E suite).

- Starts an isolated SPMS web server per test (uvicorn subprocess with a temp
  PM_DATA_DIR, deterministic super password, Co-Camp auto-pull disabled).
- Drives the app with Playwright (Python API, Chromium headless shell).
- Records video on every page; on failures also captures screenshots and traces.
"""
from __future__ import annotations

import os
import shutil
import socket
import sqlite3
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"

TEST_PASSWORD = "e2e-pass-123"
ARTIFACTS = ROOT / "dist" / "e2e-artifacts"
DEMO_DIR = ROOT / "dist" / "demo-videos"

SERVER_ENV = {
    "PM_WEB_SECRET_KEY": "e2e-test-secret-" + "x" * 48,
    "PM_WEB_UNLOCK_RATE_LIMIT": "100",
    "PM_WEB_UNLOCK_RATE_WINDOW_SEC": "600",
    "PYTHONPATH": f"{SRC}{os.pathsep}{ROOT}",
}


# Re-export root tests/conftest.py helpers so `from conftest import ...` in
# top-level tests still resolves when pytest collects tests/e2e/conftest.py.
def _reexport_root_conftest():
    import importlib.util as _ilu

    root = Path(__file__).resolve().parents[1] / "conftest.py"
    if not root.exists():
        return
    spec = _ilu.spec_from_file_location("_root_tests_conftest", root)
    if spec is None or spec.loader is None:
        return
    mod = _ilu.module_from_spec(spec)
    spec.loader.exec_module(mod)
    for k, v in vars(mod).items():
        if k.startswith("__"):
            continue
        globals().setdefault(k, v)


_reexport_root_conftest()


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_health(base_url: str, timeout: float = 90.0, log_file: Path | None = None) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(base_url + "/healthz", timeout=2) as resp:
                if resp.status == 200:
                    return
        except Exception:
            pass
        time.sleep(0.25)
    tail = ""
    if log_file and log_file.exists():
        try:
            tail = "\n--- server.log tail ---\n" + log_file.read_text(encoding="utf-8", errors="replace")[-4000:]
        except Exception:
            pass
    raise RuntimeError(f"Server did not become healthy at {base_url}{tail}")


def _seed_db(data_dir: Path) -> None:
    """Fresh DB with seeded defaults + deterministic super password + auto-pull off."""
    env = {**os.environ, **SERVER_ENV, "PM_DATA_DIR": str(data_dir)}
    code = (
        "from app_core import services\n"
        "services.init_db()\n"
        f"services.set_super_password({TEST_PASSWORD!r})\n"
        "services.set_setting('assistant_models_auto_pull', 'false')\n"
    )
    subprocess.run([sys.executable, "-c", code], check=True, cwd=ROOT, env=env)


@pytest.fixture
def e2e_server(tmp_path, request):
    """Isolated running SPMS web server for one test."""
    art = ARTIFACTS / request.node.name
    art.mkdir(parents=True, exist_ok=True)
    server_log = art / "server.log"
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    env = {**os.environ, **SERVER_ENV, "PM_DATA_DIR": str(data_dir)}
    _seed_db(data_dir)
    port = _free_port()
    base_url = f"http://127.0.0.1:{port}"
    with open(server_log, "w", encoding="utf-8") as log_f:
        proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "ui.web.server:app",
             "--host", "127.0.0.1", "--port", str(port), "--workers", "1"],
            cwd=ROOT, env=env, stdout=log_f, stderr=subprocess.STDOUT, text=True,
        )
        try:
            _wait_health(base_url, log_file=server_log)
            yield SimpleNamespace(base_url=base_url, data_dir=data_dir, log_file=server_log)
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()


# ── Playwright plumbing ───────────────────────────────────────────────────────

@pytest.fixture
def playwright():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        yield pw


@pytest.fixture
def browser(playwright):
    b = playwright.chromium.launch(headless=True)
    yield b
    b.close()


@pytest.fixture
def context(browser, request):
    art = ARTIFACTS / request.node.name
    art.mkdir(parents=True, exist_ok=True)
    ctx = browser.new_context(viewport={"width": 1280, "height": 900}, record_video_dir=str(art / "video"))
    ctx.tracing.start(screenshots=True, sources=True)
    try:
        yield ctx
    finally:
        try:
            ctx.tracing.stop(path=str(art / "trace.zip"))
        except Exception:
            pass
        ctx.close()


@pytest.fixture
def page(request, context):
    p = context.new_page()
    console_errors: list[str] = []
    p.on("console", lambda m: console_errors.append(m.text) if m.type == "error" else None)
    p.on("pageerror", lambda e: console_errors.append(str(e)))
    p.on("requestfailed", lambda r: console_errors.append(f"request failed: {r.url} -> {r.failure}"))
    p._console_errors = console_errors
    try:
        yield p
    finally:
        if getattr(request.node, "_e2e_failed", False):
            try:
                p.screenshot(path=str(ARTIFACTS / request.node.name / "screenshot.png"), full_page=True)
            except Exception:
                pass
        p.close()
        try:
            vid = p.video
            if vid and vid.path():
                shutil.copy(vid.path(), str(ARTIFACTS / request.node.name / "video.webm"))
        except Exception:
            pass


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):  # pragma: no cover - hook
    outcome = yield
    rep = outcome.get_result()
    if rep.when == "call" and rep.failed:
        setattr(item, "_e2e_failed", True)


def csrf(page) -> str:
    return page.locator('input[name="csrf"]').first.input_value()


def record_video(page, name: str) -> str:
    """Save the page's Playwright video to dist/demo-videos/<name>.webm."""
    DEMO_DIR.mkdir(parents=True, exist_ok=True)
    page.wait_for_timeout(300)  # brief settle, no long blank lead-in
    page.wait_for_load_state("networkidle")
    src = None
    try:
        vid = page.video
        src = vid.path() if vid else None
    except Exception:
        src = None
    dst = str(DEMO_DIR / f"{name}.webm")
    if src and Path(src) != Path(dst):
        shutil.copy(src, dst)
    return dst


def caption(page, text: str, duration: float = 2.5) -> None:
    """Show a caption overlay on the page (silent demo videos)."""
    page.evaluate(
        """([text, duration]) => {
            let el = document.getElementById('demo-caption');
            if (!el) {
                el = document.createElement('div');
                el.id = 'demo-caption';
                Object.assign(el.style, {
                    position: 'fixed', left: '50%', bottom: '24px',
                    transform: 'translateX(-50%)', maxWidth: '85%',
                    padding: '10px 16px', background: 'rgba(18,26,51,0.85)',
                    color: '#fff', font: 'bold 18px/1.3 sans-serif',
                    borderRadius: '8px', zIndex: '2147483000',
                    textAlign: 'center', whiteSpace: 'nowrap',
                });
                document.body.appendChild(el);
            }
            el.textContent = text;
            el.style.display = 'block';
            setTimeout(() => { el.style.display = 'none'; }, duration * 1000);
        }""",
        [text, duration],
    )
    page.wait_for_timeout(int(duration * 1000))


def _setup_unlock(page, e2e_server):
    base = e2e_server.base_url
    page.goto(base + "/setup")
    page.fill('input[name="display_name"]', "E2E Property")
    page.select_option('select[name="animation"]', "reveal")
    page.click('button[type="submit"]')
    page.wait_for_url(lambda url: url == base + "/")
    page.goto(base + "/unlock")
    page.fill('input[name="password"]', "e2e-pass-123")
    page.click('button[type="submit"]')
    page.wait_for_url(lambda url: url == base + "/")


def _fill_create_form(page, base, guest_name):
    page.goto(base + "/reservations?tab=create")
    page.fill('input[name="guest_name"]', guest_name)
    page.select_option("select[name=room_id]", index=0)
    page.fill("input[name=check_in]", datetime.now().strftime("%Y-%m-%d"))
    page.fill("input[name=check_out]", (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d"))
    page.fill('input[name="rate"]', "100")


@pytest.fixture
def setup_app(page, e2e_server):
    def _setup(name: str = "Acadia Camp"):
        base = e2e_server.base_url
        page.goto(base + "/setup")
        page.fill('input[name="display_name"]', name)
        page.fill('input[name="tagline"]', "E2E property")
        page.select_option('select[name="animation"]', "reveal")
        page.click('button[type="submit"]')
        page.wait_for_url(lambda url: url == f"{base}/")
        return page

    return _setup


@pytest.fixture
def unlock(page, e2e_server):
    def _unlock(password: str = TEST_PASSWORD):
        base = e2e_server.base_url
        page.goto(base + "/unlock")
        page.fill('input[name="password"]', password)
        page.click('button[type="submit"]')
        page.wait_for_url(lambda url: url == f"{base}/")
        return page

    return _unlock


@pytest.fixture
def password():
    return TEST_PASSWORD


@pytest.fixture
def seed_guest(e2e_server):
    def _seed(name: str, phone: str = "", email: str = ""):
        code = (
            "from app_core import services\n"
            f"g = services.find_or_create_guest({name!r}, phone={phone!r}, email={email!r})\n"
            "print(g[0])\n"
        )
        env = {**os.environ, **SERVER_ENV, "PM_DATA_DIR": str(e2e_server.data_dir)}
        out = subprocess.run(
            [sys.executable, "-c", code], capture_output=True, text=True, check=True, cwd=ROOT, env=env,
        )
        return int(out.stdout.strip().splitlines()[-1])

    return _seed


@pytest.fixture
def seed_inventory(e2e_server):
    """Add an inventory item via the services API (requires the test super password)."""

    def _seed(name: str, selling_price: float = 12.5, stock_qty: int = 5):
        code = (
            "from app_core import services\n"
            "item_id = services.add_inventory_item(\n"
            f"    {name!r}, 'Supplies', 'unit', {stock_qty!r}, 0.0, {selling_price!r}, 0, 0, {TEST_PASSWORD!r})\n"
            "print(item_id)\n"
        )
        env = {**os.environ, **SERVER_ENV, "PM_DATA_DIR": str(e2e_server.data_dir)}
        out = subprocess.run(
            [sys.executable, "-c", code], capture_output=True, text=True, check=True, cwd=ROOT, env=env,
        )
        return int(out.stdout.strip().splitlines()[-1])

    return _seed


@pytest.fixture
def seed_expense_category(e2e_server):
    """Insert an expense category row directly (no add route on this page)."""

    def _seed(name: str = "E2E Expense"):
        code = (
            "from app_core import db\n"
            "conn = db.connect()\n"
            f"conn.execute(\"INSERT INTO expense_categories (category_name) VALUES ({name!r})\")\n"
            "conn.commit()\n"
        )
        env = {**os.environ, **SERVER_ENV, "PM_DATA_DIR": str(e2e_server.data_dir)}
        subprocess.run(
            [sys.executable, "-c", code], capture_output=True, text=True, check=True, cwd=ROOT, env=env,
        )
        return name

    return _seed
