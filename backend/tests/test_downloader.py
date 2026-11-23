import asyncio
import os
import sqlite3
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app import cookies, downloader
from app.config import Settings, get_settings
from app.cookies import cookie_opts
from app.download_api import looks_like_cookies_txt
from app.downloader import (
    DownloadError,
    DownloadManager,
    DownloadRequest,
    Selection,
    analyze_formats,
    build_selector,
    is_youtube_url,
    sanitize_filename,
    selected_size,
)


# ---- selection & format strings ----------------------------------------------
@pytest.mark.parametrize("sel,ff,expected", [
    ({"kind": "video"}, True, "bv*+ba/b"),
    ({"kind": "video", "height": 720}, True, "bv*[height<=720]+ba/bv*[height<=720]+ba/b[height<=720]"),
    ({"kind": "video", "height": 1080, "codec": "avc"}, True,
     "bv*[vcodec^=avc][height<=1080]+ba[acodec^=mp4a]/bv*[vcodec^=avc][height<=1080]+ba/b[height<=1080]"),
    ({"kind": "video", "codec": "avc"}, True, "bv*[vcodec^=avc]+ba[acodec^=mp4a]/bv*[vcodec^=avc]+ba/b"),
    ({"kind": "video", "height": 480, "codec": "vp9"}, False, "b[height<=480][vcodec^=vp]"),
    ({"kind": "audio", "mode": "m4a"}, True, "ba[acodec^=mp4a]/ba/b"),
    ({"kind": "audio", "mode": "opus"}, True, "ba[acodec^=opus]/ba/b"),
    ({"kind": "audio"}, False, "ba/b"),
])
def test_build_selector(sel, ff, expected):
    assert build_selector(Selection(**sel), ff)[0] == expected


def test_mp3_and_subs_options():
    fmt, extra = build_selector(Selection(kind="audio", mode="mp3"), True)
    assert fmt == "ba/b" and extra["postprocessors"][0]["preferredcodec"] == "mp3"
    with pytest.raises(DownloadError):
        build_selector(Selection(kind="audio", mode="mp3"), False)
    assert build_selector(Selection(kind="subs"), True)[1] == {"skip_download": True}


@pytest.mark.parametrize("bad", [
    {"kind": "exe"}, {"codec": "h265"}, {"height": 50}, {"height": 99999}, {"height": "720p"}, {"mode": "flac"},
])
def test_selection_rejects_unknown_values(bad):
    with pytest.raises(ValidationError):
        Selection(**bad)


def test_download_request_validation():
    with pytest.raises(ValidationError):
        DownloadRequest(url="https://youtu.be/x", sel={}, subs="en; rm -rf /")
    r = DownloadRequest(url="https://youtu.be/x", sel={}, subs="zh-Hans", title="t" * 500)
    assert r.subs == "zh-Hans" and len(r.title) == 180


def test_urls_and_filenames():
    assert is_youtube_url("https://www.youtube.com/watch?v=abc")
    assert is_youtube_url("https://youtu.be/abc") and is_youtube_url("https://music.youtube.com/watch?v=a")
    assert not is_youtube_url("https://evil.com/youtube.com") and not is_youtube_url("file:///etc/passwd")
    assert not is_youtube_url("https://notyoutube.com/watch")
    assert sanitize_filename('a/b:c*?"<>|d') == "a b c d"
    assert sanitize_filename("...") == "video"


# ---- format analysis ---------------------------------------------------------
FORMATS = {"duration": 100, "formats": [
    {"format_id": "140", "vcodec": "none", "acodec": "mp4a.40.2", "filesize": 1_000},
    {"format_id": "251", "vcodec": "none", "acodec": "opus", "filesize": 1_200},
    {"format_id": "137", "vcodec": "avc1.640028", "acodec": "none", "height": 1080, "filesize": 50_000},
    {"format_id": "248", "vcodec": "vp9", "acodec": "none", "height": 1080, "filesize": 40_000},
    {"format_id": "18", "vcodec": "avc1.42001E", "acodec": "mp4a.40.2", "height": 360, "tbr": 8},
]}


def test_analyze_formats():
    a = analyze_formats(FORMATS, True)
    assert [h["h"] for h in a["heights"]] == [1080, 360]
    top = a["heights"][0]
    assert top["codecs"] == ["any", "vp9", "avc"] and top["sizes"]["any"] == 40_000
    assert a["audio"] == {"best": 1_200, "m4a": 1_000, "opus": 1_200}
    assert a["best_total"] == 41_200

    no_ff = analyze_formats(FORMATS, False)  # only the progressive 360p format remains
    assert [h["h"] for h in no_ff["heights"]] == [360]
    assert no_ff["heights"][0]["sizes"]["avc"] == 8 * 1024 // 8 * 100


