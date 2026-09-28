"""
Sign-up and sign-in input rules.

The API is the authority; the frontend mirrors these rules only to show
problems while the user types (frontend/utils/auth-validation.ts).

Emails for new accounts must be well-formed: a local part of allowed
characters without leading, trailing or doubled dots, and a domain of at
least two labels ending in a letter TLD. Sign-in only normalises the email
(trim, lower-case) with the old, looser check, so an account created before
these rules can always still sign in.

New passwords follow NIST SP 800-63B: length matters, composition rules
("one symbol, one digit") don't. On top of 12 characters and bcrypt's
72-byte limit, a password is refused when it is easy to guess:

* made of very few different characters ("aaaaaaaaaaaa", "121212121212");
* digits only;
* a common password, or one with digits or symbols added to the end
  ("password1234", "Welcome@2026");
* a straight run on the keyboard, alphabet or number row;
* containing the person's email name, own name or organization name.

Existing passwords are never re-checked, so a stricter policy can't lock
anyone out.
"""

from __future__ import annotations

import re
import unicodedata

PASSWORD_MIN_CHARS = 12
PASSWORD_MAX_BYTES = 72
_MIN_DISTINCT = 5

# Most common passwords and their stems (lower-case, letters only after
# trailing digits/symbols are removed). Enough to stop the obvious choices;
# length does the rest.
COMMON_PASSWORDS = frozenset(
    """
    password passw0rd passwd pass word admin administrator root user login welcome
    letmein iloveyou qwerty qwertyuiop asdfgh asdfghjkl zxcvbnm abc abcdef abcdefgh
    monkey dragon master shadow sunshine princess football baseball superman batman
    trustno starwars whatever freedom secret changeme default guest test testing
    india bharat hello hellohello computer internet company contract contracts
    docunexa contractiq summer winter spring autumn january december
    """.split()
)

_SEQUENCES = (
    "abcdefghijklmnopqrstuvwxyz",
    "01234567890",
    "qwertyuiopasdfghjklzxcvbnm",
    "1qaz2wsx3edc4rfv5tgb6yhn7ujm8ik9ol0p",
)

_EMAIL_LOCAL = re.compile(
    r"^[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+(?:\.[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+)*$"
)
_DOMAIN_LABEL = re.compile(r"^(?!-)[a-z0-9-]{1,63}(?<!-)$")
_TLD = re.compile(r"^(?:[a-z]{2,63}|xn--[a-z0-9-]{1,59})$")
_LOOSE_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_MARKUP = re.compile(r"[<>]|https?://|www\.", re.IGNORECASE)


class CredentialError(ValueError):
    """A user-facing reason the value is not accepted."""


def normalize_email(value: str) -> str:
    """Sign-in: trim and lower-case, with the original loose shape check."""
    value = value.strip().lower()
    if len(value) > 320 or not _LOOSE_EMAIL.match(value):
        raise CredentialError("Enter a valid email address.")
    return value


def validate_new_email(value: str) -> str:
    """New accounts and invitations: a well-formed address."""
    value = value.strip().lower()
    if not value:
        raise CredentialError("Enter your email address.")
    if len(value) > 254 or value.count("@") != 1:
        raise CredentialError("Enter a valid email address, like name@company.com.")
    local, domain = value.split("@")
    if not local or len(local) > 64 or not _EMAIL_LOCAL.match(local):
        raise CredentialError("Enter a valid email address, like name@company.com.")
    labels = domain.split(".")
    if len(labels) < 2 or not all(_DOMAIN_LABEL.match(label) for label in labels):
        raise CredentialError("The part after @ isn't a valid domain, like company.com.")
    if not _TLD.match(labels[-1]):
        raise CredentialError("The part after @ isn't a valid domain, like company.com.")
    return value


def clean_display_text(value: str, *, what: str, min_chars: int, max_chars: int) -> str:
    """Names shown to other people: trimmed, single spaces, no markup."""
    value = " ".join(unicodedata.normalize("NFC", value).split())
    if len(value) < min_chars:
        raise CredentialError(
            f"Enter {what}."
            if min_chars <= 1
            else f"{what.capitalize()} must be at least {min_chars} characters."
        )
    if len(value) > max_chars:
        raise CredentialError(f"{what.capitalize()} must be at most {max_chars} characters.")
    if _CONTROL.search(value) or _MARKUP.search(value):
        raise CredentialError(f"{what.capitalize()} can't contain links or the characters < and >.")
    return value


def validate_full_name(value: str) -> str:
    value = clean_display_text(value, what="your name", min_chars=1, max_chars=200)
    if not any(ch.isalpha() for ch in value):
        raise CredentialError("Your name must contain letters.")
    return value


def validate_organization_name(value: str) -> str:
    value = clean_display_text(value, what="the organization name", min_chars=2, max_chars=200)
    if not any(ch.isalnum() for ch in value):
        raise CredentialError("The organization name must contain letters or numbers.")
    return value


def _compact(value: str) -> str:
    return re.sub(r"[\W_]+", "", value.lower())


def _is_sequence(text: str) -> bool:
    return len(text) >= 6 and any(text in seq or text in seq[::-1] for seq in _SEQUENCES)


def validate_new_password(value: str, *, personal: tuple[str | None, ...] = ()) -> str:
    """Raise CredentialError with the first reason the password is weak.

    `personal`: the person's email, name and organization, when known.
    """
    if len(value) < PASSWORD_MIN_CHARS:
        raise CredentialError(f"Password must be at least {PASSWORD_MIN_CHARS} characters.")
    if len(value.encode()) > PASSWORD_MAX_BYTES:
        raise CredentialError(f"Password must be at most {PASSWORD_MAX_BYTES} bytes.")
    if not value.strip() or _CONTROL.search(value):
        raise CredentialError("Password can't be blank or contain control characters.")
    if len(set(value.lower())) < _MIN_DISTINCT:
        raise CredentialError("Password repeats too few characters. Use a longer phrase.")
    compact = _compact(value)
    if compact.isdigit():
        raise CredentialError("Password can't be only numbers. Use words, e.g. a short phrase.")
    stem = re.sub(r"\d+$", "", compact)
    if compact in COMMON_PASSWORDS or stem in COMMON_PASSWORDS or _is_sequence(compact):
        raise CredentialError("This password is too common. Choose something less predictable.")
    for item in personal:
        if not item:
            continue
        for part in _personal_parts(item):
            if part in compact:
                raise CredentialError(
                    "Password can't contain your email, name or organization name."
                )
    return value


def _personal_parts(item: str) -> list[str]:
    """Guessable pieces of an email, name or organization (4+ characters)."""
    text = item.split("@")[0] if "@" in item else item
    parts = {_compact(text), *(_compact(p) for p in re.split(r"[\s._+-]+", text))}
    return [p for p in parts if len(p) >= 4]
