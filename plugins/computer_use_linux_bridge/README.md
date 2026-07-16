# Computer-use-linux bridge (CPEX)

Native CPEX plugin for ContextForge sessions that use the `computer-use-linux`
MCP server.

## What It Does

| Hook | Behavior |
|------|----------|
| `agent_pre_invoke` | Injects the bundled desktop-control guidance when the session is tagged `computer-use-linux` or `activation.always_on` is enabled. |
| `tool_pre_invoke` | Detects `computer-use-linux` tool calls, strips `_computer_use_linux_confirmed`, adds bounded screenshot defaults, and blocks guarded setup/destructive tools without confirmation or a trusted session tag. |

## What It Does Not Do

CPEX plugins do not register MCP tools. Register `computer-use-linux mcp` with
ContextForge through the normal gateway/server path, then enable this plugin to
govern those tool calls.

For process isolation, use the external Python bridge in
`plugins/external/computer_use_linux_bridge/`. It exposes the CPEX-required MCP
plugin tools over STDIO and loads this native hook class behind that boundary.

## Enable

1. Build or install `RouterCore/mcp-servers/external/computer-use-linux`.
2. Register the MCP server in ContextForge as a stdio upstream using the command
   `computer-use-linux mcp` or an absolute path to the built binary.
3. Enable `ComputerUseLinuxBridge` in `plugins/config.yaml` by setting `mode` to
   `sequential`.
4. Tag sessions with `computer-use-linux` for guidance injection. Tag sessions
   with `computer-use-linux-approved` or pass `_computer_use_linux_confirmed=true`
   for guarded desktop mutations.

Reference config: `plugins/computer_use_linux.config.yaml`.
