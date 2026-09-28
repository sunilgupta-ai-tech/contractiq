"""Sign-up and sign-in validation (app/core/credentials.py, app/schemas/auth.py)."""

import pytest
from pydantic import ValidationError

from app.core.credentials import (
    CredentialError,
    normalize_email,
    validate_full_name,
    validate_new_email,
    validate_new_password,
    validate_organization_name,
)
from app.schemas.auth import LoginRequest, RegisterRequest
from app.schemas.invitation import AcceptInvitationRequest

GOOD_PASSWORD = "correct horse battery staple"


# --- Email -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "email",
    [
        "priya@acme.com",
        "  Priya.Sharma+legal@Acme.CO.IN ",
        "o'neil@example.org",
        "a_b-c@sub.example-domain.com",
        "user@xn--80ak6aa92e.xn--p1ai",
    ],
)
def test_valid_new_emails(email):
    assert validate_new_email(email) == email.strip().lower()


@pytest.mark.parametrize(
    "email",
    [
        "",
        "plainaddress",
        "@acme.com",
        "priya@",
        "priya@@acme.com",
        "priya@acme",
        "priya@acme.c",  # one-letter TLD
        "priya@acme.123",
        "priya@-acme.com",
        "priya@acme-.com",
        "priya@acme..com",
        ".priya@acme.com",
        "priya.@acme.com",
        "pri..ya@acme.com",
        "pri ya@acme.com",
        "priya@ac me.com",
        "priya@[127.0.0.1]",
        "<script>@acme.com",
        "a" * 65 + "@acme.com",
        "priya@" + "a" * 250 + ".com",
    ],
)
def test_invalid_new_emails(email):
    with pytest.raises(CredentialError):
        validate_new_email(email)


def test_sign_in_keeps_the_old_looser_email_check():
    # An account created before the stricter rules must still be able to sign in.
    assert normalize_email(" Old@Acme.C ") == "old@acme.c"
    assert LoginRequest(email="Old@Acme.C", password="x").email == "old@acme.c"
    with pytest.raises(ValidationError):
        LoginRequest(email="not-an-email", password="x")


# --- Names -----------------------------------------------------------------------------


def test_names_are_trimmed_and_single_spaced():
    assert validate_full_name("  Priya   Sharma ") == "Priya Sharma"
    assert validate_full_name("José Núñez") == "José Núñez"
    assert validate_full_name("प्रिया शर्मा") == "प्रिया शर्मा"
    assert validate_organization_name(" Acme   Legal LLP ") == "Acme Legal LLP"
    assert validate_organization_name("3M") == "3M"


@pytest.mark.parametrize(
    "name",
    ["", "   ", "12345", "<b>Priya</b>", "Visit http://spam.example", "www.spam.in", "a\x00b"],
)
def test_invalid_full_names(name):
    with pytest.raises(CredentialError):
        validate_full_name(name)


@pytest.mark.parametrize("name", ["", "A", "  A ", "--", "<Acme>", "https://acme.com", "x" * 201])
def test_invalid_organization_names(name):
    with pytest.raises(CredentialError):
        validate_organization_name(name)


# --- Passwords -------------------------------------------------------------------------


@pytest.mark.parametrize(
    "password",
    [GOOD_PASSWORD, "platform admin demo pass", "Monsoon-train-7-mangoes", "जल्दी घर आओ भाई"],
)
def test_strong_passwords_are_accepted(password):
    assert validate_new_password(password) == password


@pytest.mark.parametrize(
    ("password", "reason"),
    [
        ("short pass", "at least 12"),
        ("x" * 73, "at most 72"),
        ("            ", "blank"),
        ("aaaaaaaaaaaa", "too few"),
        ("121212121212", "too few"),
        ("123456789012", "only numbers"),
        ("9876 5432 1098", "only numbers"),
        ("password1234", "too common"),
        ("Password@2026", "too common"),
        ("Welcome@2026", "too common"),
        ("qwertyuiop12", "too common"),
        ("abcdefghijklmn", "too common"),
        ("zyxwvutsrqpo", "too common"),
        ("docunexa2026!", "too common"),
    ],
)
def test_weak_passwords_are_refused_with_a_reason(password, reason):
    with pytest.raises(CredentialError, match=reason):
        validate_new_password(password)


def test_password_may_not_contain_personal_details():
    personal = ("priya.sharma@acme.com", "Priya Sharma", "Acme Legal")
    for password in ("priya-loves-mangoes", "i work at acme legal!", "sharma family 2026"):
        with pytest.raises(CredentialError, match="email, name or organization"):
            validate_new_password(password, personal=personal)
    assert validate_new_password(GOOD_PASSWORD, personal=personal) == GOOD_PASSWORD


# --- Schemas: messages the frontend shows under each field ---------------------------------


def _errors(model, **data) -> dict[str, str]:
    with pytest.raises(ValidationError) as caught:
        model(**data)
    return {".".join(map(str, e["loc"])): e["msg"] for e in caught.value.errors()}


def test_register_reports_each_field_with_a_plain_message():
    errors = _errors(
        RegisterRequest,
        organization_name=" ",
        full_name="<script>",
        email="priya@acme",
        password="password1234",
    )
    assert set(errors) == {"organization_name", "full_name", "email", "password"}
    assert errors["email"] == "The part after @ isn't a valid domain, like company.com."
    assert not any(m.startswith("Value error") for m in errors.values())


def test_register_password_checked_against_the_same_request():
    errors = _errors(
        RegisterRequest,
        organization_name="Acme Legal",
        full_name="Priya Sharma",
        email="priya@acme.com",
        password="acmelegal-contracts-2026",
    )
    assert errors == {"password": "Password can't contain your email, name or organization name."}


def test_register_normalises_valid_input():
    request = RegisterRequest(
        organization_name="  Acme   Legal ",
        full_name=" Priya  Sharma ",
        email=" Priya@Acme.com ",
        password=GOOD_PASSWORD,
    )
    assert (request.organization_name, request.full_name, request.email) == (
        "Acme Legal",
        "Priya Sharma",
        "priya@acme.com",
    )


def test_invitation_password_may_not_contain_the_name():
    errors = _errors(AcceptInvitationRequest, full_name="Ravi Kumar", password="ravikumar@office1")
    assert "password" in errors
