# -*- coding: utf-8 -*-
"""Career-ops bridge — CPEX plugin connecting career-ops agents to ContextForge.

When a career-ops session is active this plugin:

* Injects career-ops skill guidance on ``agent_pre_invoke`` (including a reminder that the
  full federated MCP tool catalog on the gateway is available).
* Injects ``Authorization: Bearer …`` on ``tool_pre_invoke`` for configured
  ``career_ops_*`` REST tools so internal localhost feeds authenticate correctly.

Native career-ops tools must be registered as REST tools on the gateway (see
``gateway_tools.yaml``). CPEX hooks cannot register tools or short-circuit execution;
they govern and enrich invocations that already flow through ContextForge.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

from cpex.framework import (
    AgentPreInvokePayload,
    AgentPreInvokeResult,
    HttpHeaderPayload,
    Plugin,
    PluginConfig,
    PluginContext,
    PluginViolation,
    ToolPreInvokePayload,
    ToolPreInvokeResult,
)
from cpex.framework.utils import get_attr
from mcpgateway.services.logging_service import LoggingService

from plugins.vault_credential.contextforge_secrets_client import (
    ContextForgeSecretsClient,
    ContextForgeSecretsError,
    SecretNotFoundError,
)

logger = LoggingService().get_logger(__name__)

_PLUGIN = "career_ops_bridge"
_DEFAULT_SKILL = Path(__file__).resolve().parent / "skill.md"
FailMode = Literal["open", "closed"]


class ActivationConfig(BaseModel):
    """When to treat a session as career-ops."""

    always_on: bool = False
    session_tags: list[str] = Field(default_factory=lambda: ["career-ops"])
    agent_id_prefixes: list[str] = Field(default_factory=list)


class CareerOpsBridgeConfig(BaseModel):
    """Plugin configuration."""

    activation: ActivationConfig = Field(default_factory=ActivationConfig)
    skill_path: Optional[str] = None
    max_skill_chars: int = Field(default=12000, ge=256)
    inject_args_key: str = "_career_ops_context"
    career_ops_tools: list[str] = Field(
        default_factory=lambda: ["career_ops_ingest", "career_ops_search"]
    )
    career_ops_tool_prefix: str = "career_ops_"
    bearer_secret: Optional[str] = Field(
        default=None,
        description="ContextForge secret name for MCP bearer token (localhost feed auth).",
    )
    lookup_timeout_seconds: float = 2.0
    fail_mode: FailMode = "open"
    gateway_tools_note: str = (
        "All MCP tools registered on this ContextForge gateway are available in this session. "
        "Inspect the session tool list and prefer gateway tools over shell when applicable."
    )


def _normalized_gateway_tags(context: PluginContext) -> list[str]:
    gateway_metadata = context.global_context.metadata.get("gateway")
    tags_raw = get_attr(gateway_metadata, "tags", []) or []
    out: list[str] = []
    for tag in tags_raw:
        if isinstance(tag, dict):
            val = str(tag.get("label", "")).strip()
        elif hasattr(tag, "label"):
            val = str(getattr(tag, "label")).strip()
        else:
            val = str(tag).strip()
        if val:
            out.append(val)
    return out


def _header_map(payload: ToolPreInvokePayload) -> dict[str, str]:
    if not payload.headers:
        return {}
    return {k.lower(): v for k, v in payload.headers.root.items()}


class CareerOpsBridgePlugin(Plugin):
    """Bridge career-ops agents to ContextForge tool catalog + internal job feeds."""

    def __init__(self, config: PluginConfig) -> None:
        super().__init__(config)
        raw = config.config or {}
        self._cfg = CareerOpsBridgeConfig.model_validate(raw)
        if self._cfg.fail_mode not in ("open", "closed"):
            raise ValueError(f"{_PLUGIN}: fail_mode must be 'open' or 'closed'")
        self._skill_text: Optional[str] = None
        self._secrets: Optional[ContextForgeSecretsClient] = None
        if self._cfg.bearer_secret:
            self._secrets = ContextForgeSecretsClient(
                lookup_timeout=self._cfg.lookup_timeout_seconds
            )
        logger.info(
            "plugin=%s always_on=%s tools=%s bearer_secret=%s",
            _PLUGIN,
            self._cfg.activation.always_on,
            self._cfg.career_ops_tools,
            bool(self._cfg.bearer_secret),
        )

    def _load_skill(self) -> str:
        if self._skill_text is not None:
            return self._skill_text
        path = Path(self._cfg.skill_path) if self._cfg.skill_path else _DEFAULT_SKILL
        if path.is_file():
            text = path.read_text(encoding="utf-8")
        else:
            text = _DEFAULT_SKILL.read_text(encoding="utf-8")
        self._skill_text = text[: self._cfg.max_skill_chars]
        return self._skill_text

    def _is_career_ops_session(
        self, context: PluginContext, agent_id: Optional[str] = None
    ) -> bool:
        if self._cfg.activation.always_on:
            return True
        tags = set(_normalized_gateway_tags(context))
        if tags.intersection(self._cfg.activation.session_tags):
            return True
        if agent_id:
            aid = str(agent_id)
            for prefix in self._cfg.activation.agent_id_prefixes:
                if aid.startswith(prefix):
                    return True
        return False

    def _is_career_ops_tool(self, tool_name: str) -> bool:
        if tool_name in self._cfg.career_ops_tools:
            return True
        prefix = self._cfg.career_ops_tool_prefix
        return bool(prefix) and tool_name.startswith(prefix)

    def _skill_block(self) -> str:
        skill = self._load_skill().strip()
        note = self._cfg.gateway_tools_note.strip()
        return f"{skill}\n\n---\n\n{note}"

    async def agent_pre_invoke(
        self, payload: AgentPreInvokePayload, context: PluginContext
    ) -> AgentPreInvokeResult:
        if not self._is_career_ops_session(context, payload.agent_id):
            return AgentPreInvokeResult(continue_processing=True)

        block = self._skill_block()
        existing = (payload.system_prompt or "").strip()
        if block in existing:
            return AgentPreInvokeResult(
                continue_processing=True,
                metadata={"career_ops_bridge": "skill_already_present"},
            )

        merged = f"{existing}\n\n{block}".strip() if existing else block
        modified = AgentPreInvokePayload(
            agent_id=payload.agent_id,
            messages=payload.messages,
            tools=payload.tools,
            headers=payload.headers,
            model=payload.model,
            system_prompt=merged,
            parameters=payload.parameters,
        )
        return AgentPreInvokeResult(
            continue_processing=True,
            modified_payload=modified,
            metadata={"career_ops_bridge": "skill_injected", "skill_chars": len(block)},
        )

    async def tool_pre_invoke(
        self, payload: ToolPreInvokePayload, context: PluginContext
    ) -> ToolPreInvokeResult:
        career_ops_session = self._is_career_ops_session(context)
        is_native = self._is_career_ops_tool(payload.name)

        if not career_ops_session and not is_native:
            return ToolPreInvokeResult(continue_processing=True)

        metadata: dict[str, Any] = {
            "career_ops_bridge": True,
            "career_ops_session": career_ops_session,
            "career_ops_native_tool": is_native,
        }

        modified_payload: Optional[ToolPreInvokePayload] = None

        if career_ops_session and self._cfg.inject_args_key:
            args = dict(payload.args or {})
            if self._cfg.inject_args_key not in args:
                args[self._cfg.inject_args_key] = {
                    "skill_preview": self._load_skill()[:2048],
                    "gateway_tools_note": self._cfg.gateway_tools_note,
                }
                modified_payload = payload.model_copy(update={"args": args})

        if is_native:
            auth_result = await self._inject_bearer(payload, modified_payload or payload)
            if auth_result.violation is not None:
                return auth_result
            modified_payload = auth_result.modified_payload or modified_payload
            metadata["career_ops_auth_injected"] = auth_result.metadata.get(
                "career_ops_auth_injected", False
            )

        return ToolPreInvokeResult(
            continue_processing=True,
            modified_payload=modified_payload,
            metadata=metadata,
        )

    async def _inject_bearer(
        self, payload: ToolPreInvokePayload, base: ToolPreInvokePayload
    ) -> ToolPreInvokeResult:
        headers = _header_map(base)
        if headers.get("authorization"):
            return ToolPreInvokeResult(
                continue_processing=True,
                modified_payload=base,
                metadata={"career_ops_auth_injected": False, "reason": "already_present"},
            )

        if not self._cfg.bearer_secret or not self._secrets:
            return ToolPreInvokeResult(
                continue_processing=True,
                modified_payload=base,
                metadata={"career_ops_auth_injected": False, "reason": "no_bearer_secret"},
            )

        try:
            token = await self._secrets.read_secret(self._cfg.bearer_secret)
        except SecretNotFoundError:
            logger.error("plugin=%s bearer_secret=%s result=not_found", _PLUGIN, self._cfg.bearer_secret)
            return self._auth_failure("secret_not_found")
        except ContextForgeSecretsError as exc:
            logger.error(
                "plugin=%s bearer_secret=%s result=lookup_error error=%s",
                _PLUGIN,
                self._cfg.bearer_secret,
                type(exc).__name__,
            )
            return self._auth_failure("lookup_error")
        except Exception:
            logger.error("plugin=%s bearer_secret=%s result=unexpected", _PLUGIN, self._cfg.bearer_secret, exc_info=True)
            return self._auth_failure("unexpected_error")

        headers["authorization"] = f"Bearer {token}"
        modified = base.model_copy(update={"headers": HttpHeaderPayload(root=headers)})
        return ToolPreInvokeResult(
            continue_processing=True,
            modified_payload=modified,
            metadata={"career_ops_auth_injected": True},
        )

    def _auth_failure(self, reason: str) -> ToolPreInvokeResult:
        if self._cfg.fail_mode == "open":
            return ToolPreInvokeResult(
                continue_processing=True,
                metadata={"career_ops_auth_injected": False, "reason": reason},
            )
        return ToolPreInvokeResult(
            continue_processing=False,
            violation=PluginViolation(
                reason="Career-ops bearer injection failed",
                description=f"{_PLUGIN}: {reason} for bearer_secret={self._cfg.bearer_secret}",
                code="CAREER_OPS_AUTH_FAILED",
                details={"plugin": _PLUGIN, "reason": reason},
                http_status_code=503,
            ),
        )

    async def shutdown(self) -> None:
        if self._secrets is not None:
            try:
                await self._secrets.aclose()
            except Exception:
                pass
