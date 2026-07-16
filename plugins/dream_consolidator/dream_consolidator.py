# -*- coding: utf-8 -*-
"""Location: ./plugins/dream_consolidator/dream_consolidator.py
SPDX-License-Identifier: Apache-2.0
Authors: EVECOR (concept forked from grandamenium/dream-skill, MIT)

Dream Consolidator — thin native cpex observer.

Fire-and-forget: each post-hook serializes a turn envelope and POSTs it over
the Unix-domain socket to the out-of-process Dreaming service
(memory/dreaming), which owns redaction, storage (PostgreSQL), the trigger
heuristic, and the LLM consolidation pass. Nothing here touches disk or
blocks a response; an unreachable service drops the envelope with a warning
and a monotonic drop counter.

Content exception: unlike the other EVECOR observers this envelope carries
conversation CONTENT (that is the feature), clipped per field. The service
redacts on write; nothing content-bearing is ever logged here.

Post-hooks only, one shared ``_emit`` discipline:

  * ``prompt_post_fetch``  — rendered prompt messages (MCP prompt templates)
  * ``tool_post_invoke``   — tool results
  * ``agent_post_invoke``  — A2A agent conversation messages
"""
from __future__ import annotations

# Standard
import asyncio
from typing import Any, Optional

# First-Party
from cpex.framework import (
    AgentPostInvokePayload,
    AgentPostInvokeResult,
    PluginConfig,
    PluginContext,
    PromptPosthookPayload,
    PromptPosthookResult,
    ToolPostInvokePayload,
    ToolPostInvokeResult,
)
from mcpgateway.services.logging_service import LoggingService
from plugins.evecor_common import EvecorObserverAdapter

logging_service = LoggingService()
logger = logging_service.get_logger(__name__)

SCHEMA_VERSION = "dreaming.turn.v1"
_MAX_FIELD_CHARS = 4096


class DreamConsolidator(EvecorObserverAdapter):
    """Feed conversation turns to the Dreaming service without ever blocking."""

    SERVICE = "dreaming"

    def __init__(self, config: PluginConfig):
        super().__init__(config)
        cfg = self._config.config or {}
        self._enabled: bool = bool(cfg.get("enabled", True))
        self._max_field: int = int(cfg.get("max_field_chars", _MAX_FIELD_CHARS))
        self._dropped: int = 0
        # Strong refs: cpex only gathers background_tasks on response flush,
        # so we also keep our own set and drain it in shutdown().
        self._tasks: set[asyncio.Task] = set()

    # ---- hooks -----------------------------------------------------------

    async def prompt_post_fetch(self, payload: PromptPosthookPayload, context: PluginContext) -> PromptPosthookResult:
        result = PromptPosthookResult(continue_processing=True)
        if self._enabled:
            content = {
                "prompt_id": _clip(payload.prompt_id, self._max_field),
                "messages": _messages_of(getattr(payload, "result", None), self._max_field),
            }
            self._attach(result, self._emit("prompt", payload.prompt_id, content, context))
        return result

    async def tool_post_invoke(self, payload: ToolPostInvokePayload, context: PluginContext) -> ToolPostInvokeResult:
        result = ToolPostInvokeResult(continue_processing=True)
        if self._enabled:
            content = {
                "tool": _clip(payload.name, self._max_field),
                "result": _jsonish(payload.result, self._max_field),
            }
            self._attach(result, self._emit("tool", payload.name, content, context))
        return result

    async def agent_post_invoke(self, payload: AgentPostInvokePayload, context: PluginContext) -> AgentPostInvokeResult:
        result = AgentPostInvokeResult(continue_processing=True)
        if self._enabled:
            content = {
                "agent_id": _clip(payload.agent_id, self._max_field),
                "messages": _messages_of(payload, self._max_field),
                "tool_calls": len(payload.tool_calls or []),
            }
            self._attach(result, self._emit("agent", payload.agent_id, content, context))
        return result

    # ---- emit discipline ---------------------------------------------------

    def _emit(self, kind: str, payload_id: str, content: dict[str, Any], context: PluginContext) -> Optional[asyncio.Task]:
        try:
            identity = _public_context(context)
            if identity.pop("origin", "") == "dreaming":
                return None  # never observe the dream's own traffic
            envelope = {
                "schema_version": SCHEMA_VERSION,
                "kind": kind,
                "payload_id": str(payload_id or ""),
                "content": content,
                **identity,
            }
            return asyncio.create_task(self._guarded_post(envelope, identity.get("request_id") or None))
        except Exception as exc:  # noqa: BLE001 — an observer must never raise
            logger.warning("EVECOR observer 'dreaming' failed to schedule an emit: %r", exc)
            return None

    def _attach(self, result: Any, task: Optional[asyncio.Task]) -> None:
        if task is None:
            return
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        # cpex strong-refs these and gathers them with return_exceptions=True.
        result.background_tasks.append(task)

    async def _guarded_post(self, envelope: dict[str, Any], rid: Optional[str]) -> None:
        try:
            await self._post(envelope)
        except Exception as exc:  # noqa: BLE001 — never propagate to a tool call
            self._dropped += 1
            logger.warning(
                "EVECOR observer 'dreaming' dropped a turn (request_id=%s, drop #%d): %r",
                rid, self._dropped, exc,
            )

    async def shutdown(self) -> None:
        """Drain in-flight emits (bounded), then close the pooled client."""
        pending = [t for t in self._tasks if not t.done()]
        if pending:
            with_timeout = asyncio.wait(pending, timeout=5)
            try:
                await with_timeout
            except Exception:  # noqa: BLE001
                pass
        await super().shutdown()


