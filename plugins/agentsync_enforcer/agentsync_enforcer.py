# -*- coding: utf-8 -*-
"""Location: ./plugins/agentsync_enforcer/agentsync_enforcer.py
SPDX-License-Identifier: Apache-2.0
Authors: EVECOR

AgentSync enforcer gate — evaluates rules/obligations on ``tool_pre_invoke`` and blocks
disallowed tool invocations, delegating the verdict to the out-of-process AgentSync service
(EVECOR, Python 3.14) which already exposes enforcer tools via its FastMCP server.

Thin native adapter: see ``plugins.evecor_common.EvecorGateAdapter`` for transport and the
explicit fail-mode discipline. Source service at ``agentsync/src/agentsync`` (enforcer).
"""

# First-Party
from cpex.framework import PluginContext, ToolPreInvokePayload, ToolPreInvokeResult
from plugins.evecor_common import EvecorGateAdapter


class AgentSyncEnforcer(EvecorGateAdapter):
    """Block tool calls that violate AgentSync rules/obligations."""

    SERVICE = "agentsync_enforcer"

    async def tool_pre_invoke(self, payload: ToolPreInvokePayload, context: PluginContext) -> ToolPreInvokeResult:
        return await self._gate(payload, context)
