# Demo Videos Plan — SPMS E2E (app issue #42 follow-up)

**Goal:** one 20–40 second screen recording per app action, showing real UI
steps *and* the underlying business/data flow. Videos are local artifacts under
`dist/demo-videos/` (`.webm`, 1280×900, Chromium headless).

## Harness (planned)

Extend `tests/e2e/conftest.py` with a video helper:

```python
def record_video(page, out_path: str) -> str:
    """Save the page's Playwright video to out_path (returns the path)."""
    page.wait_for_timeout(1500)  # settle after the last step
    page.wait_for_load_state("networkidle")
    vid = page.video
    src = vid.path() if vid else None
    dst = str(out_path)
    if src and src != dst:
        shutil.copy(src, dst)
    return dst
```

Demo videos need the context started with `record_video_dir` (the existing
`context` fixture does this) — record into `dist/demo-videos/<action>.webm`.

## Captions (silent videos)

Videos are silent — captions carry the narration. Two options:

1. **In-page captions (recommended — works via Playwright):** add this helper to the conftest; call `caption(page, "1. Click Create reservation")` between steps (before the action it describes):

```python
def caption(page, text: str, duration: float = 2.5) -> None:
    """Show a caption overlay on the page (captured into the recorded video)."""
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
```

2. **Burn-in captions (post-recording, .srt):** generate `dist/demo-videos/<action>.srt` with timestamps per step and convert with `ffmpeg -i video.webm -vf subtitles=captions.srt demo.mp4`.

## Timing — 20–40s per video

- **No 4s white screen at the start:** recording starts as the page opens the app URL; `record_video` waits only ~300ms after the last step before saving — no long blank lead-in.
- **Paced actions:** captions show ~2–3s each (readable but not too fast-forwarded); steps use `wait_for_load_state("networkidle")`.
- **Total length ≈ 20–40s per video** (Video 1 ≈ 25s).

## Demo videos — plan (first video: setup; later videos continue after setup)

**Video 1 — Setup wizard (starts at the app URL, ~25s)**
- Steps: browser opens the app URL (e.g. `http://127.0.0.1:8000`) → `/setup` → mouse moves to the display-name field, types the brand ("Acadia Camp"), moves to tagline, types it, picks the loading animation → clicks Save/Apply → app redirects to the dashboard.
- Flow: `POST /setup` → `services.apply_branding_settings` → 303 → `/` (dashboard) — this is why all other videos start from the dashboard.

**Videos 2+ — start from the dashboard (already set up)** — each picks up where the previous stopped: dashboard → guests/reservations/POS/etc. as listed below.

## Task list (all videos, with durations)

Each video: show the cursor moving and typing into fields (Playwright records mouse movement + fills). Videos 2+ start from `/` (dashboard).

