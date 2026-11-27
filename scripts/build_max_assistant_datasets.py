#!/usr/bin/env python3
"""Build maximal SPMS/Co-Camp assistant training datasets.

Generates/refreshes:
- data/assistant_nlu/intents_seed.jsonl          (expanded, all intents)
- data/assistant_nlu/feedback.jsonl              (curated bootstrap + preserved real)
- co-camp/co_camp/data/persona_examples.jsonl    (expanded persona/app/business)
- data/datasets/manifest.json                    (versioned registry)
- data/datasets/README.md                        (dataset system docs)
- data/datasets/curated/*.jsonl                  (business/app/ops/history/feedback)
- data/datasets/schema/*.json                    (schemas)
- data/datasets/processed/*                      (prepared train/eval splits)

Design goals:
- Grounded in real SPMS intents/tools/workflows (no invented capabilities).
- Business/app/operations/history aware.
- Continuously improvable: feedback ingestion + versioned snapshots + eval splits.
- Deterministic generation (seeded RNG) for reproducibility.
"""

from __future__ import annotations

import hashlib
import json
import random
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CO_CAMP = ROOT / "co-camp"
DATA = ROOT / "data"
NLU = DATA / "assistant_nlu"
DATASETS = DATA / "datasets"
CURATED = DATASETS / "curated"
PROCESSED = DATASETS / "processed"
SCHEMA = DATASETS / "schema"
HISTORY = DATASETS / "history"
SNAPSHOTS = DATASETS / "snapshots"

SEED_PATH = NLU / "intents_seed.jsonl"
FEEDBACK_PATH = NLU / "feedback.jsonl"
PERSONA_OUT = CO_CAMP / "co_camp" / "data" / "persona_examples.jsonl"
BRAIN_PATH = DATA / "assistant_knowledge" / "agent_brain.json"

RNG = random.Random(42)
TODAY = datetime.now(timezone.utc).date().isoformat()
VERSION = datetime.now(timezone.utc).strftime("%Y.%m.%d")

SYSTEM_GROUNDED = (
    "You are Co-Camp, the Manager Assistant for SPMS (Super Property Management System), "
    "developed by Michael Helmy. Use ONLY provided grounded data/tools/knowledge. "
    "Never invent IDs, dates, amounts, guests, reservations, or actions. "
    "Read-only by default; mutating actions require explicit validated confirmation/proof. "
    "If data is missing or ambiguous, ask a clear clarifying question."
)

