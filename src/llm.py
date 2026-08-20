"""The only place that talks to a model provider.

Two SPEC constraints meet here. **§2**: provider access sits behind one thin interface, so
swapping providers is a one-file change — a demo talking point ("are we locked into OpenAI?"),
so it has to be genuinely true. **§5.2**: exactly one call produces an answer, and there is one
call site in the answer path, which is what makes the constraint checkable.

Eval-time calls are exempt but never routed through the answer path — `src/eval/summarize.py` is
the one that exists, and `tests/test_ask.py` names it.
"""

from __future__ import annotations

from typing import Protocol

from src.config import settings


class ProviderNotConfigured(RuntimeError):
    """No provider credentials are present.

    Deliberately an error rather than a canned answer. A fabricated reply that
    reads as real is worse than a failure that says what is wrong.
    """


class LLM(Protocol):
    """Turns one system + user prompt into one answer. One call, one answer."""

    def complete(self, *, system: str, user: str) -> str: ...


class OpenAILLM:
    """OpenAI chat completions. The single provider implementation."""

    def __init__(self, *, api_key: str | None, base_url: str | None, model: str) -> None:
        import openai

        self._model = model
        # A local OpenAI-compatible server (LM Studio / vLLM / LiteLLM) needs no
        # real key, but the SDK requires the argument to be present.
        self._client = openai.OpenAI(api_key=api_key or "not-needed", base_url=base_url)

    def complete(self, *, system: str, user: str) -> str:
        response = self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        return response.choices[0].message.content or ""


def build_llm() -> LLM:
    """The configured provider, or an error naming what is missing."""
    config = settings()
    if not config.provider_configured:
        raise ProviderNotConfigured(
            "No LLM provider is configured. Set OPENAI_API_KEY, or OPENAI_BASE_URL "
            "to point at an OpenAI-compatible server."
        )
    return OpenAILLM(
        api_key=config.openai_api_key,
        base_url=config.openai_base_url,
        model=config.generation_model,
    )
