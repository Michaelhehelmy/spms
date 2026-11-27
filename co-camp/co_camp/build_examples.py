#!/usr/bin/env python3
"""Generate the Co-Camp persona training examples (text, label) JSONL.

Sources:
- SPMS app seed data:  ``spms/data/assistant_nlu/intents_seed.jsonl`` (specialization in the app)
- Co-Camp persona Q&A: ``co_camp/persona.py``                          (identity / role / expertise)

Output: ``co_camp/data/persona_examples.jsonl``

Run: ``python co_camp/build_examples.py`` (from anywhere; writes into co-camp/co_camp/data/).
"""
from __future__ import annotations

import ast
import json
from pathlib import Path

from .persona import NAME, PERSONA_QA

CO_CAMP = Path(__file__).resolve().parents[1]   # .../co-camp
SPMS = Path(__file__).resolve().parents[2]       # the SPMS app repo

APP_COMMON = SPMS / "src" / "app_core" / "assistant" / "common.py"
SEED = SPMS / "data" / "assistant_nlu" / "intents_seed.jsonl"
OUT = CO_CAMP / "co_camp" / "data" / "persona_examples.jsonl"


def app_intent_labels():
    """Parse INTENT_LABELS out of the SPMS app (no imports needed)."""
    tree = ast.parse(APP_COMMON.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "INTENT_LABELS" for t in node.targets
        ):
            return ast.literal_eval(node.value)
    raise RuntimeError(f"INTENT_LABELS not found in {APP_COMMON}")


def seed_rows():
    rows = []
    for line in SEED.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        if r.get("text") and r.get("label"):
            rows.append({"text": r["text"], "label": r["label"]})
    return rows


def generate_persona_examples(app_labels=None, rows=None):
    app_labels = app_labels if app_labels is not None else app_intent_labels()
    rows = rows if rows is not None else seed_rows()
    out, seen = [], set()

    def add(text, label, **extra):
        key = (text.strip().lower(), label)
        if key in seen or not text or not label:
            return
        seen.add(key)
        row = {"text": text.strip(), "label": label}
        row.update({k: v for k, v in extra.items() if v not in (None, "", [], {})})
        out.append(row)

    # 0) Preserve existing curated/rich examples (generated_max, curated_* etc.)
    if OUT.exists():
        for r in json.loads("[]"):
            pass
        for line in OUT.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                r = json.loads(line)
            except Exception:
                continue
            src = (r.get("source") or "")
            if src.startswith("curated") or src == "seed_original":
                add(r.get("text", ""), r.get("label", ""), source=src, target_answer=r.get("target_answer"))

    # 1) Persona identity / role / expertise questions
    for text, label in PERSONA_QA:
        add(text, label, source="persona_qa")

    # 2) Co-Camp-flavored variants of real SPMS app seed examples.
    per_label = {}
    for r in rows:
        per_label.setdefault(r["label"], []).append(r["text"])
    for label in app_labels:
        for text in per_label.get(label, [])[:4]:
            add(f"{NAME}, {text}", label, source="persona_seed_variant")

    # 3) Per-intent Co-Camp questions (role/expertise awareness).
    for label in app_labels:
        human = label.replace("_", " ")
        add(f"{NAME} — do you know how to help with '{human}'?", "capabilities_help", source="persona_capability")
        add(f"Can you help with {human} in SPMS?", "capabilities_help", source="persona_capability")

    return out


def main():
    examples = generate_persona_examples()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8") as f:
        for r in examples:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"Generated {len(examples)} persona examples -> {OUT}")


if __name__ == "__main__":
    main()
