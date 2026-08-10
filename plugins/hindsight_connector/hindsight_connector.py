# -*- coding: utf-8 -*-
"""Hindsight connector for ContextForge CPEX.

This plugin is intentionally a connector, not a memory policy engine.

Hindsight remains the memory system and exposes its own MCP/HTTP API. ContextForge remains
the route/hook station. This plugin only adds route context for matching sessions and
metadata for Hindsight tool traffic already flowing through ContextForge.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from pydantic import BaseModel, Field

from cpex.framework import (
    AgentPreInvokePayload,
    AgentPreInvokeResult,
    Plugin,
    PluginConfig,
    PluginContext,
    ToolPreInvokePayload,
    ToolPreInvokeResult,
)
from cpex.framework.utils import get_attr

logger = logging.getLogger(__name__)

_PLUGIN = "hindsight_connector"


class ActivationConfig(BaseModel):
    """When to add Hindsight route context to an agent session."""

    always_on: bool = False
    session_tags: list[str] = Field(default_factory=lambda: ["hindsight", "memory"])
    agent_id_prefixes: list[str] = Field(default_factory=list)


class HindsightConnectorConfig(BaseModel):
    """Connector behavior.

    ``default_bank_id`` is advisory route context. Hindsight tools still receive normal
    caller-provided arguments and enforce their own bank semantics.
    """

    activation: ActivationConfig = Field(default_factory=ActivationConfig)
    default_bank_id: str = "JARVIS"
    mcp_gateway_name: str = "hindsight-agent-memory"
    mcp_url: str = "http://host.docker.internal:8888/mcp/JARVIS/"
    http_base_url: str = "http://host.docker.internal:8888"
    # Documentation only — this connector makes no outbound HTTP calls of its own
    # (``tool_pre_invoke`` annotates routing metadata). Since 2026-08-05 Hindsight
    # sits behind an authenticating Caddy proxy, and the credential that actually
    # authorizes the upstream call is carried by the ``hindsight-agent-memory``
    # gateway registration itself (auth_type ``authheaders``, header ``X-Api-Key``).
    # Recorded here so the connector stays self-describing about which secret
    # gates its route. See memory/hindsight/Caddyfile.
    api_key_env: str = "HINDSIGHT_PROXY_API_KEY"
    auth_header_name: str = "X-Api-Key"
    hindsight_tools: list[str] = Field(
        default_factory=lambda: [
            "retain",
            "sync_retain",
            "recall",
            "reflect",
            "get_bank",
            "list_memories",
            "get_memory",
            "list_documents",
            "get_document",
            "list_operations",
            "get_operation",
            "list_tags",
        ]
    )
    hindsight_tool_prefixes: list[str] = Field(default_factory=lambda: ["hindsight_", "hindsight-agent-memory-", "hindsight-agent-memory."])
    route_note: str = (
        "Hindsight memory is available through the ContextForge gateway. Use the Hindsight "
        "bank-pinned MCP tools for memory operations against JARVIS."
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


class HindsightConnectorPlugin(Plugin):
    """Attach Hindsight route context without changing Hindsight behavior."""

    def __init__(self, config: PluginConfig) -> None:
        super().__init__(config)
        self._cfg = HindsightConnectorConfig.model_validate(config.config or {})
        logger.info(
            "plugin=%s default_bank_id=%s mcp_gateway_name=%s mcp_url=%s",
            _PLUGIN,
            self._cfg.default_bank_id,
            self._cfg.mcp_gateway_name,
            self._cfg.mcp_url,
        )

    def _is_memory_session(self, context: PluginContext, agent_id: Optional[str] = None) -> bool:
        activation = self._cfg.activation
        if activation.always_on:
            return True
        tags = set(_normalized_gateway_tags(context))
        if tags.intersection(activation.session_tags):
            return True
        if agent_id:
            aid = str(agent_id)
            return any(aid.startswith(prefix) for prefix in activation.agent_id_prefixes)
        return False

    def _is_hindsight_tool(self, tool_name: str) -> bool:
        if tool_name in self._cfg.hindsight_tools:
            return True
        return any(tool_name.startswith(prefix) for prefix in self._cfg.hindsight_tool_prefixes)

    def _route_metadata(self) -> dict[str, Any]:
        return {
            "hindsight_connector": True,
            "default_bank_id": self._cfg.default_bank_id,
            "mcp_gateway_name": self._cfg.mcp_gateway_name,
            "mcp_url": self._cfg.mcp_url,
            "http_base_url": self._cfg.http_base_url,
        }

    async def agent_pre_invoke(
        self, payload: AgentPreInvokePayload, context: PluginContext
    ) -> AgentPreInvokeResult:
        if not self._is_memory_session(context, payload.agent_id):
            return AgentPreInvokeResult(continue_processing=True)

        note = self._cfg.route_note.strip()
        existing = (payload.system_prompt or "").strip()
        if not note or note in existing:
            return AgentPreInvokeResult(continue_processing=True, metadata=self._route_metadata())

        merged = f"{existing}\n\n{note}".strip() if existing else note
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
            metadata={**self._route_metadata(), "route_note_injected": True},
        )

    async def tool_pre_invoke(
        self, payload: ToolPreInvokePayload, context: PluginContext
    ) -> ToolPreInvokeResult:
        if not self._is_hindsight_tool(payload.name):
            return ToolPreInvokeResult(continue_processing=True)

        metadata = self._route_metadata()
        metadata.update(
            {
                "tool": payload.name,
                "has_bank_id_arg": bool((payload.args or {}).get("bank_id")),
            }
        )
        return ToolPreInvokeResult(continue_processing=True, metadata=metadata)