# ---- serialization helpers --------------------------------------------------

def _clip(value: Any, limit: int) -> str:
    s = value if isinstance(value, str) else ("" if value is None else str(value))
    if len(s) > limit:
        return s[:limit] + f"... [+{len(s) - limit} chars]"
    return s


def _jsonish(value: Any, limit: int) -> Any:
    """JSON-safe, clipped rendering of an arbitrary tool result."""
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return _clip(value, limit)
    if isinstance(value, dict):
        return {str(k)[:128]: _jsonish(v, limit) for k, v in list(value.items())[:64]}
    if isinstance(value, (list, tuple)):
        return [_jsonish(v, limit) for v in list(value)[:64]]
    try:
        return _clip(repr(value), limit)
    except Exception:  # noqa: BLE001
        return "[unserializable]"


def _messages_of(obj: Any, limit: int) -> list[dict[str, str]]:
    """Tolerant extraction of MessageLike/PromptResultLike conversation text.

    Accepts an object with ``.messages`` (PromptResultLike) or a payload whose
    ``.messages`` is a list of MessageLike (role, content). Content may be a
    string, an object with ``.text``, or a list of such parts.
    """
    messages = getattr(obj, "messages", None)
    if messages is None:
        return []
    out: list[dict[str, str]] = []
    try:
        for m in list(messages)[:64]:
            role = str(getattr(m, "role", "") or "")
            content = getattr(m, "content", None)
            text = _text_of(content)
            out.append({"role": _clip(role, 64), "text": _clip(text, limit)})
    except Exception:  # noqa: BLE001 — serialization must never break a hook
        return out
    return out


def _text_of(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    text = getattr(content, "text", None)
    if isinstance(text, str):
        return text
    if isinstance(content, (list, tuple)):
        parts = []
        for part in content:
            if isinstance(part, str):
                parts.append(part)
            else:
                t = getattr(part, "text", None)
                if isinstance(t, str):
                    parts.append(t)
        return "\n".join(parts)
    return str(content)


def _public_context(context: PluginContext) -> dict[str, str]:
    """Identity attribution for the envelope (parity with evecor_common's
    ``_public_context``, which is module-private there), plus the origin
    marker used to filter the dream's own traffic."""
    gc = getattr(context, "global_context", None)
    if gc is None:
        return {
            "tenant_id": "", "user_identity": "", "agent_identity": "",
            "server_id": "", "session_id": "", "request_id": "", "correlation_id": "",
            "origin": "",
        }
    metadata = getattr(gc, "metadata", None) or {}
    gstate = getattr(gc, "state", None) or {}
    request_id = str(getattr(gc, "request_id", None) or "")
    session_id = _s(metadata.get("session_id") or gstate.get("session_id"))
    return {
        "tenant_id": _s(getattr(gc, "tenant_id", None)),
        "user_identity": _s(getattr(gc, "user", None)),
        "agent_identity": _s(metadata.get("agent") or metadata.get("agent_identity") or gstate.get("agent")),
        "server_id": _s(getattr(gc, "server_id", None)),
        "session_id": session_id,
        "request_id": request_id,
        "correlation_id": _s(metadata.get("correlation_id") or gstate.get("correlation_id")) or request_id or session_id,
        "origin": _s(metadata.get("origin") or gstate.get("origin")),
    }


def _s(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    # Structured identities (e.g. user dicts) are hashed upstream by the
    # gateway's auth layer; here a compact repr suffices and is never logged.
    try:
        return str(value)[:256]
    except Exception:  # noqa: BLE001
        return ""
