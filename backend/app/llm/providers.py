"""Ollama (local), OpenAI(-compatible) and Claude/Anthropic(-compatible) providers behind one interface."""

import anthropic
import ollama
import openai

from ..config import Settings
from .base import LLMError, LLMProvider, NotConfigured

# Local OpenAI/Anthropic-compatible servers (LM Studio, vLLM, llama.cpp, ...) often need no key,
# but the SDKs refuse to start without one.
_NO_KEY = "not-needed"


class OllamaProvider(LLMProvider):
    name = "ollama"
    base_url = None

    def __init__(self, s: Settings):
        self.model, self.host, self.num_ctx = s.ollama_model, s.ollama_host, s.ollama_num_ctx
        self._client = ollama.AsyncClient(host=self.host, timeout=s.llm_timeout_seconds)

    @property
    def configured(self) -> bool:
        return bool(self.host and self.model)

    async def complete(self, system: str, prompt: str) -> str:
        try:
            r = await self._client.chat(
                model=self.model,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": prompt}],
                options={"num_ctx": self.num_ctx},
            )
        except ollama.ResponseError as e:
            hint = f" (try `ollama pull {self.model}`)" if e.status_code == 404 else ""
            raise LLMError(f"Ollama error: {e.error}{hint}") from e
        except Exception as e:  # connection refused, timeout, ...
            raise LLMError(f"Cannot reach Ollama at {self.host}: {e}") from e
        return r.message.content or ""

    async def check(self) -> str | None:
        try:
            listed = await self._client.list()
        except Exception as e:
            raise LLMError(f"Cannot reach Ollama at {self.host}: {e}") from e
        names = {m.model for m in listed.models}
        if self.model not in names and f"{self.model}:latest" not in names:
            raise LLMError(f"Model {self.model!r} is not pulled on {self.host}")
        return None


async def _check_model(client, model: str, sdk, label: str) -> str | None:
    """Verify the model exists. Many compatible servers lack GET /models/{id}, so fall back
    to listing models, and accept servers that cannot list models at all."""
    try:
        await client.models.retrieve(model)
        return None
    except sdk.AuthenticationError as e:
        raise LLMError(f"{label} rejected the API key") from e
    except (sdk.NotFoundError, sdk.UnprocessableEntityError, sdk.BadRequestError, sdk.APIStatusError):
        pass  # try listing instead
    except sdk.APIConnectionError as e:
        raise LLMError(f"Cannot reach {label}: {e}") from e
    except sdk.APIError as e:
        raise LLMError(f"{label}: {e}") from e
    try:
        ids = [m.id async for m in client.models.list()]
    except sdk.AuthenticationError as e:
        raise LLMError(f"{label} rejected the API key") from e
    except sdk.APIConnectionError as e:
        raise LLMError(f"Cannot reach {label}: {e}") from e
    except sdk.APIStatusError:
        return "Connected, but this server can't list models, so the model name wasn't checked"
    if model not in ids:
        sample = ", ".join(ids[:5]) + (" …" if len(ids) > 5 else "")
        raise LLMError(f"Model {model!r} not found on {label}" + (f" (available: {sample})" if ids else ""))
    return None


class OpenAIProvider(LLMProvider):
    name = "openai"

    def __init__(self, s: Settings):
        self.model, self.base_url = s.openai_model, s.openai_base_url
        key = s.openai_api_key or (_NO_KEY if self.base_url else None)
        self._client = (openai.AsyncOpenAI(api_key=key, base_url=self.base_url, timeout=s.llm_timeout_seconds)
                        if key else None)
        self.label = f"the server at {self.base_url}" if self.base_url else "OpenAI"

    @property
    def configured(self) -> bool:
        return self._client is not None

    async def complete(self, system: str, prompt: str) -> str:
        if not self._client:
            raise NotConfigured("OPENAI_API_KEY is not set")
        try:
            r = await self._client.chat.completions.create(
                model=self.model,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": prompt}],
                max_completion_tokens=4096,
            )
        except openai.APIStatusError as e:
            raise LLMError(f"{self.label} error {e.status_code}: {e.message}") from e
        except openai.APIConnectionError as e:
            raise LLMError(f"Cannot reach {self.label}: {e}") from e
        if not r.choices:
            raise LLMError(f"{self.label} returned no choices")
        return r.choices[0].message.content or ""

    async def check(self) -> str | None:
        if not self._client:
            raise NotConfigured("OPENAI_API_KEY is not set")
        return await _check_model(self._client, self.model, openai, self.label)


class ClaudeProvider(LLMProvider):
    name = "claude"

    def __init__(self, s: Settings):
        self.model, self.effort, self.base_url = s.claude_model, s.claude_effort, s.anthropic_base_url
        key = s.anthropic_api_key or (_NO_KEY if self.base_url else None)
        self._client = (anthropic.AsyncAnthropic(api_key=key, base_url=self.base_url, timeout=s.llm_timeout_seconds)
                        if key else None)
        self.label = f"the server at {self.base_url}" if self.base_url else "Claude"

    @property
    def configured(self) -> bool:
        return self._client is not None

    async def complete(self, system: str, prompt: str) -> str:
        if not self._client:
            raise NotConfigured("ANTHROPIC_API_KEY is not set")
        try:
            msg = await self._client.messages.create(
                model=self.model,
                max_tokens=8000,
                system=system,
                messages=[{"role": "user", "content": prompt}],
                output_config={"effort": self.effort},
            )
        except anthropic.AuthenticationError as e:
            raise LLMError(f"{self.label} rejected the API key (check ANTHROPIC_API_KEY)") from e
        except anthropic.NotFoundError as e:
            raise LLMError(f"Model {self.model!r} not found on {self.label}") from e
        except anthropic.RateLimitError as e:
            raise LLMError(f"{self.label} rate limit reached; try again shortly") from e
        except anthropic.APIStatusError as e:
            raise LLMError(f"{self.label} error {e.status_code}: {e.message}") from e
        except anthropic.APIConnectionError as e:
            raise LLMError(f"Cannot reach {self.label}: {e}") from e
        if msg.stop_reason == "refusal":
            raise LLMError("Claude declined to summarize this video")
        text = "".join(b.text for b in msg.content if b.type == "text")
        if msg.stop_reason == "max_tokens":
            text += "\n\n_(summary cut off at the length limit)_"
        return text

    async def check(self) -> str | None:
        if not self._client:
            raise NotConfigured("ANTHROPIC_API_KEY is not set")
        return await _check_model(self._client, self.model, anthropic, self.label)
