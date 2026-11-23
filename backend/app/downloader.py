"""Video / audio / subtitle downloads via the yt-dlp Python API.

Ported from the standalone Node downloader. The client sends a structured, allowlisted
selection; the yt-dlp format string is always built here.
"""

import asyncio
import logging
import re
import shutil
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlparse

import yt_dlp
from pydantic import BaseModel, Field, field_validator

from .config import Settings
from .cookies import cookie_opts
from .youtube import clean_ytdlp_error, ffmpeg_path, is_channel_url, normalize_channel_url, ydl_base_opts

log = logging.getLogger(__name__)

MAX_AGE_SECONDS = 3600     # temp files and finished jobs are swept after an hour
MAX_PLAYLIST = 1000        # entries listed for a playlist
SIZE_CACHE_SECONDS = 600
LANG_RE = re.compile(r"^[A-Za-z0-9._-]{1,16}$")
_SIGNIN_RE = re.compile(r"sign in|members[- ]only|member[- ]only|not a bot|age[- ]?confirm|cookies",
                        re.IGNORECASE)
_YT_HOSTS = ("youtube.com", "youtu.be", "youtube-nocookie.com")


class DownloadError(Exception):
    pass


# ---- selection -----------------------------------------------------------
class Selection(BaseModel):
    kind: Literal["video", "audio", "subs"] = "video"
    codec: Literal["any", "avc", "vp9", "av1", "other"] = "any"
    height: Annotated[int, Field(ge=120, le=4320)] | Literal["best"] = "best"
    mode: Literal["best", "mp3", "m4a", "opus"] | None = None


class DownloadRequest(BaseModel):
    url: str
    sel: Selection
    subs: str | None = None
    title: str | None = None
    keep: bool = False

    @field_validator("subs")
    @classmethod
    def _lang(cls, v: str | None) -> str | None:
        if v is not None and not LANG_RE.match(v):
            raise ValueError("Invalid subtitle language code")
        return v or None

    @field_validator("title")
    @classmethod
    def _title(cls, v: str | None) -> str | None:
        return v[:180] if v else v


_CODEC_FILTER = {"avc": "[vcodec^=avc]", "vp9": "[vcodec^=vp]", "av1": "[vcodec^=av01]", "other": "[vcodec^=mp4v]"}


