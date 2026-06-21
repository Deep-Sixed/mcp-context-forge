# -*- coding: utf-8 -*-
"""A2A protocol-compliance harness fixtures.

Location: ./tests/live_gateway/a2a_compliance/conftest.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: ContextForge Contributors

The ``client`` fixture is parametrized over every ``(target, transport)``
pair declared below, so every test body runs across the full matrix
automatically:

    reference-jsonrpc       — direct to the live a2a_echo_agent
    gateway_proxy-jsonrpc   — via ContextForge native passthrough
    gateway_virtual-jsonrpc — via ContextForge virtual server

T30 (Wave 7) closed A2A-GAP-001: the gateway-target placeholders are
gone, both ``gateway_proxy`` and ``gateway_virtual`` now drive the
native A2A passthrough that landed in Waves 3 + 4. The blanket
``pytest_collection_modifyitems`` xfail hook was deleted as part of
the closure — per-test ``xfail_on`` (in ``helpers/compliance.py``)
remains available for narrower gaps that don't have a stable
column-wide pattern.
"""

from __future__ import annotations

import os
from typing import AsyncIterator

import httpx
import pytest
import pytest_asyncio
from a2a.client.client import Client

from tests.helpers.auth import make_test_jwt

from .fixtures.echo_agent import (  # noqa: F401 — re-exported for pytest fixture discovery
    echo_agent_base_url,
    echo_agent_card_url,
)
from .targets.base import Transport
from .targets.gateway_proxy import A2AGatewayProxyTarget
from .targets.gateway_virtual import A2AGatewayVirtualServerTarget
from .targets.reference import A2AReferenceTarget

_CASES: list[tuple[str, Transport]] = [
    ("reference", "jsonrpc"),
    ("gateway_proxy", "jsonrpc"),
    ("gateway_virtual", "jsonrpc"),
]

# ───────────────────────────────────────────────────────────────────────
# T28 Part A — minimal gateway-target fixtures for Wave 2 gap closure
# (executes before T8 audit + T9/T10 gap-closure tests per plan P5).
#
# Tests that call ``ClientFactory`` (i.e. ``client`` fixture) still hit
# the placeholder ``_open_client`` which raises ``NotImplementedError``
# until T29 in Wave 7. Wave 2's gap-closure tests are RAW-HTTP based:
# they consume ``raw_card_url`` and ``raw_dispatch_url`` fixtures which
# build target-correct URLs without going through ``ClientFactory``,
# so they can collect, run, and surface their (intended) failures
# against ``gateway_proxy`` while Wave 3 implementation is still
# in flight.
#
# Part B of T28 (server creation + sanity test + ``gateway_virtual``
# parameterization) stays in Wave 7 because it depends on T20's
# server-CRUD wiring verification.
# ───────────────────────────────────────────────────────────────────────

# T28 Part B (Wave 7): ``gateway_virtual`` joined the parametrize after
# T20 + T22 confirmed server-CRUD wiring round-trips through
# ``server_a2a_association``. All three targets now share the gap-closure
# matrix.
_PART_A_GAP_CLOSURE_TARGETS: tuple[str, ...] = ("reference", "gateway_proxy", "gateway_virtual")


def _build_target(target_name: str, request: pytest.FixtureRequest):
    """Construct an A2AComplianceTarget for ``target_name``.

    Reference target pulls the resolved card URL from the
    ``echo_agent_card_url`` fixture (which transitively probes the
    agent's ``/health`` and skips the session if it's unreachable).

    T29 (Wave 7): gateway targets now resolve real fixtures —
    ``gateway_base_url`` + ``auth_token`` + ``registered_agent_id``
    (triggers gateway probe + agent registration), and additionally
    ``server_id`` for ``gateway_virtual``. Their ``_open_client``
    bodies actually connect via the SDK's ``ClientFactory`` so the
    matrix tests run end-to-end against the live native passthrough.
    """
    if target_name == "reference":
        base_url = request.getfixturevalue("echo_agent_base_url")
        return A2AReferenceTarget(base_url=base_url)
    if target_name == "gateway_proxy":
        gateway_base_url = request.getfixturevalue("gateway_base_url")
        auth_token = request.getfixturevalue("auth_token")
        agent_name = request.getfixturevalue("registered_agent_name")
        request.getfixturevalue("registered_agent_id")
        return A2AGatewayProxyTarget(
            base_url=gateway_base_url,
            auth_token=auth_token,
            agent_name=agent_name,
        )
    if target_name == "gateway_virtual":
        gateway_base_url = request.getfixturevalue("gateway_base_url")
        auth_token = request.getfixturevalue("auth_token")
        agent_name = request.getfixturevalue("registered_agent_name")
        server_id_value = request.getfixturevalue("server_id")
        return A2AGatewayVirtualServerTarget(
            base_url=gateway_base_url,
            auth_token=auth_token,
            server_id=server_id_value,
            agent_name=agent_name,
        )
    raise AssertionError(f"unknown target: {target_name!r}")


