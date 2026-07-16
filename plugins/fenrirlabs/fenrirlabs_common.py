# -*- coding: utf-8 -*-
"""Location: ./plugins/fenrirlabs/fenrirlabs_common.py
SPDX-License-Identifier: Apache-2.0

Shared adapter base for Fenrir Labs thin native cpex skill hooks.

These plugins run in-process in the ContextForge gateway and reach the out-of-process
fenrirlabs gateway service over UDS or loopback HTTP. The gateway loads SKILL.md assets
by calling the standalone FenrirLabs gateway (127.0.0.1:8778), which serves skill
injection context for matching tool/prompt events.
invocations.

Skill hooks are **transform** mode: they never block tool calls; they attach skill guidance
via result metadata (and optional args augmentation when configured).
"""

from __future__ import annotations

import json
from typing import Any, Literal, Optional

import httpx
from pydantic import BaseModel, Field

from cpex.framework import (
    Plugin,
    PluginConfig,
    PluginContext,
    PromptPrehookPayload,
    PromptPrehookResult,
    ToolPreInvokePayload,
    ToolPreInvokeResult,
)
from mcpgateway.services.logging_service import LoggingService

logger = LoggingService().get_logger(__name__)

FailMode = Literal["open", "closed"]


class EndpointConfig(BaseModel):
    """How to reach the out-of-process fenrirlabs gateway."""

    socket_path: Optional[str] = Field(default=None, description="Unix-domain socket path (preferred).")
    base_url: Optional[str] = Field(default=None, description="Loopback base URL, e.g. http://127.0.0.1:8778")
    path: str = Field(default="/v1/hook", description="HTTP path POSTed for each hook call.")
    timeout_ms: int = Field(default=500, ge=1, description="Per-call timeout in milliseconds.")


def _request_id(context: PluginContext) -> Optional[str]:
    gc = getattr(context, "global_context", None)
    return getattr(gc, "request_id", None) if gc is not None else None


class FenrirSkillAdapter(Plugin):
    """Base: holds endpoint config, skill_id, and a pooled httpx client."""

    HOOK_KIND: str = "skill"

    def __init__(self, config: PluginConfig):
        super().__init__(config)
        cfg = self._config.config or {}
        self._skill_id: str = cfg.get("skill_id", "")
        if not self._skill_id:
            raise ValueError("fenrirlabs skill hook requires config.skill_id")
        self._endpoint = EndpointConfig.model_validate(cfg.get("endpoint", {}))
        self._inject_args_key: str = cfg.get("inject_args_key", "_fenrirlabs_skill_context")
        self._max_instruction_chars: int = int(cfg.get("max_instruction_chars", 8000))
        fm = cfg.get("fail_mode", "open")
        if fm not in ("open", "closed"):
            raise ValueError(f"fenrirlabs skill hook fail_mode must be 'open' or 'closed' (got {fm!r})")
        self._fail_mode: FailMode = fm
        self._client: Optional[httpx.AsyncClient] = None

    @property
    def skill_id(self) -> str:
        return self._skill_id

    def _get_client(self) -> httpx.AsyncClient:
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
        resp = await self._get_client().post(self._endpoint.path, json=body)
        resp.raise_for_status()
        return resp.json() if resp.content else {}

    async def shutdown(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def _fail(self, hook: str, reason: str, detail: Any, rid: Optional[str]) -> dict[str, Any]:
        logger.error(
            "Fenrir skill '%s' [%s] gateway unavailable (request_id=%s, failure=%s): %s; fail_mode=%s",
            self._skill_id,
            hook,
            rid,
            reason,
            detail,
            self._fail_mode,
        )
        return {"match": False, "gateway_unavailable": True, "failure": reason, "fail_mode": self._fail_mode}

    async def _call_gateway(self, hook: str, body: dict[str, Any], rid: Optional[str]) -> dict[str, Any]:
        try:
            verdict = await self._post(body)
        except Exception as exc:
            return self._fail(hook, "unreachable_or_timeout", exc, rid)
        if not isinstance(verdict, dict):
            return self._fail(hook, "malformed_response", verdict, rid)
        return verdict

    def _build_metadata(self, verdict: dict[str, Any]) -> dict[str, Any]:
        meta: dict[str, Any] = {
            "fenrirlabs_skill_id": self._skill_id,
            "fenrirlabs_match": bool(verdict.get("match")),
        }
        if verdict.get("match"):
            meta["fenrirlabs_skill_name"] = verdict.get("skill_name")
            meta["fenrirlabs_instructions_preview"] = (verdict.get("instructions") or "")[:512]
        if verdict.get("gateway_unavailable"):
            meta["fenrirlabs_gateway_unavailable"] = True
        return meta

    async def tool_pre_invoke(self, payload: ToolPreInvokePayload, context: PluginContext) -> ToolPreInvokeResult:
        rid = _request_id(context)
        body = {
            "hook": "tool_pre_invoke",
            "skill_id": self._skill_id,
            "request_id": rid,
            "tool": payload.name,
            "args": payload.args or {},
        }
        verdict = await self._call_gateway("tool_pre_invoke", body, rid)
        if verdict.get("gateway_unavailable") and self._fail_mode == "closed":
            from cpex.framework import PluginViolation

            return ToolPreInvokeResult(
                continue_processing=False,
                violation=PluginViolation(
                    reason="Fenrir skill gateway unavailable",
                    description=f"Skill hook {self._skill_id} could not reach the fenrirlabs gateway",
                    code="FENRIR_GATE_UNAVAILABLE",
                    details={"skill_id": self._skill_id, **verdict},
                    http_status_code=503,
                ),
            )
        if not verdict.get("match"):
            return ToolPreInvokeResult(continue_processing=True, metadata=self._build_metadata(verdict))

        args = dict(payload.args or {})
        context_blob = {
            "skill_id": self._skill_id,
            "skill_name": verdict.get("skill_name"),
            "instructions": (verdict.get("instructions") or "")[: self._max_instruction_chars],
            "scripts_dir": verdict.get("scripts_dir"),
            "security_notice": verdict.get("security_notice"),
        }
        args[self._inject_args_key] = context_blob
        modified = payload.model_copy(update={"args": args})
        return ToolPreInvokeResult(
            continue_processing=True,
            modified_payload=modified,
            metadata=self._build_metadata(verdict),
        )

    async def prompt_pre_fetch(self, payload: PromptPrehookPayload, context: PluginContext) -> PromptPrehookResult:
        rid = _request_id(context)
        body = {
            "hook": "prompt_pre_fetch",
            "skill_id": self._skill_id,
            "request_id": rid,
            "prompt_id": payload.prompt_id,
            "args": payload.args or {},
        }
        verdict = await self._call_gateway("prompt_pre_fetch", body, rid)
        if not verdict.get("match"):
            return PromptPrehookResult(continue_processing=True, metadata=self._build_metadata(verdict))

        args = dict(payload.args or {})
        args[self._inject_args_key] = {
            "skill_id": self._skill_id,
            "skill_name": verdict.get("skill_name"),
            "instructions": (verdict.get("instructions") or "")[: self._max_instruction_chars],
            "security_notice": verdict.get("security_notice"),
        }
        modified = payload.model_copy(update={"args": args})
        return PromptPrehookResult(
            continue_processing=True,
            modified_payload=modified,
            metadata=self._build_metadata(verdict),
        )
