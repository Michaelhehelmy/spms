#!/usr/bin/env python3
"""Prepare SPMS/Co-Camp assistant training datasets.

Builds processed datasets from local SPMS sources:
- data/assistant_nlu/feedback.jsonl
- data/assistant_nlu/intents_seed.jsonl
- co-camp/co_camp/data/persona_examples.jsonl
- data/assistant_knowledge/agent_brain.json
- data/datasets/curated/business_history.jsonl
- data/datasets/curated/app_operations_knowledge.jsonl
- data/datasets/curated/feedback_bootstrap.jsonl (if present)

Outputs:
- data/datasets/processed/intent_examples.jsonl
- data/datasets/processed/grounded_chat.jsonl
- data/datasets/processed/train.jsonl
- data/datasets/processed/eval.jsonl
"""

from __future__ import annotations

import json
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FEEDBACK = ROOT / "data/assistant_nlu/feedback.jsonl"
SEED = ROOT / "data/assistant_nlu/intents_seed.jsonl"
PERSONA = ROOT / "co-camp/co_camp/data/persona_examples.jsonl"
BRAIN = ROOT / "data/assistant_knowledge/agent_brain.json"
CURATED_HISTORY = ROOT / "data/datasets/curated/business_history.jsonl"
CURATED_OPS = ROOT / "data/datasets/curated/app_operations_knowledge.jsonl"
CURATED_FEEDBACK = ROOT / "data/datasets/curated/feedback_bootstrap.jsonl"
OUT_DIR = ROOT / "data/datasets/processed"
SYSTEM = (
    "You are Co-Camp, the Manager Assistant for SPMS (Super Property Management System), "
    "developed by Michael Helmy. Use ONLY the provided grounded data/answer/context. "
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


def _chat(user, assistant, source, intent="", grounded=None):
    gd = grounded if grounded is not None else {}
    return {
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": f"Manager question: {user}\n\nGrounded data (JSON): {json.dumps(gd, ensure_ascii=False, default=str)[:3500]}"},
            {"role": "assistant", "content": assistant},
        ],
        "source": source,
        "intent": intent,
    }


def build_intent_examples():
    rows = []
    for r in load_jsonl(SEED):
        text = (r.get("text") or "").strip()
        label = (r.get("label") or "").strip()
        if text and label:
            rows.append({"text": text, "label": label, "source": r.get("source", "intent_seed")})
    for r in load_jsonl(PERSONA):
        text = (r.get("text") or "").strip()
        label = (r.get("label") or "").strip()
        if text and label:
            rows.append({"text": text, "label": label, "source": r.get("source", "persona")})
    for fb_path in [FEEDBACK, CURATED_FEEDBACK]:
        for r in load_jsonl(fb_path):
            msg = (r.get("message") or "").strip()
            label = (r.get("corrected_intent") or (r.get("predicted_intent") if int(r.get("rating") or 0) == 1 else "")).strip()
            if msg and label:
                rows.append({"text": msg, "label": label, "source": r.get("source", "feedback")})
    for r in load_jsonl(CURATED_HISTORY):
        if r.get("type") == "history_qa" and r.get("question") and r.get("intent"):
            rows.append({"text": r["question"], "label": r["intent"], "source": "business_history"})
    for r in load_jsonl(CURATED_OPS):
        t = r.get("type")
        if t == "app_knowledge" and r.get("module"):
            rows.append({"text": f"How does {r['module']} work in SPMS?", "label": "capabilities_help", "source": "app_ops"})
        elif t == "ops_playbook" and r.get("name"):
            rows.append({"text": f"What is the SOP for {r['name']}?", "label": "capabilities_help", "source": "app_ops"})
    return dedupe(rows, lambda r: (r["text"].lower(), r["label"]))


def build_grounded_chat():
    rows = []
    # Feedback
    for fb_path in [FEEDBACK, CURATED_FEEDBACK]:
        for r in load_jsonl(fb_path):
            msg = (r.get("message") or "").strip()
            ans = (r.get("expected_answer") or r.get("corrected_answer") or r.get("answer") or r.get("answer_preview") or "").strip()
            ctx = r.get("data") or r.get("context") or r.get("tool_result") or r.get("slots") or {}
            intent = (r.get("corrected_intent") or r.get("predicted_intent") or "").strip()
            if not msg or not ans:
                continue
            rows.append(_chat(msg, ans, r.get("source", "feedback"), intent, ctx))

    # Persona with target answers
    for r in load_jsonl(PERSONA):
        ans = (r.get("target_answer") or "").strip()
        msg = (r.get("text") or "").strip()
        if not msg or not ans:
            continue
        rows.append(_chat(msg, ans, r.get("source", "persona"), r.get("label", ""), {"persona": "Co-Camp", "app": "SPMS"}))

    # Business history
    for r in load_jsonl(CURATED_HISTORY):
        if r.get("type") != "history_qa":
            continue
        q = (r.get("question") or "").strip(); a = (r.get("answer") or "").strip()
        if q and a:
            rows.append(_chat(q, a, "business_history", r.get("intent", ""), r.get("grounded_data", {})))

    # App/ops knowledge
    for r in load_jsonl(CURATED_OPS):
        if r.get("type") == "app_knowledge":
            q = f"What does the {r.get('module','')} module do in SPMS?"
            a = f"{r.get('module','')}: {r.get('content','')}"
            gd = {"module": r.get("module"), "content": r.get("content")}
        elif r.get("type") == "ops_playbook":
            q = f"What is the SPMS SOP for {r.get('name','')}?"
            a = f"{r.get('name','')}: {r.get('content','')}"
            gd = {"playbook": r.get("name"), "content": r.get("content")}
        else:
            continue
        if q and a:
            rows.append(_chat(q, a, r.get("source", "curated_ops"), "capabilities_help", gd))

    # Brain knowledge
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
            grounded = {"title": title, "content": content, "source": k.get("source_path", "")}
            rows.append(_chat(q, content[:1200], "brain_knowledge", "capabilities_help", grounded))

    return dedupe(rows, lambda r: json.dumps(r["messages"], ensure_ascii=False))


def main():
    random.seed(42)
    intent_rows = build_intent_examples()
    chat_rows = build_grounded_chat()
    write_jsonl(OUT_DIR / "intent_examples.jsonl", intent_rows)
    write_jsonl(OUT_DIR / "grounded_chat.jsonl", chat_rows)

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
