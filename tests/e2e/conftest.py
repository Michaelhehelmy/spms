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
E2E_DIR = Path(__file__).resolve().parent
if str(E2E_DIR) not in sys.path:
    sys.path.insert(0, str(E2E_DIR))

TEST_PASSWORD = "e2e-pass-123"
ARTIFACTS = ROOT / "dist" / "e2e-artifacts"
DEMO_DIR = ROOT / "dist" / "demo-videos"

E2E_DEMO = os.environ.get("E2E_DEMO", "").strip().lower() in {"1", "true", "yes", "on", "demo"}

SERVER_ENV = {
    "PM_WEB_SECRET_KEY": "e2e-test-secret-" + "x" * 48,
    "PM_WEB_UNLOCK_RATE_LIMIT": "100",
    "PM_WEB_UNLOCK_RATE_WINDOW_SEC": "600",
    "PYTHONPATH": f"{SRC}{os.pathsep}{ROOT}",
}


def is_demo_mode(request=None) -> bool:
    """True when demo capture/pacing should be enabled."""
    if E2E_DEMO:
        return True
    if request is not None:
        try:
            for mark in ("demo", "story"):
                if request.node.get_closest_marker(mark):
                    return True
        except Exception:
            pass
    return False


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


def _seed_db(data_dir: Path, *, set_password: bool = True) -> None:
    """Fresh DB with seeded defaults + optional deterministic super password + auto-pull off."""
    env = {**os.environ, **SERVER_ENV, "PM_DATA_DIR": str(data_dir)}
    lines = [
        "from app_core import services",
        "services.init_db()",
        "services.set_setting('assistant_models_auto_pull', 'false')",
        "services.set_setting('auto_check_updates', 'false')",
    ]
    if set_password:
        lines.append(f"services.set_super_password({TEST_PASSWORD!r})")
    code = "\n".join(lines) + "\n"
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


@pytest.fixture
def e2e_server_fresh(tmp_path, request):
    """Isolated running SPMS web server with no super password set (first-run flow)."""
    art = ARTIFACTS / request.node.name
    art.mkdir(parents=True, exist_ok=True)
    server_log = art / "server.log"
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    env = {**os.environ, **SERVER_ENV, "PM_DATA_DIR": str(data_dir)}
    _seed_db(data_dir, set_password=False)
    port = _free_port()
    base_url = f"http://127.0.0.1:{port}"
    with open(server_log, "w", encoding="utf-8") as log_f:
        proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "ui.web.server:app",
             "--host", "127.0.0.1", "--port", str(port), "--workers", "1"],
            cwd=ROOT, env=env, stdout=log_f, stderr=subprocess.STDOUT, text=True,
        )
        try:
            _wait_health(base_url)
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
    ctx = browser.new_context(
        viewport={"width": 1920, "height": 1080},
        record_video_size={"width": 1920, "height": 1080},
        record_video_dir=str(art / "video"),
    )
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
    p._demo_mode = is_demo_mode(request)
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
                src = vid.path()
                shutil.copy(src, str(ARTIFACTS / request.node.name / "video.webm"))
                demo = getattr(p, "_demo_video", None)
                if demo:
                    name, trim_start, speed = demo
                    DEMO_DIR.mkdir(parents=True, exist_ok=True)
                    dst = DEMO_DIR / f"{name}.webm"
                    low = DEMO_DIR / f"{name}.low.webm"
                    shutil.copy(src, str(dst))
                    if shutil.which("ffmpeg"):
                        def _encode(out: Path, *, height: int, crf: str, cpu_used: str) -> None:
                            tmp = out.with_suffix(".tmp.webm")
                            vf = []
                            if trim_start > 0:
                                pass
                            if speed != 1.0:
                                vf.append(f"setpts=PTS/{speed}")
                            vf.append(f"scale=-2:{height}")
                            cmd = ["ffmpeg", "-y"]
                            if trim_start > 0:
                                cmd += ["-ss", str(trim_start)]
                            cmd += ["-i", str(src), "-filter:v", ",".join(vf), "-an", "-c:v", "libvpx-vp9", "-crf", crf, "-b:v", "0", "-row-mt", "1", "-cpu-used", cpu_used, str(tmp)]
                            try:
                                r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
                                if r.returncode == 0 and tmp.exists():
                                    tmp.replace(out)
                            except Exception:
                                pass
                            finally:
                                if tmp.exists():
                                    tmp.unlink()
                        # Low-quality (default working copy for review/iteration)
                        _encode(low, height=720, crf="36", cpu_used="4")
                        # High-quality (YouTube/production) only on explicit request
                        if os.environ.get("E2E_DEMO_PROD", "").strip().lower() in {"1", "true", "yes", "prod"}:
                            _encode(dst, height=1080, crf="28", cpu_used="1")
                        else:
                            # Keep a small placeholder note? No - just keep low as primary.
                            # Remove high-res intermediate copy to save space; low is the review artifact.
                            try:
                                if dst.exists() and low.exists():
                                    dst.unlink()
                            except Exception:
                                pass
        except Exception:
            pass


