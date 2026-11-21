# Assistant Training Datasets

This folder holds datasets used to train/fine-tune the SPMS assistant.

## Goals
- Improve intent understanding (NLU/exemplars).
- Fine-tune a small local GGUF model (SmolLM2-360M-Instruct) for grounded rephrasing/answers.
- Keep training data app-specific and sanitized (no secrets, no unnecessary PII).

## Recommended layout

```text
data/datasets/
  README.md
  manifest.json              # dataset registry / provenance
  raw/                       # downloaded/original datasets (not committed if large/private)
  processed/
    intent_examples.jsonl    # {"text","label","slots"?,"source"}
    grounded_chat.jsonl      # {"messages":[...]} or {"instruction","input","output"}
    eval.jsonl               # held-out eval set
```

## Target format for SmolLM2 fine-tuning (grounded chat)

`processed/grounded_chat.jsonl` (one JSON per line):

```json
{
  "messages": [
    {"role": "system", "content": "You are SPMS assistant. Use ONLY provided grounded data. Do not invent facts."},
    {"role": "user", "content": "Manager question: ...\n\nGrounded data (JSON): ..."},
    {"role": "assistant", "content": "Grounded, friendly answer..."}
  ],
  "source": "feedback|synthetic|multiwoz-mapped",
  "intent": "reservation_balance"
}
```

## Suggested sources

| Dataset | Use | Notes |
|---|---|---|
| SPMS feedback (`data/assistant_nlu/feedback.jsonl`) | Highest value | Approved thumbs-up/expected-answer examples. Sanitize PII. |
| SPMS intent seed (`data/assistant_nlu/intents_seed.jsonl`) | Intent NLU | Already used by `scripts/train_assistant_intent.py`. |
| Bitext Hospitality | Support paraphrases | Map to SPMS intents/knowledge; review before use. |
| MultiWOZ (hotel) | Booking/dialogue paraphrases | Map to SPMS schema; extract relevant turns. |
| SGD (hotel/travel) | Tool-call/dialogue patterns | Map to SPMS tools; useful for synthetic tool-use examples. |

## Workflow

1. Put raw datasets in `data/datasets/raw/`.
2. Register them in `manifest.json`.
3. Build processed datasets:
   ```bash
   python scripts/prepare_assistant_dataset.py
   ```
4. Train intent classifier (existing):
   ```bash
   python scripts/train_assistant_intent.py --backend sklearn
   ```
5. Fine-tune SmolLM2-360M (separate training env with GPU recommended):
   ```bash
   python scripts/train_assistant_llm.py --model HuggingFaceTB/SmolLM2-360M-Instruct --dataset data/datasets/processed/grounded_chat.jsonl --output models/assistant-smollm2-360m
   ```
6. Export GGUF and place it at the configured `assistant_local_model_path`.
