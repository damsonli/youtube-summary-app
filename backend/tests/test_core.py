import json
from datetime import UTC, datetime, time, timedelta

import pytest

from app.config import Settings, parse_times
from app.db import Database
from app.llm import LLMError
from app.mailer import EmailError, Mailer, markdown_to_safe_html
from app.notifier import Notifier
from app.youtube import is_channel_url, normalize_channel_url, parse_captions, video_id_from_url


# ---- pure helpers ------------------------------------------------------------
def test_parse_times():
    assert parse_times("9:00, 18:30,09:00") == [time(9), time(18, 30)]
    for bad in ("9", "25:00", "9:5", "", "ab:cd"):
        with pytest.raises(ValueError):
            parse_times(bad)


def test_schedule_time_alias(monkeypatch):
    monkeypatch.setenv("SCHEDULE_TIME", "7:15")
    assert Settings().parsed_schedule_times == [time(7, 15)]


@pytest.mark.parametrize("url,expected", [
    ("https://youtube.com/@veritasium", "https://www.youtube.com/@veritasium/videos"),
    ("www.youtube.com/@veritasium/", "https://www.youtube.com/@veritasium/videos"),
    ("https://www.youtube.com/@veritasium/videos", "https://www.youtube.com/@veritasium/videos"),
    ("https://www.youtube.com/channel/UC123", "https://www.youtube.com/channel/UC123/videos"),
])
def test_normalize_channel_url(url, expected):
    assert normalize_channel_url(url) == expected


def test_url_kinds():
    assert is_channel_url("https://www.youtube.com/@x")
    assert not is_channel_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    assert video_id_from_url("https://youtu.be/dQw4w9WgXcQ?t=3") == "dQw4w9WgXcQ"
    assert video_id_from_url("https://www.youtube.com/shorts/dQw4w9WgXcQ") == "dQw4w9WgXcQ"


def test_parse_vtt_dedupes_rolling_lines():
    vtt = "WEBVTT\n\n00:00.000 --> 00:01.000\nhello <c>world</c>\n\n00:01.000 --> 00:02.000\nhello world\nnext"
    assert parse_captions(vtt, "vtt") == "hello world next"


def test_markdown_is_escaped():
    out = str(markdown_to_safe_html("**bold** <script>alert(1)</script>"))
    assert "<strong>bold</strong>" in out and "<script>" not in out


# ---- db ----------------------------------------------------------------------
def test_legacy_import(tmp_path):
    legacy = tmp_path / "subscriptions.json"
    legacy.write_text(json.dumps([
        {"id": "a", "channel_url": "https://youtube.com/@x", "channel_name": "X", "user_email": "me@ex.com",
         "created_at": "2025-01-01T00:00:00+00:00", "last_checked": "2025-09-01T09:00:00+00:00", "active": True},
        {"id": "b", "channel_url": "https://youtube.com/@y", "channel_name": "Y", "user_email": "me@ex.com",
         "created_at": "2025-01-01T00:00:00+00:00", "active": False},
    ]))
    db = Database(tmp_path / "app.db")
    assert db.import_legacy_json(legacy) == 1
    assert not legacy.exists() and (tmp_path / "subscriptions.json.imported").exists()
    assert [s["channel_name"] for s in db.list_subscriptions("ME@ex.com")] == ["X"]


# ---- notifier ----------------------------------------------------------------
class FakeYT:
    def __init__(self):
        self.entries: list[str] = []          # newest first
        self.published: dict[str, datetime] = {}
        self.fail = False

    async def list_channel(self, url, limit=30):
        if self.fail:
            raise RuntimeError("youtube down")
        return {"channel_id": "UC1", "channel_name": "Chan", "url": url,
                "entries": [{"id": i, "title": i, "url": f"https://www.youtube.com/watch?v={i}"}
                            for i in self.entries[:limit]]}

    async def get_video(self, url, tz=UTC, with_transcript=True):
        vid = url.rsplit("=", 1)[1]
        pub = self.published.get(vid, datetime.now(UTC))
        return {"video_id": vid, "title": f"Video {vid}", "url": url, "channel": "Chan", "duration": "1:00",
                "published_at": pub.isoformat(), "published_date": pub.date().isoformat(), "thumbnail": "",
                "description": "d", "live_status": "not_live", "transcript": "", "has_transcript": False}


