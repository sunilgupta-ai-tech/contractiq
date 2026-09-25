"""Ollama provider — local, zero-cost LLM and embeddings for development."""

from __future__ import annotations

import time

import httpx

from app.llm.base import ChatMessage, LLMResult


class OllamaProvider:
    name = "ollama"

    def __init__(self, base_url: str, model: str, timeout_s: float = 120.0) -> None:
        self.model = model
        self._client = httpx.AsyncClient(base_url=base_url, timeout=timeout_s)

    async def generate(
        self, messages: list[ChatMessage], *, temperature: float = 0.0, max_tokens: int = 1024
    ) -> LLMResult:
        started = time.perf_counter()
        response = await self._client.post(
            "/api/chat",
            json={
                "model": self.model,
                "messages": [{"role": m.role, "content": m.content} for m in messages],
                "stream": False,
                "options": {"temperature": temperature, "num_predict": max_tokens},
            },
        )
        response.raise_for_status()
        body = response.json()
        return LLMResult(
            text=body["message"]["content"],
            model=self.model,
            prompt_tokens=body.get("prompt_eval_count"),
            completion_tokens=body.get("eval_count"),
            latency_ms=round((time.perf_counter() - started) * 1000, 2),
        )


class OllamaEmbeddings:
    name = "ollama"

    def __init__(self, base_url: str, model: str, dimension: int) -> None:
        self.model = model
        self.dimension = dimension
        self._client = httpx.AsyncClient(base_url=base_url, timeout=60.0)

    async def embed(self, texts: list[str]) -> list[list[float]]:
        response = await self._client.post("/api/embed", json={"model": self.model, "input": texts})
        response.raise_for_status()
        return response.json()["embeddings"]  # type: ignore[no-any-return]
