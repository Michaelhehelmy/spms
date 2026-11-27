# SPMS / Co-Camp Assistant Datasets

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
    {"role": "user", "content": "Manager question: ...\n\nGrounded data (JSON): ..."},
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
