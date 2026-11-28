"""Ranked business map for grounded assistant routing/answers (V2).

Deterministic index of key business entities, routes, and actions. No external calls.
"""

from __future__ import annotations

from typing import Any

from .common import _norm_text

_ENTITIES = [
    {"id": "reservations", "label": "Reservations", "route": "/reservations", "keywords": ["reservation", "booking", "check in", "check out", "cancel", "no show", "folio", "guest stay"], "actions": ["propose_create_reservation", "propose_record_payment"]},
    {"id": "guests", "label": "Guests", "route": "/guests", "keywords": ["guest", "profile", "contact", "history", "vip"], "actions": []},
    {"id": "housekeeping", "label": "Housekeeping", "route": "/housekeeping", "keywords": ["housekeeping", "clean", "dirty", "ooo", "oos", "maintenance", "room status"], "actions": []},
    {"id": "pos", "label": "POS / Inventory", "route": "/pos", "keywords": ["pos", "sale", "walk in", "item", "inventory", "stock", "meal", "recipe", "activity", "trip"], "actions": ["propose_add_pos_item", "propose_complete_walkin_sale", "propose_book_activity"]},
    {"id": "accounting", "label": "Accounting", "route": "/accounting", "keywords": ["accounting", "expense", "ledger", "payment", "refund", "void"], "actions": ["propose_record_payment"]},
    {"id": "reports", "label": "Reports & Analytics", "route": "/reports", "keywords": ["report", "analytics", "p&l", "profit", "cash flow", "vat", "occupancy", "daily ops"], "actions": []},
    {"id": "settings", "label": "Settings / Branding", "route": "/settings", "keywords": ["setting", "branding", "backup", "update", "rate plan", "room", "users", "permissions"], "actions": []},
    {"id": "assistant", "label": "Manager Assistant", "route": "/assistant", "keywords": ["assistant", "help", "what can you do", "policy", "model", "training"], "actions": []},
]


def rank(message: str = "", intent: str = "", limit: int = 5) -> list[dict[str, Any]]:
    t = _norm_text(message)
    it = _norm_text(intent)
    scored = []
    for e in _ENTITIES:
        score = 0.0
        for kw in e.get("keywords", []):
            k = _norm_text(kw)
            if k and k in t:
                score += 2.0 if " " in k else 1.0
        if it and any(it in _norm_text(a) for a in e.get("actions", [])):
            score += 1.5
        if it and it.replace("_", " ") in " ".join(e.get("keywords", [])):
            score += 1.0
        if score > 0:
            scored.append({**e, "score": score})
    scored.sort(key=lambda x: (-x["score"], x["id"]))
    return scored[: max(1, min(int(limit or 5), 20))]


def get_map() -> list[dict[str, Any]]:
    return [dict(e) for e in _ENTITIES]
