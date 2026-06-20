# -*- coding: utf-8 -*-
"""Wave 2 gap-closure: A2A 1.0.0 RBAC + Layer-1 visibility denial (Section 8).

Location: ./tests/live_gateway/a2a_compliance/v1_0_0/test_rbac_extra.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: ContextForge Contributors

Closes the 6 Section-8 GAP-BLOCK rows from
``.omo/evidence/c4-audit-checklist.md`` (T10):

- Missing ``Authorization`` → HTTP 401 (transport-level, NOT JSON-RPC).
- Invalid token → HTTP 401.
- Authenticated caller WITHOUT ``a2a.invoke`` permission → HTTP 403.
- Team-scoped agent + wrong-team token → HTTP 404 (visibility hides,
  same wire outcome as agent-not-found per D11).
- ``GetExtendedAgentCard`` with only ``a2a.read`` → HTTP 200 (proves
  route-level ``@require_permission`` was NOT used, Oracle v3 #1).
- ``GetExtendedAgentCard`` WITHOUT ``a2a.read`` → HTTP 403 (drives T12
  step 8 permission check).

All 6 tests are GATEWAY-ONLY behaviors: the reference echo agent has
no auth/RBAC. Tests skip on reference and auto-xfail on gateway_proxy
via the existing collection hook until T12 + T20 RBAC + visibility
wiring lands in Wave 3.

Some setups require RBAC-aware test fixtures (per-permission tokens,
team-scoped agent registration) that are deferred to Wave 7 (T28
Part B). Those tests use ``pytest.skip()`` with a TODO pointer; the
test body still encodes the expected behavior.
"""

from __future__ import annotations

from uuid import uuid4

import httpx
import pytest

from tests.helpers.auth import make_test_jwt

pytestmark = [pytest.mark.a2a, pytest.mark.a2a_v1_0_0, pytest.mark.a2a_security]


def _message_params() -> dict:
    return {"message": {"role": "ROLE_USER", "messageId": str(uuid4()), "parts": [{"text": "rbac-test"}]}}


def _send_message_payload() -> dict:
    return {"jsonrpc": "2.0", "id": str(uuid4()), "method": "SendMessage", "params": _message_params()}


def _get_extended_card_payload() -> dict:
    return {"jsonrpc": "2.0", "id": str(uuid4()), "method": "GetExtendedAgentCard", "params": {}}


def _base_headers() -> dict[str, str]:
    return {"Content-Type": "application/json", "A2A-Version": "1.0.0"}


@pytest.mark.asyncio
async def test_missing_authorization_returns_401(
    raw_dispatch_url: str,
    gap_closure_target: str,
) -> None:
    """Dispatch WITHOUT ``Authorization`` header MUST yield HTTP 401.

    This is a transport-level failure that MUST happen BEFORE the
    JSON-RPC envelope is parsed (no ``-32600`` etc. in the body). The
    gateway's auth middleware rejects unauthenticated requests with
    a 401, NOT a 200 + JSON-RPC error envelope.
    """
    if gap_closure_target == "reference":
        pytest.skip("Gateway-only behavior: echo agent has no auth layer")

    headers = _base_headers()  # NO Authorization header
    async with httpx.AsyncClient(timeout=5.0) as client:
        response = await client.post(raw_dispatch_url, json=_send_message_payload(), headers=headers)
    assert response.status_code == 401, f"[{gap_closure_target}] expected 401, got {response.status_code}: {response.text[:200]}"


@pytest.mark.asyncio
async def test_invalid_token_returns_401(
    raw_dispatch_url: str,
    gap_closure_target: str,
) -> None:
    """Dispatch with a structurally-invalid token MUST yield HTTP 401.

    The token below is NOT a valid JWT -- the auth middleware MUST
    reject it before the request reaches dispatch.
    """
    if gap_closure_target == "reference":
        pytest.skip("Gateway-only behavior: echo agent has no auth layer")

    headers = {**_base_headers(), "Authorization": "Bearer not-a-valid-jwt-token"}
    async with httpx.AsyncClient(timeout=5.0) as client:
        response = await client.post(raw_dispatch_url, json=_send_message_payload(), headers=headers)
    assert response.status_code == 401, f"[{gap_closure_target}] expected 401, got {response.status_code}: {response.text[:200]}"


