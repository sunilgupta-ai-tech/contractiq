"""Helpers shared by LLM/embedding providers: error mapping and normalisation."""

from __future__ import annotations

import math

import httpx

from app.llm.base import EmbeddingConfigError, EmbeddingError, LLMConfigError, LLMError

# Status codes worth retrying: rate limited, request timeout, server errors.
RETRYABLE_STATUS = frozenset({408, 429, 500, 502, 503, 504})


def check_response(response: httpx.Response, provider: str) -> None:
    """Map an HTTP error to a retryable or a configuration error.

    The response body is deliberately not included in the message: providers
    sometimes echo the request (i.e. contract text) back in error bodies.
    """
    if response.is_success:
        return
    detail = f"{provider} embeddings failed with HTTP {response.status_code}"
    if response.status_code in RETRYABLE_STATUS:
        raise EmbeddingError(detail)
    raise EmbeddingConfigError(detail)


def check_llm_response(response: httpx.Response, provider: str) -> None:
    """Same classification as `check_response`, for text generation."""
    if response.is_success:
        return
    detail = f"{provider} generation failed with HTTP {response.status_code}"
    if response.status_code in RETRYABLE_STATUS:
        raise LLMError(detail)
    raise LLMConfigError(detail)


def l2_normalize(vector: list[float]) -> list[float]:
    """Scale a vector to unit length.

    Cosine similarity ignores length, but unit vectors make scores comparable
    across providers and keep dot-product search (if ever used) correct.
    Gemini returns normalised vectors only at its full 3072 dimensions, so
    reduced-size outputs must be normalised here.
    """
    norm = math.sqrt(sum(v * v for v in vector))
    return [v / norm for v in vector] if norm else vector


def validate_vectors(
    vectors: list[list[float]], *, expected_count: int, dimension: int, provider: str
) -> None:
    """A wrong count or size would silently mis-align vectors with chunks or
    be rejected by Qdrant later; fail loudly here instead."""
    if len(vectors) != expected_count:
        raise EmbeddingConfigError(
            f"{provider} returned {len(vectors)} vectors for {expected_count} texts"
        )
    wrong = next((len(v) for v in vectors if len(v) != dimension), None)
    if wrong is not None:
        raise EmbeddingConfigError(
            f"{provider} returned {wrong}-dimensional vectors; EMBEDDING_DIMENSION={dimension}"
        )
