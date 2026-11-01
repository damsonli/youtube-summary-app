"""SMTP sending and digest rendering."""

import asyncio
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import make_msgid
from pathlib import Path

import markdown as md
from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup

from .config import Settings

_env = Environment(
    loader=FileSystemLoader(Path(__file__).parent / "templates"),
    autoescape=select_autoescape(["html"]),
    trim_blocks=True, lstrip_blocks=True,
)


def markdown_to_safe_html(text: str) -> Markup:
    # LLM output is untrusted: neutralise raw HTML before rendering markdown.
    # ('>' is left alone so markdown blockquotes still work.)
    escaped = (text or "").replace("&", "&amp;").replace("<", "&lt;")
    return Markup(md.markdown(escaped, extensions=["sane_lists"]))


_env.filters["markdown"] = markdown_to_safe_html


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def channel_note(c: dict) -> str:
    """'7 new videos since Thu, Oct 30, 9:00 AM. The newest 3 have AI summaries; ...'"""
    n = c.get("new_count", len(c["videos"]))
    limit = c.get("ai_limit", 0)
    text = _plural(n, "new video") + (f" since {c['since']}." if c.get("since") else ".")
    if limit == 0:
        text += " AI summaries are turned off in Settings, so videos are listed with their descriptions."
    elif n > limit:
        text += (f" The newest {limit} {'has an AI summary' if limit == 1 else 'have AI summaries'}"
                 f" (your limit per channel); the other {n - limit} {'is' if n - limit == 1 else 'are'}"
                 " listed with their descriptions.")
    return text


class EmailError(Exception):
    pass


class Mailer:
    def __init__(self, s: Settings):
        self.s = s

    def render_digest(self, channels: list[dict], *, date_label: str) -> tuple[str, str, str]:
        """channels: [{'name','url','videos':[...], 'new_count','ai_count','ai_limit','since'}]"""
        total = sum(c.get("new_count", len(c["videos"])) for c in channels)
        names = [c["name"] for c in channels]
        who = ", ".join(names[:2]) + (f" and {len(names) - 2} more" if len(names) > 2 else "")
        subject = f"{total} new video{'s' if total != 1 else ''} from {who}"
        headline = (f"{_plural(total, 'new video')} from {_plural(len(channels), 'channel')} since your last digest"
                    if len(channels) > 1 else f"{_plural(total, 'new video')} from {names[0]}")
        for c in channels:
            c["note"] = channel_note(c)
        ctx = {"channels": channels, "total": total, "headline": headline, "date_label": date_label,
               "app_url": self.s.app_url}
        return subject, _env.get_template("digest.txt").render(ctx), _env.get_template("digest.html").render(ctx)

    async def send(self, to: str, subject: str, text: str, html: str | None = None) -> None:
        if not self.s.email_configured:
            raise EmailError("Email is not configured (set EMAIL_USER, EMAIL_PASSWORD, FROM_EMAIL)")
        msg = EmailMessage()
        msg["Subject"], msg["From"], msg["To"] = subject, self.s.sender, to
        msg["Message-ID"] = make_msgid(domain=self.s.sender.split("@")[-1])
        msg.set_content(text)
        if html:
            msg.add_alternative(html, subtype="html")
        try:
            await asyncio.to_thread(self._send_sync, msg)
        except smtplib.SMTPAuthenticationError as e:
            raise EmailError("SMTP login failed. For Gmail use an App Password, not your normal password"
                             f" ({e.smtp_code})") from e
        except (smtplib.SMTPException, OSError) as e:
            raise EmailError(f"SMTP error via {self.s.smtp_server}:{self.s.smtp_port}: {e}") from e

    def _send_sync(self, msg: EmailMessage) -> None:
        s = self.s
        ctx = ssl.create_default_context()
        if s.smtp_security == "ssl":
            server = smtplib.SMTP_SSL(s.smtp_server, s.smtp_port, context=ctx, timeout=30)
        else:
            server = smtplib.SMTP(s.smtp_server, s.smtp_port, timeout=30)
        with server:
            if s.smtp_security == "starttls":
                server.starttls(context=ctx)
            server.login(s.email_user, s.email_password)
            server.send_message(msg)
