"""Subscription checks and digest emails.

New videos are detected by ID ("not yet seen for this subscription"), not by
comparing dates, and a video only becomes "seen" after its email was sent.
"""

import asyncio
import logging
from collections import defaultdict
from datetime import UTC, datetime, timedelta

from .config import Settings
from .db import Database
from .llm import LLMError, Registry
from .mailer import EmailError, Mailer
from .youtube import YouTubeClient

log = logging.getLogger(__name__)

MAX_NEW_PER_CHANNEL = 15  # beyond this, older new videos are listed without fetching details
BASELINE_LOOKBACK = 5     # for subscriptions with no history: how many recent videos to inspect


class AlreadyRunning(Exception):
    pass


class RunLog:
    def __init__(self):
        self.lines: list[str] = []

    def __call__(self, msg: str, *args, level=logging.INFO) -> None:
        text = msg % args if args else msg
        log.log(level, text)
        self.lines.append(f"{datetime.now(UTC):%H:%M:%S} {text}")

    def text(self) -> str:
        return "\n".join(self.lines[-400:])


class Notifier:
    def __init__(self, s: Settings, db: Database, yt: YouTubeClient, llm: Registry, mailer: Mailer):
        self.s, self.db, self.yt, self.llm, self.mailer = s, db, yt, llm, mailer
        self._lock = asyncio.Lock()
        self._tasks: set[asyncio.Task] = set()

    @property
    def running(self) -> bool:
        return self._lock.locked()

    def start(self, trigger: str) -> int:
        """Create a run row and process it in the background. Returns the run id."""
        if self._lock.locked():
            raise AlreadyRunning("A check is already running")
        run_id = self.db.start_run(trigger)
        task = asyncio.create_task(self.run(run_id))
        self._tasks.add(task)  # keep a reference so the task isn't garbage-collected
        task.add_done_callback(self._tasks.discard)
        return run_id

    async def scheduled(self) -> None:
        try:
            self.start("schedule")
        except AlreadyRunning:
            log.warning("Scheduled check skipped: previous check still running")

    async def run(self, run_id: int) -> None:
        if self._lock.locked():
            self.db.finish_run(run_id, status="skipped", videos_found=0, emails_sent=0,
                               log_text="Another check was already running")
            return
        async with self._lock:
            rl, found, sent, failures = RunLog(), 0, 0, 0
            try:
                by_email: dict[str, list[dict]] = defaultdict(list)
                for sub in self.db.list_subscriptions():
                    by_email[sub["email"].lower()].append(sub)
                rl("Checking %d subscriptions for %d recipients",
                   sum(map(len, by_email.values())), len(by_email))
                for subs in by_email.values():
                    f, ok, errs = await self._process_recipient(subs[0]["email"], subs, rl)
                    found, sent, failures = found + f, sent + ok, failures + errs
                status = "ok" if not failures else ("partial" if sent else "error")
            except Exception as e:
                log.exception("Run %s crashed", run_id)
                rl("Run failed: %s", e, level=logging.ERROR)
                status = "error"
            self.db.finish_run(run_id, status=status, videos_found=found, emails_sent=sent,
                               log_text=rl.text())

    async def _process_recipient(self, email: str, subs: list[dict], rl: RunLog) -> tuple[int, int, int]:
        channels, to_mark, checked_ok, errors = [], {}, [], 0
        for sub in subs:
            try:
                new_videos, seen_ids = await self._check_subscription(sub, rl)
            except Exception as e:
                errors += 1
                rl("  %s: check failed: %s", sub["channel_name"], e, level=logging.WARNING)
                self.db.mark_checked(sub["id"], error=str(e)[:500])
                continue
            to_mark[sub["id"]] = seen_ids
            checked_ok.append(sub["id"])
            if new_videos:
                channels.append({
                    "name": sub["channel_name"], "url": sub["channel_url"].removesuffix("/videos"),
                    "videos": new_videos, "new_count": len(new_videos),
                    "ai_count": sum(1 for v in new_videos if v.get("ai")),
                    "ai_limit": self.s.max_ai_summaries_per_channel,
                    "since": self._since_label(sub.get("last_checked") or sub.get("created_at")),
                })

        found = sum(len(c["videos"]) for c in channels)
        sent = 0
        if channels:
            date_label = datetime.now(self.s.tz).strftime("%A, %B %-d, %Y")
            subject, text, html = self.mailer.render_digest(channels, date_label=date_label)
            try:
                await self.mailer.send(email, subject, text, html)
                sent = 1
                rl("  Emailed %s: %s", email, subject)
            except EmailError as e:
                errors += 1
                rl("  Email to %s failed: %s (videos will be retried next run)", email, e,
                   level=logging.ERROR)
                for sid in checked_ok:
                    self.db.mark_checked(sid, error=f"Email failed: {e}"[:500])
                return found, 0, errors
        else:
            rl("  %s: nothing new", email)

        for sid in checked_ok:
            self.db.mark_seen(sid, to_mark[sid])
            self.db.mark_checked(sid)
        return found, sent, errors

    async def _check_subscription(self, sub: dict, rl: RunLog) -> tuple[list[dict], list[str]]:
        """Return (new videos ready for the email, ids to mark seen once the email is sent)."""
        listing = await self.yt.list_channel(sub["channel_url"], limit=self.s.channel_scan_limit)
        entries = listing["entries"]
        seen = self.db.seen_ids(sub["id"])

        if not seen:
            candidates, cutoff = await self._baseline_candidates(sub, entries)
            rl("  %s: first check, %d video(s) since %s", sub["channel_name"], len(candidates),
               cutoff.isoformat(timespec="minutes"))
        else:
            candidates = []
            for e in entries:  # newest first; stop at the first one already handled
                if e["id"] in seen:
                    break
                candidates.append(e)
            rl("  %s: %d new", sub["channel_name"], len(candidates))

        new_videos, mark = [], [e["id"] for e in entries if e["id"] in seen or not seen]
        ai_budget = self.s.max_ai_summaries_per_channel
        for i, e in enumerate(candidates):
            if i >= MAX_NEW_PER_CHANNEL:
                new_videos.append({**e, "published_date": "", "duration": "", "thumbnail": "",
                                   "summary": None, "ai": False})
                mark.append(e["id"])
                continue
            v = e.get("_full") or await self.yt.get_video(e["url"], self.s.tz, with_transcript=ai_budget > 0)
            if v.get("live_status") in ("is_upcoming", "is_live"):
                # Not watchable yet: don't mark seen, report it once it has aired.
                if e["id"] in mark:
                    mark.remove(e["id"])
                continue
            v.update(summary=None, summary_error=None, ai=False)
            if ai_budget > 0:
                ai_budget -= 1
                try:
                    v["summary"] = await self.llm.get().summarize(v)
                    v["ai"] = True
                except LLMError as err:
                    v["summary_error"] = str(err)
                    rl("    summary failed for %s: %s", v["title"], err, level=logging.WARNING)
            new_videos.append(v)
            mark.append(e["id"])
        return new_videos, list(dict.fromkeys(mark))

    async def _baseline_candidates(self, sub: dict, entries: list[dict]) -> tuple[list[dict], datetime]:
        """No seen history (e.g. imported from the old JSON store): use publish time
        against last_checked, looking at a handful of the newest videos only."""
        ref = sub.get("last_checked")
        cutoff = datetime.fromisoformat(ref) if ref else datetime.now(UTC) - timedelta(hours=24)
        if cutoff.tzinfo is None:
            cutoff = cutoff.replace(tzinfo=UTC)
        out, budget = [], self.s.max_ai_summaries_per_channel
        for e in entries[:BASELINE_LOOKBACK]:
            v = await self.yt.get_video(e["url"], self.s.tz, with_transcript=len(out) < budget)
            pub = v.get("published_at")
            if pub and datetime.fromisoformat(pub) <= cutoff:
                break
            out.append({**e, "_full": v})
        return out, cutoff

    def _since_label(self, iso: str | None) -> str | None:
        """'Thu, Oct 30, 9:00 AM' in the configured timezone."""
        if not iso:
            return None
        dt = datetime.fromisoformat(iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt.astimezone(self.s.tz).strftime("%a, %b %-d, %-I:%M %p")

    async def send_test_email(self, to: str) -> None:
        sample = [{"name": "Test channel", "url": self.s.app_url, "videos": [{
            "title": "Your email settings work", "url": self.s.app_url, "published_date": "today",
            "duration": "0:42", "thumbnail": "", "ai": True, "has_transcript": False,
            "summary": "## Summary\nThis is a **test** message from YouTube Digest. "
                       "If you can read it, SMTP is configured correctly.",
        }], "new_count": 1, "ai_count": 1, "ai_limit": self.s.max_ai_summaries_per_channel, "since": None}]
        subject, text, html = self.mailer.render_digest(sample, date_label="Test message")
        await self.mailer.send(to, "Test: " + subject, text, html)
