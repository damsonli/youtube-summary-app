# CLAUDE.md

Guidance for Claude Code in this repository.

## What this is
"Tube Desk": a personal YouTube suite (Summarize, Download, Library, Channels, Settings) in one container. FastAPI (Python 3.14) serves `/api/*` and the built React 19 SPA. An in-process APScheduler runs the daily subscription check. SQLite is at `$DATA_DIR/app.db` (`./data` is mounted); kept downloads are in `$DATA_DIR/downloads`, sign-in cookies in `$DATA_DIR/cookies.txt`.

## Commands (nothing runs on the host; hooks block pip/npm/python there)
```bash
docker compose up --build -d          # build + run on :8090 (APP_PORT)
docker compose logs -f app
make test                             # ruff + pytest in the Dockerfile `test` stage
make lint-web                         # eslint + vite build in a node container
docker run --rm -v "$PWD/backend:/w" -w /w astral/uv:0.13.6-python3.14-trixie-slim uv lock   # after editing deps
```

## Layout
- `Dockerfile`: web build (node:26 LTS), then `base` (python 3.14 + uv + deno for yt-dlp + static ffmpeg/ffprobe), then `test`, then `runtime`.
- `backend/app/config.py`: all settings (pydantic-settings). `EDITABLE` lists the fields the Settings page may change; `SECRETS` (API keys, SMTP password) are env-only and never returned by the API. `SCHEDULE_TIME` is accepted as an alias of `SCHEDULE_TIMES`.
- `backend/app/runtime.py`: effective settings = environment + overrides from the `settings` table (`build`, `load`, `describe`); `apply()` swaps settings, LLM registry, mailer and scheduler jobs live, with no restart.
- `backend/app/db.py`: sqlite tables: subscriptions, seen_videos, runs, analyses, settings (UI overrides as JSON). Also the one-time import of the legacy `subscriptions.json`.
- `backend/app/youtube.py`: yt-dlp wrapper. Channel URLs are normalized to `/videos`; caption-track selection avoids machine-translated tracks. `ydl_base_opts(settings)` (cookies + ffmpeg) is shared by every yt-dlp call.
- `backend/app/cookies.py`: sign-in cookie source (`COOKIES_SOURCE`: `upload` = `cookies.txt`, `firefox` = live from the Firefox folder that compose mounts read-only at `/firefox` via `FIREFOX_PROFILES`). Firefox's `cookies.sqlite` + WAL are snapshotted into `$DATA_DIR/.firefox-cookies` when they change; `firefox` falls back to `cookies.txt` when no profile is found. Chrome/Edge on Windows can't be read (app-bound encryption).
- `backend/app/downloader.py`: `DownloadManager` (in-memory jobs, semaphore, hourly sweep of `downloads/.tmp`). The client sends a `Selection` (allowlisted kind/codec/height/mode); `build_selector` turns it into the yt-dlp format string, so never accept raw format strings. `download_api.py` holds the `/api/download`, `/api/files` and `/api/cookies` routes; cookie content is never returned, except by `POST /api/cookies/export` (Firefox's youtube.com cookies as a cookies.txt, so another server can upload them).
- `backend/app/llm/`: `Registry` holding Ollama, OpenAI(-compatible) and Claude(-compatible) providers. All raise `LLMError`; summaries use `build_prompt`. `check()` falls back to listing models for servers without `GET /models/{id}`.
- `backend/app/notifier.py`: check logic. New = video ID not in `seen_videos`. Videos are marked seen only after the email is sent.
- `backend/app/mailer.py` + `templates/digest.{html,txt}`: Jinja2 email. LLM markdown is HTML-escaped before rendering.
- `frontend/src/`: `App.jsx` (hash router with query params, e.g. `#/download?url=…`; `#/read`, `#/subscriptions` and `#/status` are aliases), `views/` (Read = Summarize page, Download, Library, Channels, Settings), `components/` (`Article.jsx`, `ui.jsx` form/section pieces, `download/` pickers and progress), `format.js` (incl. `toolLink(tool, url)` for cross-links), `api.js`.

## Conventions
- Pin exact versions (pyproject + uv.lock, package.json + lockfile, image tags). Images use LTS or stable lines, never `latest`.
- Never read or edit `.env`; document new settings in `.env.example` and `config.py`. A new UI-editable setting also goes in `EDITABLE` and the matching form in `views/Settings.jsx`.
- Adding an LLM provider: subclass `LLMProvider` in `llm/providers.py` (`configured`, `complete`, `check`), register it in `llm/__init__.py`, and add its settings to `config.py`, `.env.example` and the README.
