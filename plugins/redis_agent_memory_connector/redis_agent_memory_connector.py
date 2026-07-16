# -*- coding: utf-8 -*-
"""Redis Agent Memory connector for ContextForge CPEX.

This plugin is intentionally a connector, not a memory policy engine.

Redis Agent Memory remains the memory system and exposes its own REST/MCP APIs.
ContextForge remains the route/hook station. This plugin only adds route context
for matching sessions and metadata for Redis Agent Memory tool traffic already
flowing through ContextForge.
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

_PLUGIN = "redis_agent_memory_connector"


class ActivationConfig(BaseModel):
    """When to add Redis Agent Memory route context to an agent session."""

    always_on: bool = False
    session_tags: list[str] = Field(default_factory=lambda: ["redis-memory", "agent-memory"])
    agent_id_prefixes: list[str] = Field(default_factory=list)


class RedisAgentMemoryConnectorConfig(BaseModel):
    """Connector behavior."""

    activation: ActivationConfig = Field(default_factory=ActivationConfig)
    default_namespace: str = "JARVIS"
    mcp_gateway_name: str = "redis-agent-memory"
    mcp_url: str = "http://host.docker.internal:8101/mcp"
    http_base_url: str = "http://host.docker.internal:8100"
    redis_agent_memory_tool_prefixes: list[str] = Field(
        default_factory=lambda: ["redis-agent-memory-", "redis-agent-memory.", "agent-memory-", "agent_memory_"]
    )
    route_note: str = (
        "Redis Agent Memory is available through the ContextForge gateway. Use its MCP "
        "tools for explicit memory operations against the JARVIS namespace."
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


class RedisAgentMemoryConnectorPlugin(Plugin):
    """Attach Redis Agent Memory route context without changing memory behavior."""

    def __init__(self, config: PluginConfig) -> None:
        super().__init__(config)
        self._cfg = RedisAgentMemoryConnectorConfig.model_validate(config.config or {})
        logger.info(
            "plugin=%s default_namespace=%s mcp_gateway_name=%s mcp_url=%s",
            _PLUGIN,
            self._cfg.default_namespace,
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

    def _is_redis_agent_memory_tool(self, tool_name: str) -> bool:
        return any(tool_name.startswith(prefix) for prefix in self._cfg.redis_agent_memory_tool_prefixes)

    def _route_metadata(self) -> dict[str, Any]:
        return {
            "redis_agent_memory_connector": True,
            "default_namespace": self._cfg.default_namespace,
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
        if not self._is_redis_agent_memory_tool(payload.name):
            return ToolPreInvokeResult(continue_processing=True)

        metadata = self._route_metadata()
        metadata.update(
            {
                "tool": payload.name,
                "has_namespace_arg": bool((payload.args or {}).get("namespace")),
                "has_user_id_arg": bool((payload.args or {}).get("user_id")),
                "has_session_id_arg": bool((payload.args or {}).get("session_id")),
            }
        )
        return ToolPreInvokeResult(continue_processing=True, metadata=metadata)