def build_selector(sel: Selection, has_ffmpeg: bool) -> tuple[str, dict]:
    """(yt-dlp format string, extra YoutubeDL options) for a selection."""
    if sel.kind == "audio":
        if sel.mode == "mp3":
            if not has_ffmpeg:
                raise DownloadError("MP3 extraction needs ffmpeg.")
            return "ba/b", {"postprocessors": [
                {"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "4"}]}
        if sel.mode == "m4a":
            return "ba[acodec^=mp4a]/ba/b", {}
        if sel.mode == "opus":
            return "ba[acodec^=opus]/ba/b", {}
        return "ba/b", {}
    if sel.kind == "subs":
        return "bv*+ba/b", {"skip_download": True}

    h = f"[height<={sel.height}]" if isinstance(sel.height, int) else ""
    cf = _CODEC_FILTER.get(sel.codec, "")
    if not has_ffmpeg:  # only single-file formats (video + audio together) work without merging
        return f"b{h}{cf}", {}
    v = f"bv*{cf}{h}"
    a = "+ba[acodec^=mp4a]" if sel.codec == "avc" else "+ba"
    if not h:
        return (f"{v}{a}/{v}+ba/b" if sel.codec == "avc" else f"{v}+ba/b"), {}
    return f"{v}{a}/{v}+ba/b{h}", {}


# ---- metadata ------------------------------------------------------------
def is_youtube_url(raw: str) -> bool:
    try:
        u = urlparse(raw.strip())
    except ValueError:
        return False
    if u.scheme not in ("http", "https"):
        return False
    host = (u.hostname or "").removeprefix("www.")
    return any(host == h or host.endswith("." + h) for h in _YT_HOSTS)


def sanitize_filename(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|\x00-\x1f]+', " ", str(name)).strip(" .")[:180] or "video"


def _codec_of(f: dict) -> str:
    v = (f.get("vcodec") or "").lower()
    if v.startswith("avc"):
        return "avc"
    if v.startswith("vp"):
        return "vp9"
    if v.startswith(("av01", "av1")):
        return "av1"
    return "other"


def _format_size(f: dict, duration: float) -> int:
    if f.get("filesize"):
        return int(f["filesize"])
    if f.get("filesize_approx"):
        return int(f["filesize_approx"])
    if f.get("frag_size") and f.get("fragment_count"):
        return int(f["frag_size"] * f["fragment_count"])
    if f.get("tbr"):
        return int(f["tbr"] * 1024 / 8 * (f.get("duration") or duration))
    return 0


def analyze_formats(info: dict, has_ffmpeg: bool) -> dict:
    """Per-height codec options with estimated sizes, plus audio-only sizes."""
    fmts = info.get("formats") or []
    dur = info.get("duration") or 0

    def has(f, k):
        return f.get(k) and f.get(k) != "none"

    video = [f for f in fmts if has(f, "vcodec") and f.get("height")]
    audio = [f for f in fmts if has(f, "acodec") and not has(f, "vcodec")]
    progressive = [f for f in video if has(f, "acodec")]

    def best(fs):
        return max((_format_size(f, dur) for f in fs), default=0)

    by_height: dict[int, dict] = {}
    for f in video if has_ffmpeg else progressive:
        rec = by_height.setdefault(f["height"], {"codecs": set(), "sizes": {}, "max": 0})
        c, size = _codec_of(f), _format_size(f, dur)
        rec["codecs"].add(c)
        rec["max"] = max(rec["max"], size)
        rec["sizes"][c] = max(rec["sizes"].get(c, 0), size)

    def auto(rec):  # mimics yt-dlp's default preference: VP9 > H.264 > AV1
        s = rec["sizes"]
        return s.get("vp9") or s.get("avc") or s.get("av1") or s.get("other") or rec["max"]

    heights = []
    for h in sorted(by_height, reverse=True)[:10]:
        rec = by_height[h]
        heights.append({
            "h": h,
            "codecs": ["any", *[c for c in ("vp9", "avc", "av1", "other") if c in rec["codecs"]]],
            "sizes": {**rec["sizes"], "any": auto(rec)},
        })
    audio_best = best(audio)
    best_video = auto(by_height[heights[0]["h"]]) if heights else 0
    return {
        "heights": heights,
        "audio": {
            "best": audio_best,
            "m4a": best(f for f in audio if (f.get("acodec") or "").startswith("mp4a")),
            "opus": best(f for f in audio if (f.get("acodec") or "").startswith("opus")),
        },
        "best_total": best_video + audio_best if best_video and audio_best else best_video,
        "ffmpeg": has_ffmpeg,
        "progressive_count": len(progressive),
    }


def subtitles_info(info: dict) -> dict:
    def clean(obj):
        return [{"code": code, "name": (tracks[0].get("name") if tracks else None)}
                for code, tracks in (obj or {}).items() if LANG_RE.match(code)]
    return {"manual": clean(info.get("subtitles")), "auto": clean(info.get("automatic_captions"))}


def selected_size(info: dict) -> int:
    """Byte size of the format(s) yt-dlp selected in an extract_info(download=False) result."""
    dur = info.get("duration") or 0
    parts = info.get("requested_formats")
    if parts:
        return sum(_format_size(f, dur) for f in parts)
    return _format_size(info, dur)


# ---- jobs ----------------------------------------------------------------
@dataclass
class Job:
    id: str
    url: str
    sel: Selection
    subs: str | None
    title: str | None
    keep: bool
    status: str = "queued"  # queued | downloading | processing | done | error
    percent: float = 0
    text: str = "Waiting for a free slot…"
    error: str | None = None
    video_id: str | None = None
    files: list[dict] = field(default_factory=list)  # {path, name, kind}
    started_at: float = field(default_factory=time.time)

    def public(self) -> dict:
        main = next((f for f in self.files if f["kind"] == "main"), None)
        size = 0
        if main and Path(main["path"]).is_file():
            size = Path(main["path"]).stat().st_size
        return {
            "id": self.id, "status": self.status, "percent": round(self.percent), "text": self.text,
            "error": self.error, "title": self.title, "kept": self.keep, "size": size,
            "files": [{"name": f["name"], "url": f"/api/download/jobs/{self.id}/files/{i}"}
                      for i, f in enumerate(self.files)] if self.status == "done" else [],
        }


class DownloadManager:
    def __init__(self, settings: Callable[[], Settings]):
        self._settings = settings
        self.jobs: dict[str, Job] = {}
        self._tasks: set[asyncio.Task] = set()
        self._size_cache: dict[tuple[str, str], tuple[int, float]] = {}
        self._sem = asyncio.Semaphore(settings().max_concurrent_downloads)

    @property
    def s(self) -> Settings:
        return self._settings()

    @property
    def tmp_dir(self) -> Path:
        return self.s.downloads_dir / ".tmp"

    def _opts(self, **extra) -> dict:
        return {"quiet": True, "no_warnings": True, "noplaylist": True, "noprogress": True,
                **ydl_base_opts(self.s), **extra}

    def _hint(self, msg: str) -> str:
        if not cookie_opts(self.s)[1] and _SIGNIN_RE.search(msg):
            return (msg + "\nThis looks like sign-in-gated content (members-only, age-gated or private). "
                    "Add your YouTube cookies under Settings → YouTube sign-in.")
        return msg

    def _extract(self, url: str, **opts) -> dict:
        try:
            with yt_dlp.YoutubeDL(self._opts(**opts)) as ydl:
                return ydl.extract_info(url, download=False)
        except yt_dlp.utils.DownloadError as e:
            raise DownloadError(self._hint(clean_ytdlp_error(e))) from e

    # ---- info & size ---------------------------------------------------
    async def info(self, url: str) -> dict:
        if not is_youtube_url(url):
            raise DownloadError("Enter a valid YouTube URL (youtube.com / youtu.be).")
        has_ff = bool(ffmpeg_path())
        if is_channel_url(url):
            url = normalize_channel_url(url)
        j = await asyncio.to_thread(self._extract, url, extract_flat="in_playlist", playlistend=MAX_PLAYLIST)
        if j.get("_type") == "playlist" or "entries" in j:
            entries = []
            for e in j.get("entries") or []:
                vid = (e or {}).get("id")
                if not vid or e.get("_type") == "playlist":
                    continue
                thumbs = e.get("thumbnails") or []
                entries.append({
                    "id": vid, "title": e.get("title") or vid, "duration": e.get("duration"),
                    "thumbnail": (thumbs[0].get("url") if thumbs else None)
                    or f"https://i.ytimg.com/vi/{vid}/mqdefault.jpg",
                    "url": f"https://www.youtube.com/watch?v={vid}",
                })
            if not entries:
                raise DownloadError("The playlist is empty or unavailable.")
            first = await asyncio.to_thread(self._extract, entries[0]["url"])
            total = j.get("playlist_count") or len(entries)
            return {
                "kind": "playlist", "id": j.get("id"),
                "title": re.sub(r"\s+-\s+Videos$", "", j.get("title") or "") or "Playlist",
                "entries_count": total, "entries": entries,
                "qualities": analyze_formats(first, has_ff),
                "note": f"Showing the first {len(entries)} of {total} videos." if len(entries) < total else None,
            }
        q = analyze_formats(j, has_ff)
        note = None
        if not has_ff and not q["progressive_count"]:
            note = "No single-file formats available; ffmpeg is needed to download this video."
        return {
            "kind": "video", "id": j.get("id"), "title": j.get("title"), "url": j.get("webpage_url") or url,
            "thumbnail": j.get("thumbnail"), "duration": j.get("duration"),
            "uploader": j.get("uploader") or j.get("channel"),
            "qualities": q, "subtitles": subtitles_info(j), "note": note,
        }

    async def size(self, url: str, sel: Selection) -> int:
        if not is_youtube_url(url):
            raise DownloadError("Invalid YouTube URL.")
        fmt, _ = build_selector(sel, bool(ffmpeg_path()))
        key = (url, fmt)
        hit = self._size_cache.get(key)
        if hit and time.time() - hit[1] < SIZE_CACHE_SECONDS:
            return hit[0]
        try:
            info = await asyncio.to_thread(self._extract, url, format=fmt)
        except DownloadError:
            return 0
        n = selected_size(info)
        self._size_cache[key] = (n, time.time())
        return n

    # ---- downloads -----------------------------------------------------
    def start(self, req: DownloadRequest) -> Job:
        if not is_youtube_url(req.url):
            raise DownloadError("Invalid YouTube URL.")
        if req.sel.kind == "subs" and not req.subs:
            raise DownloadError("Pick a subtitle language first.")
        build_selector(req.sel, bool(ffmpeg_path()))  # fail fast (e.g. MP3 without ffmpeg)
        job = Job(id=uuid.uuid4().hex, url=req.url, sel=req.sel, subs=req.subs, title=req.title, keep=req.keep)
        self.jobs[job.id] = job
        task = asyncio.create_task(self._run(job))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return job

    async def _run(self, job: Job) -> None:
        async with self._sem:
            job.status, job.text = "downloading", "Starting…"
            try:
                await asyncio.to_thread(self._download, job)
            except DownloadError as e:
                job.status, job.error = "error", str(e)
            except Exception as e:
                log.exception("download %s failed", job.id)
                job.status, job.error = "error", f"Unexpected error: {e}"

    def _download(self, job: Job) -> None:
        has_ff = bool(ffmpeg_path())
        fmt, extra = build_selector(job.sel, has_ff)
        self.tmp_dir.mkdir(parents=True, exist_ok=True)
        opts = self._opts(format=fmt, outtmpl={"default": str(self.tmp_dir / f"{job.id}.%(ext)s")},
                          progress_hooks=[lambda d: _on_progress(job, d)],
                          postprocessor_hooks=[lambda d: _on_postprocess(job, d)], **extra)
        if job.subs:
            opts.update(writesubtitles=True, writeautomaticsub=True, subtitleslangs=[job.subs])
            if has_ff:
                opts["postprocessors"] = [*opts.get("postprocessors", []),
                                          {"key": "FFmpegSubtitlesConvertor", "format": "srt"}]
        job.text = "Fetching subtitles…" if job.sel.kind == "subs" else "Downloading…"
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(job.url, download=True)
        except yt_dlp.utils.DownloadError as e:
            raise DownloadError(self._hint(clean_ytdlp_error(e))) from e
        job.video_id = (info or {}).get("id")
        job.title = job.title or (info or {}).get("title")
        self._collect(job)

    def _collect(self, job: Job) -> None:
        """Name the output files after the title; move them to the downloads folder if kept."""
        found = sorted(p for p in self.tmp_dir.glob(f"{job.id}.*") if not p.name.endswith((".part", ".ytdl")))
        if not found:
            raise DownloadError("No subtitles available for that language." if job.sel.kind == "subs"
                                else "Finished, but the output file was not found.")
        base = sanitize_filename(job.title or job.video_id or job.id)
        files = []
        for p in found:
            rest = p.name[len(job.id) + 1:]  # "webm" or "en.srt"
            main = "." not in rest
            name = f"{base}.{rest}"
            if job.keep:
                stem = f"{base} [{job.video_id}]" if job.video_id else base
                dest = self.s.downloads_dir / f"{stem}.{rest}"
                shutil.move(p, dest)
                p = dest
            files.append({"path": str(p), "name": name, "kind": "main" if main else "sub"})
        files.sort(key=lambda f: f["kind"] != "main")
        job.files = files
        job.status, job.percent, job.text = "done", 100, "Complete"

    def file(self, job_id: str, index: int) -> tuple[Job, dict] | None:
        job = self.jobs.get(job_id)
        if not job or job.status != "done" or not 0 <= index < len(job.files):
            return None
        f = job.files[index]
        return (job, f) if Path(f["path"]).is_file() else None

    # ---- saved files ---------------------------------------------------
    def saved(self) -> list[dict]:
        d = self.s.downloads_dir
        if not d.is_dir():
            return []
        out = [{"name": p.name, "size": p.stat().st_size, "modified": p.stat().st_mtime}
               for p in d.iterdir() if p.is_file() and not p.name.startswith(".")]
        return sorted(out, key=lambda x: x["modified"], reverse=True)

    def saved_path(self, name: str) -> Path | None:
        root = self.s.downloads_dir.resolve()
        p = (root / name).resolve()
        if p.parent != root or p.name.startswith(".") or not p.is_file():
            return None
        return p

    # ---- housekeeping --------------------------------------------------
    def sweep(self, now: float | None = None) -> int:
        """Delete temp files and forget jobs older than an hour. Kept files are never touched."""
        now = now or time.time()
        removed = 0
        if self.tmp_dir.is_dir():
            for p in self.tmp_dir.iterdir():
                if p.is_file() and now - p.stat().st_mtime > MAX_AGE_SECONDS:
                    p.unlink(missing_ok=True)
                    removed += 1
        for jid, job in list(self.jobs.items()):
            if now - job.started_at > MAX_AGE_SECONDS and job.status in ("done", "error"):
                del self.jobs[jid]
        self._size_cache = {k: v for k, v in self._size_cache.items() if now - v[1] < SIZE_CACHE_SECONDS}
        return removed


def _on_progress(job: Job, d: dict) -> None:
    if d.get("status") == "downloading":
        total = d.get("total_bytes") or d.get("total_bytes_estimate")
        if total:
            job.percent = min(99.0, d.get("downloaded_bytes", 0) * 100 / total)
        job.status, job.text = "downloading", "Downloading…"


def _on_postprocess(job: Job, d: dict) -> None:
    if d.get("status") == "started" and d.get("postprocessor") not in ("MoveFiles",):
        job.status, job.percent, job.text = "processing", 100, "Processing…"
