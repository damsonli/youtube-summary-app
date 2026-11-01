"""FastAPI app: JSON/SSE API under /api, the built SPA everywhere else, scheduler in-process."""

import json
import logging
import re
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import APIRouter, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from . import runtime
from .config import EDITABLE, get_settings
from .db import Database
from .llm import LLMError, NotConfigured, Registry, build_provider, check_status
from .mailer import EmailError, Mailer
from .notifier import AlreadyRunning, Notifier
from .youtube import YouTubeClient, YouTubeError, is_channel_url, normalize_channel_url

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("app")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@asynccontextmanager
async def lifespan(app: FastAPI):
    env = get_settings()
    db = Database(env.db_path)
    db.import_legacy_json(env.data_dir / "subscriptions.json")
    db.fail_stale_runs()
    s = runtime.load(db)  # environment + values saved from the Settings page
    yt = YouTubeClient(s.transcript_max_chars)
    notifier = Notifier(s, db, yt, Registry(s), Mailer(s))
    app.state.__dict__.update(db=db, yt=yt, notifier=notifier, scheduler=AsyncIOScheduler())
    runtime.apply(app.state, s)
    log.info("LLM default: %s; email %s", s.llm_service, "configured" if s.email_configured else "NOT configured")
    yield
    if app.state.scheduler.running:
        app.state.scheduler.shutdown(wait=False)


app = FastAPI(title="YouTube Digest", version="2.0.0", lifespan=lifespan)
api = APIRouter(prefix="/api")


# ---- models ----------------------------------------------------------------
class AnalyzeRequest(BaseModel):
    url: str = Field(min_length=5)
    provider: str | None = None
    limit: int = Field(default=5, ge=1, le=25)


class SubscriptionCreate(BaseModel):
    channel_url: str
    email: str
    channel_name: str | None = None

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        v = v.strip()
        if not EMAIL_RE.match(v):
            raise ValueError("Enter a valid email address")
        return v


class TestEmail(BaseModel):
    to: str

    @field_validator("to")
    @classmethod
    def _email(cls, v: str) -> str:
        return SubscriptionCreate._email(v)


# ---- status ----------------------------------------------------------------
@api.get("/health")
async def health():
    return {"ok": True}


@api.get("/status")
async def status(request: Request):
    st = request.app.state
    s = st.settings
    jobs = st.scheduler.get_jobs() if st.scheduler.running else []
    return {
        "timezone": s.timezone,
        "schedule_times": [f"{t:%H:%M}" for t in s.parsed_schedule_times],
        "next_runs": sorted(j.next_run_time.isoformat() for j in jobs if j.next_run_time),
        "email_configured": s.email_configured,
        "email_from": s.sender,
        "smtp": f"{s.smtp_server}:{s.smtp_port} ({s.smtp_security})",
        "check_running": st.notifier.running,
        "default_provider": s.llm_service,
        "max_ai_summaries_per_channel": s.max_ai_summaries_per_channel,
    }


# ---- settings (Settings page) ----------------------------------------------
def _settings_error(e: runtime.SettingsError) -> HTTPException:
    return HTTPException(422, {"message": "Some values are not valid", "fields": e.fields})


@api.get("/settings")
async def get_app_settings(request: Request):
    st = request.app.state
    return runtime.describe(st.settings, st.db.get_overrides())


@api.put("/settings")
async def save_app_settings(changes: dict[str, Any], request: Request):
    """Save values from the Settings page. A null value resets that field to the environment value."""
    st = request.app.state
    bad = sorted(set(changes) - EDITABLE)
    if bad:
        raise HTTPException(400, f"These settings can't be changed here: {', '.join(bad)}")
    merged = {**st.db.get_overrides(), **changes}
    merged = {k: v for k, v in merged.items() if v is not None}
    try:
        new = runtime.build(merged)
    except runtime.SettingsError as e:
        raise _settings_error(e)
    st.db.set_overrides(changes)
    runtime.apply(st, new)
    log.info("Settings updated: %s", ", ".join(sorted(changes)))
    return runtime.describe(new, st.db.get_overrides())


class ProviderTest(BaseModel):
    provider: str
    model: str | None = None
    base_url: str | None = None  # openai / claude
    host: str | None = None      # ollama


_TEST_FIELDS = {
    "ollama": {"host": "ollama_host", "model": "ollama_model"},
    "openai": {"base_url": "openai_base_url", "model": "openai_model"},
    "claude": {"base_url": "anthropic_base_url", "model": "claude_model"},
}


@api.post("/settings/test-provider")
async def test_provider(body: ProviderTest, request: Request):
    """Check a provider with the (possibly unsaved) values from the form."""
    st = request.app.state
    fields = _TEST_FIELDS.get(body.provider)
    if fields is None:
        raise HTTPException(400, f"Unknown provider {body.provider!r}")
    values = {**st.db.get_overrides()}
    for attr, field in fields.items():
        if attr in body.model_fields_set:
            values[field] = getattr(body, attr) or ""
    try:
        s = runtime.build(values)
    except runtime.SettingsError as e:
        raise _settings_error(e)
    return await check_status(build_provider(body.provider, s))


