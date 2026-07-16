# -*- coding: utf-8 -*-
"""Location: ./plugins/recon_recorder/recon_recorder.py
SPDX-License-Identifier: Apache-2.0
Authors: EVECOR

RECON recorder — flight-recorder observer. Records each tool invocation on
``tool_post_invoke`` by fire-and-forget to the out-of-process RECON service. It NEVER blocks
or fails a tool call: an unreachable recorder drops the record with a warning.

Thin native adapter: see ``plugins.evecor_common.EvecorObserverAdapter``. Source service at
``agentsync/src/recon``. RECON in turn persists to the stele attestation store (3.12),
reached out-of-process from RECON — not from this adapter.
"""

# First-Party
from cpex.framework import PluginContext, ToolPostInvokePayload, ToolPostInvokeResult
from plugins.evecor_common import EvecorObserverAdapter


class ReconRecorder(EvecorObserverAdapter):
    """Record tool invocations to RECON without ever blocking the response."""

    SERVICE = "recon"

    async def tool_post_invoke(self, payload: ToolPostInvokePayload, context: PluginContext) -> ToolPostInvokeResult:
        return await self._observe(payload, context)
