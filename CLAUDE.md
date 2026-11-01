# CLAUDE.md

Guidance for Claude Code in this repository.

## What this is
One-container app: FastAPI (Python 3.14) serves `/api/*` and the built React 19 SPA. An in-process APScheduler runs the daily subscription check. SQLite is at `$DATA_DIR/app.db` (`./data` is mounted).

## Commands (nothing runs on the host; hooks block pip/npm/python there)
```bash
docker compose up --build -d          # build + run on :8090 (APP_PORT)
docker compose logs -f app
make test                             # ruff + pytest in the Dockerfile `test` stage
make lint-web                         # eslint + vite build in a node container
docker run --rm -v "$PWD/backend:/w" -w /w astral/uv:0.13.6-python3.14-trixie-slim uv lock   # after editing deps
```

## Layout
- `Dockerfile`: web build (node:26 LTS), then `base` (python 3.14 + uv + deno for yt-dlp), then `test`, then `runtime`.
- `backend/app/config.py`: all settings (pydantic-settings). `EDITABLE` lists the fields the Settings page may change; `SECRETS` (API keys, SMTP password) are env-only and never returned by the API. `SCHEDULE_TIME` is accepted as an alias of `SCHEDULE_TIMES`.
- `backend/app/runtime.py`: effective settings = environment + overrides from the `settings` table (`build`, `load`, `describe`); `apply()` swaps settings, LLM registry, mailer and scheduler jobs live, with no restart.
- `backend/app/db.py`: sqlite tables: subscriptions, seen_videos, runs, analyses, settings (UI overrides as JSON). Also the one-time import of the legacy `subscriptions.json`.
- `backend/app/youtube.py`: yt-dlp wrapper. Channel URLs are normalized to `/videos`; caption-track selection avoids machine-translated tracks.
- `backend/app/llm/`: `Registry` holding Ollama, OpenAI(-compatible) and Claude(-compatible) providers. All raise `LLMError`; summaries use `build_prompt`. `check()` falls back to listing models for servers without `GET /models/{id}`.
- `backend/app/notifier.py`: check logic. New = video ID not in `seen_videos`. Videos are marked seen only after the email is sent.
- `backend/app/mailer.py` + `templates/digest.{html,txt}`: Jinja2 email. LLM markdown is HTML-escaped before rendering.
- `frontend/src/`: `App.jsx` (hash router; `#/subscriptions` and `#/status` alias the new pages), `views/` (Read, Library, Channels, Settings), `components/` (`Article.jsx`, `ui.jsx` form/section pieces), `format.js`, `api.js`.

## Conventions
- Pin exact versions (pyproject + uv.lock, package.json + lockfile, image tags). Images use LTS or stable lines, never `latest`.
- Never read or edit `.env`; document new settings in `.env.example` and `config.py`. A new UI-editable setting also goes in `EDITABLE` and the matching form in `views/Settings.jsx`.
- Adding an LLM provider: subclass `LLMProvider` in `llm/providers.py` (`configured`, `complete`, `check`), register it in `llm/__init__.py`, and add its settings to `config.py`, `.env.example` and the README.
