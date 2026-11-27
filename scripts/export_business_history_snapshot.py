#!/usr/bin/env python3
"""Export a sanitized business-history snapshot for assistant training.

This makes Co-Camp "smarter over time" by capturing real (sanitized) historical
business metrics into data/datasets/history/. Run periodically (e.g., monthly)
and then rebuild datasets:

  python scripts/export_business_history_snapshot.py
  python scripts/build_max_assistant_datasets.py
  python scripts/prepare_assistant_dataset.py

The export contains aggregated metrics only - no guest names, phones, emails,
or raw PII. It is safe to use for local training data.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

OUT_DIR = ROOT / "data" / "datasets" / "history"


def _iso(d):
    return d.strftime("%Y-%m-%d")


def _month_range(year: int, month: int):
    start = datetime(year, month, 1).date()
    if month == 12:
        end = datetime(year + 1, 1, 1).date() - timedelta(days=1)
    else:
        end = datetime(year, month + 1, 1).date() - timedelta(days=1)
    return start, end


def _safe_float(v, default=0.0):
    try:
        return float(v)
    except Exception:
        return default


def collect_snapshot(months_back: int = 6) -> dict:
    # Import lazily so script can be inspected without DB deps.
    try:
        from app_core import services
    except Exception as e:
        return {"ok": False, "error": f"Cannot import app_core.services: {e}", "snapshots": []}

    today = datetime.now().date().replace(day=1)
    snaps = []
    for i in range(months_back - 1, -1, -1):
        y = (today.year * 12 + (today.month - 1) - i)
        year, month = divmod(y, 12)
        month += 1
        start, end = _month_range(year, month)
        period = f"{year:04d}-{month:02d}"
        rec = {"period": period, "start": _iso(start), "end": _iso(end), "source": "spms_db_aggregates", "anonymized": True}
        # P&L
        try:
            pl = services.report_pl(rec["start"], rec["end"]) if hasattr(services, "report_pl") else {}
            rec["revenue"] = _safe_float(pl.get("revenue") or pl.get("total_revenue") or pl.get("income"))
            rec["expenses"] = _safe_float(pl.get("expenses") or pl.get("total_expenses"))
            rec["net_profit"] = _safe_float(pl.get("net_profit") or pl.get("profit") or (rec["revenue"] - rec["expenses"]))
        except Exception:
            pass
        # Cash flow
        try:
            cf = services.report_cash_flow(rec["start"], rec["end"]) if hasattr(services, "report_cash_flow") else {}
            rec["cash_in"] = _safe_float(cf.get("cash_in") or cf.get("total_in") or cf.get("inflow"))
            rec["cash_out"] = _safe_float(cf.get("cash_out") or cf.get("total_out") or cf.get("outflow"))
            rec["net_cash_flow"] = _safe_float(cf.get("net_cash_flow") or cf.get("net") or (rec.get("cash_in", 0) - rec.get("cash_out", 0)))
        except Exception:
            pass
        # Occupancy
        try:
            occ = services.report_occupancy(rec["start"], rec["end"]) if hasattr(services, "report_occupancy") else {}
            rec["occupancy_pct"] = _safe_float(occ.get("occupancy_pct") or occ.get("occupancy") or occ.get("rate"))
            rec["adr"] = _safe_float(occ.get("adr"))
            rec["revpar"] = _safe_float(occ.get("revpar"))
        except Exception:
            pass
        # Ops counts (sanitized aggregates)
        try:
            stats = services.get_property_stats() if hasattr(services, "get_property_stats") else {}
            rec["property_stats_at_export"] = {k: v for k, v in stats.items() if isinstance(v, (int, float, str)) and k in {"total_guests", "total_rooms", "total_reservations"}}
        except Exception:
            pass
        snaps.append(rec)

    return {
        "ok": True,
        "version": datetime.now(timezone.utc).strftime("%Y.%m.%d"),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "type": "spms_business_history_snapshot",
        "anonymized": True,
        "snapshots": snaps,
        "notes": "Aggregated metrics only. No PII. Regenerate periodically and rebuild datasets.",
    }


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--months", type=int, default=6)
    ap.add_argument("--output", default=str(OUT_DIR / "latest_real.json"))
    args = ap.parse_args()
    snap = collect_snapshot(months_back=args.months)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(snap, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    # also versioned copy
    versioned = OUT_DIR / f"real_business_history_{datetime.now(timezone.utc).strftime('%Y%m%d')}.json"
    versioned.write_text(json.dumps(snap, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"ok": snap.get("ok"), "output": str(out), "versioned": str(versioned), "count": len(snap.get("snapshots", []))}, indent=2))


if __name__ == "__main__":
    main()
