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
    gateway_proxy-jsonrpc   — via ContextForge proxy (placeholder)
    gateway_virtual-jsonrpc — via ContextForge virtual server (placeholder)

The two gateway cells are blanket-xfailed at collection time
(``pytest_collection_modifyitems`` below) under **A2A-GAP-001** — see
``COMPLIANCE_GAPS.md`` — because ContextForge does not yet expose a
native A2A JSON-RPC endpoint. Their placeholder targets raise
``NotImplementedError`` inside ``_open_client``; with the xfail marker
already attached at collection time, pytest reports each cell as
``XFAIL`` rather than ``ERROR``. When the gap closes, delete the
collection hook below and the next matrix run will surface ``XPASS``
on each newly-passing cell.
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

# Wave 2 gap-closure tests parametrize over THESE targets. ``gateway_virtual``
# is added in Wave 7 (T28 Part B) after T20 verifies server-CRUD wiring.
_PART_A_GAP_CLOSURE_TARGETS: tuple[str, ...] = ("reference", "gateway_proxy")

_GATEWAY_TARGET_NAMES = frozenset({"gateway_proxy", "gateway_virtual"})
_GATEWAY_XFAIL_REASON = "A2A-GAP-001: ContextForge lacks native A2A passthrough at a public " "JSON-RPC + well-known-card route. See " "tests/live_gateway/a2a_compliance/COMPLIANCE_GAPS.md."


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Blanket-xfail every gateway-target matrix cell (A2A-GAP-001).

    The entire ``gateway_proxy`` and ``gateway_virtual`` columns are
    known broken via A2A-GAP-001 — the gateway has no native A2A
    JSON-RPC endpoint, so the placeholder targets raise
    ``NotImplementedError`` inside ``_open_client``. Marking xfail at
    collection time (before fixture setup runs) means the fixture's
    exception lands inside an xfail-wrapped test and pytest reports
    ``XFAIL`` instead of ``ERROR``.

    Rather than requiring every future test author to remember to call
    ``xfail_on`` for this column-wide gap, this hook applies the
    marker once per cell. When A2A-GAP-001 closes, delete this hook
    entirely and the next matrix run surfaces ``XPASS`` on each
    newly-passing gateway cell — the cue to move the gap entry to
    "Closed gaps" in COMPLIANCE_GAPS.md.

    Per-test ``xfail_on`` calls (the helper in
    ``helpers/compliance.py``) remain the right tool for narrower
    gaps that don't have a stable column-wide pattern.
    """
    del config  # unused; pytest-canonical signature
    for item in items:
        callspec = getattr(item, "callspec", None)
        if callspec is None:
            continue
        target_name = callspec.id.split("-")[0]
        if target_name in _GATEWAY_TARGET_NAMES:
            item.add_marker(pytest.mark.xfail(strict=False, reason=_GATEWAY_XFAIL_REASON))


def _build_target(target_name: str, request: pytest.FixtureRequest):
    """Construct an A2AComplianceTarget for ``target_name``.

    Reference target pulls the resolved card URL from the
    ``echo_agent_card_url`` fixture (which transitively probes the
    agent's ``/health`` and skips the session if it's unreachable).
    Gateway placeholders are constructed unconditionally — their
    ``_open_client`` raises at fixture-setup time, captured by the
    collection-modify hook above.
    """
    if target_name == "reference":
        base_url = request.getfixturevalue("echo_agent_base_url")
        return A2AReferenceTarget(base_url=base_url)
    if target_name == "gateway_proxy":
        return A2AGatewayProxyTarget(
            base_url="http://placeholder",
            auth_token="placeholder",
            agent_name="a2a-echo-agent",
        )
    if target_name == "gateway_virtual":
        return A2AGatewayVirtualServerTarget(
            base_url="http://placeholder",
            auth_token="placeholder",
            server_id="placeholder",
            agent_name="a2a-echo-agent",
        )
    raise AssertionError(f"unknown target: {target_name!r}")


@pytest_asyncio.fixture(params=_CASES, ids=[f"{t}-{x}" for t, x in _CASES])
async def client(request: pytest.FixtureRequest) -> AsyncIterator[Client]:
    """Yield a connected ``a2a.client.Client`` for the parametrized cell.

    Reference target opens a fresh ``httpx.AsyncClient`` + ``ClientFactory``
    per invocation; the SDK auto-routes via JSON-RPC per the echo
    agent's advertised card interfaces.

    Gateway targets raise ``NotImplementedError`` inside
    ``_open_client`` (see ``targets/gateway_proxy.py`` /
    ``gateway_virtual.py``). The collection hook above attaches an
    ``xfail`` marker to every gateway cell so the exception is
    captured as ``XFAIL``.
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


@pytest.fixture
def raw_card_url(
    gap_closure_target: str,
    gateway_base_url: str,
    registered_agent_name: str,
    echo_agent_base_url: str,
) -> str:
    """Target-aware well-known card URL for raw-HTTP gap-closure tests.

    Plan T28 Part A: lets T9 card-discovery tests parametrize over
    ``{reference, gateway_proxy}`` and exercise the same raw HTTP path
    that ``ClientFactory.create_from_url`` would. The gateway target
    follows the F8 + T11 URL convention
    ``/a2a/{agent_name}/.well-known/agent-card.json``.

    Args:
        gap_closure_target: Current parametrize cell.
        gateway_base_url: Gateway base for gateway-target URLs.
        registered_agent_name: Agent name used in the URL path.
        echo_agent_base_url: Reference target's base URL (echo agent).

    Returns:
        The well-known card URL for the parametrized target.
    """
    if gap_closure_target == "reference":
        return f"{echo_agent_base_url}/.well-known/agent-card.json"
    if gap_closure_target == "gateway_proxy":
        return f"{gateway_base_url}/a2a/{registered_agent_name}/.well-known/agent-card.json"
    raise AssertionError(f"unsupported gap-closure target {gap_closure_target!r}")


@pytest.fixture
def raw_dispatch_url(
    gap_closure_target: str,
    gateway_base_url: str,
    registered_agent_name: str,
    echo_agent_base_url: str,
) -> str:
    """Target-aware dispatch URL for raw-HTTP gap-closure tests.

    Plan T28 Part A: lets T10 dispatch-tests parametrize over
    ``{reference, gateway_proxy}``. The gateway target follows the
    F8 + T12 URL convention ``/a2a/{agent_name}`` (bare POST endpoint,
    NOT ``/jsonrpc`` suffix — that decision lives in Q9 of the plan).

    Reference target uses the echo agent's bare base URL, which is the
    JSON-RPC endpoint A2A 1.0.0 advertises in its card.
    """
    if gap_closure_target == "reference":
        return echo_agent_base_url
    if gap_closure_target == "gateway_proxy":
        return f"{gateway_base_url}/a2a/{registered_agent_name}"
    raise AssertionError(f"unsupported gap-closure target {gap_closure_target!r}")
