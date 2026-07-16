# -*- coding: utf-8 -*-
"""Server-side bearer injection for Codex Desktop -> ContextForge MCP.

This CPEX HTTP pre-request hook lets Codex Desktop connect directly to
ContextForge without storing a bearer token in ``~/.codex/config.toml``.
It only creates an Authorization header for loopback MCP requests that do not
already provide one.
"""

from __future__ import annotations

import os
from typing import Any

from cpex.framework import (
    HttpHeaderPayload,
    HttpPreRequestPayload,
    Plugin,
    PluginConfig,
    PluginContext,
    PluginResult,
)
from mcpgateway.config import settings
from mcpgateway.services.logging_service import LoggingService
from mcpgateway.utils.create_jwt_token import _create_jwt_token

_logging_service = LoggingService()
logger = _logging_service.get_logger(__name__)

_PLUGIN = "codex_desktop_contextforge_auth"
_LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost"}


def _as_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


class CodexDesktopContextForgeAuthPlugin(Plugin):
    """Inject ContextForge bearer credentials for local Codex Desktop MCP."""

    def __init__(self, config: PluginConfig) -> None:
        super().__init__(config)
        cfg = config.config or {}
        self._enabled = _as_bool(cfg.get("enabled"), True)
        self._paths = tuple(str(p).rstrip("/") or "/" for p in cfg.get("paths", ["/mcp"]))
        self._allowed_hosts = set(cfg.get("allowed_client_hosts") or _LOOPBACK_HOSTS)
        self._token_env_var = str(cfg.get("bearer_token_env_var", "ROUTERCORE_MCP_BEARER_TOKEN"))
        self._mint_if_missing = _as_bool(cfg.get("mint_if_missing"), True)
        self._mint_expires_minutes = int(cfg.get("mint_expires_minutes", 60))
        self._subject = str(cfg.get("subject") or settings.platform_admin_email)
        self._require_no_authorization = _as_bool(cfg.get("require_no_authorization"), True)

        logger.info(
            "plugin=%s enabled=%s paths=%s allowed_hosts=%s token_env_var=%s mint_if_missing=%s",
            _PLUGIN,
            self._enabled,
            list(self._paths),
            sorted(self._allowed_hosts),
            self._token_env_var,
            self._mint_if_missing,
        )

    async def http_pre_request(
        self,
        payload: HttpPreRequestPayload,
        context: PluginContext,
    ) -> PluginResult[HttpHeaderPayload]:
        """Create an Authorization header for trusted local Codex MCP calls."""
        if not self._enabled or not self._is_allowed_request(payload):
            return PluginResult(continue_processing=True)

        headers = {str(k).lower(): str(v) for k, v in (payload.headers.root if payload.headers else {}).items()}
        if self._require_no_authorization and headers.get("authorization"):
            return PluginResult(continue_processing=True)

        token = self._server_side_token()
        if not token:
            logger.warning("plugin=%s result=no_token source=server_side", _PLUGIN)
            return PluginResult(continue_processing=True)

        headers["authorization"] = f"Bearer {token}"
        logger.debug("plugin=%s result=bearer_injected path=%s client_host=%s", _PLUGIN, payload.path, payload.client_host)
        return PluginResult(
            modified_payload=HttpHeaderPayload(root=headers),
            metadata={"auth_source": _PLUGIN, "token_injected": True},
            continue_processing=True,
        )

    def _is_allowed_request(self, payload: HttpPreRequestPayload) -> bool:
        method = (payload.method or "").upper()
        if method not in {"POST", "GET"}:
            return False

        client_host = payload.client_host or ""
        if client_host not in self._allowed_hosts:
            return False

        path = (payload.path or "").rstrip("/") or "/"
        return any(path == allowed or path.startswith(allowed + "/") for allowed in self._paths)

    def _server_side_token(self) -> str | None:
        env_token = os.environ.get(self._token_env_var, "").strip()
        if env_token:
            return env_token

        if not self._mint_if_missing:
            return None

        return _create_jwt_token(
            {
                "sub": self._subject,
                "email": self._subject,
                "is_admin": True,
                "source": _PLUGIN,
                "token_use": "session",
            },
            expires_in_minutes=self._mint_expires_minutes,
            user_data={
                "email": self._subject,
                "full_name": "Codex Desktop ContextForge",
                "is_admin": True,
                "auth_provider": _PLUGIN,
            },
            teams=None,
        )