class FakeProvider:
    name, model, configured = "fake", "fake-1", True

    def __init__(self, fail=False):
        self.fail = fail

    async def summarize(self, v):
        if self.fail:
            raise LLMError("llm down")
        return f"summary of {v['title']}"


class FakeRegistry:
    def __init__(self, p):
        self.p = p

    def get(self, name=None):
        return self.p


class FakeMailer(Mailer):
    def __init__(self, s):
        super().__init__(s)
        self.sent: list[tuple[str, str, str]] = []
        self.fail = False

    async def send(self, to, subject, text, html=None):
        if self.fail:
            raise EmailError("smtp down")
        self.sent.append((to, subject, html))


@pytest.fixture
def env(tmp_path):
    s = Settings(data_dir=tmp_path, scheduler_enabled=False)
    db = Database(s.db_path)
    yt, mailer = FakeYT(), FakeMailer(s)
    n = Notifier(s, db, yt, FakeRegistry(FakeProvider()), mailer)
    return s, db, yt, mailer, n


async def run(n, db):
    rid = db.start_run("test")
    await n.run(rid)
    return db.list_runs(1)[0]


async def test_only_unseen_videos_are_emailed_once(env):
    s, db, yt, mailer, n = env
    yt.entries = ["old2", "old1"]
    sub = db.add_subscription(channel_url="u", channel_name="Chan", email="a@b.co", seen_video_ids=["old2", "old1"])

    assert (await run(n, db))["emails_sent"] == 0      # nothing new
    yt.entries = ["new2", "new1", "old2", "old1"]       # published late in the day: old bug missed these
    r = await run(n, db)
    assert r["status"] == "ok" and r["videos_found"] == 2 and len(mailer.sent) == 1
    assert "summary of Video new2" in mailer.sent[0][2]
    assert db.seen_ids(sub["id"]) >= {"new1", "new2"}

    assert (await run(n, db))["emails_sent"] == 0      # no duplicates
    assert len(mailer.sent) == 1


async def test_failed_email_retries_next_run(env):
    s, db, yt, mailer, n = env
    sub = db.add_subscription(channel_url="u", channel_name="Chan", email="a@b.co", seen_video_ids=["old"])
    yt.entries = ["new", "old"]
    mailer.fail = True
    r = await run(n, db)
    assert r["status"] == "error" and "new" not in db.seen_ids(sub["id"])
    assert db.get_subscription(sub["id"])["last_error"].startswith("Email failed")
    mailer.fail = False
    assert (await run(n, db))["emails_sent"] == 1


async def test_youtube_failure_does_not_advance(env):
    s, db, yt, mailer, n = env
    sub = db.add_subscription(channel_url="u", channel_name="Chan", email="a@b.co", seen_video_ids=["old"])
    yt.fail = True
    r = await run(n, db)
    assert r["status"] == "error" and db.get_subscription(sub["id"])["last_checked"] is None


async def test_llm_failure_still_sends(env):
    s, db, yt, mailer, n = env
    n.llm = FakeRegistry(FakeProvider(fail=True))
    db.add_subscription(channel_url="u", channel_name="Chan", email="a@b.co", seen_video_ids=["old"])
    yt.entries = ["new", "old"]
    assert (await run(n, db))["emails_sent"] == 1
    assert "No AI summary: llm down" in mailer.sent[0][2]


async def test_ai_summary_cap(env):
    s, db, yt, mailer, n = env
    db.add_subscription(channel_url="u", channel_name="Chan", email="a@b.co", seen_video_ids=["old"])
    yt.entries = ["n5", "n4", "n3", "n2", "n1", "old"]
    await run(n, db)
    assert mailer.sent[0][2].count("summary of Video") == s.max_ai_summaries_per_channel


async def test_legacy_baseline_uses_publish_time(env):
    s, db, yt, mailer, n = env
    checked = datetime.now(UTC) - timedelta(hours=10)
    sub = db.add_subscription(channel_url="u", channel_name="Chan", email="a@b.co")
    with db._conn() as c:
        c.execute("UPDATE subscriptions SET last_checked = ? WHERE id = ?", (checked.isoformat(), sub["id"]))
    yt.entries = ["fresh", "stale", "older"]
    yt.published = {"fresh": checked + timedelta(hours=5), "stale": checked - timedelta(hours=1),
                    "older": checked - timedelta(days=3)}
    r = await run(n, db)
    assert r["videos_found"] == 1 and "Video fresh" in mailer.sent[0][2]
    assert db.seen_ids(sub["id"]) == {"fresh", "stale", "older"}
