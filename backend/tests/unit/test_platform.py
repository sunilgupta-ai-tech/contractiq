"""Phase 18: plans, console request rules and the platform token audience."""

import pytest
from pydantic import ValidationError

from app.core.exceptions import UnauthorizedError
from app.core.security import create_platform_token, decode_platform_token, decode_token
from app.db.models import Organization, OrganizationStatus, Plan
from app.schemas.platform import UpdateOrganizationRequest
from app.services.plans import PLAN_LIMITS, apply_plan
from tests.tokens import token_for


def test_every_plan_has_limits_and_enterprise_is_unlimited():
    assert set(PLAN_LIMITS) == set(Plan)
    enterprise = PLAN_LIMITS[Plan.ENTERPRISE]
    assert (enterprise.max_users, enterprise.max_documents, enterprise.max_storage_mb) == (
        None,
    ) * 3


def test_choosing_a_plan_resets_limits_to_its_defaults():
    org = Organization(name="x", slug="x", max_users=1)
    apply_plan(org, Plan.STARTER)
    assert org.plan is Plan.STARTER and org.max_users == PLAN_LIMITS[Plan.STARTER].max_users


def test_suspension_needs_a_reason_and_unlimited_names_are_checked():
    with pytest.raises(ValidationError, match="reason"):
        UpdateOrganizationRequest(status=OrganizationStatus.SUSPENDED)
    with pytest.raises(ValidationError):
        UpdateOrganizationRequest(unlimited=["password"])
    ok = UpdateOrganizationRequest(status=OrganizationStatus.SUSPENDED, suspended_reason="Fraud")
    assert ok.status is OrganizationStatus.SUSPENDED


def test_platform_and_tenant_tokens_are_not_interchangeable(settings):
    platform = create_platform_token(settings, subject="a", role="SUPER_ADMIN")
    assert decode_platform_token(settings, platform)["prole"] == "SUPER_ADMIN"
    with pytest.raises(UnauthorizedError):
        decode_token(settings, platform)
    with pytest.raises(UnauthorizedError):
        decode_platform_token(settings, token_for(settings))


def test_organization_status_drives_is_active():
    org = Organization(name="x", slug="x", status=OrganizationStatus.SUSPENDED)
    assert not org.is_active
    org.status = OrganizationStatus.ACTIVE
    assert org.is_active
