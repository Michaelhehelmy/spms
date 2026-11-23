# Playwright E2E tests

Browser-driven end-to-end tests for the SPMS web app using Python Playwright on **headless Chromium**. Each test starts an isolated SPMS server (uvicorn subprocess with its own temp `PM_DATA_DIR`), so tests never touch real user data.

## Run locally with one command

```bash
.venv-build/bin/python -m pytest tests/e2e -q
```

First-time setup (already done in the dev venv `.venv-build`):

```bash
python -m venv .venv-build
.venv-build/bin/pip install -r requirements.txt -r requirements-dev.txt
.venv-build/bin/pip install playwright
.venv-build/bin/python -m playwright install chromium
```

The suite runs headless; `pytest -p no:randomly` is not needed.

## Coverage by area

| File | Area |
|---|---|
| `tests/e2e/test_auth_setup.py` | setup wizard, unlock success/wrong password/lock, sensitive-action guard, session expiry |
| `tests/e2e/test_dashboard_nav.py` | dashboard widgets, 10 nav links, mobile viewport |
| `tests/e2e/test_guests.py` | guest search, 360° portfolio, profile edit |
| `tests/e2e/test_reservations.py` | create reservation, detail page, record payment, pricing quote, check-in/check-out via detail |
| `tests/e2e/test_pos_inventory.py` | POS sell page, add custom item to cart, clear cart, inventory search, walk-in sale flow |
| `tests/e2e/test_housekeeping.py` | housekeeping page, create task, generate tasks for dirty rooms |
| `tests/e2e/test_housekeeping_blocks.py` | room block create + resolve (password-protected) |
| `tests/e2e/test_accounting_reports.py` | accounting overview/expenses/payments/shifts, shift movement, P&L report, refund flow, void expense, night audit run |
| `tests/e2e/test_assistant.py` | assistant page, ask route via session, send via UI, clear chat |
| `tests/e2e/test_settings_admin.py` | settings: apply branding, Backup now, add room (Rooms & Plans tab) |
| `tests/e2e/test_settings_support.py` | settings general + save via UI, support report page |
| `tests/e2e/test_pwa_a11y.py` | manifest + icon assets, no console errors on key pages, mobile viewport smoke, keyboard navigation |
| `tests/e2e/test_network_errors.py` | friendly error flash on invalid input, unknown route returns 404 |
| `tests/e2e/test_cross_browser.py` | chromium + firefox + webkit smoke on key pages (optional browsers, see below) |

## Harness (`tests/e2e/conftest.py`)

- `e2e_server` — per-test isolated server: temp `PM_DATA_DIR`, fresh DB + seeded defaults, deterministic super password `e2e-pass-123` (`TEST_PASSWORD`), Co-Camp auto-pull disabled; waits for `/healthz`.
- `playwright` / `browser` / `context` / `page` — Playwright sync fixtures; `context` records video to the artifacts dir; the `page` fixture captures console errors, page errors and failed requests; on failure it writes a screenshot to the artifacts dir and copies the video on close.
- `setup_app(name)` — runs the setup wizard flow (`POST /setup`, redirects to `/`).
- `unlock(password=TEST_PASSWORD)` — unlocks the web session (`POST /unlock`).
- `password` — returns the deterministic super password.
- `seed_guest(name, phone, email)` — creates a guest via the services API.
- `seed_inventory(name, selling_price, stock_qty)` — adds an inventory item via `services.add_inventory_item`.
- `seed_expense_category(name)` — inserts an expense category row.

## Failure artifacts

On failure, `dist/e2e-artifacts/<test-name>/` contains `screenshot.png`, `video.webm`, `trace.zip`, and `server.log`.

## Writing tests

- **Role-based clicks** — use `page.get_by_role("button", name="...")` or `page.get_by_text(...).first`. `page.click('button[type="submit"]')` can click the sidebar *Lock session* button (it appears earlier in the DOM than page-content forms).
- **Auto-retrying assertions** — use `expect(locator).to_be_visible()` / `to_have_value(...)`.
- **Duplicates** — when a text appears both in a table cell and a heading, assert the visible one (e.g. `page.locator("td:has-text(...)")`).
- **Locked flows** — `setup_app(...)` then `unlock()` first (most mutations require unlock + super password).
- **Scoped form fills** — when a page has multiple inputs with the same `name`, fill via a scoped locator: `form = page.locator('form[action="/..."]'); form.locator('input[name="q"]').fill(...)`.
- **Routes without a UI form** — use `page.request.post(url, form={...})` (note: `data=` sends JSON, which the CSRF middleware rejects; `form=` sends form-encoded).
- **Keyboard navigation** — `test_keyboard_navigation_reaches_nav`: tabbing on the dashboard reaches the sidebar nav.
- **Long flows** — add `@pytest.mark.timeout(N)` when the flow needs longer than the default (see `test_session_expires_after_idle`, which needs >60s because the app's minimum session timeout is 1 minute).

**Cross-browser (optionally installed):** chromium smoke is required; Firefox and WebKit smoke run when installed locally: `python -m playwright install firefox webkit` (Linux may need `--with-deps`, e.g. `sudo apt-get install -y` per Playwright's list — or use `--with-deps` as root with sudo configured).

## Debugging

```bash
.venv-build/bin/python -m pytest "tests/e2e/test_x.py::test_y" -x -q -p no:randomly
```

- Server log for a failing test: `dist/e2e-artifacts/<nodeid>/server.log`
- Reproduce manually: start the server with a temp `PM_DATA_DIR`, or use the interactive scripts in `/tmp/opencode/debug_e2e*.py` as a starting point.

## CI

`.github/workflows/e2e.yml` runs the suite on PR/main: checkout → setup-python 3.12 → create `.venv-build` (runtime + dev hash-pinned deps) + `playwright==1.65.2` → `playwright install chromium --with-deps` → `pytest tests/e2e -q`; failure artifacts are uploaded as `e2e-artifacts`.

## Notes

- `test_session_expires_after_idle` is slow by design (~2 minutes).
- The service worker (`ui/web/static/sw.js`) only controls `/static/*` (the script's scope); the app-shell pages still load normally.
- Known benign console warning: the SW scope error (`... max scope allowed ('/static/') ...`).
