"""YouTube metadata and transcript extraction via yt-dlp."""

import asyncio
import json
import logging
import re
from datetime import UTC, datetime, tzinfo
from urllib.parse import parse_qs, urlparse

import httpx
import yt_dlp

log = logging.getLogger(__name__)

_BASE_OPTS = {"quiet": True, "no_warnings": True, "skip_download": True, "noplaylist": True}
_CHANNEL_PATH = re.compile(r"^/(@[^/]+|channel/[^/]+|c/[^/]+|user/[^/]+)/?$")
_VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")


class YouTubeError(Exception):
    pass


def is_channel_url(url: str) -> bool:
    p = urlparse(url.strip())
    return "youtube.com" in p.netloc and bool(
        re.match(r"^/(@[^/]+|channel/|c/|user/)", p.path))


def normalize_channel_url(url: str) -> str:
    """https://youtube.com/@x -> https://www.youtube.com/@x/videos.

    A bare channel URL makes yt-dlp return the channel's *tabs* (Videos, Shorts, Live)
    rather than videos, so always point at the Videos tab.
    """
    url = url.strip()
    if "://" not in url:
        url = "https://" + url
    p = urlparse(url)
    path = p.path.rstrip("/")
    if _CHANNEL_PATH.match(path + "/"):
        path += "/videos"
    return f"https://www.youtube.com{path}"


def video_id_from_url(url: str) -> str | None:
    p = urlparse(url.strip())
    if p.netloc.endswith("youtu.be"):
        cand = p.path.lstrip("/").split("/")[0]
    elif p.path.startswith(("/shorts/", "/live/", "/embed/")):
        cand = p.path.split("/")[2]
    else:
        cand = (parse_qs(p.query).get("v") or [""])[0]
    return cand if _VIDEO_ID.match(cand or "") else None


def format_duration(seconds: float | None) -> str:
    s = int(seconds or 0)
    if not s:
        return "—"
    h, rem = divmod(s, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _published(info: dict) -> datetime | None:
    ts = info.get("timestamp") or info.get("release_timestamp")
    if ts:
        return datetime.fromtimestamp(ts, tz=UTC)
    d = info.get("upload_date")
    if d and len(d) == 8:
        return datetime.strptime(d, "%Y%m%d").replace(tzinfo=UTC)
    return None


class YouTubeClient:
    def __init__(self, transcript_max_chars: int = 20000):
        self.transcript_max_chars = transcript_max_chars

    # ---- extraction ----------------------------------------------------
    @staticmethod
    def _extract(url: str, **opts) -> dict:
        with yt_dlp.YoutubeDL({**_BASE_OPTS, **opts}) as ydl:
            return ydl.extract_info(url, download=False)

    async def get_video(self, url: str, tz: tzinfo = UTC, *, with_transcript: bool = True) -> dict:
        try:
            info = await asyncio.to_thread(self._extract, url)
        except yt_dlp.utils.DownloadError as e:
            raise YouTubeError(_clean_ytdlp_error(e)) from e
        if info.get("_type") == "playlist":
            raise YouTubeError("That URL is a playlist or channel, not a single video")
        transcript = await self._transcript(info) if with_transcript else ""
        published = _published(info)
        return {
            "video_id": info.get("id"),
            "title": info.get("title") or "Untitled",
            "url": info.get("webpage_url") or url,
            "channel": info.get("channel") or info.get("uploader") or "",
            "duration": format_duration(info.get("duration")),
            "published_at": published.isoformat() if published else None,
            "published_date": published.astimezone(tz).strftime("%Y-%m-%d") if published else "",
            "thumbnail": info.get("thumbnail") or "",
            "description": (info.get("description") or "")[:2000],
            "view_count": info.get("view_count") or 0,
            "live_status": info.get("live_status"),
            "transcript": transcript,
            "has_transcript": bool(transcript),
        }

    async def list_channel(self, url: str, limit: int = 30) -> dict:
        """Return {'channel_id', 'channel_name', 'url', 'entries': [{'id','title','url'}]} newest first."""
        url = normalize_channel_url(url)
        try:
            info = await asyncio.to_thread(self._extract, url, extract_flat="in_playlist",
                                           playlistend=limit, noplaylist=False)
        except yt_dlp.utils.DownloadError as e:
            raise YouTubeError(_clean_ytdlp_error(e)) from e
        entries = []
        for e in info.get("entries") or []:
            vid = (e or {}).get("id")
            if vid and _VIDEO_ID.match(vid):
                entries.append({"id": vid, "title": e.get("title") or "",
                                "url": f"https://www.youtube.com/watch?v={vid}"})
        name = info.get("channel") or info.get("uploader") or info.get("title") or ""
        return {
            "channel_id": info.get("channel_id") or info.get("id"),
            "channel_name": re.sub(r"\s+-\s+Videos$", "", name),
            "url": url,
            "entries": entries[:limit],
        }

    # ---- transcripts ---------------------------------------------------
    async def _transcript(self, info: dict) -> str:
        track = _pick_caption_track(info)
        if not track:
            return ""
        try:
            async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
                r = await client.get(track["url"])
            if r.status_code == 429:
                log.warning("Rate limited fetching captions for %s", info.get("id"))
                return ""
            r.raise_for_status()
            text = parse_captions(r.text, track.get("ext", ""))
        except Exception as e:  # captions are best-effort
            log.warning("Caption fetch failed for %s: %s", info.get("id"), e)
            return ""
        if len(text) > self.transcript_max_chars:
            text = text[: self.transcript_max_chars] + " … (transcript truncated)"
        return text


def _pick_caption_track(info: dict) -> dict | None:
    """Prefer human subtitles, then auto captions in the video's own language.

    automatic_captions also lists machine translations into every language, so never
    take an arbitrary first key from it (the old code could pick e.g. Abkhazian).
    """
    subs = info.get("subtitles") or {}
    auto = info.get("automatic_captions") or {}
    orig = (info.get("language") or "").split("-")[0]
    candidates: list[list[dict]] = []
    for lang in ("en", "en-US", "en-GB", orig):
        if lang and lang in subs:
            candidates.append(subs[lang])
    for lang in (f"{orig}-orig", orig, "en-orig", "en"):
        if lang and lang in auto:
            candidates.append(auto[lang])
    if subs:
        candidates.append(next(iter(subs.values())))
    for formats in candidates:
        for ext in ("json3", "srv1", "vtt", "ttml"):
            for f in formats:
                if f.get("ext") == ext and f.get("url"):
                    return f
    return None


def parse_captions(content: str, ext: str) -> str:
    if ext == "json3":
        data = json.loads(content)
        parts = [seg.get("utf8", "") for ev in data.get("events", []) for seg in ev.get("segs") or []]
        text = "".join(parts)
    elif ext == "vtt":
        lines, prev = [], None
        for line in content.splitlines():
            line = line.strip()
            if not line or "-->" in line or line.startswith(("WEBVTT", "NOTE", "Kind:", "Language:")):
                continue
            line = re.sub(r"<[^>]+>", "", line)
            if line and line != prev:  # auto-captions repeat each line while scrolling
                lines.append(line)
            prev = line
        text = " ".join(lines)
    else:  # srv1 / ttml / anything XML-ish
        text = re.sub(r"<[^>]+>", " ", content)
    text = text.replace("&amp;", "&").replace("&#39;", "'").replace("&quot;", '"')
    return re.sub(r"\s+", " ", text).strip()


def _clean_ytdlp_error(e: Exception) -> str:
    msg = re.sub(r"\x1b\[[0-9;]*m", "", str(e))
    return msg.removeprefix("ERROR: ").strip()
