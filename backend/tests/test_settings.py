import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi.testclient import TestClient

from app import runtime
from app.config import Settings, get_settings
from app.db import Database
from app.llm import check_status
from app.llm.providers import ClaudeProvider, OpenAIProvider
from app.mailer import Mailer, channel_note


# ---- precedence & validation -------------------------------------------------
def test_ui_value_overrides_environment(monkeypatch):
    monkeypatch.setenv("OPENAI_MODEL", "from-env")
    assert runtime.build({}).openai_model == "from-env"
    assert runtime.build({"openai_model": "from-ui"}).openai_model == "from-ui"


def test_sources(monkeypatch):
    monkeypatch.setenv("SMTP_SERVER", "mail.example.com")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-secret")
    d = runtime.describe(runtime.build({"openai_model": "x"}), {"openai_model": "x"})
    assert d["source"]["openai_model"] == "ui"
    assert d["source"]["smtp_server"] == "env"
    assert d["source"]["claude_model"] == "default"
    assert d["secrets_set"]["openai_api_key"] is True
    assert "sk-secret" not in json.dumps(d)


@pytest.mark.parametrize("bad,field", [
    ({"smtp_port": 0}, "smtp_port"),
    ({"schedule_times": "25:00"}, "schedule_times"),
    ({"timezone": "Mars/Base"}, "timezone"),
    ({"openai_base_url": "localhost:1234"}, "openai_base_url"),
    ({"max_ai_summaries_per_channel": 11}, "max_ai_summaries_per_channel"),
])
def test_invalid_values_name_the_field(bad, field):
    with pytest.raises(runtime.SettingsError) as e:
        runtime.build(bad)
    assert field in e.value.fields


def test_normalization():
    s = runtime.build({"schedule_times": "18:00, 7:30", "openai_base_url": "http://h:1234/v1/", "from_email": " "})
    assert s.schedule_times == "07:30,18:00"
    assert s.openai_base_url == "http://h:1234/v1"
    assert s.from_email is None


def test_overrides_roundtrip_and_reset(tmp_path):
    db = Database(tmp_path / "app.db")
    db.set_overrides({"openai_model": "m", "max_ai_summaries_per_channel": 0})
    assert db.get_overrides() == {"openai_model": "m", "max_ai_summaries_per_channel": 0}
    db.set_overrides({"openai_model": None})
    assert db.get_overrides() == {"max_ai_summaries_per_channel": 0}


def test_invalid_saved_value_is_dropped_at_startup(tmp_path):
    db = Database(tmp_path / "app.db")
    db.set_overrides({"smtp_port": 0, "openai_model": "ok"})
    s = runtime.load(db)
    assert s.smtp_port == 587 and s.openai_model == "ok"
    assert db.get_overrides() == {"openai_model": "ok"}


# ---- live rescheduling -------------------------------------------------------
async def test_schedule_is_rebuilt():
    class N:
        async def scheduled(self):
            pass

    sched = AsyncIOScheduler()
    runtime.schedule(sched, N(), Settings(schedule_times="07:30,18:00", timezone="Asia/Tokyo"))
    assert sorted(j.id for j in sched.get_jobs()) == ["check-0730", "check-1800"]
    job = sched.get_jobs()[0]
    assert str(job.next_run_time.tzinfo) == "Asia/Tokyo"
    runtime.schedule(sched, N(), Settings(schedule_times="06:00"))
    assert [j.id for j in sched.get_jobs()] == ["check-0600"]
    runtime.schedule(sched, N(), Settings(scheduler_enabled=False))
    assert sched.get_jobs() == []
    sched.shutdown(wait=False)