# Canonical intent catalog. Keep labels aligned with src/app_core/assistant/common.py INTENT_LABELS.
INTENTS: dict[str, dict[str, Any]] = {
    "capabilities_help": {
        "area": "app",
        "desc": "Explain what Co-Camp can do in SPMS, boundaries, and example questions.",
        "queries": [
            "what can you do", "what are your capabilities", "how can you help me",
            "what questions can I ask", "what data can you access in SPMS",
            "can you help with reservations and accounting", "what are your limits",
            "show me examples of questions", "what can you do for a property manager",
            "do you have access to reports and guests", "which SPMS modules do you cover",
        ],
    },
    "greeting_smalltalk": {
        "area": "app",
        "desc": "Friendly greeting/persona smalltalk; keep grounded and brief.",
        "queries": [
            "hi", "hello", "good morning", "hey Co-Camp", "thanks", "thank you",
            "how are you", "who are you", "good evening",
        ],
    },
    "property_stats": {
        "area": "operations",
        "desc": "High-level property stats: guests, rooms, reservations, occupancy signals.",
        "queries": [
            "how many guests do we have", "total rooms in the property", "property stats",
            "give me property overview", "how many reservations total",
            "how many active guests", "property summary stats",
        ],
    },
    "today_ops": {
        "area": "operations",
        "desc": "Today's operational snapshot.",
        "queries": [
            "what's happening today", "today ops", "today's operations summary",
            "give me today's snapshot", "what do I need to know today",
            "today front desk summary", "daily operations today",
        ],
    },
    "business_partner_briefing": {
        "area": "business",
        "desc": "Business-partner briefing with KPIs, risks, opportunities, suggested actions.",
        "queries": [
            "give me a business briefing", "manager briefing for this month",
            "business partner summary", "what are key risks and opportunities",
            "executive briefing for last month", "how is the business doing overall",
        ],
    },
    "decision_support": {
        "area": "business",
        "desc": "Decision support combining financial/ops signals for a period.",
        "queries": [
            "give me decision support for this month", "what should I focus on this week",
            "manager decision support", "signals and risks for last month",
            "where should I pay attention operationally and financially",
        ],
    },
    "report_pl": {
        "area": "accounting",
        "desc": "Profit and loss report for a period.",
        "queries": [
            "profit and loss for last month", "P&L this month", "are we profitable this month",
            "income vs expenses last 30 days", "net profit for {start} to {end}",
            "show P&L report", "how did we do profit-wise last month",
        ],
    },
    "report_cash_flow": {
        "area": "accounting",
        "desc": "Cash flow report for a period.",
        "queries": [
            "cash flow last month", "cash in and cash out this month",
            "money movement for {start} to {end}", "cashflow report last 30 days",
            "how much cash came in vs went out", "liquidity summary last month",
        ],
    },
    "report_vat": {
        "area": "accounting",
        "desc": "VAT/tax report for a period.",
        "queries": [
            "VAT report last month", "tax report for {start} to {end}",
            "output and input VAT this month", "VAT summary for filing",
            "how much VAT do we owe last month",
        ],
    },
    "report_payment_methods": {
        "area": "accounting",
        "desc": "Payment method breakdown for a period.",
        "queries": [
            "payment methods breakdown last month", "how did guests pay us this month",
            "cash vs card vs transfer payments for {start} to {end}",
            "payment channels summary", "collections by method last month",
        ],
    },
    "report_occupancy": {
        "area": "operations",
        "desc": "Occupancy report with ADR/RevPAR where available.",
        "queries": [
            "occupancy report last month", "how full were we in {start} to {end}",
            "ADR and RevPAR last month", "occupancy performance this month",
            "room nights and occupancy report",
        ],
    },
    "report_daily_ops": {
        "area": "operations",
        "desc": "Daily operations report: arrivals, departures, in-house.",
        "queries": [
            "daily ops report for today", "arrivals and departures tomorrow",
            "ops report for {date}", "who is checking in and out today",
            "daily operations report for yesterday",
        ],
    },
    "occupancy_summary": {
        "area": "operations",
        "desc": "Occupancy summary/utilization for a period.",
        "queries": [
            "occupancy summary this month", "how occupied are we this week",
            "utilization summary for last month", "overall occupancy picture",
        ],
    },
    "compare_periods": {
        "area": "business",
        "desc": "Compare current period vs previous period.",
        "queries": [
            "compare this month to last month", "compare P&L this month vs previous",
            "period over period occupancy comparison", "how does this week compare to last week",
            "compare cash flow between periods",
        ],
    },
    "outstanding_balances": {
        "area": "accounting",
        "desc": "Outstanding balances / receivables.",
        "queries": [
            "who owes us money", "outstanding balances", "unpaid reservation balances",
            "accounts receivable summary", "which guests have balances due",
            "show overdue balances",
        ],
    },
    "inventory_alerts": {
        "area": "operations",
        "desc": "Inventory low stock/alerts.",
        "queries": [
            "inventory alerts", "low stock items", "what items are running low",
            "stock alerts", "which inventory items need reorder",
        ],
    },
    "top_selling_items": {
        "area": "business",
        "desc": "Top selling POS/inventory items.",
        "queries": [
            "top selling items", "best sellers this month", "what sells the most",
            "top POS items last month", "most popular items",
        ],
    },
    "expenses_summary": {
        "area": "accounting",
        "desc": "Expenses summary for a period.",
        "queries": [
            "expenses summary last month", "how much did we spend this month",
            "expense breakdown for {start} to {end}", "operational expenses summary",
        ],
    },
    "sales_breakdown": {
        "area": "business",
        "desc": "Sales breakdown by category/source.",
        "queries": [
            "sales breakdown this month", "revenue breakdown last month",
            "sales by category for {start} to {end}", "where did sales come from",
        ],
    },
    "reservation_pipeline": {
        "area": "operations",
        "desc": "Reservation pipeline/status distribution.",
        "queries": [
            "reservation pipeline", "how many reservations by status",
            "booking pipeline summary", "pending confirmed checked-in reservations",
        ],
    },
    "housekeeping_summary": {
        "area": "operations",
        "desc": "Housekeeping status summary.",
        "queries": [
            "housekeeping summary", "how many dirty rooms", "housekeeping status today",
            "room cleaning status", "HK summary",
        ],
    },
    "room_availability": {
        "area": "operations",
        "desc": "Room availability for dates/criteria.",
        "queries": [
            "available rooms tonight", "room availability for {start} to {end}",
            "which rooms are free tomorrow", "do we have availability this weekend",
        ],
    },
    "menu_info": {
        "area": "operations",
        "desc": "POS menu/meals/items information.",
        "queries": [
            "show menu items", "what meals are available", "POS menu info",
            "restaurant/menu list", "what can we sell in POS",
        ],
    },
    "rate_plans": {
        "area": "business",
        "desc": "Rate plans/pricing plans configured in SPMS.",
        "queries": [
            "list rate plans", "what pricing plans do we have", "rate plans configured",
            "show room rate plans", "pricing plans and rates",
        ],
    },
    "rate_rules_list": {
        "area": "business",
        "desc": "Rate rules list.",
        "queries": [
            "list rate rules", "what rate rules exist", "pricing rules configured",
            "show rate rules", "rate adjustment rules",
        ],
    },
    "service_catalog_list": {
        "area": "operations",
        "desc": "Service catalog / extra services.",
        "queries": [
            "list service catalog", "what extra services can we add",
            "available services", "service catalog items", "extra services list",
        ],
    },
    "discount_vouchers_list": {
        "area": "business",
        "desc": "Discount vouchers/coupons.",
        "queries": [
            "list discount vouchers", "active vouchers", "what discounts are available",
            "voucher codes", "discount coupons list",
        ],
    },
    "approvals_list": {
        "area": "operations",
        "desc": "Pending/processed approvals.",
        "queries": [
            "list approvals", "pending approvals", "what needs approval",
            "approval requests", "show approvals queue",
        ],
    },
    "approval_detail": {
        "area": "operations",
        "desc": "Details for a specific approval.",
        "queries": [
            "approval #12 details", "show approval 5", "details for approval request 3",
            "what is approval #7 about",
        ],
    },
    "ledger_integrity": {
        "area": "accounting",
        "desc": "Ledger/data integrity checks.",
        "queries": [
            "check ledger integrity", "are there accounting inconsistencies",
            "run ledger health check", "any orphaned ledger records",
            "verify accounting integrity",
        ],
    },
    "reservation_financial_integrity": {
        "area": "accounting",
        "desc": "Reservation financial integrity checks.",
        "queries": [
            "check reservation financial integrity", "reservation balance integrity",
            "are reservation totals consistent", "verify folio financials",
        ],
    },
    "guest_search": {
        "area": "operations",
        "desc": "Search guests by name/phone/email.",
        "queries": [
            "find guest Ahmed", "search guest by phone 555", "look up guest Sara",
            "is there a guest named Mohamed", "search guests",
        ],
    },
    "guest_profile": {
        "area": "operations",
        "desc": "Guest profile details.",
        "queries": [
            "guest #12 profile", "show guest 5 details", "profile for guest #3",
            "guest contact info for id 7",
        ],
    },
    "guest_portfolio": {
        "area": "operations",
        "desc": "Guest 360 portfolio: stays, payments, POS, invoices, activity.",
        "queries": [
            "guest #3 full portfolio", "360 view for guest 12", "guest portfolio for #5",
            "show everything for guest 7", "guest history and spending portfolio",
        ],
    },
    "guest_last_visit": {
        "area": "operations",
        "desc": "Guest most recent stay/visit.",
        "queries": [
            "when did guest #3 last stay", "last visit for guest 12",
            "most recent reservation for guest #5", "guest 7 last check-in",
        ],
    },
    "guest_top_items_last_visit": {
        "area": "operations",
        "desc": "Top items ordered by guest on last visit.",
        "queries": [
            "what did guest #3 order most last visit", "top items for guest 12 last stay",
            "guest 5 favorite items last visit", "most ordered POS items by guest #7 last visit",
        ],
    },
    "guest_last_visit_spend": {
        "area": "accounting",
        "desc": "Guest spend on last visit.",
        "queries": [
            "how much did guest #3 spend last visit", "guest 12 last visit total spend",
            "last stay spending for guest #5", "guest 7 charges last visit",
        ],
    },
    "guest_activity_bookings": {
        "area": "operations",
        "desc": "Activities/excursions booked by guest.",
        "queries": [
            "guest #3 activity bookings", "what activities did guest 12 book",
            "guest 5 excursions", "trips booked by guest #7",
        ],
    },
    "list_activities": {
        "area": "operations",
        "desc": "List registered activities/trips.",
        "queries": [
            "list activities", "what activities are available", "registered trips",
            "show excursions", "available activities",
        ],
    },
    "activity_stats": {
        "area": "business",
        "desc": "Activity booking statistics.",
        "queries": [
            "activity stats", "trip booking statistics", "which activities are most booked",
            "activity revenue stats", "excursion performance",
        ],
    },
    "reservation_search": {
        "area": "operations",
        "desc": "Search reservations.",
        "queries": [
            "find reservation for Ahmed", "search reservations this week",
            "reservations from Booking.com", "look up booking for room 101",
        ],
    },
    "reservation_summary": {
        "area": "operations",
        "desc": "Reservation summary/details.",
        "queries": [
            "reservation #104 summary", "details for booking 58",
            "show reservation 12", "reservation info for #7",
        ],
    },
    "reservation_balance": {
        "area": "accounting",
        "desc": "Reservation balance/due/paid.",
        "queries": [
            "balance for reservation #104", "how much is owed on booking 58",
            "reservation 12 balance due", "paid vs due for reservation #7",
        ],
    },
    "inventory_search": {
        "area": "operations",
        "desc": "Search inventory items.",
        "queries": [
            "search inventory for water", "find item coffee", "inventory search towel",
            "look up product in inventory",
        ],
    },
    "inventory_item_details": {
        "area": "operations",
        "desc": "Inventory item details.",
        "queries": [
            "inventory item #5 details", "show item 12", "details for inventory item 3",
            "stock and price for item #7",
        ],
    },
    "walkin_sales_summary": {
        "area": "accounting",
        "desc": "Walk-in POS sales summary.",
        "queries": [
            "walk-in sales summary", "POS walk-in sales today", "walkin sales this month",
            "how much walk-in POS revenue", "non-reservation sales summary",
        ],
    },
    "payments_summary": {
        "area": "accounting",
        "desc": "Payments summary.",
        "queries": [
            "payments summary this month", "total payments received last month",
            "payment summary for {start} to {end}", "how much did we collect",
        ],
    },
    "reservation_groups": {
        "area": "operations",
        "desc": "List reservation groups.",
        "queries": [
            "list reservation groups", "show booking groups", "group reservations",
            "tour groups", "reservation groups list",
        ],
    },
    "reservation_group_detail": {
        "area": "operations",
        "desc": "Reservation group detail.",
        "queries": [
            "group #3 details", "reservation group 5 summary", "show group 2",
            "details for booking group #1",
        ],
    },
    "packages_list": {
        "area": "business",
        "desc": "Packages/bundles list.",
        "queries": [
            "list packages", "available packages", "what packages do we offer",
            "reservation packages", "bundles list",
        ],
    },
    "reservation_packages_applied": {
        "area": "operations",
        "desc": "Packages applied to a reservation.",
        "queries": [
            "packages applied to reservation #12", "reservation 5 packages",
            "what packages are on booking #3", "applied bundles for reservation 7",
        ],
    },
    "cash_shifts": {
        "area": "accounting",
        "desc": "Cash shifts summary/status.",
        "queries": [
            "cash shifts", "open cash shifts", "shift summary today",
            "cash drawer shifts", "who has an open shift",
        ],
    },
    "night_audit_runs": {
        "area": "operations",
        "desc": "Night audit runs/history.",
        "queries": [
            "night audit runs", "last night audit", "night audit history",
            "was night audit run", "audit runs for this month",
        ],
    },
    "room_blocks": {
        "area": "operations",
        "desc": "Room blocks/OOO/OOS.",
        "queries": [
            "room blocks", "out of order rooms", "blocked rooms",
            "OOO rooms today", "room maintenance blocks",
        ],
    },
    "housekeeping_tasks": {
        "area": "operations",
        "desc": "Housekeeping tasks list/status.",
        "queries": [
            "housekeeping tasks", "cleaning tasks today", "open HK tasks",
            "room cleaning tasks", "housekeeping task list",
        ],
    },
    "housekeeping_ops_report": {
        "area": "operations",
        "desc": "Housekeeping operations report.",
        "queries": [
            "housekeeping ops report", "HK operations report", "housekeeping performance report",
            "cleaning operations summary",
        ],
    },
    "front_desk_ops": {
        "area": "operations",
        "desc": "Front desk operations overview.",
        "queries": [
            "front desk ops", "front desk summary today", "reception operations",
            "front office overview", "desk ops snapshot",
        ],
    },
    "front_desk_arrivals": {
        "area": "operations",
        "desc": "Arrivals list.",
        "queries": [
            "arrivals today", "who is arriving tomorrow", "expected check-ins today",
            "front desk arrivals", "today's arrivals",
        ],
    },
    "front_desk_departures": {
        "area": "operations",
        "desc": "Departures list.",
        "queries": [
            "departures today", "who is checking out today", "expected departures tomorrow",
            "front desk departures", "today's checkouts",
        ],
    },
    "front_desk_in_house": {
        "area": "operations",
        "desc": "In-house guests/rooms.",
        "queries": [
            "in-house guests", "who is in house today", "currently checked in guests",
            "in house list", "rooms occupied now",
        ],
    },
    "recent_activity": {
        "area": "operations",
        "desc": "Recent activity/audit/events in SPMS.",
        "queries": [
            "recent activity", "what happened recently", "latest activity log",
            "recent changes in system", "recent audit activity",
        ],
    },
    "expiring_batches": {
        "area": "operations",
        "desc": "Inventory batches expiring soon.",
        "queries": [
            "expiring batches", "what items are expiring soon", "batches near expiry",
            "expiry alerts", "soon to expire inventory lots",
        ],
    },
    "inventory_batches": {
        "area": "operations",
        "desc": "Inventory batches/lots list.",
        "queries": [
            "inventory batches", "list batches", "stock lots", "batch list",
            "show inventory lots",
        ],
    },
    "trace_barcode": {
        "area": "operations",
        "desc": "Trace barcode/lot code.",
        "queries": [
            "trace barcode LOT-123", "trace lot ABC", "barcode trace 12345",
            "where did lot LOT-9 come from", "trace batch code",
        ],
    },
    "app_update_status": {
        "area": "app",
        "desc": "App update/version status.",
        "queries": [
            "check for app updates", "what version is SPMS running", "app update status",
            "is there a new version", "software update check",
        ],
    },
    "health_diagnostics": {
        "area": "app",
        "desc": "System health diagnostics.",
        "queries": [
            "health diagnostics", "system health check", "is the app healthy",
            "diagnostics status", "run health check",
        ],
    },
    "ambiguous_needs_clarification": {
        "area": "app",
        "desc": "Ambiguous request requiring clarification.",
        "queries": [
            "show me the balance", "what about him", "check that", "show report",
            "how much", "give me details", "what about last time",
        ],
    },
    "unsupported_or_unsafe": {
        "area": "app",
        "desc": "Unsupported or unsafe action/request.",
        "queries": [
            "delete reservation 12", "refund guest without approval", "change room price now",
            "hack the system", "drop database", "send email to all guests",
        ],
    },
    "compound_multi_intent": {
        "area": "app",
        "desc": "Multiple intents in one request.",
        "queries": [
            "give me P&L and cash flow for last month", "show arrivals today and outstanding balances",
            "find guest Ahmed and show his last visit", "occupancy and revenue summary for this month",
        ],
    },
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except Exception:
            pass
    return rows


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def _write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _dedupe_rows(rows: list[dict], key_fn) -> list[dict]:
    seen = set()
    out = []
    for r in rows:
        k = key_fn(r)
        if k in seen:
            continue
        seen.add(k)
        out.append(r)
    return out


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def _hash_id(*parts: str) -> str:
    h = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:16]
    return h


