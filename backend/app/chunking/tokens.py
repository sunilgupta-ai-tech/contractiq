"""
Token estimation for chunk sizing.

Why an estimate instead of a real tokenizer
-------------------------------------------
Each embedding model tokenizes differently (nomic-embed-text, Gemini, ...),
and the model is configurable. Tying chunk sizes to one tokenizer would
silently change chunking whenever the model changes, and would add a heavy
dependency to the worker.

Instead we use a deliberately *conservative* estimate — about 4 characters
per token, which slightly over-counts for English legal prose. Over-counting
means chunks come out a little smaller than the limit, never larger, so they
always fit the embedding model's input window.
"""

from __future__ import annotations

import math

CHARS_PER_TOKEN = 4.0


def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return math.ceil(len(text) / CHARS_PER_TOKEN)
