# -*- coding: utf-8 -*-
"""Location: ./plugins/truthguard_gate/truthguard_gate.py
SPDX-License-Identifier: Apache-2.0
Authors: EVECOR

TruthGuard gate — blocks dangerous/phantom tool invocations on ``tool_pre_invoke`` by
delegating the verdict to the out-of-process TruthGuard service (EVECOR, Python 3.14).

Thin native adapter: see ``plugins.evecor_common.EvecorGateAdapter`` for transport and the
explicit fail-mode discipline. TruthGuard is the source service at
``agentsync/src/truthguard``.
"""

# First-Party
from cpex.framework import PluginContext, ToolPreInvokePayload, ToolPreInvokeResult
from plugins.evecor_common import EvecorGateAdapter


class TruthGuardGate(EvecorGateAdapter):
    """Block tool calls that TruthGuard rules reject (dangerous, phantom, ...)."""

    SERVICE = "truthguard"

    async def tool_pre_invoke(self, payload: ToolPreInvokePayload, context: PluginContext) -> ToolPreInvokeResult:
        return await self._gate(payload, context)
