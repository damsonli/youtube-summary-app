import asyncio

from ..config import Provider, Settings
from .base import LLMError, LLMProvider, NotConfigured, build_prompt
from .providers import ClaudeProvider, OllamaProvider, OpenAIProvider

__all__ = ["LLMError", "LLMProvider", "NotConfigured", "Registry", "build_prompt", "build_provider", "check_status"]

PROVIDERS = {"ollama": OllamaProvider, "openai": OpenAIProvider, "claude": ClaudeProvider}
CHECK_TIMEOUT = 10


def build_provider(name: str, s: Settings) -> LLMProvider:
    if name not in PROVIDERS:
        raise NotConfigured(f"Unknown provider {name!r}")
    return PROVIDERS[name](s)


async def check_status(p: LLMProvider) -> dict:
    """Live health of one provider: {'status': ok|error|not_configured, 'detail': str|None}."""
    if not p.configured:
        return {"status": "not_configured", "detail": None}
    try:
        note = await asyncio.wait_for(p.check(), timeout=CHECK_TIMEOUT)
        return {"status": "ok", "detail": note}
    except TimeoutError:
        return {"status": "error", "detail": f"No answer within {CHECK_TIMEOUT}s"}
    except LLMError as e:
        return {"status": "error", "detail": str(e)}


class Registry:
    """All three providers, built from one Settings; `default` is LLM_SERVICE."""

    def __init__(self, s: Settings):
        self.default: Provider = s.llm_service
        self.providers: dict[str, LLMProvider] = {n: cls(s) for n, cls in PROVIDERS.items()}

    def get(self, name: str | None = None) -> LLMProvider:
        p = self.providers.get(name or self.default)
        if p is None:
            raise NotConfigured(f"Unknown provider {name!r}")
        if not p.configured:
            raise NotConfigured(f"{p.name} is not configured on the server")
        return p

    async def status(self) -> list[dict]:
        async def one(name: str, p: LLMProvider) -> dict:
            item = {"name": name, "model": p.model, "default": name == self.default,
                    "configured": p.configured, "base_url": p.base_url}
            if name == "ollama":
                item["host"] = p.host
            return item | await check_status(p)

        return list(await asyncio.gather(*(one(n, p) for n, p in self.providers.items())))
