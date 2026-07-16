# -*- coding: utf-8 -*-
"""CPEX bridge for the computer-use-linux MCP server.

This plugin does not register MCP tools. ContextForge still needs the
``computer-use-linux`` MCP server registered through the normal gateway/server
path. The bridge governs those tool invocations once they flow through CPEX.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, Field

from cpex.framework import (
    AgentPreInvokePayload,
    AgentPreInvokeResult,
    Plugin,
    PluginConfig,
    PluginContext,
    PluginViolation,
    ToolPreInvokePayload,
    ToolPreInvokeResult,
)

_PLUGIN = "computer_use_linux_bridge"
_DEFAULT_SKILL = Path(__file__).resolve().parent / "skill.md"

_READ_ONLY_TOOLS = {
    "doctor",
    "list_apps",
    "list_windows",
    "focused_window",
    "get_app_state",
}
_SETUP_TOOLS = {
    "setup_accessibility",
    "setup_window_targeting",
}
_FOCUS_TOOLS = {
    "activate_window",
    "scroll",
    "screenshot",
}
_DESTRUCTIVE_TOOLS = {
    "click",
    "drag",
    "press_key",
    "type_text",
    "perform_action",
    "set_value",
}
_ALL_TOOLS = _READ_ONLY_TOOLS | _SETUP_TOOLS | _FOCUS_TOOLS | _DESTRUCTIVE_TOOLS
_SCREENSHOT_TOOLS = {"get_app_state", "screenshot"}


class ActivationConfig(BaseModel):
    """When to inject desktop-control guidance into agent prompts."""

    always_on: bool = False
    session_tags: list[str] = Field(default_factory=lambda: ["computer-use-linux"])
    agent_id_prefixes: list[str] = Field(default_factory=list)


class ScreenshotDefaults(BaseModel):
    """Default/cap screenshot payload options forwarded to computer-use-linux."""

    max_width: int = Field(default=1920, ge=1)
    max_height: int = Field(default=1920, ge=1)
    max_bytes: int = Field(default=2 * 1024 * 1024, ge=1024)
    format: Optional[str] = None
    quality: Optional[int] = Field(default=None, ge=1, le=95)


class ComputerUseLinuxBridgeConfig(BaseModel):
    """Plugin configuration."""

    activation: ActivationConfig = Field(default_factory=ActivationConfig)
    skill_path: Optional[str] = None
    max_skill_chars: int = Field(default=12000, ge=256)

    tool_prefixes: list[str] = Field(
        default_factory=lambda: [
            "computer_use_linux_",
            "computer-use-linux.",
            "computer-use-linux/",
            "computer-use-linux:",
            "computer-use-linux-",
        ]
    )
    server_id_fragments: list[str] = Field(
        default_factory=lambda: ["computer-use-linux", "computer_use_linux"]
    )
    match_unqualified_tools: bool = False

    confirmation_arg: str = "_computer_use_linux_confirmed"
    trusted_session_tags: list[str] = Field(
        default_factory=lambda: ["computer-use-linux-approved", "desktop-control-approved"]
    )
    guarded_tool_classes: list[str] = Field(default_factory=lambda: ["setup", "destructive"])

    enforce_screenshot_defaults: bool = True
    screenshot_defaults: ScreenshotDefaults = Field(default_factory=ScreenshotDefaults)


def _context_tags(context: PluginContext) -> set[str]:
    tags: set[str] = set()
    metadata = context.global_context.metadata or {}
    for raw in metadata.get("tags", []) or []:
        if isinstance(raw, str) and raw.strip():
            tags.add(raw.strip())

    gateway = metadata.get("gateway") or {}
    gateway_tags = gateway.get("tags", []) if isinstance(gateway, dict) else []
    for raw in gateway_tags or []:
        if isinstance(raw, dict):
            value = str(raw.get("label", "")).strip()
        elif hasattr(raw, "label"):
            value = str(getattr(raw, "label")).strip()
        else:
            value = str(raw).strip()
        if value:
            tags.add(value)
    return tags


def _server_strings(context: PluginContext) -> list[str]:
    values: list[str] = []
    server_id = context.global_context.server_id
    if server_id:
        values.append(str(server_id))

    metadata = context.global_context.metadata or {}
    for key in ("server_id", "server_name", "gateway_id", "gateway_name"):
        value = metadata.get(key)
        if value:
            values.append(str(value))
    return values


def _is_confirmed(args: dict[str, Any], key: str) -> bool:
    value = args.get(key)
    if value is True:
        return True
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "confirmed", "approved"}
    return False


class ComputerUseLinuxBridgePlugin(Plugin):
    """Guard and guide computer-use-linux MCP tool calls."""

    def __init__(self, config: PluginConfig) -> None:
        super().__init__(config)
        self._cfg = ComputerUseLinuxBridgeConfig.model_validate(config.config or {})
        self._skill_text: Optional[str] = None

    async def agent_pre_invoke(
        self, payload: AgentPreInvokePayload, context: PluginContext
    ) -> AgentPreInvokeResult:
        if not self._is_active_session(context, payload.agent_id):
            return AgentPreInvokeResult(continue_processing=True)

        block = self._load_skill().strip()
        existing = (payload.system_prompt or "").strip()
        if block in existing:
            return AgentPreInvokeResult(
                continue_processing=True,
                metadata={"computer_use_linux_bridge": "skill_already_present"},
            )

        merged = f"{existing}\n\n{block}".strip() if existing else block
        return AgentPreInvokeResult(
            continue_processing=True,
            modified_payload=payload.model_copy(update={"system_prompt": merged}),
            metadata={"computer_use_linux_bridge": "skill_injected", "skill_chars": len(block)},
        )

    async def tool_pre_invoke(
        self, payload: ToolPreInvokePayload, context: PluginContext
    ) -> ToolPreInvokeResult:
        local_tool = self._matched_tool(payload.name, context)
        if local_tool is None:
            return ToolPreInvokeResult(continue_processing=True)

        tool_class = self._tool_class(local_tool)
        args = dict(payload.args or {})
        confirmed = _is_confirmed(args, self._cfg.confirmation_arg)
        trusted = self._is_trusted_session(context)
        guarded = tool_class in set(self._cfg.guarded_tool_classes)

        if guarded and not confirmed and not trusted:
            return ToolPreInvokeResult(
                continue_processing=False,
                violation=PluginViolation(
                    reason="Computer Use confirmation required",
                    description=(
                        f"{_PLUGIN}: {local_tool} is a {tool_class} desktop-control tool. "
                        f"Set {self._cfg.confirmation_arg}=true or use a trusted session tag."
                    ),
                    code="COMPUTER_USE_LINUX_CONFIRMATION_REQUIRED",
                    details={
                        "plugin": _PLUGIN,
                        "tool": local_tool,
                        "tool_class": tool_class,
                        "confirmation_arg": self._cfg.confirmation_arg,
                    },
                    http_status_code=403,
                ),
            )

        modified = False
        if self._cfg.confirmation_arg in args:
            args.pop(self._cfg.confirmation_arg, None)
            modified = True

        screenshot_defaults_applied = False
        if self._cfg.enforce_screenshot_defaults and local_tool in _SCREENSHOT_TOOLS:
            screenshot_defaults_applied = self._apply_screenshot_defaults(args)
            modified = modified or screenshot_defaults_applied

        return ToolPreInvokeResult(
            continue_processing=True,
            modified_payload=payload.model_copy(update={"args": args}) if modified else None,
            metadata={
                "computer_use_linux_bridge": True,
                "tool": local_tool,
                "tool_class": tool_class,
                "confirmed": confirmed,
                "trusted_session": trusted,
                "screenshot_defaults_applied": screenshot_defaults_applied,
            },
        )

    def _load_skill(self) -> str:
        if self._skill_text is not None:
            return self._skill_text
        path = Path(self._cfg.skill_path) if self._cfg.skill_path else _DEFAULT_SKILL
        if not path.is_file():
            path = _DEFAULT_SKILL
        self._skill_text = path.read_text(encoding="utf-8")[: self._cfg.max_skill_chars]
        return self._skill_text

    def _is_active_session(self, context: PluginContext, agent_id: Optional[str]) -> bool:
        activation = self._cfg.activation
        if activation.always_on:
            return True
        if _context_tags(context).intersection(activation.session_tags):
            return True
        if agent_id:
            return any(str(agent_id).startswith(prefix) for prefix in activation.agent_id_prefixes)
        return False

    def _is_trusted_session(self, context: PluginContext) -> bool:
        return bool(_context_tags(context).intersection(self._cfg.trusted_session_tags))

    def _matched_tool(self, name: str, context: PluginContext) -> Optional[str]:
        by_prefix = self._local_from_prefix(name)
        if by_prefix is not None:
            return by_prefix

        local = self._local_from_separators(name)
        if local not in _ALL_TOOLS:
            return None

        if self._server_matches(context):
            return local
        if self._cfg.match_unqualified_tools and name == local:
            return local
        return None

    def _local_from_prefix(self, name: str) -> Optional[str]:
        for prefix in self._cfg.tool_prefixes:
            if name.startswith(prefix):
                local = name[len(prefix) :].lstrip(".:/_-")
                return local if local in _ALL_TOOLS else None
        return None

    @staticmethod
    def _local_from_separators(name: str) -> str:
        local = name
        for separator in ("/", ".", ":"):
            if separator in local:
                local = local.rsplit(separator, 1)[-1]
        return local

    def _server_matches(self, context: PluginContext) -> bool:
        fragments = [fragment.lower() for fragment in self._cfg.server_id_fragments]
        for value in _server_strings(context):
            lowered = value.lower()
            if any(fragment in lowered for fragment in fragments):
                return True
        return False

    @staticmethod
    def _tool_class(local_tool: str) -> str:
        if local_tool in _READ_ONLY_TOOLS:
            return "read_only"
        if local_tool in _SETUP_TOOLS:
            return "setup"
        if local_tool in _FOCUS_TOOLS:
            return "focus"
        return "destructive"

    def _apply_screenshot_defaults(self, args: dict[str, Any]) -> bool:
        defaults = self._cfg.screenshot_defaults
        changed = False
        for key in ("max_width", "max_height", "max_bytes"):
            default_value = getattr(defaults, key)
            raw_value = args.get(key)
            try:
                current_value = int(raw_value) if raw_value is not None else None
            except (TypeError, ValueError):
                current_value = None
            if current_value is None or current_value > default_value:
                args[key] = default_value
                changed = True

        if defaults.format and not args.get("format"):
            args["format"] = defaults.format
            changed = True
        if defaults.quality is not None:
            raw_quality = args.get("quality")
            try:
                current_quality = int(raw_quality) if raw_quality is not None else None
            except (TypeError, ValueError):
                current_quality = None
            if current_quality is None or current_quality > defaults.quality:
                args["quality"] = defaults.quality
                changed = True

        return changed
