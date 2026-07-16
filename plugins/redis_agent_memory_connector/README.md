# Redis Agent Memory Connector (CPEX)

Thin ContextForge connector for Redis Agent Memory.

## What It Does

| Surface | Behavior |
|---|---|
| Redis Agent Memory MCP gateway | Register the upstream `agent-memory mcp --mode streamable-http` endpoint with ContextForge so agents discover native Redis Agent Memory tools through normal MCP `tools/list`. |
| `agent_pre_invoke` | Optionally adds a short route note for sessions tagged `redis-memory` or `agent-memory`. |
| `tool_pre_invoke` | Adds CPEX metadata for Redis Agent Memory tool traffic. It does not rewrite arguments or decide memory policy. |

## What It Does Not Do

- It does not fork or patch ContextForge.
- It does not fork or patch Redis Agent Memory.
- It does not auto-write memories.
- It does not filter what Redis Agent Memory stores or recalls.
- It does not register tools by itself; CPEX hooks do not create gateway tool rows.

## Register Redis Agent Memory

Preferred path: register Redis Agent Memory as an MCP gateway/server using:

```text
Name: redis-agent-memory
URL:  http://host.docker.internal:8101/mcp
Transport: Streamable HTTP
```

The active local Redis Agent Memory services are available from the host at:

```text
REST API: http://127.0.0.1:8100
MCP:      http://127.0.0.1:8101/mcp
Redis:    127.0.0.1:6390
Namespace default: JARVIS
```

## Enable Plugin

1. Start the Redis Agent Memory MCP service.
2. Register the MCP endpoint in ContextForge.
3. Confirm API health: `GET http://127.0.0.1:8100/v1/health`.
4. Flip `RedisAgentMemoryConnector` in `plugins/config.yaml` to `transform`.
5. Restart ContextForge.
