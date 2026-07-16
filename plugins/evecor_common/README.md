# EVECOR control-surface plugins

Four thin native cpex plugins that put EVECOR's control surfaces on the ContextForge
tool-invocation path. They run **in-process** in the gateway (Python 3.14) and call the
EVECOR services **out-of-process** (the services pin Python ≥3.14 / ≥3.12 and live in a
separate project, so they cannot be imported in-process — the hop is mandatory).

| Plugin | Source service | Hook | Role | Fails how |
|---|---|---|---|---|
| `TruthGuardGate` | `agentsync/src/truthguard` | `tool_pre_invoke` | **gate** (may block) | explicit `fail_mode` + ERROR alert |
| `AgentSyncEnforcer` | `agentsync/src/agentsync` (enforcer) | `tool_pre_invoke` | **gate** (may block) | explicit `fail_mode` + ERROR alert |
| `ReconRecorder` | `agentsync/src/recon` | `tool_post_invoke` | **observer** (never blocks) | swallow + WARNING |
| `LedgerWriter` | `agentsync/src/ledger` | `tool_post_invoke` | **observer** (never blocks) | swallow + WARNING |

Shared transport and both fail-mode disciplines live in `plugins/evecor_common/__init__.py`
(`EvecorGateAdapter`, `EvecorObserverAdapter`).

## Design invariants

- **Gates may block; their fail-mode is operator-chosen.** `fail_mode` is **required** (no
  default). When the gate service is unreachable: `closed` → block (503 `GATE_UNREACHABLE`),
  `open` → allow. Either way the event is logged at **ERROR** so a degraded gate is never
  silent. Wire that ERROR line to your alerting.
- **Observers never block.** The service call is scheduled as a guarded background task
  (returned via cpex `background_tasks`, which the manager gathers with
  `return_exceptions=True`). Any failure drops the record with a WARNING; the tool result is
  returned untouched. "Never blocks" is enforced in the adapter, not merely intended.
- **Use loopback TCP for the current deployment.** The active EVECOR connector ports are
  `8771` TruthGuard, `8772` AgentSync, `8773` Recon, and `8774` Ledger. `socket_path`
  remains supported by the adapter, but the checked-in EVECOR config uses `base_url`.

## Service-side contract

Each service must expose an HTTP listener (on the UDS or loopback) honoring:

**Gate** — `POST <endpoint.path>` (default `/v1/gate`):
```json
// request
{"surface": "truthguard", "request_id": "abc", "tool": "fs.write", "args": {"path": "/etc/x"}}
// 2xx response
{"decision": "allow" | "deny", "reason": "...", "code": "TRUTHGUARD_DANGEROUS", "details": {}}
```
`deny` → the tool call is blocked with a 403 `PluginViolation`.

**Observer** — `POST <endpoint.path>` (default `/v1/record`):
```json
// request (fire-and-forget; response body ignored, just needs 2xx)
{"surface": "recon", "request_id": "abc", "tool": "fs.write", "result": <tool result>}
```

Ledger persists only enriched receipt metadata from this envelope. It does not persist
prompts, payload bodies, result bodies, bearer tokens, environment dumps, or sensitive tool
arguments. Canonical Ledger claims are written through explicit ClaimRecord operations, not
through the passive `claims.jsonl` receipt stream.

`stele` (the 3.12 attestation/parse store) is **not** a plugin here — RECON and Ledger write
to it on their own side, out-of-process. Build it last as their backing store.

## Enabling

1. Stand up the service listener (loopback TCP in the current deployment).
2. Copy the matching entry from `plugins/evecor.config.yaml` into the active plugins config.
3. Set `endpoint.socket_path` (or `base_url`); for gates choose `fail_mode`.
4. Flip `mode`: gates → `sequential`, observers → `fire_and_forget`. Set `PLUGINS_ENABLED=true`.

## Tests

```bash
cd RouterCore && .venv/bin/python -m pytest tests/unit/mcpgateway/plugins/test_evecor_adapters.py -q
```
