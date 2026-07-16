# -*- coding: utf-8 -*-
"""Location: ./plugins/evecor_common/__init__.py
SPDX-License-Identifier: Apache-2.0
Authors: EVECOR

Shared adapter base for EVECOR thin native cpex plugins.

These plugins run *in-process* inside the ContextForge gateway (Python 3.11) and reach the
EVECOR services (`truthguard`/3.14, `agentsync`/3.14, `recon`, `ledger`) **out-of-process**
over a Unix-domain socket (preferred) or loopback HTTP. The services live in a separate
project with a higher Python pin and therefore cannot be imported in-process — the process
hop is mandatory, not a preference.

Two disciplines are enforced here, once, so every adapter inherits them:

* **Gates** (``tool_pre_invoke``) MAY block a tool call. When the gate service is
  unreachable the fail-mode is **explicit and operator-chosen** (``fail_mode: open|closed``)
  and the event is logged at ERROR ("alert loudly") so a degraded gate is never silent.
* **Observers** (``tool_post_invoke``) MUST NEVER block or fail a tool call. The service
  call is scheduled as a guarded background task; any error is swallowed-and-warned. The
  tool result is returned untouched regardless of observer health.
"""

# Future
from __future__ import annotations

# Standard
import asyncio
import json
import hashlib
from typing import Any, Literal, Optional

# Third-Party
import httpx
from pydantic import BaseModel, Field

# First-Party
from cpex.framework import (
    Plugin,
    PluginConfig,
    PluginContext,
    PluginViolation,
    ToolPostInvokePayload,
    ToolPostInvokeResult,
    ToolPreInvokePayload,
    ToolPreInvokeResult,
)
from mcpgateway.services.logging_service import LoggingService

logging_service = LoggingService()
logger = logging_service.get_logger(__name__)

FailMode = Literal["open", "closed"]


class EndpointConfig(BaseModel):
    """How to reach the out-of-process EVECOR service.

    Prefer ``socket_path`` (Unix-domain socket, sub-millisecond, no network exposure).
    Use ``base_url`` only for a loopback TCP listener.
    """

    socket_path: Optional[str] = Field(default=None, description="Unix-domain socket path (preferred).")
    base_url: Optional[str] = Field(default=None, description="Loopback base URL, e.g. http://127.0.0.1:8771")
    path: str = Field(default="/v1/hook", description="HTTP path POSTed for each hook call.")
    timeout_ms: int = Field(default=250, ge=1, description="Per-call timeout in milliseconds.")


def _request_id(context: PluginContext) -> Optional[str]:
    """Best-effort extraction of the request id; never raises."""
    gc = getattr(context, "global_context", None)
    return getattr(gc, "request_id", None) if gc is not None else None


def _public_context(context: PluginContext) -> dict[str, Any]:
    """Non-content cpex attribution safe for observer receipts."""
    gc = getattr(context, "global_context", None)
    if gc is None:
        return {
            "agent_identity": "",
            "user_identity": "",
            "tenant_id": "",
            "server_id": "",
            "session_id": "",
            "correlation_id": "",
        }

    request_id = getattr(gc, "request_id", None) or ""
    metadata = getattr(gc, "metadata", None) or {}
    state = getattr(gc, "state", None) or {}
    user = _safe_identity(getattr(gc, "user", None))
    user_context = getattr(gc, "user_context", None)
    user_identity = user or _safe_identity(getattr(user_context, "id", None)) or _safe_identity(getattr(user_context, "email", None))
    agent_identity = _safe_identity(metadata.get("agent") or metadata.get("agent_identity") or state.get("agent") or state.get("agent_identity"))
    session_id = _safe_identity(metadata.get("session_id") or state.get("session_id"))
    correlation_id = _safe_identity(metadata.get("correlation_id") or state.get("correlation_id") or request_id or session_id)

    return {
        "agent_identity": agent_identity,
        "user_identity": user_identity,
        "tenant_id": _safe_identity(getattr(gc, "tenant_id", None)),
        "server_id": _safe_identity(getattr(gc, "server_id", None)),
        "session_id": session_id,
        "correlation_id": correlation_id,
    }


