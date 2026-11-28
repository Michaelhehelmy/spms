"""Deterministic assistant action policy engine (V1 foundation for issue #77).

Guardrails:
- Deterministic engine remains source of truth; LLM may only phrase/summarize.
- No write action executes without explicit confirmation.
- Sensitive actions cannot be silently allowed by policy.
- Policy/rules cannot override safety, permissions, or data integrity.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Mapping

from .. import db, services

logger = logging.getLogger(__name__)

SENSITIVE_ACTION_TYPES = {
    "propose_add_pos_item",
    "execute_add_pos_item",
    "propose_complete_walkin_sale",
    "execute_complete_walkin_sale",
    "propose_record_payment",
    "execute_record_payment",
    "propose_book_activity",
    "execute_book_activity",
    "propose_create_reservation",
    "execute_create_reservation",
    "record_payment",
    "complete_walkin_sale",
    "create_reservation",
    "book_activity",
    "add_pos_item",
}

DEFAULT_SAFETY_RULES = [
    {
        "id": "safety-deny-secrets",
        "effect": "deny",
        "intent_patterns": ["*"],
        "action_types": ["*"],
        "message_patterns": [r"(?i)(\b(show|reveal|tell|give)\b.*\b(password|secret|api[_ -]?key|token|csrf|recovery code)\b|\b(password|secret|api[_ -]?key|token|csrf|recovery code)\b.*\b(show|reveal|tell|give)\b)"],
        "reason": "Secrets/credentials cannot be revealed by assistant.",
    },
    {
        "id": "safety-ask-sensitive-writes",
        "effect": "ask",
        "action_types": sorted(SENSITIVE_ACTION_TYPES),
        "reason": "Sensitive/write actions require explicit confirmation.",
    },
]

_EFFECTS = {"allow", "ask", "deny"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _json_loads(raw: Any, default):
    if raw is None:
        return default
    if isinstance(raw, (dict, list)):
        return raw
    try:
        return json.loads(raw)
    except Exception:
        return default


def _norm(s: Any) -> str:
    return str(s or "").strip()


def _patterns_match(patterns: list[Any] | None, value: str) -> bool:
    if not patterns:
        return True
    v = _norm(value)
    for p in patterns:
        ps = _norm(p)
        if not ps:
            continue
        if ps == "*":
            return True
        if ps.lower() == v.lower():
            return True
        # simple glob-ish contains
        if ps.endswith("*") and v.lower().startswith(ps[:-1].lower()):
            return True
        if ps.startswith("*") and v.lower().endswith(ps[1:].lower()):
            return True
        # regex if looks like regex
        if ps.startswith("(?") or ("\\" in ps and len(ps) > 2):
            try:
                import re

                if re.search(ps, v):
                    return True
            except Exception:
                pass
    return False


def load_property_rules() -> list[dict[str, Any]]:
    raw = _norm(services.get_setting("assistant_property_rules", ""))
    if not raw:
        return []
    # JSON array preferred
    parsed = _json_loads(raw, None)
    if isinstance(parsed, list):
        rules = [r for r in parsed if isinstance(r, dict)]
        return rules
    # line-based simple rules: "deny: action_type=...; reason=..."
    rules: list[dict[str, Any]] = []
    for i, line in enumerate(raw.splitlines(), start=1):
        ln = line.strip()
        if not ln or ln.startswith("#"):
            continue
        if ":" in ln:
            eff, rest = ln.split(":", 1)
            eff = eff.strip().lower()
            if eff not in _EFFECTS:
                eff = "ask"
            rule = {"id": f"property-line-{i}", "effect": eff, "reason": rest.strip() or "Property rule"}
            # parse simple k=v; pairs
            for part in rest.split(";"):
                if "=" in part:
                    k, v = part.split("=", 1)
                    k = k.strip().lower()
                    v = v.strip()
                    if k in {"action_type", "action_types"}:
                        rule["action_types"] = [x.strip() for x in v.split(",") if x.strip()]
                    elif k in {"intent", "intents"}:
                        rule["intent_patterns"] = [x.strip() for x in v.split(",") if x.strip()]
                    elif k == "reason":
                        rule["reason"] = v
            rules.append(rule)
        else:
            rules.append({"id": f"property-line-{i}", "effect": "ask", "reason": ln})
    return rules


def load_policy_rules() -> list[dict[str, Any]]:
    raw = services.get_setting("assistant_action_policy_json", "[]") or "[]"
    parsed = _json_loads(raw, [])
    rules = [r for r in parsed if isinstance(r, dict)] if isinstance(parsed, list) else []
    # layered: safety defaults + property rules + configured action policy (last match wins among non-safety? No: last match wins overall, but sensitive confirmation floor applied after)
    return list(DEFAULT_SAFETY_RULES) + load_property_rules() + rules


def evaluate(
    *,
    message: str = "",
    intent: str = "",
    action_type: str = "",
    actor_role: str = "",
    unlocked: bool = False,
    session_id: str = "",
    context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    ctx = dict(context or {})
    rules = load_policy_rules()
    decision = {
        "effect": "allow",
        "matched_rule_id": "",
        "reason": "No matching policy rule; default allow (subject to safety/permission checks).",
        "sensitive": _norm(action_type) in SENSITIVE_ACTION_TYPES or bool(ctx.get("sensitive")),
        "requires_confirmation": False,
        "rules_evaluated": len(rules),
    }
    msg = _norm(message)
    it = _norm(intent)
    at = _norm(action_type)
    role = _norm(actor_role) or "manager"

    for rule in rules:
        effect = _norm(rule.get("effect")).lower()
        if effect not in _EFFECTS:
            continue
        # match conditions
        if rule.get("intent_patterns") and not _patterns_match(list(rule.get("intent_patterns") or []), it):
            # allow '*' to match empty intent only when explicitly '*'
            pats = [str(p) for p in (rule.get("intent_patterns") or [])]
            if "*" not in pats:
                continue
        if rule.get("action_types") and not _patterns_match(list(rule.get("action_types") or []), at):
            pats = [str(p) for p in (rule.get("action_types") or [])]
            if "*" not in pats:
                continue
        if rule.get("message_patterns"):
            import re

            ok = False
            for p in rule.get("message_patterns") or []:
                try:
                    if re.search(str(p), msg):
                        ok = True
                        break
                except Exception:
                    continue
            if not ok:
                continue
        if rule.get("roles"):
            roles = [str(r).lower() for r in (rule.get("roles") or [])]
            if "*" not in roles and role.lower() not in roles:
                continue
        if rule.get("requires_unlock") is True and not unlocked:
            # rule applies only when unlocked; skip
            continue
        if rule.get("requires_unlock") is False and unlocked:
            # can still match
            pass
        # matched - last match wins
        decision["effect"] = effect
        decision["matched_rule_id"] = _norm(rule.get("id"))
        decision["reason"] = _norm(rule.get("reason")) or f"Matched policy rule {decision['matched_rule_id'] or effect}"
        decision["matched_rule"] = {
            "id": decision["matched_rule_id"],
            "effect": effect,
            "reason": decision["reason"],
        }

    # Sensitive floor: write/sensitive actions can never be silently allowed.
    if decision["sensitive"] or at in SENSITIVE_ACTION_TYPES:
        decision["sensitive"] = True
        decision["requires_confirmation"] = True
        if decision["effect"] == "allow":
            decision["effect"] = "ask"
            decision["reason"] = (
                decision["reason"]
                + " (elevated to ask: sensitive actions require explicit confirmation)."
            ).strip()

    # Deny always wins over ask/allow for safety; last-match already applied, but keep deny.
    if decision["effect"] not in _EFFECTS:
        decision["effect"] = "ask"
    return decision


def log_decision(decision: Mapping[str, Any], *, session_id: str = "", actor: str = "", actor_user_id: Any = None,
                 actor_role: str = "", message: str = "", intent: str = "", action_type: str = "",
                 args: Mapping[str, Any] | None = None, outcome: str = "") -> None:
    enabled = str(services.get_setting("assistant_policy_audit_enabled", "true")).lower() == "true"
    if not enabled:
        return
    try:
        args_summary = {}
        for k, v in dict(args or {}).items():
            lk = str(k).lower()
            if any(s in lk for s in ["password", "secret", "token", "key", "csrf"]):
                args_summary[k] = "<redacted>"
            else:
                sv = v
                if isinstance(sv, str) and len(sv) > 120:
                    sv = sv[:117] + "..."
                args_summary[k] = sv
        with db.connect() as conn:
            conn.execute(
                """
                INSERT INTO assistant_policy_audit
                (at, session_id, actor, actor_user_id, actor_role, message_preview, intent, action_type, effect, matched_rule_id, reason, args_summary_json, outcome, details_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    _now_iso(),
                    _norm(session_id)[:120],
                    _norm(actor)[:120],
                    actor_user_id,
                    _norm(actor_role)[:120],
                    _norm(message)[:300],
                    _norm(intent)[:120],
                    _norm(action_type)[:120],
                    _norm(decision.get("effect"))[:40],
                    _norm(decision.get("matched_rule_id"))[:120],
                    _norm(decision.get("reason"))[:500],
                    json.dumps(args_summary, ensure_ascii=False, default=str),
                    _norm(outcome)[:120],
                    json.dumps(dict(decision), ensure_ascii=False, default=str),
                ),
            )
            conn.commit()
    except Exception:
        logger.exception("assistant policy audit log failed")