@pytest_asyncio.fixture(params=_CASES, ids=[f"{t}-{x}" for t, x in _CASES])
async def client(request: pytest.FixtureRequest) -> AsyncIterator[Client]:
    """Yield a connected ``a2a.client.Client`` for the parametrized cell.

    Reference target opens a fresh ``httpx.AsyncClient`` + ``ClientFactory``
    per invocation; the SDK auto-routes via JSON-RPC per the echo
    agent's advertised card interfaces.

    Gateway targets (``gateway_proxy``, ``gateway_virtual``) drive
    ContextForge's native A2A passthrough at ``/a2a/{name}`` and
    ``/servers/{id}/a2a/{name}`` respectively. Their ``_open_client``
    bodies mirror the reference target's shape exactly, with the URL
    pointed at the gateway's synthesized well-known card.
    """
    target_name, transport = request.param
    target = _build_target(target_name, request)
    async with target.client(transport) as connected:
        yield connected


# ───────────────────────────────────────────────────────────────────────
# T28 Part A fixtures (Wave 2 prerequisite — execute BEFORE T8/T9/T10).
# ───────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="session")
def gateway_base_url() -> str:
    """Read ``A2A_COMPLIANCE_GATEWAY_URL``, default ``http://localhost:4444``.

    Plan T28 Part A: target-aware URL building for Wave 2 gap-closure
    tests starts from this base. Overridable via env so the harness can
    run against any running ContextForge gateway instance (compose,
    Kubernetes port-forward, etc.).
    """
    return os.getenv("A2A_COMPLIANCE_GATEWAY_URL", "http://localhost:4444")


@pytest.fixture(scope="session")
def auth_token() -> str:
    """Session-scoped admin JWT signed with ``JWT_SECRET_KEY`` from env.

    Plan T28 Part A: uses ``tests.helpers.auth.make_test_jwt`` per the
    canonical test-JWT helper per ``tests/AGENTS.md`` (NOT
    ``mcpgateway.utils.create_jwt_token.create_jwt_token`` which is the
    CLI-facing helper). The resulting token has ``is_admin=True`` so it
    can call admin endpoints like ``POST /a2a`` for agent registration.

    The empty-string ``secret`` argument lets ``make_test_jwt`` fall
    through to ``settings.JWT_SECRET_KEY`` from the environment, so a
    real gateway accepts it.
    """
    return make_test_jwt(email="admin@example.com", is_admin=True)


@pytest.fixture(scope="session")
def registered_agent_name() -> str:
    """Canonical name of the live echo agent the harness drives.

    Defaults to ``a2a-echo-agent`` (matching the docker-compose
    ``testing`` profile + ``_build_target`` defaults above). Override
    via ``A2A_COMPLIANCE_AGENT_NAME`` env when the gateway has the echo
    agent registered under a different name.
    """
    return os.getenv("A2A_COMPLIANCE_AGENT_NAME", "a2a-echo-agent")