1. **Video 2 — Dashboard overview (30s)** — dashboard widgets: arrivals, departures, in-house/stayovers, financial snapshot. Flow: `GET /`.
2. **Video 3 — Dashboard day filter (20s)** — fill `?day=` → click View. Flow: `GET /` + ops day.
3. **Video 4 — Guests search (20s)** — search by name. Flow: `GET /guests?tab=directory` → `services.get_all_guests`.
4. **Video 5 — Guest portfolio (30s)** — open the 360° portfolio (profile, trips, POS/activity, payments, invoices). Flow: `GET /guests/{id}` → `services.get_guest_portfolio`.
5. **Video 6 — Guest edit profile (25s)** — edit name/notes + super password → "Guest updated". Flow: `POST /guests/{id}/update`.
6. **Video 7 — Reservations create (30s)** — fill guest/room/dates/rate → Create reservation → open the detail page. Flow: `POST /reservations/create` → detail.
7. **Video 8 — Reservation detail/folio (25s)** — folio, payments, check-in button. Flow: `GET /reservations/{id}`.
8. **Video 9 — Pricing quote (25s)** — Get pricing quote → suggested nightly + totals panel. Flow: `POST /reservations/quote`.
9. **Video 10 — Check-in (20s)** — Check in on the detail page. Flow: `POST /reservations/{id}/checkin`.
10. **Video 11 — Reservation groups: create (25s)** — groups page → create group. Flow: `POST /reservations/groups/create`.
11. **Video 12 — Reservation groups: add (25s)** — add a reservation to a group. Flow: `POST /reservations/groups/{gid}/add`.
12. **Video 13 — Group folio (20s)** — view group folio/report. Flow: `GET /reservations/groups/{gid}/folio`.
13. **Video 14 — POS inventory tab (20s)** — `/pos?tab=inventory` — items, stock, batches. Flow: `GET /pos?tab=inventory`.
14. **Video 15 — POS batches tab (20s)** — `/pos?tab=batches` — batch traceability. Flow: `GET /pos?tab=batches`.
15. **Video 16 — POS activities tab (20s)** — register new activity/trip + registered activities. Flow: `GET /pos?tab=activities` → `POST /activities/create`.
16. **Video 17 — POS history tab (20s)** — past walk-in sales/receipts. Flow: `GET /pos?tab=history`.
17. **Video 18 — POS add to reservation (25s)** — add a POS item to a reservation folio. Flow: `POST /pos/add`.
18. **Video 19 — Walk-in sale → receipt (30s)** — add item to cart → complete sale → invoice receipt served. Flow: `POST /pos/cart/add`, `POST /pos/walkin` → `/files/invoice/{name}`.
19. **Video 20 — Housekeeping tasks (25s)** — create task. Flow: `POST /housekeeping/tasks/create`.
20. **Video 21 — Accounting: expense (25s)** — record expense. Flow: `POST /accounting/expense`.
21. **Video 22 — Accounting: payment (25s)** — record payment. Flow: `POST /accounting/payment`.
22. **Video 23 — Accounting: shifts open + movement (30s)** — open shift + record movement. Flow: `POST /accounting/shifts/open`, `POST .../movement`.
23. **Video 24 — Accounting: night audit (20s)** — run advisory snapshot. Flow: `POST /accounting/night-audit/run`.
24. **Video 25 — Accounting: ledger (20s)** — `GET /accounting?tab=ledger`.
25. **Video 26 — Reports: P&L (25s)** — generate report. Flow: `POST /reports/run`.
26. **Video 27 — Reports: analytics export (20s)** — export → downloads tab. Flow: `POST /reports/analytics-export`.
27. **Video 28 — Assistant: ask (25s)** — ask a question → grounded answer. Flow: `POST /assistant/ask`.
28. **Video 29 — Settings: general save (20s)** — Save settings with super password. Flow: `POST /settings/save`.
29. **Video 30 — Settings: branding (20s)** — apply branding. Flow: `POST /settings/branding`.
30. **Video 31 — Settings: rooms (20s)** — add room. Flow: `POST /settings/rooms/add`.
31. **Video 32 — Settings: rate plans (20s)** — add rate plan. Flow: `POST /settings/rate-plans/add`.
32. **Video 33 — Settings: users (20s)** — users page + create user. Flow: `GET /settings/users`, `POST /settings/users/add`.
33. **Video 34 — Settings: health (20s)** — data health check page. Flow: `GET /settings/health`.
34. **Video 35 — Support: report page (20s)** — report an issue + diagnostics preview. Flow: `GET /support/report`.

## Complete list of actions (all possible demo videos)

(from the earlier section — pick from this when you want more than the 35 above)

1. **Setup wizard** (25s)
   - Steps: `/setup` → type display name, tagline → select animation → submit → `/`.
   - Flow: `POST /setup` → `services.apply_branding_settings` → dashboard renders (`GET /`).

2. **Unlock** (20s)
   - Steps: `/unlock` → type super password → submit → `/` (lock button visible).
   - Flow: `POST /unlock` → `deps.unlock` → `services.unlock_session` (per-session unlock).

