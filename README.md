# Tube Desk (YouTube Digest)

A personal YouTube toolkit: summarize videos and channels with AI, download videos, audio and subtitles, and get a daily email of new uploads from the channels you follow.

- **Summarize**: paste a video or channel link and get a structured summary, built from the transcript when one exists.
- **Download**: paste a video, playlist or channel link, pick the resolution and codec (or audio only: M4A, Opus, MP3), optionally subtitles as `.srt`, and see the exact size before you start. Files go to your browser; tick "Also keep a copy on the server" to keep them in `data/downloads/` as well.
- **Library**: every summary you make is kept.
- **Channels**: enter your email, then follow channels; new uploads arrive in one email per check, with AI summaries for the newest few.
- **Settings**: AI provider (with connection tests), check times and time zone, email contents, mail server, a test email, YouTube sign-in cookies, and the log of every check.

The pages link to each other: a summary has a "Download video" link, the Download page has "Summarize this video", and a channel link can be followed by email from either page.

AI providers: **Ollama** (local), **OpenAI or any OpenAI-compatible server** (LM Studio, vLLM, OpenRouter, LiteLLM…), or **Claude or any Anthropic-compatible gateway**. Pick the default in Settings (or `.env`); you can switch per summary on the Summarize page.

Everything runs in **one container**: FastAPI serves the API (`/api/*`) and the built React app, and the daily scheduler runs in the same process. Data lives in SQLite at `./data/app.db`. The image includes yt-dlp, deno (which yt-dlp needs for YouTube) and a static ffmpeg.

## Quick start

```bash
cp .env.example .env     # then edit: AI provider + email settings
docker compose up --build -d
```

Open http://localhost:8090 (change with `APP_PORT`). Or run `./start.sh`, which does the same.

Upgrading from the old two-container version: on first start, `data/subscriptions.json` is imported automatically and renamed to `subscriptions.json.imported`.

## Configuration

There are two places, and the Settings page wins:

1. **`.env`** sets the starting values, and is the **only** place for secrets: `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `EMAIL_PASSWORD`. Changes need a restart (`docker compose up -d`).
2. **The Settings page** can change everything else while the app runs; changes apply immediately (including the schedule). Saved values are stored in `data/app.db` and override `.env`. Each changed field has a "Use the .env value instead" link.

See `.env.example` for every option. The important ones:

| Setting | Meaning |
|---|---|
| `LLM_SERVICE` | `ollama`, `openai` or `claude`: the default provider |
| `OLLAMA_HOST`, `OLLAMA_MODEL`, `OLLAMA_NUM_CTX` | Ollama server, model (must be pulled) and context size |
| `OPENAI_API_KEY`, `OPENAI_BASE_URL`, `OPENAI_MODEL` | OpenAI, or any OpenAI-compatible server (see below) |
| `ANTHROPIC_API_KEY`, `ANTHROPIC_BASE_URL`, `CLAUDE_MODEL`, `CLAUDE_EFFORT` | Claude (default `claude-haiku-5-5`, effort `low`), or an Anthropic-compatible gateway |
| `SMTP_SERVER`, `SMTP_PORT`, `SMTP_SECURITY` | `starttls` for port 587, `ssl` for 465 |
| `EMAIL_USER`, `EMAIL_PASSWORD`, `FROM_EMAIL` | SMTP login; for Gmail use an App Password |
| `TIMEZONE`, `SCHEDULE_TIMES` | e.g. `America/New_York` and `07:30,18:00` (local times; DST-safe) |
| `MAX_AI_SUMMARIES_PER_CHANNEL` | How many of the newest new videos per channel get an AI summary in each email (default 3). Every new video is listed regardless; `0` turns summaries off. |
| `TRANSCRIPT_MAX_CHARS` | Characters of transcript sent to the AI per video (default 20000, about 25 minutes of speech) |
| `APP_URL` | Link used in emails |

Ollama on the same machine: keep `OLLAMA_HOST=http://host.docker.internal:11434`. On another machine, use its address, and start Ollama there with `OLLAMA_HOST=0.0.0.0`.

### Compatible APIs