# ---- compatible servers ------------------------------------------------------
class FakeServer:
    """Minimal OpenAI/Anthropic-compatible server: GET /models/{id}, GET /models."""

    def __init__(self):
        self.retrieve_status, self.list_status, self.models = 200, 200, ["local-model"]
        fake = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                path = self.path.split("?")[0].rstrip("/")
                if path.endswith("/models"):
                    status = fake.list_status
                    body = {"object": "list", "data": [
                        {"id": m, "object": "model", "type": "model", "created": 0, "owned_by": "x",
                         "created_at": "2026-01-01T00:00:00Z", "display_name": m} for m in fake.models],
                        "has_more": False, "first_id": None, "last_id": None}
                else:
                    status = fake.retrieve_status
                    mid = path.rsplit("/", 1)[1]
                    body = {"id": mid, "object": "model", "type": "model", "created": 0, "owned_by": "x",
                            "created_at": "2026-01-01T00:00:00Z", "display_name": mid}
                if status != 200:
                    body = {"error": {"type": "not_found_error", "message": "nope"}}
                data = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        self.srv = HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.srv.server_port}"


@pytest.fixture
def fake():
    f = FakeServer()
    yield f
    f.srv.shutdown()


@pytest.mark.parametrize("make", [
    lambda url, model: OpenAIProvider(Settings(openai_base_url=url + "/v1", openai_model=model)),
    lambda url, model: ClaudeProvider(Settings(anthropic_base_url=url, claude_model=model)),
])
async def test_compatible_server_checks(fake, make):
    p = make(fake.url, "local-model")
    p._client = p._client.with_options(max_retries=0)
    assert p.configured  # no API key needed when a base URL is set
    assert (await check_status(p)) == {"status": "ok", "detail": None}

    fake.retrieve_status = 404  # server without GET /models/{id}: fall back to the list
    assert (await check_status(p))["status"] == "ok"

    fake.models = ["other-model"]
    r = await check_status(p)
    assert r["status"] == "error" and "other-model" in r["detail"]

    fake.list_status = 404  # cannot list either: connected, model unverified
    r = await check_status(p)
    assert r["status"] == "ok" and "can't list models" in r["detail"]


# ---- email counts ------------------------------------------------------------
def test_channel_notes():
    base = {"videos": [], "since": "Thu, Oct 30, 9:00 AM"}
    assert channel_note({**base, "new_count": 7, "ai_limit": 3}) == (
        "7 new videos since Thu, Oct 30, 9:00 AM. The newest 3 have AI summaries (your limit per channel);"
        " the other 4 are listed with their descriptions.")
    assert channel_note({**base, "new_count": 2, "ai_limit": 3}) == "2 new videos since Thu, Oct 30, 9:00 AM."
    assert "turned off" in channel_note({**base, "new_count": 1, "ai_limit": 0})
    assert channel_note({"videos": [], "new_count": 1, "ai_limit": 3, "since": None}) == "1 new video."


def test_digest_headline_counts():
    channels = [{"name": n, "url": "u", "videos": [], "new_count": k, "ai_limit": 3, "since": None}
                for n, k in (("A", 5), ("B", 2))]
    subject, text, html = Mailer(Settings()).render_digest(channels, date_label="today")
    assert subject == "7 new videos from A, B"
    assert "7 new videos from 2 channels since your last digest" in text and html
    assert "The newest 3 have AI summaries" in html


# ---- API ---------------------------------------------------------------------
@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("SCHEDULER_ENABLED", "false")
    get_settings.cache_clear()
    from app.main import app
    with TestClient(app) as c:
        yield c
    get_settings.cache_clear()


def test_settings_api(client):
    r = client.put("/api/settings", json={"max_ai_summaries_per_channel": 1, "schedule_times": "7:00"})
    assert r.status_code == 200
    body = r.json()
    assert body["values"]["schedule_times"] == "07:00" and body["source"]["max_ai_summaries_per_channel"] == "ui"
    assert client.get("/api/status").json()["max_ai_summaries_per_channel"] == 1

    r = client.put("/api/settings", json={"smtp_port": 99999})
    assert r.status_code == 422 and "smtp_port" in r.json()["detail"]["fields"]

    assert client.put("/api/settings", json={"openai_api_key": "x"}).status_code == 400

    r = client.put("/api/settings", json={"max_ai_summaries_per_channel": None})
    assert r.json()["values"]["max_ai_summaries_per_channel"] == 3
