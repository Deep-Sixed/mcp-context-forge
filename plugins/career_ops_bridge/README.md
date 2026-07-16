# Career-ops bridge (CPEX)

Python hook plugin for ContextForge that connects **career-ops** workflows to the
**full federated MCP tool catalog** on the gateway.

## What it does

| Hook | Behavior |
|------|----------|
| `agent_pre_invoke` | Appends bundled `skill.md` + gateway-tools note to `system_prompt` when the session is tagged `career-ops` (or `activation.always_on`). |
| `tool_pre_invoke` | Injects `Authorization: Bearer …` for `career_ops_*` REST tools; attaches `_career_ops_context` args blob on career-ops sessions. |

## What it does *not* do

CPEX plugins **do not register tools**. Register the native feeds as REST tools using
`gateway_tools.yaml`, then agents discover them through normal MCP `tools/list` along with
every other server on ContextForge.

## Enable

1. Set gateway env: `CAREER_OPS_FEED_ENABLED=true`, mount career-ops `data/` (see `compose.yml`).
2. Store bearer token in ContextForge Secrets (same token as `ROUTERCORE_MCP_BEARER_TOKEN`).
3. Register REST tools from `gateway_tools.yaml`.
4. Enable plugin in `plugins/config.yaml` (`mode: transform`) and set `bearer_secret`.
5. Tag gateway sessions or agents with `career-ops`, or set `activation.always_on: true`.

Reference config: `plugins/career_ops.config.yaml`.

## career-ops Node plugin

The Node `plugins.local/evecor` plugin remains the CLI ingest path for `node plugins.mjs run evecor`.
This CPEX bridge is the **agent/MCP path** through ContextForge.