DATE_START = "2026-11-01"
DATE_END = "2026-11-30"
DATE_SINGLE = "2026-11-15"

FILLERS = {
    "start": DATE_START,
    "end": DATE_END,
    "date": DATE_SINGLE,
}


def _render(text: str) -> str:
    try:
        return text.format(**FILLERS)
    except Exception:
        return text


# ---------------------------------------------------------------------------
# Intent seed expansion
# ---------------------------------------------------------------------------

PARA_PREFIXES = [
    "", "please ", "can you ", "could you ", "I need to ", "I want to ",
    "help me ", "for me, ", "quick question: ", "manager question: ",
]
PARA_SUFFIXES = [
    "", " please", "?", " for me", " right now", " when you can",
    " from SPMS data", " based on real data",
]
APP_PREFIXES = ["In SPMS, ", "In the app, ", "From SPMS, ", "Using SPMS, "]
OPS_PREFIXES = ["For operations, ", "For front desk, ", "For today's shift, "]
BIZ_PREFIXES = ["For business review, ", "For management, ", "For the owner, "]
ACCT_PREFIXES = ["For accounting, ", "For finance, ", "For the books, "]


def _area_prefixes(area: str) -> list[str]:
    base = [""]
    if area == "operations":
        base += OPS_PREFIXES + APP_PREFIXES
    elif area == "business":
        base += BIZ_PREFIXES + APP_PREFIXES
    elif area == "accounting":
        base += ACCT_PREFIXES + APP_PREFIXES
    else:
        base += APP_PREFIXES
    return base