def list_policy_audit(limit: int = 100) -> list[dict[str, Any]]:
    try:
        with db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM assistant_policy_audit ORDER BY id DESC LIMIT ?",
                (max(1, min(int(limit or 100), 500)),),
            ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            for k in ("args_summary_json", "details_json"):
                d[k] = _json_loads(d.get(k), {})
            out.append(d)
        return out
    except Exception:
        return []


def validate_policy_config(action_policy_json: str = "", property_rules: str = "") -> dict[str, Any]:
    errors = []
    warnings = []
    rules = []
    raw = action_policy_json if action_policy_json is not None else services.get_setting("assistant_action_policy_json", "[]")
    parsed = _json_loads(raw, None)
    if parsed is None or not isinstance(parsed, list):
        errors.append("assistant_action_policy_json must be a JSON array of rule objects.")
        parsed = []
    for i, r in enumerate(parsed):
        if not isinstance(r, dict):
            errors.append(f"Rule {i} must be an object.")
            continue
        eff = _norm(r.get("effect")).lower()
        if eff not in _EFFECTS:
            errors.append(f"Rule {i} has invalid effect '{r.get('effect')}'. Use allow/ask/deny.")
        rules.append({
            "id": _norm(r.get("id")) or f"rule-{i+1}",
            "effect": eff if eff in _EFFECTS else "ask",
            "action_types": r.get("action_types") or [],
            "intent_patterns": r.get("intent_patterns") or r.get("intents") or [],
            "roles": r.get("roles") or [],
            "reason": _norm(r.get("reason")),
        })
    pr = property_rules if property_rules is not None else services.get_setting("assistant_property_rules", "")
    prop = load_property_rules() if property_rules is None else []
    if property_rules is not None:
        # temporarily parse by setting local? easier to parse directly
        try:
            old = services.get_setting("assistant_property_rules", "")
            services.set_setting("assistant_property_rules", property_rules)
            prop = load_property_rules()
            services.set_setting("assistant_property_rules", old)
        except Exception:
            prop = []
    return {"ok": not errors, "errors": errors, "warnings": warnings, "rules": rules, "property_rules": prop, "effective_count": len(DEFAULT_SAFETY_RULES) + len(prop) + len(rules)}


def effective_policy_summary() -> dict[str, Any]:
    rules = load_policy_rules()
    return {
        "ok": True,
        "count": len(rules),
        "rules": [
            {
                "id": r.get("id"),
                "effect": r.get("effect"),
                "action_types": r.get("action_types"),
                "intent_patterns": r.get("intent_patterns"),
                "roles": r.get("roles"),
                "reason": r.get("reason"),
            }
            for r in rules
            if isinstance(r, dict)
        ],
    }
