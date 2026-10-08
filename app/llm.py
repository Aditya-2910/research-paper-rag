"""
LLM provider switch. Same calling code regardless of backend — config
decides which one runs:

  LLM_PROVIDER=ollama   -> local, via Ollama's REST API, no network needed
  LLM_PROVIDER=groq     -> hosted, via Groq's OpenAI-compatible API

Both are "free" in the sense that matters here: Ollama costs nothing and
runs fully offline; Groq has a generous free tier. Swap by editing .env,
no code changes.
"""
from __future__ import annotations

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from app.config import settings


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=2, max=20))
def _generate_ollama(prompt: str, system: str | None = None) -> str:
    payload = {
        "model": settings.ollama_model,
        "prompt": prompt,
        "stream": False,
    }
    if system:
        payload["system"] = system

    resp = httpx.post(
        f"{settings.ollama_base_url}/api/generate",
        json=payload,
        timeout=120.0,
    )
    resp.raise_for_status()
    return resp.json()["response"].strip()


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=2, max=20))
def _generate_groq(prompt: str, system: str | None = None) -> str:
    if not settings.groq_api_key:
        raise RuntimeError("GROQ_API_KEY is not set in .env but LLM_PROVIDER=groq")

    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    resp = httpx.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={"Authorization": f"Bearer {settings.groq_api_key}"},
        json={"model": settings.groq_model, "messages": messages, "temperature": 0.2},
        timeout=60.0,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"].strip()


def generate(prompt: str, system: str | None = None) -> str:
    if settings.llm_provider == "groq":
        return _generate_groq(prompt, system)
    return _generate_ollama(prompt, system)
