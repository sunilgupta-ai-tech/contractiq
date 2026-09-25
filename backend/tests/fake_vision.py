"""
A deterministic stand-in for the vision model (Gemini/Ollama) in tests.

Replies in the format the image prompt asks for when an image is attached,
and with a one-line summary for a table prompt, so captioning, table
summaries and caption chunks can be tested without network or API keys.
"""

from __future__ import annotations

from app.llm.base import ChatMessage, LLMResult

CAPTION = "Bar chart of monthly service credits; the highest value is 5% in March."
TABLE_SUMMARY = "Payment milestones with the week each is due and its fee."


class FakeVision:
    name = "fake"
    model = "fake-vlm"

    def __init__(self, reply: str | None = None) -> None:
        self.reply = reply  # overrides the image reply when set
        self.calls: list[list[ChatMessage]] = []

    async def generate(
        self, messages: list[ChatMessage], *, temperature: float = 0.0, max_tokens: int = 1024
    ) -> LLMResult:
        self.calls.append(messages)
        if any(m.images for m in messages):
            text = self.reply or f"KIND: chart\nDESCRIPTION: {CAPTION}"
        else:
            text = TABLE_SUMMARY
        return LLMResult(text=text, model=self.model)

    async def aclose(self) -> None:
        return None

    @property
    def image_calls(self) -> int:
        return sum(1 for call in self.calls if any(m.images for m in call))