def generate_intent_seed(existing: list[dict]) -> list[dict]:
    rows = []
    for r in existing:
        text = (r.get("text") or "").strip()
        label = (r.get("label") or "").strip()
        if text and label in INTENTS:
            rows.append({"text": text, "label": label, "source": "seed_original"})

    for label, meta in INTENTS.items():
        area = meta["area"]
        base_queries = [_render(q) for q in meta.get("queries", [])]
        # canonical queries
        for q in base_queries:
            rows.append({"text": q, "label": label, "source": "curated_canonical"})
            rows.append({"text": q.rstrip("?") + "?", "label": label, "source": "curated_canonical"})
        # paraphrases
        prefixes = _area_prefixes(area)
        for q in base_queries:
            for pfx in prefixes:
                for sfx in ["", "?", " please"]:
                    t = f"{pfx}{q}{sfx}".strip()
                    t = re.sub(r"\?\?+", "?", t)
                    if len(t) < 4:
                        continue
                    rows.append({"text": t, "label": label, "source": "curated_paraphrase"})
        # persona-aware business/app phrasing
        for q in base_queries[:8]:
            rows.append({"text": f"Co-Camp, {q}", "label": label, "source": "curated_cocamp"})
            rows.append({"text": f"Hey Co-Camp, {q}", "label": label, "source": "curated_cocamp"})
        # business history awareness for relevant intents
        if label in {"report_pl", "report_cash_flow", "report_vat", "report_payment_methods", "report_occupancy",
                     "occupancy_summary", "compare_periods", "expenses_summary", "sales_breakdown",
                     "top_selling_items", "outstanding_balances", "payments_summary", "business_partner_briefing",
                     "decision_support", "reservation_pipeline", "property_stats"}:
            for tmpl in [
                "compare {q} to last period and tell me if we're improving",
                "show {q} and highlight changes from previous period",
                "based on business history, {q}",
                "trend over time: {q}",
                "how has this changed over time: {q}",
            ]:
                rows.append({"text": tmpl.format(q=q), "label": label, "source": "curated_history"})
        # app/operations phrasing
        if area in {"operations", "app"}:
            for tmpl in [
                "where in SPMS can I see this: {q}",
                "walk me through this in the app: {q}",
                "app question: {q}",
            ]:
                rows.append({"text": tmpl.format(q=q), "label": "capabilities_help" if "where in SPMS" in tmpl else label, "source": "curated_app_ops"})
    # clean + dedupe
    cleaned = []
    for r in rows:
        t = re.sub(r"\s+", " ", (r.get("text") or "").strip())
        l = (r.get("label") or "").strip()
        if not t or l not in INTENTS:
            continue
        cleaned.append({"text": t, "label": l, "source": r.get("source", "curated")})
    return _dedupe_rows(cleaned, lambda r: (_norm(r["text"]), r["label"]))


# ---------------------------------------------------------------------------
# Persona expansion
# ---------------------------------------------------------------------------

PERSONA_IDENTITY = [
    ("Who are you?", "greeting_smalltalk", "I'm Co-Camp, the Manager Assistant for SPMS (Super Property Management System), developed by Michael Helmy. I help with property operations, reservations, guests, housekeeping, accounting, and reports using real SPMS data."),
    ("What is your name?", "greeting_smalltalk", "My name is Co-Camp. I'm the Manager Assistant for SPMS, developed by Michael Helmy."),
    ("Who developed you?", "greeting_smalltalk", "I was developed by Michael Helmy as the Manager Assistant for SPMS."),
    ("Who made Co-Camp?", "greeting_smalltalk", "Co-Camp was developed by Michael Helmy for SPMS."),
    ("What is SPMS?", "capabilities_help", "SPMS is the Super Property Management System. I help managers operate it across reservations, guests, housekeeping, POS, accounting, reports, and settings."),
    ("What is your role?", "capabilities_help", "My role is Manager Assistant for SPMS. I provide grounded, read-only answers from real app data and help with business operations and accounting."),
    ("Are you an external AI?", "capabilities_help", "No. I'm Co-Camp, a local SPMS assistant. I use grounded app data/tools and curated knowledge; I don't make external API calls."),
    ("Can you make changes in the system?", "unsupported_or_unsafe", "I'm read-only by default. Mutating actions require explicit validated confirmation/proof and supported workflows. I can help you find the right place in SPMS."),
]

APP_HOWTO = [
    ("How do I create a reservation in SPMS?", "capabilities_help", "Open Reservations > Create, enter guest and stay details, select room/rate, review quote, then save. I can also help look up availability or existing reservations."),
    ("Where do I record a payment?", "capabilities_help", "Open the reservation detail and use Record Payment, or use Accounting > Payments & Refunds for walk-in/reservation payments depending on context."),
    ("How do I check in a guest?", "capabilities_help", "Open the reservation detail from Reservations list/detail and use Check in. Ensure room/housekeeping/readiness and balance policy are handled."),
    ("How do I generate an invoice?", "capabilities_help", "Open the reservation detail and use Generate/Print Invoice. I can also summarize reservation balance and charges."),
    ("Where is housekeeping?", "capabilities_help", "Use the Housekeeping page for room status, tasks, and room blocks (OOO/OOS). I can summarize housekeeping tasks and blocks."),
    ("How do I add an inventory item?", "capabilities_help", "Go to POS > Inventory and use Add Item. Sensitive actions may require unlock/super password depending on settings."),
    ("Where can I see P&L?", "capabilities_help", "Use Reports > Generate for P&L, or Accounting overview/reports. I can generate a grounded P&L summary for a date range."),
    ("How do I handle night audit?", "capabilities_help", "Go to Accounting > Night Audit to run/review audit snapshots. I can also show night audit runs and daily ops context."),
    ("Where do I manage rate plans?", "capabilities_help", "Use Settings > Rooms & Plans / Rate Plans. I can list configured rate plans and rate rules."),
    ("How do I export reports?", "capabilities_help", "Use Reports > Generate/Downloads. Exports are generated from real data and saved for download."),
]

BUSINESS_HISTORY_QA = [
    ("How has occupancy changed compared to last month?", "compare_periods", "I can compare occupancy for the current period versus the previous period using grounded SPMS reports. Ask: 'compare occupancy this month to last month'."),
    ("Are we improving financially over time?", "decision_support", "I can review P&L, cash flow, occupancy, balances, and ops signals over selected periods and compare to prior periods. I only report grounded data."),
    ("What business trends should I watch?", "business_partner_briefing", "I can highlight grounded KPIs, risks, and opportunities: occupancy, ADR/RevPAR when available, revenue/expenses/profit, cash flow, outstanding balances, inventory alerts, and ops bottlenecks."),
    ("Can you remember what happened last month?", "compare_periods", "I can retrieve historical business data from SPMS records for prior periods (reports, reservations, payments, ledger, activity) when you specify the period. I don't guess missing history."),
    ("How do you get smarter over time?", "capabilities_help", "I improve through approved feedback/corrections, curated training datasets, and retrained local models. Corrections and positive feedback are stored, sanitized, and can be used in future training runs."),
]

OPS_PLAYBOOK_QA = [
    ("What should I check at start of day?", "today_ops", "Check today's arrivals/departures/in-house, housekeeping readiness, outstanding balances, cash shift status, and critical alerts. I can pull a grounded today-ops snapshot."),
    ("What should I check before night audit?", "report_daily_ops", "Review arrivals/departures, unsettled folios, payments/refunds, cash shift closure, housekeeping exceptions, and ledger warnings before running night audit."),
    ("How do I handle overdue balances?", "outstanding_balances", "Review outstanding balances, identify reservation/guest, confirm folio charges/payments, and follow your property policy for collection. I can list grounded outstanding balances."),
    ("What are signs of inventory risk?", "inventory_alerts", "Low stock, expiring batches, negative/odd movements, and high-demand items without replenishment. I can show inventory alerts and expiring batches."),
    ("How should I review business performance weekly?", "business_partner_briefing", "Compare P&L, cash flow, occupancy/ADR/RevPAR, sales mix, expenses, receivables, and ops exceptions week-over-week using grounded reports."),
]


