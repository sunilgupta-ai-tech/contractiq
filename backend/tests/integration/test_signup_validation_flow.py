"""Sign-up and sign-in validation through the real API: field-level
messages the frontend shows under each input."""

import os

import pytest

from tests.integration.conftest import PASSWORD, new_email, register

pytestmark = pytest.mark.skipif(
    os.getenv("CONTRACTIQ_INTEGRATION") != "1", reason="set CONTRACTIQ_INTEGRATION=1"
)

API = "/api/v1"


def _fields(response) -> dict[str, str]:
    assert response.status_code == 422, response.text
    body = response.json()["error"]
    assert body["code"] == "VALIDATION_ERROR"
    return {f["loc"][-1]: f["msg"] for f in body["details"]["fields"]}


def test_register_reports_every_invalid_field(api):
    response = api.post(
        f"{API}/auth/register",
        json={
            "organization_name": "<Acme>",
            "full_name": "12345",
            "email": "priya@acme",
            "password": "password1234",
        },
    )
    assert _fields(response) == {
        "organization_name": "The organization name can't contain links or the characters < and >.",
        "full_name": "Your name must contain letters.",
        "email": "The part after @ isn't a valid domain, like company.com.",
        "password": "This password is too common. Choose something less predictable.",
    }


def test_register_refuses_a_password_built_from_the_organization_name(api):
    response = api.post(
        f"{API}/auth/register",
        json={
            "organization_name": "Mango Logistics",
            "full_name": "Priya Sharma",
            "email": new_email("pw"),
            "password": "mangologistics-2026",
        },
    )
    assert _fields(response) == {
        "password": "Password can't contain your email, name or organization name."
    }


def test_valid_sign_up_is_normalised_and_sign_in_works_with_any_case(api, cleanup):
    email = new_email("case")
    cleanup.append(email)
    response = api.post(
        f"{API}/auth/register",
        json={
            "organization_name": "  Case   Study Co ",
            "full_name": "  Priya   Sharma ",
            "email": f"  {email.upper()} ",
            "password": PASSWORD,
        },
    )
    assert response.status_code == 201, response.text
    login = api.post(f"{API}/auth/login", json={"email": email.upper(), "password": PASSWORD})
    assert login.status_code == 200, login.text
    me = api.get(
        f"{API}/users/me",
        headers={"Authorization": f"Bearer {login.json()['data']['access_token']}"},
    )
    assert me.json()["data"]["full_name"] == "Priya Sharma"


def test_a_taken_email_is_a_conflict_the_form_puts_under_email(api, cleanup):
    _, email = register(api, cleanup, "First Co")
    response = api.post(
        f"{API}/auth/register",
        json={
            "organization_name": "Second Co",
            "full_name": "Someone Else",
            "email": email,
            "password": PASSWORD,
        },
    )
    assert response.status_code == 409
    assert "email" in response.json()["error"]["message"].lower()


def test_sign_in_with_a_malformed_email_gets_a_field_message(api):
    fields = _fields(api.post(f"{API}/auth/login", json={"email": "nope", "password": "x"}))
    assert fields == {"email": "Enter a valid email address."}
