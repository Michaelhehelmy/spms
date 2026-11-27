# Co-Camp — Manager Assistant for SPMS

**Co-Camp** is the dedicated Manager Assistant for **SPMS** (Super Property
Management System), developed by **Michael Helmy**. Co-Camp is a small,
specialized assistant that knows the SPMS app: property stats, rooms and
reservations, housekeeping and front-desk operations, room availability, the
reservation pipeline, front-desk arrivals/in-house/departures, night audit,
payments, expenses, sales, P&L, cash flow, VAT, outstanding balances,
inventory alerts and traceability, and ledger/reservation financial integrity.

Everything here runs **locally and offline** — no external API calls.

## Layout

```
co-camp/                     # separate project ("sub repo" of the SPMS app)
├── co_camp/                 # Python package
│   ├── persona.py           #   Co-Camp persona constants (name/role/expertise)
│   ├── build_examples.py    #   generates the persona training examples
│   ├── train_co_camp.py     #   fine-tunes the small intent router (SetFit/sklearn)
│   └── data/
│       └── persona_examples.jsonl   # generated: SPMS seed + Co-Camp persona Q&A
├── model/
│   └── SmolLM2-135M-Instruct-Q4_K_M.gguf   # bundled small GGUF ("talking" model)
├── models/
│   └── assistant_intent_setfit/      # trained fine-tune (produced by training)
├── README.md                # this file
├── APP_INTEGRATION.md       # how to plug the models into the SPMS app
└── app_persona.patch       # optional patch to make the app say "Co-Camp"
```

## How to fine-tune (the "small model specialized for the app")

The fine-tune is the app's small-model path (`scripts/train_assistant_intent.py` in
the SPMS app) adapted to the Co-Camp persona and outputs. Training data:

- the SPMS app seed examples (`spms/data/assistant_nlu/intents_seed.jsonl`) → **specialized in the app**
- the SPMS app feedback corrections (`spms/data/assistant_nlu/feedback.jsonl`) → self-improving
- the Co-Camp persona examples (`co_camp/co_camp/data/persona_examples.jsonl`) → **knows it is Co-Camp, the Manager Assistant for SPMS, developed by Michael Helmy, and knows SPMS business operations and accounting**

1. Generate persona examples (from the SPMS app seed):
   ```sh
   python co_camp/build_examples.py
   ```
2. Create a venv and install the training deps:
   ```sh
   python3 -m venv .venv && .venv/bin/pip install -U pip
   .venv/bin/pip install "setfit>=1.0" "sentence-transformers>=2.2" "scikit-learn>=1.3" "joblib>=1.3"
   ```
   (or the tiny alternative: `--backend sklearn` — needs only scikit-learn + joblib)
3. Fine-tune:
   ```sh
   .venv/bin/python co_camp/train_co_camp.py --backend setfit
   # or the smallest model: .venv/bin/python co_camp/train_co_camp.py --backend sklearn
   ```
4. Verify (see `python co_camp/train_co_camp.py` outputs): metrics are printed and the
   model is saved to `co_camp/models/assistant_intent_setfit/` (+ `metrics.json`) or
   `co_camp/models/assistant_intent_sklearn.joblib`.
5. Predict-check:
   ```sh
   .venv/bin/python -c "
   from setfit import SetFitModel
   m = SetFitModel.from_pretrained('co_camp/models/assistant_intent_setfit')
   print(m.predict(['Who are you?']))
   print(m.predict(['What is my occupancy today?']))
   print(m.predict(['Who developed you?']))
   "
   ```

## Using the models with the SPMS app

See [APP_INTEGRATION.md](APP_INTEGRATION.md). The models are also published to
**https://github.com/Michaelhehelmy/spms-co-camp-models** (the auto-download
repo, see its `manifest.json`). The app auto-pulls the models by default on
startup (app issue https://github.com/Michaelhehelmy/spms/issues/44); the
env-var setup below is the fallback. Summary:

- **Bundled GGUF** (`co_camp/model/SmolLM2-135M-Instruct-Q4_K_M.gguf`): point the app at it
  with `ASSISTANT_LOCAL_MODEL_PATH=<path>` (or the `assistant_local_model_path` setting),
  requires `pip install ".[assistant-llm"` (llama-cpp-python).
- **Co-Camp fine-tuned intent router** (`co_camp/models/assistant_intent_setfit/`): point the
  app at it with `ASSISTANT_SETFIT_MODEL_DIR=<path>` (requires setfit installed).
- **Optional**: `app_persona.patch` — makes the app's greeting say "I'm Co-Camp, the Manager
  Assistant for SPMS, developed by Michael Helmy...". Applying it modifies the SPMS app repo.

## Feedback loop

The SPMS app records corrections (`/assistant/feedback` → `data/assistant_nlu/feedback.jsonl`
+ the `assistant_feedback` table). Re-run `co_camp/train_co_camp.py` after collecting feedback
to re-specialize the router.

## License note

SPMS is proprietary (see the SPMS repo `pyproject.toml`). This Co-Camp companion project
builds on the SPMS app's assistant data/tooling — it is meant as a separate project related
to the app, not a merge.
