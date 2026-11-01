"""Effective settings (environment + values saved from the Settings page) and applying them live."""

import logging
import os
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from pydantic import ValidationError

from .config import EDITABLE, SECRETS, Settings
from .db import Database
from .llm import Registry
from .mailer import Mailer

log = logging.getLogger(__name__)

# Environment variable names per field, where they differ from FIELD_NAME.upper().
ENV_NAMES = {"schedule_times": ("SCHEDULE_TIMES", "SCHEDULE_TIME")}


class SettingsError(ValueError):
    def __init__(self, fields: dict[str, str]):
        self.fields = fields
        super().__init__("; ".join(f"{k}: {v}" for k, v in fields.items()))


def build(overrides: dict[str, Any]) -> Settings:
    """Settings with overrides on top of the environment. Raises SettingsError per field."""
    try:
        return Settings(**{k: v for k, v in overrides.items() if k in EDITABLE})
    except ValidationError as e:
        fields = {}
        for err in e.errors():
            field = str(err["loc"][0]).lower() if err["loc"] else "settings"
            fields[field] = err["msg"].removeprefix("Value error, ")
        raise SettingsError(fields) from e


def load(db: Database) -> Settings:
    """Startup: never refuse to start because a saved value became invalid; drop it instead."""
    overrides = db.get_overrides()
    try:
        return build(overrides)
    except SettingsError as e:
        log.error("Ignoring invalid saved settings: %s", e)
        db.set_overrides({k: None for k in e.fields if k in overrides})
        return build(db.get_overrides())


def describe(s: Settings, overrides: dict[str, Any]) -> dict:
    """Payload for GET /api/settings. Secrets are reported only as set / not set."""
    def source(field: str) -> str:
        if field in overrides:
            return "ui"
        names = ENV_NAMES.get(field, (field.upper(),))
        return "env" if any(os.environ.get(n) for n in names) else "default"

    return {
        "values": {f: getattr(s, f) for f in sorted(EDITABLE)},
        "source": {f: source(f) for f in sorted(EDITABLE)},
        "secrets_set": {k: bool(getattr(s, k)) for k in SECRETS},
    }


def schedule(scheduler: AsyncIOScheduler, notifier, s: Settings) -> None:
    scheduler.remove_all_jobs()
    if not s.scheduler_enabled:
        return
    for t in s.parsed_schedule_times:
        scheduler.add_job(notifier.scheduled, CronTrigger(hour=t.hour, minute=t.minute, timezone=s.tz),
                          id=f"check-{t:%H%M}", misfire_grace_time=3600, coalesce=True)
    if not scheduler.running:
        scheduler.start()
    for job in scheduler.get_jobs():
        log.info("scheduler: next run %s", job.next_run_time.isoformat() if job.next_run_time else "-")


def apply(state, s: Settings) -> None:
    """Swap in new settings without a restart (a check already running uses them for its remaining steps)."""
    state.settings = s
    state.llm = Registry(s)
    state.mailer = Mailer(s)
    state.yt.transcript_max_chars = s.transcript_max_chars
    n = state.notifier
    n.s, n.llm, n.mailer = s, state.llm, state.mailer
    schedule(state.scheduler, n, s)