Set a **base URL** (in Settings, or `OPENAI_BASE_URL` / `ANTHROPIC_BASE_URL` in `.env`) and the model name that server uses:

| Server | Provider | Base URL |
|---|---|---|
| LM Studio on this computer | OpenAI | `http://host.docker.internal:1234/v1` |
| vLLM, llama.cpp server, LiteLLM | OpenAI | `http://<host>:<port>/v1` |
| OpenRouter | OpenAI | `https://openrouter.ai/api/v1` (needs `OPENAI_API_KEY`) |
| Anthropic-compatible gateway / proxy | Claude | the gateway's address |

Local servers usually need no API key; the app sends a placeholder when a base URL is set and no key is. "Test connection" on the Settings page checks the server and model before you save. Servers that can't list their models show as connected with a note that the model name wasn't checked.

## Downloads

- Pick resolution and codec separately (e.g. `720p` + `H.264 · MP4`). The server builds the yt-dlp format string from an allowlist; no raw format strings are accepted.
- The size next to the pickers starts as an estimate, then changes to the exact size of the streams yt-dlp will fetch.
- Playlists and channels: pick any subset. Videos download one after another, and the browser saves each one as it finishes. At most `MAX_CONCURRENT_DOWNLOADS` (default 2) downloads run at once on the server.
- Temporary files are deleted once your browser has them, and anything left after an hour is swept. Files kept on the server stay in `data/downloads/` until you delete them on the Download page.
- **Legal:** use this for content you're allowed to copy (your own videos, Creative Commons, etc.). Downloading may break YouTube's Terms of Service or copyright law where you live.

### Members-only, age-gated and private videos

By default the app talks to YouTube as a signed-out viewer. To use videos your account can watch, give it your YouTube cookies. **Settings → YouTube sign-in** offers two ways, with step-by-step instructions and live checks. Either way the cookies are used by downloads **and** by transcripts for summaries and emails.

**Read from Firefox automatically** (if you use Firefox on this computer). Nothing to export, and it doesn't go stale:

1. Sign in to YouTube in Firefox.
2. In `.env`, point `FIREFOX_PROFILES` at your Firefox `Profiles` folder, e.g. `/mnt/c/Users/<you>/AppData/Roaming/Mozilla/Firefox/Profiles` on WSL (find it via `about:support` → *Profile Folder*; use the folder above it). Run `docker compose up -d`. The folder is mounted read-only at `/firefox`.
3. On Settings → YouTube sign-in, choose **Read from Firefox automatically**.

The app copies the newest profile's `cookies.sqlite` (with its write-ahead log, so cookies from the last few minutes are included) into `data/.firefox-cookies/` whenever Firefox changes it, and yt-dlp reads that copy. Firefox can stay open. It uses whichever account is signed in to YouTube in Firefox. Chrome and Edge on Windows encrypt their cookies with a key only the browser can use, so they can't be read this way. If no Firefox profile is found, an uploaded cookies.txt is used instead.

**Running the app on a remote server?** It can't see your Firefox, so keep a local copy running with the Firefox source and, once it shows you as signed in, click **Download cookies.txt** under *Use this sign-in on another server*. Upload that file on the remote server's Settings → **Upload a cookies.txt**. The file holds only youtube.com cookies, not your other Google ones (Gmail, Drive). Treat it like a password, and download a fresh one when the remote copy goes stale.

**Upload a cookies.txt** (any browser):

1. In the browser where you're signed in (with the membership), install a cookie exporter such as "Get cookies.txt LOCALLY" or Cookie-Editor. Exporting from a private window keeps it apart from your everyday Google login.
2. On youtube.com, export the cookies in **Netscape / cookies.txt** format.
3. Upload or paste the file on **Settings → YouTube sign-in**. It's saved as `data/cookies.txt` (or wherever `COOKIES_FILE` points) with owner-only permissions and used from the next request on.

With an uploaded file, YouTube rotates cookies; if members-only videos start failing again, export a fresh one. Cookies are credentials: they are git-ignored, the API never returns them, and you can remove an uploaded file from Settings. Members-only live streams and premieres aren't supported.

## How the daily email works