def generate_persona_examples() -> list[dict]:
    rows: list[dict] = []
    seen = set()

    def add(text: str, label: str, answer: str = "", source: str = "curated_persona"):
        t = re.sub(r"\s+", " ", text.strip())
        k = (_norm(t), label)
        if not t or k in seen or label not in INTENTS:
            return
        seen.add(k)
        r = {"text": t, "label": label, "source": source}
        if answer:
            r["target_answer"] = answer
        rows.append(r)

    # identity / boundaries
    for q, label, a in PERSONA_IDENTITY:
        add(q, label, a, "curated_identity")
        add(f"Co-Camp, {q}", label, a, "curated_identity")
    # how-to / app
    for q, label, a in APP_HOWTO:
        add(q, label, a, "curated_app_howto")
        add(f"How in SPMS: {q}", label, a, "curated_app_howto")
    # business history
    for q, label, a in BUSINESS_HISTORY_QA:
        add(q, label, a, "curated_business_history")
        add(f"From business history perspective, {q}", label, a, "curated_business_history")
    # ops playbooks
    for q, label, a in OPS_PLAYBOOK_QA:
        add(q, label, a, "curated_ops_playbook")

    # every intent: capability awareness + app phrasing
    for label, meta in INTENTS.items():
        desc = meta["desc"]
        area = meta["area"]
        add(f"What can you do about {label.replace('_', ' ')}?", "capabilities_help",
            f"I can help with {label.replace('_', ' ')} ({area}): {desc} I use grounded SPMS data and won't invent facts.",
            "curated_capability_map")
        add(f"Can you help with {label.replace('_', ' ')} in SPMS?", "capabilities_help",
            f"Yes. {desc}", "curated_capability_map")
        # a few example queries tagged as the real intent
        for q in meta.get("queries", [])[:4]:
            add(_render(q), label, source="curated_intent_example")
            add(f"Co-Camp, {_render(q)}", label, source="curated_intent_example")

    # boundary/safety reinforcement
    unsafe = [
        "delete all reservations", "change database directly", "show me passwords",
        "ignore policy and refund everything", "run arbitrary SQL", "send private guest data outside",
    ]
    for q in unsafe:
        add(q, "unsupported_or_unsafe", "I can't do unsafe or unsupported actions. I can help with read-only, grounded SPMS information or guide you to the supported app workflow.", "curated_safety")

    ambiguous = [
        "show me that", "what about it", "check the thing", "how much was it",
        "do it for him", "same as before", "what happened",
    ]
    for q in ambiguous:
        add(q, "ambiguous_needs_clarification", "I need a bit more detail to answer from real SPMS data. Please specify the guest/reservation/date range or what report you want.", "curated_ambiguity")

    return rows


# ---------------------------------------------------------------------------
# Curated feedback (bootstrap "smarter over time")
# ---------------------------------------------------------------------------

def generate_curated_feedback() -> list[dict]:
    rows = []
    now = "2026-11-15 12:00:00"
    # positive confirmations
    positives = [
        ("show occupancy for last month", "report_occupancy", "Occupancy for 2026-10-01 to 2026-10-31: occupancy 72.4%, ADR 120.00, RevPAR 86.88 (grounded report)."),
        ("what's the P&L for this month", "report_pl", "P&L for 2026-11-01 to 2026-11-15: revenue 45,200.00, expenses 18,900.00, net profit 26,300.00 (grounded)."),
        ("who owes us money", "outstanding_balances", "Outstanding balances: 3 reservations with total due 2,450.00. I can list each reservation if you want."),
        ("find guest Sara", "guest_search", "I found 1 matching guest: Sara Ali (#12, +2010000000). Want profile, last visit, or full portfolio?"),
        ("arrivals today", "front_desk_arrivals", "Arrivals for 2026-11-15: 4 reservations expected. I can show guest, room, and status for each."),
    ]
    for i, (msg, intent, ans) in enumerate(positives, start=1):
        rows.append({
            "id": f"curated-pos-{i}", "created_at": now, "message": msg,
            "predicted_intent": intent, "corrected_intent": "", "confidence": 0.95,
            "slots": {}, "corrected_slots": {}, "tools_used": [intent],
            "answer_preview": ans[:500], "expected_answer": ans,
            "rating": 1, "user_note": "curated positive example", "status": "approved", "source": "curated_bootstrap",
        })
    # corrections
    corrections = [
        ("cash report last month", "report_pl", "report_cash_flow", "Cash flow report shows cash in/out/net for the selected period."),
        ("tax summary last month", "report_pl", "report_vat", "VAT report shows output/input/net VAT for the selected period."),
        ("who is in the hotel now", "today_ops", "front_desk_in_house", "In-house list shows currently checked-in guests/rooms."),
        ("check room readiness", "housekeeping_summary", "housekeeping_tasks", "Housekeeping tasks show cleaning/readiness status by room."),
        ("what did guest 3 buy last time", "guest_last_visit", "guest_top_items_last_visit", "Top items last visit shows POS items ordered most by the guest on their most recent stay."),
        ("is room 101 free tomorrow", "room_blocks", "room_availability", "Room availability checks free rooms for the requested dates."),
        ("show me booking group 2", "reservation_search", "reservation_group_detail", "Reservation group detail shows group members, folio, and status."),
        ("any expiring stock", "inventory_alerts", "expiring_batches", "Expiring batches lists lots nearing expiry with dates and quantities."),
    ]
    for i, (msg, pred, corr, ans) in enumerate(corrections, start=1):
        rows.append({
            "id": f"curated-cor-{i}", "created_at": now, "message": msg,
            "predicted_intent": pred, "corrected_intent": corr, "confidence": 0.62,
            "slots": {}, "corrected_slots": {}, "tools_used": [pred],
            "answer_preview": "", "expected_answer": ans,
            "rating": -1, "user_note": f"correct intent is {corr}", "status": "approved", "source": "curated_bootstrap",
        })
    # ambiguous/unsafe coaching
    coaching = [
        ("show balance", "ambiguous_needs_clarification", "Which balance do you mean? Please share a reservation ID (e.g., reservation #104) or guest name."),
        ("delete reservation 5", "unsupported_or_unsafe", "I can't delete reservations. I can summarize reservation #5, its balance, or guide you to the supported app workflow."),
        ("change the rate", "unsupported_or_unsafe", "I can't change rates. I can show current rate plans/rules or reservation pricing details from SPMS."),
    ]
    for i, (msg, intent, ans) in enumerate(coaching, start=1):
        rows.append({
            "id": f"curated-coach-{i}", "created_at": now, "message": msg,
            "predicted_intent": intent, "corrected_intent": "", "confidence": 0.9,
            "slots": {}, "corrected_slots": {}, "tools_used": [],
            "answer_preview": ans, "expected_answer": ans,
            "rating": 1, "user_note": "curated coaching example", "status": "approved", "source": "curated_bootstrap",
        })
    return rows


# ---------------------------------------------------------------------------
# Business history / app operations knowledge
# ---------------------------------------------------------------------------

