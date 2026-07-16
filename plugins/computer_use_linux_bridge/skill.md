# Computer Use Linux

Use `computer-use-linux` only for local desktop observation or user-approved desktop control.

Start with `doctor` when readiness is unknown. Prefer `get_app_state`, `list_windows`,
and `focused_window` before any action that changes focus or input state. Use returned
element indexes or semantic selectors instead of raw coordinates when possible.

Calls that can change local application state require explicit approval. For guarded
tools, include `_computer_use_linux_confirmed=true`; the CPEX bridge strips that flag
before forwarding the call to the MCP server.

Do not use desktop actions to submit, send, purchase, delete, overwrite, or expose
private data unless the operator has explicitly approved that exact action.