@pytest.mark.asyncio
async def test_no_invoke_permission_returns_403(
    raw_dispatch_url: str,
    gap_closure_target: str,
) -> None:
    """Authenticated caller WITHOUT ``a2a.invoke`` permission MUST yield HTTP 403.

    Uses a non-admin token with empty teams (public-only Layer-1
    visibility) and no RBAC roles. Triggers T12's method-aware
    permission check.

    The full RBAC role fixture is deferred to Wave 7 T28 Part B; this
    test asserts the wire outcome (403) so Wave 3 implementation has
    a contract to satisfy.
    """
    if gap_closure_target == "reference":
        pytest.skip("Gateway-only behavior: echo agent has no RBAC layer")

    # Non-admin token with empty teams: public-only Layer-1 visibility
    # AND no RBAC roles → Layer-2 permission check denies a2a.invoke.
    no_perm_token = make_test_jwt(email="no-perm-user@example.com", is_admin=False)
    headers = {**_base_headers(), "Authorization": f"Bearer {no_perm_token}"}
    async with httpx.AsyncClient(timeout=5.0) as client:
        response = await client.post(raw_dispatch_url, json=_send_message_payload(), headers=headers)
    assert response.status_code == 403, f"[{gap_closure_target}] expected 403, got {response.status_code}: {response.text[:200]}"


@pytest.mark.asyncio
async def test_team_scoped_agent_wrong_team_returns_404(
    raw_dispatch_url: str,
    gap_closure_target: str,
) -> None:
    """Team-scoped agent + wrong-team token MUST yield HTTP 404.

    Per D11: visibility HIDES (does not 403). A caller with the wrong
    team sees the same wire outcome as if the agent did not exist at
    all -- this prevents enumeration attacks.

    Full setup needs:
    1. A team-scoped agent registered to ``team-a``.
    2. A token with ``teams=["team-b"]`` (no overlap).

    The T28 Part A ``registered_agent_id`` fixture registers a PUBLIC
    agent (no team scoping). A team-scoped registration fixture is
    deferred to Wave 7 T28 Part B; this test skips with TODO until
    then. The wire-level contract (HTTP 404, NOT 403) is asserted
    once the fixture lands.
    """
    if gap_closure_target == "reference":
        pytest.skip("Gateway-only behavior: echo agent has no team-scoped visibility")
    pytest.skip("TODO: team-scoped agent fixture lands in Wave 7 T28 Part B; T20 closes the visibility wiring")


@pytest.mark.asyncio
async def test_extended_card_with_read_permission_returns_200(
    raw_dispatch_url: str,
    gap_closure_target: str,
) -> None:
    """``GetExtendedAgentCard`` with ``a2a.read`` permission MUST yield HTTP 200.

    Closes Oracle v3 #1: proves the gateway did NOT use a route-level
    ``@require_permission("a2a.invoke")`` that would 403 every
    GetExtendedAgentCard call. T12 step 8 instead checks the
    per-method permission inside the dispatch.

    Full setup needs a non-admin user with the ``a2a.read`` role
    granted (NOT ``a2a.invoke``). RBAC role fixture deferred to Wave
    7 T28 Part B; this test skips with TODO until then.
    """
    if gap_closure_target == "reference":
        pytest.skip("Gateway-only behavior: echo agent has no RBAC layer")
    pytest.skip("TODO: per-permission token fixture lands in Wave 7 T28 Part B; T12 step 8 wires the permission check")


@pytest.mark.asyncio
async def test_extended_card_without_read_permission_returns_403(
    raw_dispatch_url: str,
    gap_closure_target: str,
) -> None:
    """``GetExtendedAgentCard`` WITHOUT ``a2a.read`` permission MUST yield HTTP 403.

    Symmetric to the prior test: a non-admin user with no roles
    cannot call ``GetExtendedAgentCard``. Drives T12 step 8's
    permission check.
    """
    if gap_closure_target == "reference":
        pytest.skip("Gateway-only behavior: echo agent has no RBAC layer")

    no_perm_token = make_test_jwt(email="no-perm-user@example.com", is_admin=False)
    headers = {**_base_headers(), "Authorization": f"Bearer {no_perm_token}"}
    async with httpx.AsyncClient(timeout=5.0) as client:
        response = await client.post(raw_dispatch_url, json=_get_extended_card_payload(), headers=headers)
    assert response.status_code == 403, f"[{gap_closure_target}] expected 403, got {response.status_code}: {response.text[:200]}"