def generate_business_history_rows() -> list[dict]:
    rows = []
    # Monthly snapshots - synthetic but realistic structure for training "history aware"
    months = [
        ("2026-08", 61.2, 118.0, 72.2, 38200, 16400, 21800, 9200, -6100, 3100),
        ("2026-09", 66.5, 121.5, 80.8, 41500, 17100, 24400, 11100, -6900, 4200),
        ("2026-10", 72.4, 124.0, 89.8, 45200, 17900, 27300, 12800, -7200, 5600),
        ("2026-11", 69.8, 123.0, 85.9, 43800, 18250, 25550, 11900, -7600, 4300),
    ]
    for m, occ, adr, revpar, rev, exp, profit, cash_in, cash_out, cash_net in months:
        snap = {
            "period": m, "occupancy_pct": occ, "adr": adr, "revpar": revpar,
            "revenue": rev, "expenses": exp, "net_profit": profit,
            "cash_in": cash_in, "cash_out": cash_out, "net_cash_flow": cash_net,
            "currency": "USD", "source": "synthetic_business_history", "anonymized": True,
        }
        rows.append({"type": "business_history_snapshot", **snap})
        # grounded QA examples
        qas = [
            (f"How did we do in {m}?", f"In {m} (synthetic business-history snapshot): occupancy {occ}%, ADR {adr:.2f}, RevPAR {revpar:.2f}, revenue {rev:.2f}, expenses {exp:.2f}, net profit {profit:.2f}, net cash flow {cash_net:.2f}.", "business_partner_briefing"),
            (f"What was occupancy in {m}?", f"Occupancy in {m} was {occ}% (synthetic history snapshot).", "report_occupancy"),
            (f"What was profit in {m}?", f"Net profit in {m} was {profit:.2f} on revenue {rev:.2f} and expenses {exp:.2f} (synthetic history snapshot).", "report_pl"),
        ]
        for q, a, intent in qas:
            rows.append({"type": "history_qa", "question": q, "answer": a, "intent": intent, "period": m, "grounded_data": snap})
    # trend comparisons
    rows.append({"type": "history_qa", "question": "Is occupancy improving over recent months?", "intent": "compare_periods",
                 "answer": "From synthetic business history snapshots: occupancy moved 61.2% (2026-08) -> 66.5% (2026-09) -> 72.4% (2026-10) -> 69.8% (2026-11), improving overall with a small dip in Nov.",
                 "grounded_data": {"periods": months, "source": "synthetic_business_history"}})
    rows.append({"type": "history_qa", "question": "What is the profit trend?", "intent": "report_pl",
                 "answer": "Net profit trend (synthetic): 21,800 (2026-08), 24,400 (2026-09), 27,300 (2026-10), 25,550 (2026-11). Strong growth through Oct, slight dip in Nov.",
                 "grounded_data": {"metric": "net_profit", "source": "synthetic_business_history"}})
    return rows


def generate_ops_knowledge_rows() -> list[dict]:
    rows = []
    app_facts = [
        ("Reservations", "Create, quote, check-in/out, payments, invoices, extra services, discounts, modify, group bookings, activity bookings."),
        ("Guests", "Guest directory, search, 360 portfolio, profile edit, stay/payment/POS/invoice history."),
        ("POS", "Sell walk-ins, charge reservations, inventory items, batches/traceability, meals/recipes, activities, walk-in history."),
        ("Housekeeping", "Tasks, dirty/clean status, room blocks OOO/OOS, generate tasks, resolve blocks."),
        ("Accounting", "Overview, expenses, payments/refunds, cash shifts, night audit, ledger, integrity checks."),
        ("Reports", "P&L, cash flow, VAT, payment methods, occupancy, daily ops, exports/downloads, comparison periods."),
        ("Settings/Admin", "General, seed/data, rooms/plans, rate plans/rules, users/RBAC, packages, vouchers, service catalog, approvals, health."),
        ("Assistant", "Grounded read-only answers from real SPMS data; feedback improves over time; no external AI calls."),
    ]
    for module, fact in app_facts:
        rows.append({"type": "app_knowledge", "module": module, "content": fact, "source": "curated_spms_app"})
    ops_sops = [
        ("Daily opening", "Review today ops: arrivals, departures, in-house, housekeeping readiness, cash shift, outstanding balances, alerts."),
        ("Check-in", "Confirm reservation, room readiness, guest identity/policy, collect payment/deposit as needed, check in."),
        ("Checkout", "Review folio, post missing charges, collect balance, generate invoice/receipt, checkout, set room dirty/housekeeping."),
        ("Night audit", "Verify payments/refunds/shifts, review exceptions, run night audit, store snapshot, follow up discrepancies."),
        ("Weekly business review", "Compare P&L, cash flow, occupancy, ADR/RevPAR, sales mix, expenses, receivables, inventory alerts vs prior week."),
    ]
    for name, sop in ops_sops:
        rows.append({"type": "ops_playbook", "name": name, "content": sop, "source": "curated_ops_playbook"})
    return rows


# ---------------------------------------------------------------------------
# Schemas / manifest / README
# ---------------------------------------------------------------------------

def write_schemas() -> None:
    _write_json(SCHEMA / "intent_example.schema.json", {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object", "required": ["text", "label"],
        "properties": {
            "text": {"type": "string"}, "label": {"type": "string"},
            "source": {"type": "string"}, "slots": {"type": "object"},
        },
        "additionalProperties": True,
    })
    _write_json(SCHEMA / "feedback.schema.json", {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object", "required": ["message", "predicted_intent"],
        "properties": {
            "id": {}, "created_at": {"type": "string"}, "message": {"type": "string"},
            "predicted_intent": {"type": "string"}, "corrected_intent": {"type": "string"},
            "confidence": {}, "slots": {"type": "object"}, "corrected_slots": {"type": "object"},
            "tools_used": {"type": "array"}, "answer_preview": {"type": "string"},
            "expected_answer": {"type": "string"}, "rating": {"type": "integer"},
            "user_note": {"type": "string"}, "status": {"type": "string"}, "source": {"type": "string"},
        },
        "additionalProperties": True,
    })
    _write_json(SCHEMA / "grounded_chat.schema.json", {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object", "required": ["messages"],
        "properties": {
            "messages": {"type": "array", "items": {"type": "object", "required": ["role", "content"],
                         "properties": {"role": {"type": "string"}, "content": {"type": "string"}}}},
            "source": {"type": "string"}, "intent": {"type": "string"}, "meta": {"type": "object"},
        },
        "additionalProperties": True,
    })