@pytest.fixture(scope="session")
def registered_agent_id(
    gateway_base_url: str,
    auth_token: str,
    registered_agent_name: str,
    echo_agent_base_url: str,
) -> str:
    """Session-scoped: ensure echo agent is registered, return its UUID.

    Plan T28 Part A: POST /a2a admin API to register the echo agent if
    it is not already known to the gateway; on success or "already
    exists" responses, look up the agent by name to capture its UUID
    ``id``. The captured ID is what server-association tests (T20/T22)
    will pass into ``associated_a2a_agents=[...]`` per Momus v3 #3 —
    the service layer queries ``at.model.id.in_(ids)`` at
    ``server_service.py:226``, so passing the agent NAME would fail.

    Skips the session gracefully when the gateway is unreachable so a
    developer running the harness without a live gateway just sees a
    clean skip rather than a cascade of connection errors. The agent's
    own ``echo_agent_base_url`` fixture transitively skips when the
    underlying echo agent process isn't up.
    """
    # Confirm the gateway is reachable before issuing the registration.
    try:
        probe = httpx.get(f"{gateway_base_url}/health", timeout=httpx.Timeout(5.0))
    except httpx.HTTPError as exc:
        pytest.skip(f"Gateway unreachable at {gateway_base_url}: {exc}")
    if probe.status_code >= 500:
        pytest.skip(f"Gateway at {gateway_base_url} returned {probe.status_code}")

    headers = {"Authorization": f"Bearer {auth_token}", "Content-Type": "application/json"}

    # Try to look up the agent first by listing — handles the case where
    # the agent is already registered by docker-compose or a previous run.
    list_resp = httpx.get(f"{gateway_base_url}/a2a", headers=headers, timeout=httpx.Timeout(10.0))
    if list_resp.status_code == 200:
        body = list_resp.json()
        # Some endpoints return a list, others return a pagination dict —
        # accept both shapes.
        agents = body.get("items", body) if isinstance(body, dict) else body
        if isinstance(agents, list):
            for agent in agents:
                if isinstance(agent, dict) and agent.get("name") == registered_agent_name:
                    return str(agent["id"])

    # Not found — register now.
    payload = {
        "name": registered_agent_name,
        "description": "A2A 1.0.0 compliance-harness echo agent (T28 Part A registration)",
        "endpoint_url": echo_agent_base_url,
        "agent_type": "jsonrpc",
        "protocol_version": "1.0.0",
        "capabilities": {"streaming": True},
        "visibility": "public",
    }
    create_resp = httpx.post(f"{gateway_base_url}/a2a", headers=headers, json=payload, timeout=httpx.Timeout(15.0))
    if create_resp.status_code in (200, 201):
        return str(create_resp.json()["id"])

    # 409 conflict (already exists by another path) — re-list and find it.
    if create_resp.status_code == 409:
        list_resp2 = httpx.get(f"{gateway_base_url}/a2a", headers=headers, timeout=httpx.Timeout(10.0))
        if list_resp2.status_code == 200:
            body = list_resp2.json()
            agents = body.get("items", body) if isinstance(body, dict) else body
            if isinstance(agents, list):
                for agent in agents:
                    if isinstance(agent, dict) and agent.get("name") == registered_agent_name:
                        return str(agent["id"])

    pytest.skip(f"Could not register or find agent {registered_agent_name!r} on gateway " f"{gateway_base_url} (POST /a2a status {create_resp.status_code}): {create_resp.text[:200]}")


@pytest.fixture(params=_PART_A_GAP_CLOSURE_TARGETS)
def gap_closure_target(request: pytest.FixtureRequest) -> str:
    """Parametrize Wave 2 gap-closure tests over the Part A target set.

    Returns the current target name (``"reference"`` or
    ``"gateway_proxy"``). The collection hook above blanket-xfails
    ``gateway_proxy`` cells until Wave 3 implementation lands, so
    gap-closure assertions can be authored without per-test ``xfail_on``
    boilerplate.

    ``gateway_virtual`` joins this parametrize in Wave 7 (T28 Part B).
    """
    return request.param


@pytest.fixture(scope="session")
def server_id(
    gateway_base_url: str,
    auth_token: str,
    registered_agent_id: str,
) -> str:
    """Session-scoped: ensure an A2A bundling server exists, return its UUID.

    Plan T28 Part B (Wave 7): create a virtual server via
    ``POST /servers`` with ``associated_a2a_agents=[registered_agent_id]``
    so the v-server-scoped card and dispatch URLs
    (``/servers/{server_id}/a2a/{name}``) resolve to the registered
    echo agent. Returns the server's UUID for use by the
    ``gateway_virtual`` URL builders below.

    Passes the agent ID (UUID), NOT the name, per Momus v3 #3: the
    service layer queries ``at.model.id.in_(ids)`` at
    ``server_service.py:226``, so passing the agent NAME would yield
    a server with no bound agents.

    Re-list before creating: if a previous run already created the
    bundling server, reuse its UUID rather than failing on a unique
    constraint or creating a parallel server.

    Skips the session gracefully when the gateway is unreachable so
    a developer running the harness without a live gateway sees a
    clean skip rather than a cascade of connection errors.
    """
    server_name = os.getenv("A2A_COMPLIANCE_SERVER_NAME", "a2a-compliance-bundle")

    try:
        probe = httpx.get(f"{gateway_base_url}/health", timeout=httpx.Timeout(5.0))
    except httpx.HTTPError as exc:
        pytest.skip(f"Gateway unreachable at {gateway_base_url}: {exc}")
    if probe.status_code >= 500:
        pytest.skip(f"Gateway at {gateway_base_url} returned {probe.status_code}")

    headers = {"Authorization": f"Bearer {auth_token}", "Content-Type": "application/json"}

    list_resp = httpx.get(f"{gateway_base_url}/servers", headers=headers, timeout=httpx.Timeout(10.0))
    if list_resp.status_code == 200:
        body = list_resp.json()
        servers = body.get("items", body) if isinstance(body, dict) else body
        if isinstance(servers, list):
            for srv in servers:
                if isinstance(srv, dict) and srv.get("name") == server_name:
                    return str(srv["id"])

    payload = {
        "name": server_name,
        "description": "A2A 1.0.0 compliance-harness bundling server (T28 Part B)",
        "associated_a2a_agents": [registered_agent_id],
        "visibility": "public",
    }
    create_resp = httpx.post(f"{gateway_base_url}/servers", headers=headers, json=payload, timeout=httpx.Timeout(15.0))
    if create_resp.status_code in (200, 201):
        return str(create_resp.json()["id"])

    if create_resp.status_code == 409:
        list_resp2 = httpx.get(f"{gateway_base_url}/servers", headers=headers, timeout=httpx.Timeout(10.0))
        if list_resp2.status_code == 200:
            body = list_resp2.json()
            servers = body.get("items", body) if isinstance(body, dict) else body
            if isinstance(servers, list):
                for srv in servers:
                    if isinstance(srv, dict) and srv.get("name") == server_name:
                        return str(srv["id"])

    pytest.skip(f"Could not register or find server {server_name!r} on gateway " f"{gateway_base_url} (POST /servers status {create_resp.status_code}): {create_resp.text[:200]}")


