"""SQLite storage. Queries are tiny, so they run synchronously; WAL keeps readers unblocked."""

import json
import logging
import os
import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS subscriptions (
    id           TEXT PRIMARY KEY,
    channel_url  TEXT NOT NULL,
    channel_id   TEXT,
    channel_name TEXT NOT NULL,
    email        TEXT NOT NULL COLLATE NOCASE,
    created_at   TEXT NOT NULL,
    last_checked TEXT,
    last_error   TEXT,
    active       INTEGER NOT NULL DEFAULT 1,
    UNIQUE (email, channel_url)
);
CREATE TABLE IF NOT EXISTS seen_videos (
    subscription_id TEXT NOT NULL REFERENCES subscriptions(id) ON DELETE CASCADE,
    video_id        TEXT NOT NULL,
    seen_at         TEXT NOT NULL,
    PRIMARY KEY (subscription_id, video_id)
);
CREATE TABLE IF NOT EXISTS runs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    trigger      TEXT NOT NULL,
    started_at   TEXT NOT NULL,
    finished_at  TEXT,
    status       TEXT NOT NULL,
    videos_found INTEGER NOT NULL DEFAULT 0,
    emails_sent  INTEGER NOT NULL DEFAULT 0,
    log          TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS analyses (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id       TEXT,
    url            TEXT NOT NULL,
    title          TEXT NOT NULL,
    channel        TEXT,
    thumbnail      TEXT,
    duration       TEXT,
    published_at   TEXT,
    summary        TEXT NOT NULL,
    has_transcript INTEGER NOT NULL DEFAULT 0,
    provider       TEXT NOT NULL,
    model          TEXT NOT NULL,
    created_at     TEXT NOT NULL
);
"""


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class Database:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        if not os.access(path.parent, os.W_OK):
            raise RuntimeError(
                f"Data folder {path.parent} is not writable by uid {os.getuid()}. "
                f"On the host, run: sudo chown -R {os.getuid()} ./data")
        with self._conn() as c:
            c.executescript(SCHEMA)

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            with conn:  # commit / rollback
                yield conn
        finally:
            conn.close()

    # ---- subscriptions -------------------------------------------------
    def add_subscription(self, *, channel_url: str, channel_name: str, email: str,
                         channel_id: str | None = None, seen_video_ids: list[str] = ()) -> dict:
        sub = {
            "id": str(uuid.uuid4()), "channel_url": channel_url, "channel_id": channel_id,
            "channel_name": channel_name, "email": email.strip(), "created_at": now_iso(),
        }
        with self._conn() as c:
            c.execute(
                "INSERT INTO subscriptions (id, channel_url, channel_id, channel_name, email, created_at)"
                " VALUES (:id, :channel_url, :channel_id, :channel_name, :email, :created_at)", sub)
            c.executemany(
                "INSERT OR IGNORE INTO seen_videos VALUES (?, ?, ?)",
                [(sub["id"], v, sub["created_at"]) for v in seen_video_ids])
        return self.get_subscription(sub["id"])

    def get_subscription(self, sub_id: str) -> dict | None:
        with self._conn() as c:
            row = c.execute("SELECT * FROM subscriptions WHERE id = ?", (sub_id,)).fetchone()
        return _sub(row) if row else None

    def subscription_exists(self, email: str, channel_url: str) -> bool:
        with self._conn() as c:
            return c.execute("SELECT 1 FROM subscriptions WHERE email = ? AND channel_url = ?",
                             (email.strip(), channel_url)).fetchone() is not None

    def list_subscriptions(self, email: str | None = None) -> list[dict]:
        q, args = "SELECT * FROM subscriptions WHERE active = 1", []
        if email is not None:
            q += " AND email = ?"
            args.append(email.strip())
        with self._conn() as c:
            return [_sub(r) for r in c.execute(q + " ORDER BY channel_name COLLATE NOCASE", args)]

    def delete_subscription(self, sub_id: str) -> bool:
        with self._conn() as c:
            return c.execute("DELETE FROM subscriptions WHERE id = ?", (sub_id,)).rowcount > 0

    def mark_checked(self, sub_id: str, error: str | None = None) -> None:
        with self._conn() as c:
            if error:
                c.execute("UPDATE subscriptions SET last_error = ? WHERE id = ?", (error, sub_id))
            else:
                c.execute("UPDATE subscriptions SET last_checked = ?, last_error = NULL WHERE id = ?",
                          (now_iso(), sub_id))

    # ---- seen videos ---------------------------------------------------
    def seen_ids(self, sub_id: str) -> set[str]:
        with self._conn() as c:
            return {r[0] for r in c.execute(
                "SELECT video_id FROM seen_videos WHERE subscription_id = ?", (sub_id,))}

    def mark_seen(self, sub_id: str, video_ids: list[str]) -> None:
        ts = now_iso()
        with self._conn() as c:
            c.executemany("INSERT OR IGNORE INTO seen_videos VALUES (?, ?, ?)",
                          [(sub_id, v, ts) for v in video_ids])

    # ---- runs ----------------------------------------------------------
    def start_run(self, trigger: str) -> int:
        with self._conn() as c:
            return c.execute("INSERT INTO runs (trigger, started_at, status) VALUES (?, ?, 'running')",
                             (trigger, now_iso())).lastrowid

    def finish_run(self, run_id: int, *, status: str, videos_found: int, emails_sent: int,
                   log_text: str) -> None:
        with self._conn() as c:
            c.execute("UPDATE runs SET finished_at = ?, status = ?, videos_found = ?, emails_sent = ?,"
                      " log = ? WHERE id = ?",
                      (now_iso(), status, videos_found, emails_sent, log_text, run_id))

    def list_runs(self, limit: int = 20) -> list[dict]:
        with self._conn() as c:
            return [dict(r) for r in c.execute("SELECT * FROM runs ORDER BY id DESC LIMIT ?", (limit,))]

    def fail_stale_runs(self) -> None:
        """Runs left 'running' by a crash or restart can never finish."""
        with self._conn() as c:
            c.execute("UPDATE runs SET status = 'interrupted', finished_at = ? WHERE status = 'running'",
                      (now_iso(),))

    # ---- settings saved from the UI -------------------------------------
    def get_overrides(self) -> dict[str, Any]:
        with self._conn() as c:
            return {k: json.loads(v) for k, v in c.execute("SELECT key, value FROM settings")}

    def set_overrides(self, changes: dict[str, Any]) -> None:
        """Save values; a None value removes the override (back to the environment value)."""
        with self._conn() as c:
            for k, v in changes.items():
                if v is None:
                    c.execute("DELETE FROM settings WHERE key = ?", (k,))
                else:
                    c.execute("INSERT INTO settings (key, value) VALUES (?, ?)"
                              " ON CONFLICT(key) DO UPDATE SET value = excluded.value", (k, json.dumps(v)))

    # ---- analyses ------------------------------------------------------
    def save_analysis(self, a: dict[str, Any]) -> int:
        row = {k: a.get(k) for k in ("video_id", "url", "title", "channel", "thumbnail", "duration",
                                     "published_at", "summary", "provider", "model")}
        row["has_transcript"] = int(bool(a.get("has_transcript")))
        row["created_at"] = now_iso()
        cols = ", ".join(row)
        with self._conn() as c:
            return c.execute(f"INSERT INTO analyses ({cols}) VALUES ({', '.join('?' * len(row))})",
                             list(row.values())).lastrowid

    def list_analyses(self, limit: int = 50, offset: int = 0) -> list[dict]:
        with self._conn() as c:
            rows = c.execute("SELECT * FROM analyses ORDER BY id DESC LIMIT ? OFFSET ?", (limit, offset))
            return [dict(r, has_transcript=bool(r["has_transcript"])) for r in rows]

    def delete_analysis(self, analysis_id: int) -> bool:
        with self._conn() as c:
            return c.execute("DELETE FROM analyses WHERE id = ?", (analysis_id,)).rowcount > 0

    # ---- migration -----------------------------------------------------
    def import_legacy_json(self, json_path: Path) -> int:
        """Import the old data/subscriptions.json once, then rename it."""
        if not json_path.exists():
            return 0
        try:
            items = json.loads(json_path.read_text() or "[]")
        except json.JSONDecodeError:
            log.error("Could not parse %s; leaving it in place", json_path)
            return 0
        n = 0
        with self._conn() as c:
            for s in items:
                if not s.get("active", True):
                    continue
                cur = c.execute(
                    "INSERT OR IGNORE INTO subscriptions (id, channel_url, channel_name, email, created_at,"
                    " last_checked) VALUES (?, ?, ?, ?, ?, ?)",
                    (s.get("id") or str(uuid.uuid4()), s["channel_url"], s.get("channel_name") or s["channel_url"],
                     s["user_email"].strip(), s.get("created_at") or now_iso(), s.get("last_checked")))
                n += cur.rowcount
        json_path.rename(json_path.with_suffix(".json.imported"))
        log.info("Imported %d subscriptions from %s", n, json_path)
        return n


def _sub(row: sqlite3.Row) -> dict:
    d = dict(row)
    d["active"] = bool(d["active"])
    return d
