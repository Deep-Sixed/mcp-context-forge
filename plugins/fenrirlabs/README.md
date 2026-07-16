# Fenrir Labs skill plugins (ContextForge / cpex)

Thin native cpex adapters that inject Fenrir Labs Claude skill context into
tool and prompt invocations on the ContextForge gateway path.

## Layout

```
fenrirlabs/
├── manifest.yaml           # Skill registry + tool/prompt triggers
├── fenrirlabs.config.yaml  # Reference plugin entries (copied into config.yaml)
├── fenrirlabs_common.py    # FenrirSkillAdapter base
├── skill_hook.py           # FenrirSkillHook (one class, many config entries)
└── skills/                 # SKILL.md assets from fenrirlabsnl/claude-skills
    ├── inbox-triage/
    ├── lead-qualifier/
    └── ...
```

## Architecture

| Layer | Role |
|-------|------|
| `FenrirSkillHook` (in-process cpex) | Calls gateway on `tool_pre_invoke` / `prompt_pre_fetch` |
| `fenrirlabs-gateway` (out-of-process) | Loads SKILL.md, matches tools/prompts, returns context |
| `skills/` | On-disk skill assets |

On match, skill instructions are injected into tool/prompt args under
`_fenrirlabs_skill_context` and echoed in plugin metadata.

## Enabling

1. Start the gateway:
   ```bash
   systemctl --user enable --now evecor-fenrirlabs-gateway.service
   ```
2. Flip desired entries in `plugins/config.yaml` from `mode: disabled` to `mode: transform`.
3. Restart ContextForge with `PLUGINS_ENABLED=true`.

Gateway listens on `http://127.0.0.1:8778` by default.

## Tests

```bash
cd RouterCore && .venv/bin/python -m pytest tests/unit/mcpgateway/plugins/test_fenrirlabs_adapters.py -q
```

## Source

Skills sourced from [fenrirlabsnl/claude-skills](https://github.com/fenrirlabsnl/claude-skills/tree/main/plugins).
