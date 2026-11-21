#!/usr/bin/env python3
"""Prepare SPMS assistant training datasets.

Builds processed datasets from local SPMS sources:
- data/assistant_nlu/feedback.jsonl
- data/assistant_nlu/intents_seed.jsonl
- data/assistant_knowledge/agent_brain.json (knowledge -> grounded Q/A templates)

Outputs:
- data/datasets/processed/intent_examples.jsonl
- data/datasets/processed/grounded_chat.jsonl

External datasets (MultiWOZ/Bitext/SGD) should be placed under data/datasets/raw/
and mapped by custom adapters (see TODO hooks).
"""

from __future__ import annotations

import json
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FEEDBACK = ROOT / "data/assistant_nlu/feedback.jsonl"
SEED = ROOT / "data/assistant_nlu/intents_seed.jsonl"
BRAIN = ROOT / "data/assistant_knowledge/agent_brain.json"
OUT_DIR = ROOT / "data/datasets/processed"
SYSTEM = (
    "You are the SPMS property manager assistant. "
    "Use ONLY the provided grounded data/answer/context. "
    "Do not invent facts, IDs, dates, amounts, or actions. "
    "If data is missing, ask a clear clarifying question."
)


def load_jsonl(path: Path):
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except Exception:
            pass
    return rows


def write_jsonl(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def dedupe(rows, key_fn):
    seen = set()
    out = []
    for r in rows:
        k = key_fn(r)
        if k in seen:
            continue
        seen.add(k)
        out.append(r)
    return out


def build_intent_examples():
    rows = []
    for r in load_jsonl(SEED):
        text = (r.get("text") or "").strip()
        label = (r.get("label") or "").strip()
        if text and label:
            rows.append({"text": text, "label": label, "source": "intent_seed"})
    for r in load_jsonl(FEEDBACK):
        msg = (r.get("message") or "").strip()
        label = (r.get("corrected_intent") or (r.get("predicted_intent") if int(r.get("rating") or 0) == 1 else "")).strip()
        if msg and label:
            rows.append({"text": msg, "label": label, "source": "feedback"})
    return dedupe(rows, lambda r: (r["text"].lower(), r["label"]))


def build_grounded_chat():
    rows = []
    # From feedback: preferred for grounded answer style
    for r in load_jsonl(FEEDBACK):
        msg = (r.get("message") or "").strip()
        ans = (r.get("expected_answer") or r.get("corrected_answer") or r.get("answer") or "").strip()
        ctx = r.get("data") or r.get("context") or r.get("tool_result") or {}
        intent = (r.get("corrected_intent") or r.get("predicted_intent") or "").strip()
        if not msg or not ans:
            continue
        user = f"Manager question: {msg}\n\nGrounded data (JSON): {json.dumps(ctx, ensure_ascii=False, default=str)[:3500]}"
        rows.append({
            "messages": [
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": user},
                {"role": "assistant", "content": ans},
            ],
            "source": "feedback",
            "intent": intent,
        })

    # From brain knowledge: create simple grounded Q&A examples
    if BRAIN.exists():
        try:
            brain = json.loads(BRAIN.read_text(encoding="utf-8"))
        except Exception:
            brain = {}
        for k in (brain.get("knowledge") or []):
            title = (k.get("title") or "").strip()
            content = (k.get("content") or "").strip()
            if not title or not content:
                continue
            q = f"How do I {title.lower()}?" if not title.lower().startswith("how") else title
            grounded = json.dumps({"title": title, "content": content, "source": k.get("source_path", "")}, ensure_ascii=False)
            rows.append({
                "messages": [
                    {"role": "system", "content": SYSTEM},
                    {"role": "user", "content": f"Manager question: {q}\n\nGrounded data (JSON): {grounded}"},
                    {"role": "assistant", "content": content[:1200]},
                ],
                "source": "brain_knowledge",
                "intent": "capabilities_help",
            })

    # TODO: add adapters for data/datasets/raw/MultiWOZ, Bitext, SGD etc.
    return dedupe(rows, lambda r: json.dumps(r["messages"], ensure_ascii=False))


def main():
    random.seed(42)
    intent_rows = build_intent_examples()
    chat_rows = build_grounded_chat()
    write_jsonl(OUT_DIR / "intent_examples.jsonl", intent_rows)
    write_jsonl(OUT_DIR / "grounded_chat.jsonl", chat_rows)

    # simple eval split
    eval_rows = chat_rows[: max(1, len(chat_rows) // 10)] if chat_rows else []
    train_rows = chat_rows[len(eval_rows):] if chat_rows else []
    write_jsonl(OUT_DIR / "eval.jsonl", eval_rows)
    write_jsonl(OUT_DIR / "train.jsonl", train_rows)

    print(json.dumps({
        "intent_examples": len(intent_rows),
        "grounded_chat": len(chat_rows),
        "train": len(train_rows),
        "eval": len(eval_rows),
        "out_dir": str(OUT_DIR),
    }, indent=2))


if __name__ == "__main__":
    main()
