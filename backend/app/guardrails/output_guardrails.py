"""
Output guardrails (Phase 11): clean model text before a user sees it.

A model can echo parts of its prompt, especially when a contract contains
text designed to make it do so. `sanitize_output` removes or redacts:

    delimiter echoes   <untrusted_document_…> tags and their look-alikes
                       (<system>, </instructions>) copied into the answer
    secret-like tokens API keys, bearer/JWT tokens and private-key blocks,
                       which never belong in a contract answer
    runaway length     answers beyond MAX_ANSWER_CHARS are cut at a word

and reports what it did as flags (logged, and returned with the answer's
other review flags). Nothing here rewrites the substance of an answer;
whether the substance is supported is the evidence validator's job.

Structured (JSON) model outputs are validated where they are parsed:
the agent's plan (agents/prompts.parse_json_object + clean_queries), clause
extraction (agents/clause_agent.parse_extraction + typed coercion) and
summaries (services/contract_service). Anything malformed is dropped or
treated as "not found", never passed through.
"""

from __future__ import annotations

import re

from app.core.logging import get_logger

logger = get_logger(__name__)

MAX_ANSWER_CHARS = 8000

_DELIMITERS = re.compile(
    r"</?\s*(?:untrusted_document[\w-]*|system|instructions?|developer)\b[^>]*>", re.IGNORECASE
)
_SECRETS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("google_api_key", re.compile(r"\bAIza[0-9A-Za-z_\-]{30,}")),
    ("openai_style_key", re.compile(r"\bsk-[A-Za-z0-9_\-]{20,}")),
    ("aws_access_key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("jwt", re.compile(r"\beyJ[\w-]{10,}\.[\w-]{10,}\.[\w-]{10,}")),
    ("bearer_token", re.compile(r"\bBearer\s+[A-Za-z0-9._\-]{20,}", re.IGNORECASE)),
    (
        "private_key",
        re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S),
    ),
)


def sanitize_output(text: str) -> tuple[str, list[str]]:
    """(cleaned text, flags). Flags name what was removed, never the content."""
    flags: list[str] = []
    cleaned, count = _DELIMITERS.subn("", text)
    if count:
        flags.append("output:delimiter_echo")
    for name, pattern in _SECRETS:
        cleaned, count = pattern.subn("[redacted]", cleaned)
        if count:
            flags.append(f"output:secret:{name}")
    if len(cleaned) > MAX_ANSWER_CHARS:
        cleaned = cleaned[:MAX_ANSWER_CHARS].rsplit(" ", 1)[0] + " …"
        flags.append("output:truncated")
    if flags:
        logger.warning("output_sanitized", extra={"flags": flags})
    return cleaned, flags