3. **Dashboard** (30s)
   - Steps: `/` → show Arrivals/Departures/Stayovers panels + financial snapshot.
   - Flow: `GET /` → `services.get_front_desk_summary`, `get_general_ledger_summary`, ops.

4. **Guests — search** (20s)
   - Steps: `/guests` → type a name → Search → row visible.
   - Flow: `GET /guests?tab=directory` → `services.get_all_guests`.

5. **Guests — portfolio (360°)** (35s)
   - Steps: search → Open portfolio → profile/trips/POS/payments sections.
   - Flow: `GET /guests/{id}` → `services.get_guest_portfolio` + enrichments.

6. **Reservations — create** (30s)
   - Steps: `/reservations?tab=create` → guest/room/dates/rate → Create reservation → detail page.
   - Flow: `POST /reservations/create` → `services.create_reservation` → 303 to `/reservations/{id}`.

7. **Reservations — detail/folio + check-in** (30s)
   - Steps: detail page → show folio, payments, Check in → status "Checked In".
   - Flow: `GET /reservations/{id}` → folio; `POST /reservations/{id}/checkin` → `services.update_reservation_status`.

8. **Reservations — pricing quote** (25s)
   - Steps: create tab → fill → click "Get pricing quote" → quote panel (suggested/quoted nightly, totals).
   - Flow: `POST /reservations/quote` → `services.quote_reservation_pricing` → 303 with `quote=1` → create tab.

9. **POS — inventory search + add to cart** (25s)
   - Steps: `/pos?tab=sell` → search inventory → Add to cart → cart shows item.
   - Flow: `GET /pos?tab=sell` → `services.get_inventory_items(q)`; `POST /pos/cart/add` → session cart.

10. **POS — walk-in sale (complete + receipt)** (30s)
    - Steps: add item → "Complete walk-in sale & get receipt" → invoice file served.
    - Flow: `POST /pos/walkin` → `services.pos_complete_walkin` → 303 to `/files/invoice/{name}`.

11. **Housekeeping — create task** (25s)
    - Steps: `/housekeeping` → open Create task → select room/priority/assignee → Create task.
    - Flow: `POST /housekeeping/tasks/create` → `services.create_housekeeping_task`.

12. **Accounting — record expense** (25s)
    - Steps: `/accounting?tab=expenses` → fill parameter/amount/category → Record expense.
    - Flow: `POST /accounting/expense` → `services.record_operational_expense`.

13. **Accounting — record payment** (25s)
    - Steps: `/accounting?tab=payments` → fill amount → Record payment.
    - Flow: `POST /accounting/payment` → `services.record_payment`.

14. **Accounting — shift + movement** (30s)
    - Steps: `/accounting?tab=shifts` → open shift, record movement.
    - Flow: `POST /accounting/shifts/open` (`services.open_cash_shift`); `POST .../{id}/movement` (`services.add_cash_movement`).

15. **Reports — P&L generate** (25s)
    - Steps: `/reports?tab=generate` → select P&L → Generate → flash "Report generated".
    - Flow: `POST /reports/run` → `services.generate_report` (P&L).

16. **Assistant — ask** (30s)
    - Steps: `/assistant` → type a question → Send message → response.
    - Flow: `POST /assistant/ask` → `assistant.chat` (grounded answer from app data).

17. **Settings — branding + save** (25s)
    - Steps: `/settings?tab=general` → apply branding; Save settings with super password → flash.
    - Flow: `POST /settings/branding` → `services.apply_branding_settings`; `POST /settings/save` → `services.save_settings`.

18. **Settings — rooms (add room)** (25s)
    - Steps: `/settings?tab=rooms` → add room (number/type) → flash "Room added (#N)."
    - Flow: `POST /settings/rooms/add` → room row appears.

