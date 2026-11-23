"""/api/download/*, /api/files/* and /api/cookies: the Download page and YouTube sign-in."""

import asyncio
import os
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel, Field, ValidationError
from starlette.background import BackgroundTask

from . import cookies
from .downloader import DownloadError, DownloadManager, DownloadRequest, Selection

router = APIRouter(prefix="/api")
MAX_COOKIES_BYTES = 1_000_000


def _dm(request: Request) -> DownloadManager:
    return request.app.state.downloads


# ---- downloads -----------------------------------------------------------
@router.get("/download/info")
async def download_info(request: Request, url: str = Query(min_length=5)):
    try:
        return await _dm(request).info(url)
    except DownloadError as e:
        raise HTTPException(400, str(e)[:800])


@router.get("/download/size")
async def download_size(request: Request, url: str = Query(min_length=5), kind: str = "video",
                        height: str = "best", codec: str = "any", mode: str | None = None):
    try:
        sel = Selection(kind=kind, codec=codec, mode=mode or None,
                        height=int(height) if height.isdigit() else height)
    except ValidationError as e:
        raise HTTPException(400, e.errors()[0]["msg"])
    try:
        return {"bytes": await _dm(request).size(url, sel)}
    except DownloadError as e:
        raise HTTPException(400, str(e))


@router.post("/download", status_code=202)
async def download_start(body: DownloadRequest, request: Request):
    try:
        return _dm(request).start(body).public()
    except DownloadError as e:
        raise HTTPException(400, str(e))


@router.get("/download/jobs/{job_id}")
async def download_job(job_id: str, request: Request):
    job = _dm(request).jobs.get(job_id)
    if not job:
        raise HTTPException(404, "Unknown download")
    return job.public()


@router.get("/download/jobs/{job_id}/files/{index}")
async def download_job_file(job_id: str, index: int, request: Request):
    hit = _dm(request).file(job_id, index)
    if not hit:
        raise HTTPException(404, "The file is not ready or was already removed")
    job, f = hit
    cleanup = None if job.keep else BackgroundTask(Path(f["path"]).unlink, missing_ok=True)
    return FileResponse(f["path"], filename=f["name"], background=cleanup)


# ---- files kept on the server --------------------------------------------
@router.get("/files")
async def saved_files(request: Request):
    return _dm(request).saved()


def _saved(request: Request, name: str) -> Path:
    p = _dm(request).saved_path(name)
    if not p:
        raise HTTPException(404, "File not found")
    return p


@router.get("/files/{name}")
async def saved_file(name: str, request: Request):
    p = _saved(request, name)
    return FileResponse(p, filename=p.name)


@router.delete("/files/{name}")
async def delete_saved_file(name: str, request: Request):
    _saved(request, name).unlink(missing_ok=True)
    return {"ok": True}


# ---- YouTube sign-in cookies ---------------------------------------------
class CookiesBody(BaseModel):
    content: str = Field(max_length=MAX_COOKIES_BYTES)


def looks_like_cookies_txt(text: str) -> bool:
    """Netscape format: tab-separated lines of 7 fields, at least one for youtube.com."""
    rows = [ln.split("\t") for ln in text.splitlines() if ln.strip() and not ln.startswith("# ")]
    rows = [r for r in rows if len(r) == 7]
    return any("youtube.com" in r[0] for r in rows)


@router.get("/cookies")
async def cookies_status(request: Request):
    """Both cookie sources and which one is in use. Cookie values are never returned."""
    return await asyncio.to_thread(cookies.status, request.app.state.settings)


@router.put("/cookies")
async def cookies_save(body: CookiesBody, request: Request):
    if not looks_like_cookies_txt(body.content):
        raise HTTPException(400, "That doesn't look like a cookies.txt export with YouTube cookies "
                                 "(Netscape format, tab-separated).")
    s = request.app.state.settings
    path = s.cookie_path
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".new")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(body.content if body.content.endswith("\n") else body.content + "\n")
    tmp.replace(path)
    return await asyncio.to_thread(cookies.status, s)


@router.post("/cookies/export")
async def cookies_export(request: Request):
    """Firefox's YouTube cookies as a cookies.txt download, to upload on another server running the app.

    The only route that returns cookie values. POST, so a plain link or <img> can't fetch it.
    """
    text = await asyncio.to_thread(cookies.export_txt, request.app.state.settings)
    if text is None:
        raise HTTPException(404, "No Firefox profile is shared with the app, so there is nothing to export.")
    if not text:
        raise HTTPException(409, "Firefox has no YouTube cookies. Sign in to YouTube in Firefox first.")
    return PlainTextResponse(text, headers={"Content-Disposition": 'attachment; filename="cookies.txt"',
                                            "Cache-Control": "no-store"})


@router.delete("/cookies")
async def cookies_delete(request: Request):
    s = request.app.state.settings
    s.cookie_path.unlink(missing_ok=True)
    return await asyncio.to_thread(cookies.status, s)
