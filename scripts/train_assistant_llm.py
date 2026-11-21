#!/usr/bin/env python3
"""Fine-tune a small local instruction model for SPMS grounded responses.

Default target: HuggingFaceTB/SmolLM2-360M-Instruct

This script is intended for a training environment (GPU recommended).
It does NOT run well on Termux/Android.

Example:
  python scripts/train_assistant_llm.py \
    --model HuggingFaceTB/SmolLM2-360M-Instruct \
    --dataset data/datasets/processed/train.jsonl \
    --eval-dataset data/datasets/processed/eval.jsonl \
    --output models/assistant-smollm2-360m-lora

After training, merge/export to GGUF with llama.cpp (see printed instructions).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def require_deps():
    missing = []
    for mod in ["datasets", "transformers", "peft", "trl", "torch"]:
        try:
            __import__(mod)
        except Exception:
            missing.append(mod)
    if missing:
        raise SystemExit(
            "Missing training deps: " + ", ".join(missing) +
            "\nInstall in a training env, e.g.: pip install transformers datasets peft trl accelerate torch"
        )


def load_chat_dataset(path: Path):
    from datasets import Dataset

    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        obj = json.loads(line)
        msgs = obj.get("messages") or []
        if msgs:
            rows.append({"messages": msgs})
    if not rows:
        raise SystemExit(f"No training rows found in {path}")
    return Dataset.from_list(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="HuggingFaceTB/SmolLM2-360M-Instruct")
    ap.add_argument("--revision", default=None, help="Optional model revision/commit hash for reproducible downloads")
    ap.add_argument("--dataset", default="data/datasets/processed/train.jsonl")
    ap.add_argument("--eval-dataset", default="data/datasets/processed/eval.jsonl")
    ap.add_argument("--output", default="models/assistant-smollm2-360m-lora")
    ap.add_argument("--max-seq-length", type=int, default=1024)
    ap.add_argument("--epochs", type=float, default=2.0)
    ap.add_argument("--batch-size", type=int, default=2)
    ap.add_argument("--lr", type=float, default=2e-4)
    args = ap.parse_args()

    require_deps()
    import torch
    from datasets import Dataset
    from transformers import AutoModelForCausalLM, AutoTokenizer
    from peft import LoraConfig
    from trl import SFTConfig, SFTTrainer

    ds_path = Path(args.dataset)
    eval_path = Path(args.eval_dataset)
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)

    from_pretrained_kwargs = {"revision": args.revision} if args.revision else {}
    tokenizer = AutoTokenizer.from_pretrained(args.model, use_fast=True, **from_pretrained_kwargs)  # nosec B615 - revision can be pinned via --revision
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    model = AutoModelForCausalLM.from_pretrained(
        args.model,
        torch_dtype=torch.float16 if torch.cuda.is_available() else torch.float32,
        device_map="auto" if torch.cuda.is_available() else None,
        **from_pretrained_kwargs,
    )  # nosec B615 - revision can be pinned via --revision

    peft_config = LoraConfig(
        r=16,
        lora_alpha=32,
        lora_dropout=0.05,
        bias="none",
        task_type="CAUSAL_LM",
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
    )

    train_ds = load_chat_dataset(ds_path)
    eval_ds = load_chat_dataset(eval_path) if eval_path.exists() else None

    def formatting_func(example):
        # TRL can accept messages with chat template in newer versions; fallback to text
        msgs = example.get("messages")
        if isinstance(msgs, list):
            try:
                return tokenizer.apply_chat_template(msgs, tokenize=False, add_generation_prompt=False)
            except Exception:
                pass
        return str(example)

    # Handle TRL API differences
    sft_kwargs = dict(
        output_dir=str(out),
        num_train_epochs=args.epochs,
        per_device_train_batch_size=args.batch_size,
        learning_rate=args.lr,
        logging_steps=10,
        save_strategy="epoch",
        report_to=[],
        max_seq_length=args.max_seq_length,
    )
    try:
        train_args = SFTConfig(**sft_kwargs)
    except TypeError:
        # older trl
        sft_kwargs.pop("max_seq_length", None)
        train_args = SFTConfig(**sft_kwargs)

    trainer = SFTTrainer(
        model=model,
        train_dataset=train_ds,
        eval_dataset=eval_ds,
        peft_config=peft_config,
        tokenizer=tokenizer,
        args=train_args,
        formatting_func=formatting_func,
    )
    trainer.train()
    trainer.save_model(str(out))
    tokenizer.save_pretrained(str(out))

    print(f"Saved LoRA adapter to {out}")
    print("\nNext steps (merge + GGUF export):")
    print("1) Merge LoRA into base model (transformers/peft script).")
    print("2) Convert to GGUF with llama.cpp: python convert_hf_to_gguf.py merged_model --outfile models/assistant-smollm2-360m.gguf")
    print("3) Quantize: ./llama-quantize models/assistant-smollm2-360m.gguf models/assistant-smollm2-360m-q4_k_m.gguf Q4_K_M")
    print("4) Set ASSISTANT_LOCAL_MODEL_PATH to the .gguf in SPMS.")


if __name__ == "__main__":
    main()
