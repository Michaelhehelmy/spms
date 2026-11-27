# Using the Co-Camp models with the SPMS app

The Co-Camp small models are pushed to a separate artifact repo:
**https://github.com/Michaelhehelmy/spms-co-camp-models** (public; its
`manifest.json` lists the files with sizes and sha256 checksums). The app now
**auto-pulls these models by default on startup** (into the user-writable
models dir, `DATA_DIR/assistant_models/`) — see app issue
https://github.com/Michaelhehelmy/spms/issues/44. The repo URL and the pull
behavior are configurable in the app Settings (`assistant_models_repo`,
`assistant_models_auto_pull`); the manual env-var setup below remains the
fallback for overrides. Note: the repo ships the
`SmolLM2-135M-Instruct-IQ3_M.gguf` variant of the bundled GGUF — chosen to fit
GitHub's 100 MB file limit; the Co-Camp project keeps the original
`SmolLM2-135M-Instruct-Q4_K_M.gguf`.

The SPMS app supports the following plug points (`src/app_core/assistant/runtime.py`,
`src/app_core/assistant/feedback.py`). Everything runs locally; the app makes no
external API calls.

## 1. Bundled GGUF model (the "talking" model — answers rephrased by the model)

- Bundled at `co_camp/model/SmolLM2-135M-Instruct-Q4_K_M.gguf`.
- Point the app at it when launching the app (env var):
  ```
  ASSISTANT_LOCAL_MODEL_PATH=/home/michael/spms/co-camp/model/SmolLM2-135M-Instruct-Q4_K_M.gguf \
    python3 -m uvicorn ui.web.server:app --host 127.0.0.1 --port 8000 --workers 1
  ```
  (The setting `assistant_local_model_path` in the `settings` table is the DB-level
  equivalent; it is not currently exposed in the Settings UI.)
- Requirements: `pip install ".[assistant-llm"` (llama-cpp-python>=0.2) in the app venv.
- With the app default `assistant_response_mode=talking`, answers are rephrased by the
  local GGUF when available; otherwise the deterministic formatter is used.

## 2. Co-Camp fine-tuned intent router (specialized on the SPMS app + persona)

- Train/refresh: `python co_camp/train_co_camp.py --backend setfit`
- Use with the app:
  `ASSISTANT_SETFIT_MODEL_DIR=/home/michael/spms/co-camp/models/assistant_intent_setfit`
  (or copy/symlink `co_camp/models/assistant_intent_setfit` to
  `spms/models/assistant_intent_setfit`).
  Ensure `ASSISTANT_NLU=auto` or `ASSISTANT_NLU=setfit` and that setfit/datasets are
  installed in the app venv.

## 3. Optional: surface the persona in the app's greeting

The SPMS app's greeting text is hardcoded; `app_persona.patch` (in this repo) contains a
small unified diff that makes the app say "Hi! I'm Co-Camp, the Manager Assistant for SPMS,
developed by Michael Helmy...". Applying it modifies the SPMS app repo (apply with
`git apply app_persona.patch`); it is kept here as an optional extra because the Co-Camp
assistant is meant to be a separate project.

## 4. Generating/refreshing the training data

- `python co_camp/build_examples.py` regenerates `co_camp/co_camp/data/persona_examples.jsonl`
  (SPMS app seed + Co-Camp persona Q&A).
- Train again after collecting corrections in the app (the app writes
  `data/assistant_nlu/feedback.jsonl` and the `assistant_feedback` table).
