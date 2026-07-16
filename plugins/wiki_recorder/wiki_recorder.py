# -*- coding: utf-8 -*-
"""Location: ./plugins/wiki_recorder/wiki_recorder.py
SPDX-License-Identifier: Apache-2.0
Authors: EVECOR

WIKI recorder — knowledge-corpus observer. Records each tool invocation on
``tool_post_invoke`` by fire-and-forget to the out-of-process WIKI gateway, which appends
the turn into the Karpathy-three-layer wiki's ``raw/sessions/`` corpus for later synthesis.

Never blocks or fails a tool call: an unreachable recorder drops the record with a warning.

Thin native adapter: see ``plugins.evecor_common.EvecorObserverAdapter``. Source service at
``agentsync/src/wiki/gateway.py``.
"""

# First-Party
from cpex.framework import PluginContext, ToolPostInvokePayload, ToolPostInvokeResult
from plugins.evecor_common import EvecorObserverAdapter


class WikiRecorder(EvecorObserverAdapter):
    """Record tool invocations to the WIKI corpus without ever blocking the response."""

    SERVICE = "wiki"

    async def tool_post_invoke(self, payload: ToolPostInvokePayload, context: PluginContext) -> ToolPostInvokeResult:
        return await self._observe(payload, context)