def pytest_configure(config):  # pragma: no cover - hook
    config.addinivalue_line("markers", "demo: enable demo pacing/captions/video capture for this test")
    config.addinivalue_line("markers", "story: end-to-end business story test (can produce demo video)")


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):  # pragma: no cover - hook
    outcome = yield
    rep = outcome.get_result()
    if rep.when == "call" and rep.failed:
        setattr(item, "_e2e_failed", True)


def csrf(page) -> str:
    return page.locator('input[name="csrf"]').first.input_value()


def record_video(page, name: str, *, trim_start: float = 0.0, speed: float = 1.0) -> str:
    """Mark the page video to be saved as dist/demo-videos/<name>.webm on close.

    Optional trim/speed are applied by the page fixture after the video is finalized.
    """
    DEMO_DIR.mkdir(parents=True, exist_ok=True)
    page.wait_for_timeout(300)
    try:
        page.wait_for_load_state("domcontentloaded", timeout=5000)
    except Exception:
        pass
    page._demo_video = (name, float(trim_start), float(speed))
    return str(DEMO_DIR / f"{name}.webm")


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
                    padding: '14px 22px', background: 'rgba(18,26,51,0.88)',
                    color: '#fff', font: 'bold 24px/1.35 sans-serif',
                    borderRadius: '10px', zIndex: '2147483000',
                    textAlign: 'center', whiteSpace: 'nowrap',
                    boxShadow: '0 4px 24px rgba(0,0,0,0.35)',
                    pointerEvents: 'none',
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


def hide_update_modal(page) -> None:
    """Hide the update-available modal(s) (for demo videos)."""
    page.evaluate(
        """() => {
            const hide = () => {
                document.querySelectorAll('#update-modal-backdrop, .modal-backdrop').forEach((el) => {
                    if (el.textContent.indexOf('Update available') >= 0 || el.id === 'update-modal-backdrop') el.style.display = 'none';
                });
            };
            hide();
            if (!window.__demoHideUpdateModal) {
                window.__demoHideUpdateModal = true;
                new MutationObserver(hide).observe(document.documentElement, { childList: true, subtree: true });
            }
        }"""
    )


def demo_install_cursor(page) -> None:
    """Inject a visible fake cursor for demo videos (persists across navigations)."""
    script = """() => {
        if (window.__demoCursorInstalled) return;
        window.__demoCursorInstalled = true;
        const install = () => {
            if (document.getElementById('demo-cursor')) return;
            const c = document.createElement('div');
            c.id = 'demo-cursor';
            Object.assign(c.style, {
                position: 'fixed', left: '0px', top: '0px', width: '20px', height: '20px',
                borderRadius: '50%', background: 'rgba(255,80,80,0.35)',
                border: '2px solid rgba(255,80,80,0.9)', zIndex: '2147483647',
                pointerEvents: 'none', transform: 'translate(-50%, -50%)',
                transition: 'left 0.08s linear, top 0.08s linear',
                boxShadow: '0 0 0 4px rgba(255,80,80,0.15)',
            });
            (document.documentElement || document.body).appendChild(c);
            document.addEventListener('mousemove', (e) => {
                c.style.left = e.clientX + 'px';
                c.style.top = e.clientY + 'px';
            }, true);
        };
        if (document.documentElement) install();
        document.addEventListener('DOMContentLoaded', install, {once: true});
        window.addEventListener('load', install, {once: true});
    }"""
    try:
        page.add_init_script(script)
    except Exception:
        pass
    try:
        page.evaluate(script)
    except Exception:
        pass


def demo_move(page, selector: str, steps: int = 20) -> None:
    """Move the visible mouse to an element."""
    loc = page.locator(selector).first
    loc.scroll_into_view_if_needed()
    box = loc.bounding_box()
    if not box:
        return
    page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2, steps=steps)
    page.wait_for_timeout(200)


def demo_click(page, selector: str) -> None:
    """Move mouse to element and click (visible in demo)."""
    demo_move(page, selector)
    page.locator(selector).first.click()
    page.wait_for_timeout(250)


def demo_type(page, selector: str, text: str, delay: int = 55) -> None:
    """Click a field and type with human-like delay."""
    demo_move(page, selector)
    loc = page.locator(selector).first
    loc.click()
    page.wait_for_timeout(150)
    input_type = (loc.get_attribute("type") or "").lower()
    if input_type in {"date", "datetime-local", "time", "number", "email", "tel"}:
        loc.fill(text)
        page.wait_for_timeout(250)
    else:
        loc.fill("")
        page.keyboard.type(text, delay=delay)
        page.wait_for_timeout(200)


def demo_select(page, selector: str, value: str) -> None:
    """Visibly select an option."""
    demo_move(page, selector)
    page.locator(selector).first.select_option(value)
    page.wait_for_timeout(300)


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