def test_selected_size():
    assert selected_size({"requested_formats": [{"filesize": 10}, {"filesize_approx": 5}]}) == 15
    assert selected_size({"filesize": 7}) == 7


# ---- jobs --------------------------------------------------------------------
class FakeYDL:
    """Writes the files a real download would leave in the temp folder."""

    outputs = ("mp4", "en.srt")

    def __init__(self, opts):
        self.opts = opts

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def extract_info(self, url, download=False):
        tmpl = self.opts["outtmpl"]["default"]
        for ext in self.outputs:
            Path(tmpl.replace("%(ext)s", ext)).write_text("x")
        for hook in self.opts["progress_hooks"]:
            hook({"status": "downloading", "downloaded_bytes": 5, "total_bytes": 10})
        return {"id": "dQw4w9WgXcQ", "title": "Never/Gonna"}


@pytest.fixture
def dm(tmp_path, monkeypatch):
    monkeypatch.setattr(downloader.yt_dlp, "YoutubeDL", FakeYDL)
    s = Settings(data_dir=tmp_path)
    return DownloadManager(lambda: s)


async def _finish(dm, **kw):
    job = dm.start(DownloadRequest(url="https://youtu.be/dQw4w9WgXcQ", sel={"kind": "video"}, **kw))
    for _ in range(200):
        if job.status in ("done", "error"):
            break
        await asyncio.sleep(0.01)
    return job


async def test_job_names_files_after_title(dm):
    job = await _finish(dm, subs="en")
    assert job.status == "done", job.error
    assert [f["name"] for f in job.files] == ["Never Gonna.mp4", "Never Gonna.en.srt"]
    assert all(Path(f["path"]).parent == dm.tmp_dir for f in job.files)
    assert job.public()["files"][0]["url"] == f"/api/download/jobs/{job.id}/files/0"
    assert dm.saved() == []


async def test_kept_job_moves_files(dm):
    job = await _finish(dm, keep=True)
    assert job.status == "done"
    assert sorted(f["name"] for f in dm.saved()) == ["Never Gonna [dQw4w9WgXcQ].en.srt",
                                                    "Never Gonna [dQw4w9WgXcQ].mp4"]
    assert not list(dm.tmp_dir.iterdir())


async def test_subs_without_language_is_rejected(dm):
    with pytest.raises(DownloadError):
        dm.start(DownloadRequest(url="https://youtu.be/x", sel={"kind": "subs"}))


def test_sweep_removes_only_old_temp_files(dm):
    dm.tmp_dir.mkdir(parents=True)
    old, new = dm.tmp_dir / "old.mp4", dm.tmp_dir / "new.mp4"
    old.write_text("x")
    new.write_text("x")
    kept = dm.s.downloads_dir / "kept.mp4"
    kept.write_text("x")
    past = time.time() - 7200
    os.utime(old, (past, past))
    os.utime(kept, (past, past))
    assert dm.sweep() == 1
    assert not old.exists() and new.exists() and kept.exists()


def test_saved_path_is_confined(dm):
    dm.s.downloads_dir.mkdir(parents=True)
    (dm.s.downloads_dir / "ok.mp4").write_text("x")
    (dm.s.data_dir / "app.db").write_text("x")
    assert dm.saved_path("ok.mp4")
    assert dm.saved_path("../app.db") is None
    assert dm.saved_path(".tmp") is None


# ---- API ---------------------------------------------------------------------
COOKIES = "# Netscape HTTP Cookie File\n.youtube.com\tTRUE\t/\tTRUE\t0\tSID\tsecret-value\n"


def test_cookie_format_check():
    assert looks_like_cookies_txt(COOKIES)
    assert looks_like_cookies_txt("#HttpOnly_.youtube.com\tTRUE\t/\tTRUE\t0\tA\tb")
    assert not looks_like_cookies_txt("hello world")
    assert not looks_like_cookies_txt(".example.com\tTRUE\t/\tTRUE\t0\tA\tb")


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("SCHEDULER_ENABLED", "false")
    get_settings.cache_clear()
    from app.main import app
    with TestClient(app) as c:
        yield c
    get_settings.cache_clear()


def test_cookies_api(client, tmp_path):
    assert client.get("/api/cookies").json()["upload"]["present"] is False
    assert client.put("/api/cookies", json={"content": "nope"}).status_code == 400
    r = client.put("/api/cookies", json={"content": COOKIES})
    assert r.status_code == 200 and r.json()["upload"]["present"] is True and r.json()["active"] == "upload"
    assert "secret-value" not in r.text and "secret-value" not in client.get("/api/cookies").text
    assert (tmp_path / "cookies.txt").stat().st_mode & 0o777 == 0o600
    assert client.get("/api/status").json()["cookies"] == "upload"
    r = client.delete("/api/cookies").json()
    assert r["upload"]["present"] is False and r["active"] is None


