#!/usr/bin/env python3
"""Fine-tune the Co-Camp small intent router (SetFit or sklearn) on:

- SPMS app seed data      ``spms/data/assistant_nlu/intents_seed.jsonl``   (specialization in the app)
- SPMS app feedback       ``spms/data/assistant_nlu/feedback.jsonl``       (corrections; rating==1 with predicted_intent)
- Co-Camp persona examples ``co_camp/data/persona_examples.jsonl``         (name/role/expertise awareness)

Usage:
  python co_camp/train_co_camp.py --backend setfit --base-model paraphrase-MiniLM-L3-v2
  python co_camp/train_co_camp.py --backend sklearn

Outputs (under co_camp/models/):
  setfit  -> ``assistant_intent_setfit/``  (model + metrics.json)
  sklearn -> ``assistant_intent_sklearn.joblib``
"""
from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

CO_CAMP = Path(__file__).resolve().parents[1]   # .../co-camp
SPMS = Path(__file__).resolve().parents[2]       # the SPMS app repo

SEED = SPMS / "data" / "assistant_nlu" / "intents_seed.jsonl"
FEEDBACK = SPMS / "data" / "assistant_nlu" / "feedback.jsonl"
PERSONA = CO_CAMP / "co_camp" / "data" / "persona_examples.jsonl"
CURATED_INTENT = SPMS / "data" / "datasets" / "processed" / "intent_examples.jsonl"
CURATED_HISTORY = SPMS / "data" / "datasets" / "curated" / "business_history.jsonl"
CURATED_OPS = SPMS / "data" / "datasets" / "curated" / "app_operations_knowledge.jsonl"
SF_OUT = CO_CAMP / "models" / "assistant_intent_setfit"
SK_OUT = CO_CAMP / "models" / "assistant_intent_sklearn.joblib"


def load_jsonl(p: Path):
    items = []
    if not p.exists():
        return items
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            items.append(json.loads(line))
        except Exception:
            pass
    return items


def load_dataset():
    rows = []
    for r in load_jsonl(SEED):
        if r.get("text") and r.get("label"):
            rows.append({"text": r["text"], "label": r["label"]})
    for r in load_jsonl(FEEDBACK):
        intent = r.get("corrected_intent") or (r.get("predicted_intent") if int(r.get("rating") or 0) == 1 else "")
        if r.get("message") and intent:
            rows.append({"text": r["message"], "label": intent})
    for r in load_jsonl(PERSONA):
        if r.get("text") and r.get("label"):
            rows.append({"text": r["text"], "label": r["label"]})
    # Curated/processed datasets (max business/app/ops/history coverage)
    for r in load_jsonl(CURATED_INTENT):
        if r.get("text") and r.get("label"):
            rows.append({"text": r["text"], "label": r["label"]})
    for r in load_jsonl(CURATED_HISTORY):
        if r.get("type") == "history_qa" and r.get("question") and r.get("intent"):
            rows.append({"text": r["question"], "label": r["intent"]})
    for r in load_jsonl(CURATED_OPS):
        t = r.get("type")
        if t == "app_knowledge" and r.get("module"):
            rows.append({"text": f"How does {r['module']} work in SPMS?", "label": "capabilities_help"})
        elif t == "ops_playbook" and r.get("name"):
            rows.append({"text": f"What is the SOP for {r['name']}?", "label": "capabilities_help"})
    seen, out = set(), []
    for r in rows:
        k = (r["text"].strip().lower(), r["label"])
        if k in seen:
            continue
        seen.add(k)
        out.append(r)
    return out


def split(rows, test_ratio=0.2):
    by = {}
    for r in rows:
        by.setdefault(r["label"], []).append(r)
    train, test = [], []
    rng = random.Random(42)
    for lbl, items in by.items():
        items = list(items)
        rng.shuffle(items)
        n_test = max(1, int(len(items) * test_ratio)) if len(items) > 3 else (1 if len(items) > 1 else 0)
        test.extend(items[:n_test])
        train.extend(items[n_test:])
    rng.shuffle(train)
    rng.shuffle(test)
    return train, test


def train_sklearn(rows):
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import Pipeline
    from sklearn.metrics import classification_report, accuracy_score
    import joblib
    train, test = split(rows)
    Xtr = [r["text"] for r in train]; ytr = [r["label"] for r in train]
    Xte = [r["text"] for r in test]; yte = [r["label"] for r in test]
    vec = TfidfVectorizer(ngram_range=(1, 2), analyzer="char_wb", min_df=1)
    clf = LogisticRegression(max_iter=400)
    Xtrv = vec.fit_transform(Xtr)
    clf.fit(Xtrv, ytr)
    metrics = {"backend": "sklearn", "train": len(train), "test": len(test),
               "app": str(SPMS), "output": str(SK_OUT)}
    if Xte:
        pred = clf.predict(vec.transform(Xte))
        metrics["accuracy"] = float(accuracy_score(yte, pred))
        metrics["report"] = classification_report(yte, pred, zero_division=0, output_dict=True)
    SK_OUT.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump({"vectorizer": vec, "classifier": clf, "labels": sorted({r["label"] for r in rows})}, SK_OUT)
    print(json.dumps(metrics, indent=2, ensure_ascii=False))
    print(f"Saved: {SK_OUT}")


def train_setfit(rows, base_model):
    from setfit import SetFitModel, Trainer, TrainingArguments
    from datasets import Dataset
    from sklearn.metrics import classification_report, accuracy_score
    train, test = split(rows)
    ds_train = Dataset.from_list(train)
    model = SetFitModel.from_pretrained(base_model)
    # Note: with setfit 1.2 + transformers 5.x, in-training evaluation can stall in
    # this environment, so we train without eval_dataset; metrics are computed
    # afterwards with model.predict (below).
    args = TrainingArguments(batch_size=16, num_epochs=1, evaluation_strategy="no", save_strategy="no", show_progress_bar=False)
    trainer = Trainer(model=model, args=args, train_dataset=ds_train)
    trainer.train()
    metrics = {"backend": "setfit", "base_model": base_model, "train": len(train), "test": len(test),
               "app": str(SPMS), "output": str(SF_OUT)}
    if test:
        preds = model.predict([r["text"] for r in test])
        yte = [r["label"] for r in test]
        metrics["accuracy"] = float(accuracy_score(yte, preds))
        metrics["report"] = classification_report(yte, preds, zero_division=0, output_dict=True)
    SF_OUT.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(str(SF_OUT))
    (SF_OUT / "metrics.json").write_text(json.dumps(metrics, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(metrics, indent=2, ensure_ascii=False))
    print(f"Saved: {SF_OUT}")


def main():
    ap = argparse.ArgumentParser(description="Fine-tune the Co-Camp small intent router on SPMS app data + persona.")
    ap.add_argument("--backend", choices=["sklearn", "setfit"], default="setfit")
    ap.add_argument("--base-model", default="sentence-transformers/paraphrase-MiniLM-L3-v2")
    args = ap.parse_args()
    rows = load_dataset()
    if not rows:
        raise SystemExit("No training data found. Ensure data/assistant_nlu/intents_seed.jsonl exists under the SPMS app repo.")
    print(f"Loaded {len(rows)} labeled examples ({len({r['label'] for r in rows})} intents)")
    if args.backend == "sklearn":
        train_sklearn(rows)
    else:
        train_setfit(rows, args.base_model)


if __name__ == "__main__":
    main()