1. At each scheduled time, every subscription's Videos tab is listed (newest first).
2. Videos not yet *seen* for that subscription are new. When you subscribe, the channel's existing videos are marked seen, so you only get uploads from then on.
3. The newest `MAX_AI_SUMMARIES_PER_CHANNEL` (default 3) new videos per channel get an AI summary; the rest are listed with their description. Each channel in the email says how many videos are new since the last check, e.g. "7 new videos since Thu, Oct 30, 9:00 AM. The newest 3 have AI summaries; the other 4 are listed with their descriptions."
4. One email per recipient. Videos are marked seen **only after the email is sent**, so an SMTP or YouTube failure is retried on the next run instead of losing videos. Upcoming premieres and live streams wait until they have aired.

If the AI provider is down, the email still goes out with a note in place of the summary.

## Commands

```bash
docker compose logs -f app      # logs (scheduler shows "next run" on start)
docker compose down             # stop
make test                       # backend lint + tests (inside a Docker build stage)
make lint-web                   # frontend lint + production build check
```

### Developing without rebuilding the image

```bash
# backend (Python 3.14 + uv)
cd backend && uv sync && DATA_DIR=../data uv run uvicorn app.main:app --reload --port 8000
# frontend (Node 26 LTS), proxies /api to :8000
cd frontend && npm ci && npm run dev
```

## API

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health` | liveness |
| GET | `/api/status` | schedule, next runs, email config |
| GET | `/api/settings` | editable values, where each comes from (`ui`/`env`/`default`), which secrets are set |
| PUT | `/api/settings` | `{field: value}` to save (applies live), `{field: null}` to go back to the environment value |
| POST | `/api/settings/test-provider` | `{provider, base_url?, host?, model?}`: check unsaved provider settings |
| GET | `/api/llm` | provider status (live check) |
| POST | `/api/analyze` | SSE stream; body `{url, provider?, limit?}` |
| GET/DELETE | `/api/history[/{id}]` | saved summaries |
| GET | `/api/subscriptions?email=` | subscriptions for one address |
| POST | `/api/subscriptions` | `{channel_url, email, channel_name?}` |
| DELETE | `/api/subscriptions/{id}` | unsubscribe |
| POST | `/api/check` | start a check now (409 if one is running) |
| GET | `/api/runs` | recent checks with logs |
| POST | `/api/email/test` | `{to}`: send a sample digest |
| GET | `/api/download/info?url=` | formats, sizes and subtitles for a video; entry list for a playlist/channel |
| GET | `/api/download/size?url=&kind=&height=&codec=&mode=` | exact size of the selection |
| POST | `/api/download` | `{url, sel: {kind, height, codec, mode}, subs?, title?, keep?}`: start a download job |
| GET | `/api/download/jobs/{id}` | job progress and, when done, its file links |
| GET | `/api/download/jobs/{id}/files/{i}` | the file as an attachment (temp files are deleted after sending) |
| GET/DELETE | `/api/files[/{name}]` | downloads kept on the server |
| GET/PUT/DELETE | `/api/cookies` | Sign-in status for both sources (Firefox, upload) and which is in use / `{content}` to save a cookies.txt / remove it (cookie values are never returned) |
| POST | `/api/cookies/export` | Firefox's youtube.com cookies as a `cookies.txt` download, for uploading on another server (the only route that returns cookie values) |

There is no login. The app is meant for a home or office network, so don't expose the port to the internet.

## Troubleshooting

- **No email:** on Settings, use "Send test email" under Sending email. The error text says what failed (e.g. Gmail needs an App Password). Then open the latest entry under Activity to see its log.
- **Ollama unreachable:** check `OLLAMA_HOST`, that the model is pulled (`ollama pull llama3.2`), and that Ollama listens on the network.
- **"Sign in to confirm" / members-only errors:** add your cookies under Settings → YouTube sign-in. YouTube also sometimes blocks datacenter and VPN IP addresses.
- **YouTube errors:** yt-dlp changes often. Rebuild to pick up a newer pinned version: bump `yt-dlp` in `backend/pyproject.toml`, run `uv lock`, then `docker compose up --build -d`.
