# Hindsight Connector (CPEX)

Thin ContextForge connector for Hindsight Agent Memory.

## What It Does

| Surface | Behavior |
|---|---|
| Hindsight MCP gateway | Register Hindsight's own bank-pinned `/mcp/JARVIS/` endpoint with ContextForge so agents discover native Hindsight tools through normal MCP `tools/list`. |
| `agent_pre_invoke` | Optionally adds a short route note for sessions tagged `hindsight` or `memory`. |
| `tool_pre_invoke` | Adds CPEX metadata for Hindsight tool traffic. It does not rewrite arguments or decide memory policy. |

## What It Does Not Do

- It does not fork or patch ContextForge.
- It does not fork or patch Hindsight.
- It does not auto-retain sessions.
- It does not filter what Hindsight stores or recalls.
- It does not register tools by itself; CPEX hooks do not create gateway tool rows.

## Register Hindsight

Preferred path: register Hindsight as a bank-pinned MCP gateway/server using:

```text
Name: hindsight-agent-memory
URL:  http://host.docker.internal:8888/mcp/JARVIS/
Transport: Streamable HTTP
```

Use the bank-pinned endpoint, not the multi-bank `/mcp/` endpoint. The pinned endpoint
removes the `bank_id` argument from normal memory calls and avoids exposing cross-bank
management tools such as `list_banks` and `create_bank`.

The active local Hindsight service is available from the host at:

```text
API: http://127.0.0.1:8888
UI:  http://127.0.0.1:9999
Bank: JARVIS
```

If you need admin-managed REST tools instead of MCP gateway registration, use
`gateway_tools.yaml` as the registration source.

## Enable Plugin

1. Register the Hindsight bank-pinned MCP endpoint or REST tools in ContextForge.
2. Confirm Hindsight health: `GET http://127.0.0.1:8888/health`.
3. Flip `HindsightConnector` in `plugins/config.yaml` from `disabled` to `transform` or `sequential`.
4. Restart ContextForge.
