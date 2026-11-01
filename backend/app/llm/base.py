from abc import ABC, abstractmethod


class LLMError(Exception):
    """Any failure to produce a summary. The message is safe to show to the user."""


class NotConfigured(LLMError):
    pass


SYSTEM_PROMPT = (
    "You summarize YouTube videos for a busy reader. Write in clear, plain English "
    "using GitHub-flavored markdown. Be concrete: name the actual claims, numbers, tools "
    "and steps from the video rather than describing it in general terms. If only the "
    "title and description are available, say so briefly and keep the summary short. "
    "Never invent details that are not in the provided material."
)


def build_prompt(video: dict) -> str:
    transcript = (video.get("transcript") or "").strip()
    parts = [
        f"Title: {video.get('title', 'Unknown')}",
        f"Channel: {video.get('channel') or 'Unknown'}",
        f"Duration: {video.get('duration') or 'Unknown'}",
        f"Description:\n{video.get('description') or '(none)'}",
    ]
    if transcript:
        parts.append(f"Transcript:\n<transcript>\n{transcript}\n</transcript>")
    source = "the transcript (primary source) and metadata" if transcript else "the title and description only"
    return (
        "\n\n".join(parts)
        + f"\n\nSummarize this video from {source}. Use exactly these sections:\n\n"
        "## Summary\nTwo or three sentences on what the video covers and its main conclusion.\n\n"
        "## Key points\n3–7 bullets with the substantive points, in the order they appear.\n\n"
        "## Takeaways\n1–4 bullets: what a viewer should remember or do.\n\n"
        "## Worth watching if\nOne sentence on who would get the most out of it.\n\n"
        "Stay under 400 words."
    )


class LLMProvider(ABC):
    name: str
    model: str

    @property
    @abstractmethod
    def configured(self) -> bool: ...

    @abstractmethod
    async def complete(self, system: str, prompt: str) -> str: ...

    @abstractmethod
    async def check(self) -> str | None:
        """Raise LLMError if unreachable or misconfigured; may return an informational note."""

    async def summarize(self, video: dict) -> str:
        if not self.configured:
            raise NotConfigured(f"{self.name} is not configured")
        text = (await self.complete(SYSTEM_PROMPT, build_prompt(video))).strip()
        if not text:
            raise LLMError(f"{self.name} returned an empty response")
        return text