# ---- Firefox cookies -----------------------------------------------------------
def _firefox_profile(root: Path) -> sqlite3.Connection:
    """A Firefox-like profile whose newest cookie is still only in the WAL (connection kept open)."""
    prof = root / "Profiles" / "abc.default-release"
    prof.mkdir(parents=True)
    con = sqlite3.connect(prof / "cookies.sqlite")
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA wal_autocheckpoint=0")
    con.execute("CREATE TABLE moz_cookies (id INTEGER PRIMARY KEY, originAttributes TEXT DEFAULT '', name TEXT,"
                " value TEXT, host TEXT, path TEXT, expiry INTEGER, isSecure INTEGER)")
    con.execute("INSERT INTO moz_cookies (name, value, host, path, expiry, isSecure) VALUES"
                " ('LOGIN_INFO', 'secret-value', '.youtube.com', '/', 4102444800000, 1)")
    con.commit()
    return con


def test_firefox_snapshot_includes_wal(tmp_path, monkeypatch):
    con = _firefox_profile(tmp_path / "ff")
    try:
        s = Settings(data_dir=tmp_path / "data", firefox_mount=tmp_path / "ff", cookies_source="firefox")
        opts, active = cookie_opts(s)
        assert active == "firefox"
        snap = Path(opts["cookiesfrombrowser"][1]) / "cookies.sqlite"
        rows = sqlite3.connect(snap).execute("SELECT name FROM moz_cookies").fetchall()
        assert rows == [("LOGIN_INFO",)]
        assert snap.stat().st_mode & 0o777 == 0o600
        st = cookies.status(s)
        assert st["firefox"]["found"] and st["firefox"]["signed_in"] is True
        assert st["firefox"]["profile"] == "abc.default-release"
        assert "secret-value" not in str(st)
    finally:
        con.close()


def test_firefox_export(tmp_path, monkeypatch):
    con = _firefox_profile(tmp_path / "ff")
    con.execute("INSERT INTO moz_cookies (name, value, host, path, expiry, isSecure) VALUES"
                " ('SID', 'not-exported', '.google.com', '/', 4102444800, 0)")
    con.commit()
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("SCHEDULER_ENABLED", "false")
    monkeypatch.setenv("FIREFOX_MOUNT", str(tmp_path / "ff"))
    get_settings.cache_clear()
    from app.main import app
    try:
        with TestClient(app) as c:
            r = c.post("/api/cookies/export")
            assert r.status_code == 200 and "attachment" in r.headers["content-disposition"]
            assert "secret-value" in r.text and "not-exported" not in r.text
            assert looks_like_cookies_txt(r.text)
            # what we export, the upload route accepts
            assert c.put("/api/cookies", json={"content": r.text}).json()["upload"]["present"] is True
            assert c.get("/api/cookies/export").status_code == 405
    finally:
        con.close()
        get_settings.cache_clear()
    assert cookies.export_txt(Settings(data_dir=tmp_path, firefox_mount=tmp_path / "gone")) is None


def test_firefox_falls_back_to_upload(tmp_path):
    s = Settings(data_dir=tmp_path, firefox_mount=tmp_path / "missing", cookies_source="firefox")
    assert cookie_opts(s) == ({}, None)
    (tmp_path / "cookies.txt").write_text(COOKIES)
    assert cookie_opts(s) == ({"cookiefile": str(tmp_path / "cookies.txt")}, "upload")
    assert cookies.status(s)["firefox"]["mounted"] is False


def test_upload_source_ignores_firefox(tmp_path):
    con = _firefox_profile(tmp_path / "ff")
    try:
        s = Settings(data_dir=tmp_path, firefox_mount=tmp_path / "ff", cookies_source="upload")
        assert cookie_opts(s) == ({}, None)
    finally:
        con.close()


def test_files_api(client, tmp_path):
    d = tmp_path / "downloads"
    d.mkdir()
    (d / "a.mp4").write_bytes(b"data")
    assert [f["name"] for f in client.get("/api/files").json()] == ["a.mp4"]
    r = client.get("/api/files/a.mp4")
    assert r.status_code == 200 and r.content == b"data" and "attachment" in r.headers["content-disposition"]
    assert client.get("/api/files/..%2Fapp.db").status_code == 404
    assert client.delete("/api/files/a.mp4").json() == {"ok": True}
    assert client.get("/api/files").json() == []


def test_download_api_validation(client):
    r = client.post("/api/download", json={"url": "https://evil.com/x", "sel": {"kind": "video"}})
    assert r.status_code == 400
    r = client.post("/api/download", json={"url": "https://youtu.be/x", "sel": {"kind": "video", "codec": "x"}})
    assert r.status_code == 422
    assert client.get("/api/download/size", params={"url": "https://youtu.be/x", "height": "9"}).status_code == 400
    assert client.get("/api/download/jobs/nope").status_code == 404