@pytest.fixture
def raw_card_url(
    gap_closure_target: str,
    gateway_base_url: str,
    registered_agent_name: str,
    echo_agent_base_url: str,
    request: pytest.FixtureRequest,
) -> str:
    """Target-aware well-known card URL for raw-HTTP gap-closure tests.

    Plan T28 Part A + Part B: lets T9 card-discovery tests parametrize
    over ``{reference, gateway_proxy, gateway_virtual}`` and exercise
    the same raw HTTP path that ``ClientFactory.create_from_url``
    would. Per-agent gateway URL follows the F8 + T11 convention
    ``/a2a/{name}/.well-known/agent-card.json``; v-server-scoped
    gateway URL follows the F8 + T16 convention
    ``/servers/{server_id}/a2a/{name}/.well-known/agent-card.json``.

    Args:
        gap_closure_target: Current parametrize cell.
        gateway_base_url: Gateway base for gateway-target URLs.
        registered_agent_name: Agent name used in the URL path.
        echo_agent_base_url: Reference target's base URL (echo agent).
        request: pytest fixture request used to lazily resolve
            ``server_id`` only when the parametrize cell needs it
            (avoids a session-level server creation when no
            gateway_virtual test runs).

    Returns:
        The well-known card URL for the parametrized target.
    """
    if gap_closure_target == "reference":
        return f"{echo_agent_base_url}/.well-known/agent-card.json"
    if gap_closure_target == "gateway_proxy":
        return f"{gateway_base_url}/a2a/{registered_agent_name}/.well-known/agent-card.json"
    if gap_closure_target == "gateway_virtual":
        sid = request.getfixturevalue("server_id")
        return f"{gateway_base_url}/servers/{sid}/a2a/{registered_agent_name}/.well-known/agent-card.json"
    raise AssertionError(f"unsupported gap-closure target {gap_closure_target!r}")


@pytest.fixture
def raw_dispatch_url(
    gap_closure_target: str,
    gateway_base_url: str,
    registered_agent_name: str,
    echo_agent_base_url: str,
    request: pytest.FixtureRequest,
) -> str:
    """Target-aware dispatch URL for raw-HTTP gap-closure tests.

    Plan T28 Part A + Part B: lets T10 dispatch-tests parametrize over
    ``{reference, gateway_proxy, gateway_virtual}``. Per-agent gateway
    URL follows the F8 + T12 convention ``/a2a/{name}``; v-server-scoped
    gateway URL follows the F8 + T16 convention
    ``/servers/{server_id}/a2a/{name}``. Reference target uses the
    echo agent's bare base URL.
    """
    if gap_closure_target == "reference":
        return echo_agent_base_url
    if gap_closure_target == "gateway_proxy":
        return f"{gateway_base_url}/a2a/{registered_agent_name}"
    if gap_closure_target == "gateway_virtual":
        sid = request.getfixturevalue("server_id")
        return f"{gateway_base_url}/servers/{sid}/a2a/{registered_agent_name}"
    raise AssertionError(f"unsupported gap-closure target {gap_closure_target!r}")
