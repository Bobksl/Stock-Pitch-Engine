"""Thin wrapper around any OpenAI-compatible chat API.

One place to configure the generation model. Works with any provider that speaks the
OpenAI chat-completions protocol — DeepSeek, OpenAI, OpenRouter, Groq, Together, Mistral,
or a local server (Ollama, LM Studio, vLLM). Pick the provider entirely in .env
(LLM_BASE_URL / LLM_MODEL / LLM_API_KEY); no code changes needed to switch.
"""
from openai import OpenAI

from src.config import LLM_API_KEY, LLM_BASE_URL, LLM_MAX_TOKENS, LLM_MODEL

_client: OpenAI | None = None


def get_client() -> OpenAI:
    global _client
    if _client is None:
        # Some local servers (e.g. Ollama) ignore the key but the SDK still needs a non-empty string.
        _client = OpenAI(api_key=LLM_API_KEY or "not-needed", base_url=LLM_BASE_URL)
    return _client


def complete(messages: list[dict], temperature: float = 0.2, max_tokens: int | None = None):
    """Return the raw chat-completion response (use when you need .usage etc.)."""
    return get_client().chat.completions.create(
        model=LLM_MODEL,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens or LLM_MAX_TOKENS,
    )


def chat(messages: list[dict], temperature: float = 0.2, max_tokens: int | None = None) -> str:
    """Return just the assistant's text."""
    return (complete(messages, temperature, max_tokens).choices[0].message.content or "").strip()