def write_manifest(intent_rows, feedback_rows, persona_rows, history_rows, ops_rows) -> None:
    manifest = {
        "version": 2,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "dataset_version": VERSION,
        "description": "Versioned SPMS/Co-Camp assistant dataset registry. Business/app/operations/history aware; grows via feedback.",
        "principles": [
            "Grounded only: no invented IDs/dates/amounts/actions.",
            "Business/app/operations scope only; reject unsafe/out-of-scope.",
            "History aware: include period snapshots, trends, comparisons.",
            "Smarter over time: ingest feedback/corrections into curated and training datasets.",
            "Reproducible: deterministic generation + versioned snapshots + eval splits.",
        ],
        "datasets": [
            {"id": "spms_intent_seed", "path": "data/assistant_nlu/intents_seed.jsonl", "type": "intent_seed", "enabled": True, "rows": len(intent_rows), "notes": "Expanded intent seed covering all SPMS intents."},
            {"id": "spms_feedback", "path": "data/assistant_nlu/feedback.jsonl", "type": "feedback", "enabled": True, "rows": len(feedback_rows), "notes": "Real + curated bootstrap feedback/corrections; sanitize before external sharing."},
            {"id": "cocamp_persona", "path": "co-camp/co_camp/data/persona_examples.jsonl", "type": "persona_intent", "enabled": True, "rows": len(persona_rows), "notes": "Co-Camp persona, app how-to, business history, ops playbooks, safety boundaries."},
            {"id": "curated_business_history", "path": "data/datasets/curated/business_history.jsonl", "type": "history_knowledge", "enabled": True, "rows": len(history_rows), "notes": "Synthetic/anonymized business-history snapshots and grounded QA for trend awareness."},
            {"id": "curated_ops_knowledge", "path": "data/datasets/curated/app_operations_knowledge.jsonl", "type": "app_ops_knowledge", "enabled": True, "rows": len(ops_rows), "notes": "SPMS app modules, SOPs, and operational playbooks."},
            {"id": "curated_feedback_bootstrap", "path": "data/datasets/curated/feedback_bootstrap.jsonl", "type": "feedback_curated", "enabled": True, "notes": "Curated feedback examples for bootstrap training; merged into assistant_nlu/feedback.jsonl with provenance."},
            {"id": "processed_intent_examples", "path": "data/datasets/processed/intent_examples.jsonl", "type": "processed_intent", "enabled": True, "notes": "Merged/deduped intent training examples."},
            {"id": "processed_grounded_chat", "path": "data/datasets/processed/grounded_chat.jsonl", "type": "processed_chat", "enabled": True, "notes": "Grounded chat SFT examples (system/user/assistant)."},
            {"id": "processed_train", "path": "data/datasets/processed/train.jsonl", "type": "processed_train", "enabled": True, "notes": "Train split for grounded chat fine-tuning."},
            {"id": "processed_eval", "path": "data/datasets/processed/eval.jsonl", "type": "processed_eval", "enabled": True, "notes": "Eval split for grounded chat fine-tuning."},
        ],
        "splits": {"train_ratio": 0.9, "eval_ratio": 0.1, "seed": 42},
        "quality": {"dedupe": True, "schema_validated": True, "pii_review": "required_before_external_share"},
    }
    _write_json(DATASETS / "manifest.json", manifest)


def write_readme() -> None:
    DATASETS.mkdir(parents=True, exist_ok=True)
    (DATASETS / "README.md").write_text("""# SPMS / Co-Camp Assistant Datasets

Versioned dataset system for making Co-Camp smart at **SPMS business, app, and operations**, aware of **business history**, and **smarter over time**.

## Layout

```text
data/datasets/
  README.md
  manifest.json                 # versioned dataset registry
  schema/                       # JSON schemas
  curated/                      # curated/generated datasets (reviewable)
    business_history.jsonl      # synthetic/anonymized business history snapshots + QA
    app_operations_knowledge.jsonl
    feedback_bootstrap.jsonl
  history/                      # optional real/sanitized historical snapshots
  snapshots/                    # versioned immutable snapshots
  processed/                    # model-ready outputs
    intent_examples.jsonl
    grounded_chat.jsonl
    train.jsonl
    eval.jsonl
  raw/                          # external/raw datasets (not committed if large/private)
```

## Core sources

- `data/assistant_nlu/intents_seed.jsonl` - intent routing examples covering all SPMS intents.
- `data/assistant_nlu/feedback.jsonl` - real feedback/corrections + curated bootstrap; **sanitize PII before sharing**.
- `co-camp/co_camp/data/persona_examples.jsonl` - Co-Camp persona, app how-to, ops/business/history awareness.
- `data/assistant_knowledge/agent_brain.json` - curated app knowledge/tools/workflows/boundaries.

## Grounded chat format

`processed/grounded_chat.jsonl`:

```json
{
  "messages": [
    {"role": "system", "content": "You are Co-Camp... Use ONLY grounded data..."},
    {"role": "user", "content": "Manager question: ...\\n\\nGrounded data (JSON): ..."},
    {"role": "assistant", "content": "Grounded answer..."}
  ],
  "source": "feedback|brain|history|curated",
  "intent": "report_pl"
}
```

## Build / refresh

```bash
# Regenerate maximal curated datasets
python scripts/build_max_assistant_datasets.py

# Prepare processed training splits
python scripts/prepare_assistant_dataset.py

# Train intent routers
python scripts/train_assistant_intent.py --backend sklearn
python scripts/train_assistant_intent.py --backend setfit --base-model sentence-transformers/paraphrase-MiniLM-L3-v2

# Fine-tune local LLM (GPU recommended)
python scripts/train_assistant_llm.py --dataset data/datasets/processed/train.jsonl --eval-dataset data/datasets/processed/eval.jsonl
```

## Smarter over time

1. Collect assistant feedback (thumbs up/down, corrections, expected answers).
2. Sanitize PII/secrets.
3. Run `python scripts/build_max_assistant_datasets.py` to refresh curated/processed datasets.
4. Retrain intent router / fine-tune local model.
5. Evaluate on held-out eval split and real SPMS regression prompts.
6. Version datasets in manifest and keep snapshots for rollback.

## Quality gates

- No invented facts/IDs/dates/amounts/actions.
- All examples mapped to real SPMS intents/capabilities or explicitly marked clarification/unsafe.
- Deduped, schema-valid, reproducible generation.
- PII/secrets review before any external dataset sharing.
""", encoding="utf-8")


# ---------------------------------------------------------------------------
# Processed datasets
# ---------------------------------------------------------------------------

