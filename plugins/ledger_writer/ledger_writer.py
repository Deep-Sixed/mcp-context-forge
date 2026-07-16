# -*- coding: utf-8 -*-
"""Location: ./plugins/ledger_writer/ledger_writer.py
SPDX-License-Identifier: Apache-2.0
Authors: EVECOR

Ledger writer — verifiable-knowledge-ledger observer. Appends a ledger entry for each tool
invocation on ``tool_post_invoke`` by fire-and-forget to the out-of-process Ledger service.
It NEVER blocks or fails a tool call: an unreachable ledger drops the entry with a warning.

Thin native adapter: see ``plugins.evecor_common.EvecorObserverAdapter``. Source service at
``agentsync/src/ledger``. Like RECON, the Ledger persists to stele (3.12) out-of-process on
its own side, not from this adapter.
"""

# First-Party
from cpex.framework import PluginContext, ToolPostInvokePayload, ToolPostInvokeResult
from plugins.evecor_common import EvecorObserverAdapter


class LedgerWriter(EvecorObserverAdapter):
    """Append tool invocations to the Ledger without ever blocking the response."""

    SERVICE = "ledger"
    INCLUDE_RESULT = False

    async def tool_post_invoke(self, payload: ToolPostInvokePayload, context: PluginContext) -> ToolPostInvokeResult:
        return await self._observe(payload, context)
