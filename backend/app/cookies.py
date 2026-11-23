"""YouTube sign-in cookies for yt-dlp: read live from a mounted Firefox profile, or an uploaded cookies.txt.

Firefox keeps cookies in an unencrypted SQLite file (cookies.sqlite). While Firefox runs, recent
changes sit in cookies.sqlite-wal, which yt-dlp's own reader ignores, so we copy both into a private
snapshot under $DATA_DIR, fold the WAL in, and point yt-dlp at that copy. The snapshot is refreshed
only when Firefox's files change, so each yt-dlp call costs a few stat() calls.
"""

import logging
import os
import shutil
import sqlite3
import tempfile
import threading
from datetime import UTC, datetime
from pathlib import Path

from .config import Settings

log = logging.getLogger(__name__)

# Same layouts yt-dlp accepts: a profile folder, the Profiles folder, or the Firefox folder.
_PATTERNS = ("cookies.sqlite", "*/cookies.sqlite", "Profiles/*/cookies.sqlite")
# Cookies an export keeps. yt-dlp only ever sends youtube.com cookies to YouTube, so leave out the rest
# (Gmail, Drive, ...): a leaked export then signs in to YouTube only.
_EXPORT_DOMAINS = ("youtube.com",)
# Present only when signed in to a Google account on YouTube.
_SIGNIN_COOKIES = ("LOGIN_INFO", "SAPISID", "__Secure-3PAPISID")

_lock = threading.Lock()
_snap_key: tuple | None = None


def find_firefox_db(root: Path) -> Path | None:
    """The most recently used profile's cookies.sqlite under the mounted folder."""
    try:
        if not root.is_dir():
            return None
        found = [p for pat in _PATTERNS for p in root.glob(pat) if p.is_file()]
    except OSError:
        return None
    return max(found, key=lambda p: p.stat().st_mtime, default=None)


def _stamp(p: Path) -> tuple:
    try:
        st = p.stat()
        return st.st_mtime_ns, st.st_size
    except OSError:
        return 0, 0


def firefox_snapshot(s: Settings) -> Path | None:
    """Folder holding an up-to-date private copy of Firefox's cookies, or None if unavailable."""
    global _snap_key
    src = find_firefox_db(s.firefox_mount)
    if src is None:
        return None
    wal = src.with_name(src.name + "-wal")
    key = (str(src), _stamp(src), _stamp(wal))
    dest_dir = s.firefox_snapshot_dir
    dest = dest_dir / "cookies.sqlite"
    with _lock:
        if key == _snap_key and dest.is_file():
            return dest_dir
        try:
            dest_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
            with tempfile.TemporaryDirectory(dir=dest_dir) as tmp:
                work = Path(tmp) / "cookies.sqlite"
                shutil.copyfile(src, work)
                if wal.is_file():
                    shutil.copyfile(wal, work.with_name(work.name + "-wal"))
                con = sqlite3.connect(work)
                try:  # opening replays the WAL; checkpoint writes it into the main file
                    con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                    con.execute("PRAGMA journal_mode=DELETE")
                finally:
                    con.close()
                os.chmod(work, 0o600)
                os.replace(work, dest)  # atomic: a yt-dlp call copying the old file is unaffected
        except (OSError, sqlite3.Error) as e:
            log.warning("Could not read Firefox cookies from %s: %s", src, e)
            return dest_dir if dest.is_file() else None
        _snap_key = key
        log.info("Firefox cookies refreshed from %s", src.parent.name)
        return dest_dir


def _youtube_signin(db: Path) -> bool:
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        marks = ",".join("?" * len(_SIGNIN_COOKIES))
        row = con.execute(f"SELECT COUNT(*) FROM moz_cookies WHERE host LIKE '%youtube.com' AND name IN ({marks})",
                          _SIGNIN_COOKIES).fetchone()
        return bool(row and row[0])
    finally:
        con.close()


def cookie_opts(s: Settings) -> tuple[dict, str | None]:
    """yt-dlp options for the chosen cookie source, and which source is in use.

    Firefox falls back to an uploaded cookies.txt when no Firefox profile is reachable.
    """
    if s.cookies_source == "firefox" and (snap := firefox_snapshot(s)):
        # profile given as a path; keyring and container unused for Firefox
        return {"cookiesfrombrowser": ("firefox", str(snap), None, None)}, "firefox"
    if s.cookie_path.is_file():
        return {"cookiefile": str(s.cookie_path)}, "upload"
    return {}, None


def _domain_in(domain: str, *roots: str) -> bool:
    d = domain.lstrip(".").lower()
    return any(d == r or d.endswith("." + r) for r in roots)


def export_txt(s: Settings) -> str | None:
    """Firefox's youtube.com cookies as a Netscape cookies.txt.

    For taking the sign-in to another server, which then uses it as an uploaded cookies.txt.
    None when Firefox can't be read; "" when it has no YouTube cookies.
    """
    from yt_dlp.cookies import YoutubeDLCookieJar, extract_cookies_from_browser

    snap = firefox_snapshot(s)
    if snap is None:
        return None
    out = YoutubeDLCookieJar()
    for c in extract_cookies_from_browser("firefox", str(snap)):
        if _domain_in(c.domain, *_EXPORT_DOMAINS):
            out.set_cookie(c)
    if len(out) == 0:
        return ""
    with tempfile.TemporaryDirectory(dir=snap) as tmp:  # inside the owner-only snapshot folder
        path = Path(tmp) / "cookies.txt"
        out.save(str(path))
        return path.read_text(encoding="utf-8")


def _when(p: Path) -> str:
    return datetime.fromtimestamp(p.stat().st_mtime, tz=UTC).isoformat()


def status(s: Settings) -> dict:
    """What the Settings page shows. Never includes cookie values."""
    upload = {"present": s.cookie_path.is_file(), "updated_at": None}
    if upload["present"]:
        upload["updated_at"] = _when(s.cookie_path)

    firefox = {"mounted": False, "found": False, "profile": None, "updated_at": None,
               "signed_in": None, "error": None}
    try:
        firefox["mounted"] = s.firefox_mount.is_dir() and any(s.firefox_mount.iterdir())
    except OSError as e:
        firefox["error"] = str(e)
    if src := find_firefox_db(s.firefox_mount):
        firefox.update(found=True, profile=src.parent.name, updated_at=_when(src))
        if snap := firefox_snapshot(s):
            try:
                firefox["signed_in"] = _youtube_signin(snap / "cookies.sqlite")
            except sqlite3.Error as e:
                firefox["error"] = f"Could not read the cookie database: {e}"
        else:
            firefox["error"] = "Found Firefox's cookie file but could not read it (see the app log)."

    _, active = cookie_opts(s)
    return {"source": s.cookies_source, "active": active, "upload": upload, "firefox": firefox}