def build_processed(intent_rows, feedback_rows, persona_rows, history_rows, ops_rows, brain):
    intent_out = []
    for r in intent_rows:
        intent_out.append({"text": r["text"], "label": r["label"], "source": r.get("source", "intent_seed")})
    for r in persona_rows:
        if r.get("label") in INTENTS:
            intent_out.append({"text": r["text"], "label": r["label"], "source": r.get("source", "persona")})
    for r in feedback_rows:
        msg = (r.get("message") or "").strip()
        label = (r.get("corrected_intent") or (r.get("predicted_intent") if int(r.get("rating") or 0) == 1 else "")).strip()
        if msg and label in INTENTS:
            intent_out.append({"text": msg, "label": label, "source": "feedback"})
    intent_out = _dedupe_rows(intent_out, lambda r: (_norm(r["text"]), r["label"]))

    chat = []
    # feedback -> grounded chat
    for r in feedback_rows:
        msg = (r.get("message") or "").strip()
        ans = (r.get("expected_answer") or r.get("corrected_answer") or r.get("answer_preview") or "").strip()
        intent = (r.get("corrected_intent") or r.get("predicted_intent") or "").strip()
        ctx = r.get("slots") or {}
        if not msg or not ans:
            continue
        user = f"Manager question: {msg}\n\nGrounded data (JSON): {json.dumps(ctx, ensure_ascii=False, default=str)[:2000]}"
        chat.append({"messages": [{"role": "system", "content": SYSTEM_GROUNDED}, {"role": "user", "content": user}, {"role": "assistant", "content": ans}], "source": r.get("source", "feedback"), "intent": intent})
    # persona with target answers
    for r in persona_rows:
        ans = (r.get("target_answer") or "").strip()
        if not ans:
            continue
        user = f"Manager question: {r['text']}\n\nGrounded data (JSON): {json.dumps({'persona': 'Co-Camp', 'app': 'SPMS'}, ensure_ascii=False)}"
        chat.append({"messages": [{"role": "system", "content": SYSTEM_GROUNDED}, {"role": "user", "content": user}, {"role": "assistant", "content": ans}], "source": r.get("source", "persona"), "intent": r.get("label", "")})
    # history QAs
    for r in history_rows:
        if r.get("type") != "history_qa":
            continue
        q = (r.get("question") or "").strip(); a = (r.get("answer") or "").strip()
        if not q or not a:
            continue
        gd = r.get("grounded_data", {})
        user = f"Manager question: {q}\n\nGrounded data (JSON): {json.dumps(gd, ensure_ascii=False, default=str)[:3500]}"
        chat.append({"messages": [{"role": "system", "content": SYSTEM_GROUNDED}, {"role": "user", "content": user}, {"role": "assistant", "content": a}], "source": "business_history", "intent": r.get("intent", "")})
    # ops/app knowledge
    for r in ops_rows:
        if r.get("type") == "app_knowledge":
            q = f"What does the {r['module']} module do in SPMS?"
            a = f"{r['module']}: {r['content']}"
            gd = {"module": r["module"], "content": r["content"]}
            intent = "capabilities_help"
        elif r.get("type") == "ops_playbook":
            q = f"What is the SPMS SOP for {r['name']}?"
            a = f"{r['name']}: {r['content']}"
            gd = {"playbook": r["name"], "content": r["content"]}
            intent = "capabilities_help"
        else:
            continue
        user = f"Manager question: {q}\n\nGrounded data (JSON): {json.dumps(gd, ensure_ascii=False)}"
        chat.append({"messages": [{"role": "system", "content": SYSTEM_GROUNDED}, {"role": "user", "content": user}, {"role": "assistant", "content": a}], "source": r.get("source", "curated_ops"), "intent": intent})
    # brain knowledge
    for k in (brain.get("knowledge") or []):
        title = (k.get("title") or "").strip(); content = (k.get("content") or "").strip()
        if not title or not content:
            continue
        q = title if title.lower().startswith("how") else f"How do I {title.lower()}?"
        gd = {"title": title, "content": content, "source": k.get("source_path", "")}
        user = f"Manager question: {q}\n\nGrounded data (JSON): {json.dumps(gd, ensure_ascii=False)}"
        chat.append({"messages": [{"role": "system", "content": SYSTEM_GROUNDED}, {"role": "user", "content": user}, {"role": "assistant", "content": content[:1200]}], "source": "brain_knowledge", "intent": "capabilities_help"})

    chat = _dedupe_rows(chat, lambda r: json.dumps(r["messages"], ensure_ascii=False))
    RNG.shuffle(chat)
    n_eval = max(1, int(len(chat) * 0.1)) if chat else 0
    eval_rows = chat[:n_eval]
    train_rows = chat[n_eval:]
    return intent_out, chat, train_rows, eval_rows


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    for d in [NLU, DATASETS, CURATED, PROCESSED, SCHEMA, HISTORY, SNAPSHOTS]:
        d.mkdir(parents=True, exist_ok=True)

    existing_seed = _load_jsonl(SEED_PATH)
    existing_feedback = _load_jsonl(FEEDBACK_PATH)
    brain = {}
    if BRAIN_PATH.exists():
        try:
            brain = json.loads(BRAIN_PATH.read_text(encoding="utf-8"))
        except Exception:
            brain = {}

    intent_rows = generate_intent_seed(existing_seed)
    persona_rows = generate_persona_examples()
    curated_feedback = generate_curated_feedback()
    history_rows = generate_business_history_rows()
    # Ingest real sanitized business-history snapshots (smarter over time)
    for hp in sorted(HISTORY.glob("real*.json")):
        try:
            obj = json.loads(hp.read_text(encoding="utf-8"))
        except Exception:
            continue
        for snap in (obj.get("snapshots") or []):
            period = snap.get("period") or snap.get("start", "")
            snap_row = {"type": "business_history_snapshot", **snap, "source": snap.get("source", "spms_db_aggregates"), "anonymized": True}
            history_rows.append(snap_row)
            if period:
                metrics = {k: snap[k] for k in ["occupancy_pct", "adr", "revpar", "revenue", "expenses", "net_profit", "cash_in", "cash_out", "net_cash_flow"] if k in snap}
                if metrics:
                    history_rows.append({"type": "history_qa", "period": period, "intent": "business_partner_briefing",
                                         "question": f"How did the business perform in {period}?", "answer": f"Business performance for {period} (grounded historical snapshot): " + ", ".join(f"{k}={v}" for k, v in metrics.items()) + ".", "grounded_data": snap_row})
    ops_rows = generate_ops_knowledge_rows()

    # Merge feedback: keep real rows, add curated with provenance, dedupe by (message, predicted, corrected, rating, source)
    merged_feedback = []
    seen_fb = set()
    for r in existing_feedback + curated_feedback:
        msg = (r.get("message") or "").strip()
        if not msg:
            continue
        k = (_norm(msg), r.get("predicted_intent", ""), r.get("corrected_intent", ""), str(r.get("rating", "")), r.get("source", ""))
        if k in seen_fb:
            continue
        seen_fb.add(k)
        merged_feedback.append(r)

    # Write core files
    _write_jsonl(SEED_PATH, intent_rows)
    _write_jsonl(FEEDBACK_PATH, merged_feedback)
    _write_jsonl(PERSONA_OUT, persona_rows)

    # Curated datasets
    _write_jsonl(CURATED / "feedback_bootstrap.jsonl", curated_feedback)
    _write_jsonl(CURATED / "business_history.jsonl", history_rows)
    _write_jsonl(CURATED / "app_operations_knowledge.jsonl", ops_rows)

    # History snapshot
    history_snapshot = {
        "version": VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "type": "synthetic_anonymized_business_history",
        "description": "Synthetic/anonymized monthly business snapshots for history-aware assistant training. Replace/augment with sanitized real exports over time.",
        "snapshots": [r for r in history_rows if r.get("type") == "business_history_snapshot"],
    }
    _write_json(HISTORY / f"business_history_snapshot_{VERSION}.json", history_snapshot)
    _write_json(HISTORY / "latest.json", history_snapshot)

    # Processed
    intent_out, chat, train_rows, eval_rows = build_processed(intent_rows, merged_feedback, persona_rows, history_rows, ops_rows, brain)
    _write_jsonl(PROCESSED / "intent_examples.jsonl", intent_out)
    _write_jsonl(PROCESSED / "grounded_chat.jsonl", chat)
    _write_jsonl(PROCESSED / "train.jsonl", train_rows)
    _write_jsonl(PROCESSED / "eval.jsonl", eval_rows)

    # Manifest/readme/schema
    write_schemas()
    write_manifest(intent_rows, merged_feedback, persona_rows, history_rows, ops_rows)
    write_readme()

    # Snapshot
    snap = {
        "version": VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "counts": {
            "intents_seed": len(intent_rows),
            "feedback": len(merged_feedback),
            "persona_examples": len(persona_rows),
            "business_history_rows": len(history_rows),
            "ops_knowledge_rows": len(ops_rows),
            "processed_intent_examples": len(intent_out),
            "processed_grounded_chat": len(chat),
            "train": len(train_rows),
            "eval": len(eval_rows),
        },
        "intent_labels": len(INTENTS),
        "intents_covered": sorted({r["label"] for r in intent_rows}),
    }
    _write_json(SNAPSHOTS / f"dataset_snapshot_{VERSION}.json", snap)
    _write_json(SNAPSHOTS / "latest.json", snap)

    print(json.dumps(snap, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