class _EvecorAdapter(Plugin):
    """Base: holds endpoint config and a pooled httpx client over UDS or loopback."""

    #: Short service label used in logs, violation details and the request envelope.
    SERVICE: str = "evecor"

    def __init__(self, config: PluginConfig):
        super().__init__(config)
        self._endpoint = EndpointConfig.model_validate((self._config.config or {}).get("endpoint", {}))
        self._client: Optional[httpx.AsyncClient] = None

    def _get_client(self) -> httpx.AsyncClient:
        """Lazily build a pooled client; UDS transport keeps the per-call hop sub-ms."""
        if self._client is None:
            transport = httpx.AsyncHTTPTransport(uds=self._endpoint.socket_path) if self._endpoint.socket_path else None
            base_url = self._endpoint.base_url or "http://localhost"
            self._client = httpx.AsyncClient(
                transport=transport,
                base_url=base_url,
                timeout=httpx.Timeout(self._endpoint.timeout_ms / 1000.0),
            )
        return self._client

    async def _post(self, body: dict[str, Any]) -> dict[str, Any]:
        """POST the hook envelope and return the parsed JSON response. Raises on failure."""
        resp = await self._get_client().post(self._endpoint.path, json=body)
        resp.raise_for_status()
        return resp.json() if resp.content else {}

    async def shutdown(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None


class EvecorGateAdapter(_EvecorAdapter):
    """Gate adapter: blocks on ``tool_pre_invoke`` per an out-of-process verdict.

    Service contract — POST ``endpoint.path`` with::

        {"surface": str, "request_id": str|null, "tool": str, "args": object}

    Expected 2xx response::

        {"decision": "allow"|"deny", "reason": str, "code": str, "details": object}

    On transport failure the configured ``fail_mode`` decides allow vs. block, and the
    failure is always logged at ERROR.
    """

    #: The cpex hook this adapter binds to (used in logs/violation details).
    HOOK = "tool_pre_invoke"

    def __init__(self, config: PluginConfig):
        super().__init__(config)
        fm = (self._config.config or {}).get("fail_mode")
        if fm not in ("open", "closed"):
            # No default on purpose: a gate's behaviour when its service is down is a
            # conscious operator decision, not something to inherit silently.
            raise ValueError(f"{self.SERVICE} gate requires explicit fail_mode: 'open' or 'closed' (got {fm!r})")
        self._fail_mode: FailMode = fm

    def _fail(self, reason: str, detail: Any, rid: Optional[str]) -> ToolPreInvokeResult:
        """Single fail-mode resolution for EVERY gate failure: unreachable, socket-missing,
        timeout, non-2xx, or malformed response all land here. Always logged at ERROR."""
        logger.error(
            "EVECOR gate '%s' [%s] unavailable (request_id=%s, failure=%s): %s; applying fail_mode=%s",
            self.SERVICE, self.HOOK, rid, reason, detail, self._fail_mode,
        )
        if self._fail_mode == "closed":
            return ToolPreInvokeResult(
                continue_processing=False,
                violation=PluginViolation(
                    reason="Control gate unavailable",
                    description=f"{self.SERVICE} gate {reason} and fail_mode=closed",
                    code="GATE_UNAVAILABLE",
                    details={"surface": self.SERVICE, "hook": self.HOOK, "failure": reason, "detail": str(detail)},
                    http_status_code=503,
                ),
            )
        return ToolPreInvokeResult(continue_processing=True, metadata={"evecor_gate": self.SERVICE, "gate_unavailable": True, "failure": reason})

    async def _gate(self, payload: ToolPreInvokePayload, context: PluginContext) -> ToolPreInvokeResult:
        rid = _request_id(context)
        body = {"surface": self.SERVICE, "request_id": rid, "tool": payload.name, "args": payload.args or {}}
        try:
            verdict = await self._post(body)  # client carries a per-call timeout; slow -> raises -> _fail
        except Exception as exc:  # connection refused / socket missing / timeout / non-2xx / bad JSON
            return self._fail("unreachable_or_timeout", exc, rid)

        if not isinstance(verdict, dict):  # 2xx but not even a JSON object
            return self._fail("malformed_response", verdict, rid)
        decision = str(verdict.get("decision", "")).strip().lower()
        if decision == "deny":
            return ToolPreInvokeResult(
                continue_processing=False,
                violation=PluginViolation(
                    reason=str(verdict.get("reason") or f"Blocked by {self.SERVICE}"),
                    description=str(verdict.get("reason") or f"{self.SERVICE} denied this tool invocation"),
                    code=str(verdict.get("code") or f"{self.SERVICE.upper()}_DENY"),
                    details={"surface": self.SERVICE, "hook": self.HOOK, **(verdict.get("details") or {})},
                    http_status_code=403,
                ),
            )
        if decision == "allow":
            return ToolPreInvokeResult(continue_processing=True, metadata={"evecor_gate": self.SERVICE, "decision": "allow"})
        # 2xx but no recognizable allow/deny verdict -> treat as a gate failure, NOT a silent allow.
        return self._fail("malformed_response", verdict, rid)


class EvecorObserverAdapter(_EvecorAdapter):
    """Observer adapter: records on ``tool_post_invoke`` without ever blocking the response.

    Service contract — fire-and-forget POST ``endpoint.path`` with::

        {"surface": str, "request_id": str|null, "tool": str, "result": any}

    The response body is ignored. Any error (unreachable, timeout, non-2xx, serialization)
    is swallowed and logged at WARNING; the tool result is always returned untouched.
    """

    #: The cpex hook this adapter binds to (used in the drop log).
    HOOK = "tool_post_invoke"
    INCLUDE_RESULT = True

    async def _observe(self, payload: ToolPostInvokePayload, context: PluginContext) -> ToolPostInvokeResult:
        rid = _request_id(context)
        body = {"surface": self.SERVICE, "request_id": rid, "tool": payload.name, **_public_context(context)}
        if self.INCLUDE_RESULT:
            body["result"] = _safe(payload.result)
        else:
            body["result_type"] = type(payload.result).__name__
        task = asyncio.create_task(self._guarded_record(body, rid))
        # Return immediately; cpex strong-refs the task via background_tasks and gathers it
        # with return_exceptions=True on response flush, so it can never reach the caller.
        return ToolPostInvokeResult(continue_processing=True, background_tasks=[task])

    async def _guarded_record(self, body: dict[str, Any], rid: Optional[str]) -> None:
        try:
            await self._post(body)
        except Exception as exc:  # never propagate: an observer must not fail a tool call
            # Never blocks AND never silently drops: log carries service, hook and the reason.
            logger.warning("EVECOR observer '%s' [%s] dropped a record (request_id=%s): %r", self.SERVICE, self.HOOK, rid, exc)


def _safe(value: Any) -> Any:
    """Coerce a tool result into something JSON-serializable; never raises."""
    try:
        json.dumps(value)
        return value
    except Exception:
        return repr(value)


def _safe_identity(value: Any) -> str:
    """Return low-risk identity labels; hash structured values to avoid payload leakage."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    try:
        encoded = json.dumps(value, sort_keys=True, default=str)
    except Exception:
        encoded = repr(value)
    digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:16]
    return f"sha256:{digest}"
