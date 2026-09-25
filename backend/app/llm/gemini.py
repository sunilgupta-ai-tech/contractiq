"""Gemini provider — optional hosted LLM. The key is read from backend
settings only; verify current pricing, quotas and model availability before
production use."""

from __future__ import annotations

import time

import httpx

from app.llm.base import ChatMessage, LLMResult

_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"


class GeminiProvider:
    name = "gemini"

    def __init__(self, api_key: str, model: str, timeout_s: float = 60.0) -> None:
        self.model = model
        # Key goes in a header, not the URL, so it never lands in access logs.
        self._client = httpx.AsyncClient(
            base_url=_BASE_URL, timeout=timeout_s, headers={"x-goog-api-key": api_key}
        )

    async def generate(
        self, messages: list[ChatMessage], *, temperature: float = 0.0, max_tokens: int = 1024
    ) -> LLMResult:
        started = time.perf_counter()
        system = "\n\n".join(m.content for m in messages if m.role == "system")
        contents = [
            {"role": "model" if m.role == "assistant" else "user", "parts": [{"text": m.content}]}
            for m in messages
            if m.role != "system"
        ]
        payload: dict[str, object] = {
            "contents": contents,
            "generationConfig": {"temperature": temperature, "maxOutputTokens": max_tokens},
        }
        if system:
            payload["systemInstruction"] = {"parts": [{"text": system}]}
        response = await self._client.post(f"/models/{self.model}:generateContent", json=payload)
        response.raise_for_status()
        body = response.json()
        usage = body.get("usageMetadata", {})
        return LLMResult(
            text=body["candidates"][0]["content"]["parts"][0]["text"],
            model=self.model,
            prompt_tokens=usage.get("promptTokenCount"),
            completion_tokens=usage.get("candidatesTokenCount"),
            latency_ms=round((time.perf_counter() - started) * 1000, 2),
        )