@api.get("/llm")
async def llm_status(request: Request):
    return {"default": request.app.state.llm.default, "providers": await request.app.state.llm.status()}


# ---- analysis (SSE) --------------------------------------------------------
def _sse(obj: dict) -> str:
    return f"data: {json.dumps(obj)}\n\n"


@api.post("/analyze")
async def analyze(req: AnalyzeRequest, request: Request):
    st = request.app.state
    try:
        provider = st.llm.get(req.provider)
    except NotConfigured as e:
        raise HTTPException(400, str(e))

    async def gen():
        try:
            if is_channel_url(req.url):
                yield _sse({"type": "progress", "message": "Reading the channel", "step": 0, "total": 1})
                listing = await st.yt.list_channel(req.url, limit=req.limit)
                urls = [e["url"] for e in listing["entries"]]
                if not urls:
                    yield _sse({"type": "error", "message": "No videos found on that channel"})
                    return
            else:
                urls = [req.url]
            total = len(urls) * 2
            for i, url in enumerate(urls):
                yield _sse({"type": "progress", "step": i * 2, "total": total,
                            "message": f"Fetching video {i + 1} of {len(urls)}"})
                try:
                    v = await st.yt.get_video(url, st.settings.tz)
                    yield _sse({"type": "progress", "step": i * 2 + 1, "total": total,
                                "message": f"Summarizing “{v['title']}” with {provider.name}"})
                    v["summary"] = await provider.summarize(v)
                except (YouTubeError, LLMError) as e:
                    yield _sse({"type": "item_error", "url": url, "message": str(e)})
                    continue
                v.update(provider=provider.name, model=provider.model)
                v["id"] = st.db.save_analysis(v)
                v.pop("transcript", None)
                yield _sse({"type": "result", "item": v})
            yield _sse({"type": "done", "step": total, "total": total})
        except (YouTubeError, LLMError) as e:
            yield _sse({"type": "error", "message": str(e)})
        except Exception as e:
            log.exception("analyze failed")
            yield _sse({"type": "error", "message": f"Unexpected error: {e}"})

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@api.get("/history")
async def history(request: Request, limit: int = Query(30, ge=1, le=200), offset: int = Query(0, ge=0)):
    return request.app.state.db.list_analyses(limit, offset)


@api.delete("/history/{analysis_id}")
async def delete_history(analysis_id: int, request: Request):
    if not request.app.state.db.delete_analysis(analysis_id):
        raise HTTPException(404, "Not found")
    return {"ok": True}


# ---- subscriptions ---------------------------------------------------------
@api.get("/subscriptions")
async def list_subscriptions(request: Request, email: str = Query(min_length=3)):
    return request.app.state.db.list_subscriptions(email)


@api.post("/subscriptions", status_code=201)
async def create_subscription(body: SubscriptionCreate, request: Request):
    st = request.app.state
    if not is_channel_url(body.channel_url):
        raise HTTPException(400, "Use a channel URL such as https://www.youtube.com/@name")
    url = normalize_channel_url(body.channel_url)
    if st.db.subscription_exists(body.email, url):
        raise HTTPException(409, "You are already subscribed to this channel")
    try:
        listing = await st.yt.list_channel(url, limit=st.settings.channel_scan_limit)
    except YouTubeError as e:
        raise HTTPException(400, f"Could not read that channel: {e}")
    # Existing videos count as already seen, so the first email only has genuinely new ones.
    return st.db.add_subscription(
        channel_url=url, channel_name=(body.channel_name or "").strip() or listing["channel_name"] or url,
        email=body.email, channel_id=listing["channel_id"],
        seen_video_ids=[e["id"] for e in listing["entries"]])


@api.delete("/subscriptions/{sub_id}")
async def delete_subscription(sub_id: str, request: Request):
    if not request.app.state.db.delete_subscription(sub_id):
        raise HTTPException(404, "Subscription not found")
    return {"ok": True}


# ---- checks & email --------------------------------------------------------
@api.post("/check", status_code=202)
async def run_check(request: Request):
    try:
        return {"run_id": request.app.state.notifier.start("manual")}
    except AlreadyRunning as e:
        raise HTTPException(409, str(e))


@api.get("/runs")
async def runs(request: Request, limit: int = Query(15, ge=1, le=100)):
    return request.app.state.db.list_runs(limit)


@api.post("/email/test")
async def test_email(body: TestEmail, request: Request):
    try:
        await request.app.state.notifier.send_test_email(body.to)
    except EmailError as e:
        raise HTTPException(502, str(e))
    return {"ok": True}


app.include_router(api)


# ---- SPA -------------------------------------------------------------------
_static = Path(get_settings().static_dir)
if (_static / "index.html").exists():
    app.mount("/assets", StaticFiles(directory=_static / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str):
        if path.startswith("api/"):
            raise HTTPException(404)
        f = (_static / path).resolve()
        if path and f.is_file() and f.is_relative_to(_static.resolve()):
            return FileResponse(f)
        return FileResponse(_static / "index.html")