19. **Support — report page** (20s)
    - Steps: `/support/report` → type description → diagnostics preview + report preview.
    - Flow: `GET /support/report` → sanitized diagnostics.

20. **Guests — edit profile (unlock + password)** (25s)
    - Steps: open portfolio → Edit guest → change name → Update profile.
    - Flow: `POST /guests/{id}/update` → `services.update_guest` (requires unlock + super password).

## Complete list of actions (all possible demo videos)

The app has these user-facing actions; each can be a 20–40s demo video
(add `caption(page, ...)` calls between steps per the Captions section).

**Setup & infrastructure**
- Setup wizard (done) · Lock session (done) · Unlock recovery flow (`/unlock/recovery`)

**Dashboard**
- Dashboard overview (done: arrivals/departures/stayovers) · Dashboard by day (`?day=`)

**Guests**
- Search (done) · Open 360° portfolio (done) · Edit profile via UI (done)

**Reservations**
- Create (done) · Detail/folio (done) · Pricing quote (done) · Check-in/check-out (done via detail)
- Checkout override (password), Modify reservation, Cancel/No-show (password flows)
- Groups: list page, create group, add reservation to group, remove, group folio
- Book activity / trip (on the reservation detail page) · Invoice generation (done)

**POS / Inventory**
- Sell page + inventory search (done) + add to cart (done) · Walk-in sale → receipt (done)
- POS `tab=inventory` (manage items), `tab=batches` (batch traceability), `tab=meals`, `tab=activities` (done), `tab=history`
- POS add-to-reservation (`/pos/add`), walk-in cart remove/clear, Inventory restock (`/inventory/restock`), add item (`/inventory/add`), print batch label

**Housekeeping**
- Page: tasks + blocks · Create task (done) · Update task status · Edit task · Generate tasks for dirty rooms · Room blocks create/resolve (done) · Blocks filter

**Accounting & Reports**
- Accounting: expense (done), void expense, payments (done), refunds (done), shifts open (done)/movement (done)/close, night audit run, ledger tab
- Reports: `/reports/run` — P&L (done), Cash Flow, VAT, Payments, Occupancy, Daily Ops, Front Desk, Housekeeping Ops, Groups, Packages, Shifts summary · Analytics export (done) · Exports + Invoices lists

**Assistant**
- Ask (done) · Clear chat · Feedback · Action confirm/cancel · Training: sources, estimate, start

**Settings / Admin**
- General: Save settings (done), Apply branding (done) · Rooms & Plans: rooms add (done)/delete, rate plans add/edit (pages `/settings/rate-plans`, `/settings/rate-plans/add`)
- Seed & Data (done): inventory CSV export, CSV template, seed config export, demo preset, reset settings
- Users & Roles (done): page, add user (done), edit user, roles list
- Updates & Health: check for updates, health page (`/settings?tab=updates`)
- Approvals, Packages, Service Catalog, Vouchers pages
- Backup now (done), Test label print

**Support**
- Report issue page (done) — plus flows around generating the report

## Runner (after implementing the tests)

```bash
.venv-build/bin/python -m pytest tests/e2e/test_demo_videos.py -q -p no:randomly
# videos: dist/demo-videos/<action>.webm
```

Or a standalone script (`scripts/make_demo_videos.py`) that reuses the `e2e_server` harness.

## "Install" video — Playwright limitation

Playwright cannot record terminal/shell steps. For the install video
(venv + `pip install -r requirements.txt -r requirements-dev.txt` + `playwright install chromium`):

- **asciinema:** `asciinema rec -c "bash scripts/install.sh" docs/videos/install.cast` → `ffmpeg -i install.cast install.mp4`.
- **OBS / QuickTime:** screen-record the terminal while running the steps; save to `docs/videos/install.mp4`.

## Notes

- Optional: upload the videos to GitHub issue #42.
- `ffmpeg -i input.webm -t 35 -crf 20 output.mp4` for compression/trimming.
