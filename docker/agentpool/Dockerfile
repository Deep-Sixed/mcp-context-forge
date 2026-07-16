# syntax=docker/dockerfile:1
# Build the ContextForge AgentPool runtime entirely from pinned upstream sources.
# No host source tree, credentials, or operational config is bind-mounted.

FROM node:26.3.1-bookworm-slim AS adapter-builder
ARG CODEX_ACP_COMMIT=75893cd87741b2fe127f6698a8741a2e625c3787
ARG CLAUDE_AGENT_ACP_COMMIT=9cd48c597af68f630774ec00bc3adc85f6b0fd4b

RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/agentclientprotocol/codex-acp.git /src/codex-acp \
    && git -C /src/codex-acp checkout --detach "$CODEX_ACP_COMMIT" \
    && cd /src/codex-acp && npm ci && npm run build && npm prune --omit=dev \
    && git clone https://github.com/agentclientprotocol/claude-agent-acp.git /src/claude-agent-acp \
    && git -C /src/claude-agent-acp checkout --detach "$CLAUDE_AGENT_ACP_COMMIT" \
    && cd /src/claude-agent-acp && npm ci && npm run build && npm prune --omit=dev

FROM node:26.3.1-bookworm-slim AS mcacp-builder
ARG MCACP_COMMIT=cf3f452470cf5144f1baf216f6f9aed39bc6eb92

RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && git clone https://github.com/Oortonaut/mcacp.git /src/mcacp \
    && git -C /src/mcacp checkout --detach "$MCACP_COMMIT" \
    && cd /src/mcacp && npm ci && npm run build && npm prune --omit=dev

FROM python:3.14.5-slim-trixie
ARG AGENTPOOL_COMMIT=b6ddbea9cb66173c096942ac57397b636e0a2248
ARG ACP_SCHEMA_COMMIT=12bb33a4bd1c0636bf34a68791b30f34e33ad420

LABEL org.opencontainers.image.title="ContextForge AgentPool ACP runtime" \
      org.opencontainers.image.source="https://github.com/phil65/agentpool" \
      contextforge.group="contextforge" \
      contextforge.kind="mcp-and-acp" \
      contextforge.agentpool.patch="acp-empty-mcpservers" \
      contextforge.agentpool.commit="b6ddbea9cb66173c096942ac57397b636e0a2248" \
      contextforge.acp-schema.commit="12bb33a4bd1c0636bf34a68791b30f34e33ad420" \
      contextforge.codex-acp.commit="75893cd87741b2fe127f6698a8741a2e625c3787" \
      contextforge.claude-agent-acp.commit="9cd48c597af68f630774ec00bc3adc85f6b0fd4b" \
      contextforge.mcacp.commit="cf3f452470cf5144f1baf216f6f9aed39bc6eb92"

# The official Node 26 binary is copied from a Debian bookworm image. It runs
# against trixie's newer glibc and keeps the required Node version exact.
COPY --from=adapter-builder /usr/local /usr/local
# Install AgentPool from its lockfile rather than directly resolving its
# pyproject: direct installation can select an incompatible future Pydantic AI.
COPY --from=adapter-builder /src/codex-acp /opt/acp-adapters/codex-acp
COPY --from=adapter-builder /src/claude-agent-acp /opt/acp-adapters/claude-agent-acp
COPY --from=mcacp-builder /src/mcacp /opt/mcacp
# ACP schema v1 requires mcpServers even when empty. AgentPool 2.9.18 omits
# the field, which current official adapters reject.
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates build-essential g++ \
    && rm -rf /var/lib/apt/lists/* \
    && git clone https://github.com/phil65/agentpool.git /opt/agentpool \
    && git -C /opt/agentpool checkout --detach "$AGENTPOOL_COMMIT" \
    && sed -i 's/Sequence\[McpServer\] | None = None/Sequence[McpServer] = Field(default_factory=list)/g' /opt/agentpool/src/acp/schema/client_requests.py \
    && sed -i 's/list(mcp_servers) if mcp_servers else None/list(mcp_servers or [])/g' /opt/agentpool/src/acp/agent/acp_agent_api.py \
    && python -m pip install --no-cache-dir --upgrade pip uv \
    && cd /opt/agentpool \
    && uv export --frozen --no-dev --no-emit-project --format requirements-txt --output-file /tmp/agentpool-requirements.txt \
    && uv pip install --system --requirement /tmp/agentpool-requirements.txt \
    && uv pip install --system --no-deps /opt/agentpool \
    && npm install --global supergateway@3.4.3 \
    && git clone https://github.com/agentclientprotocol/agent-client-protocol.git /opt/agent-client-protocol \
    && git -C /opt/agent-client-protocol checkout --detach "$ACP_SCHEMA_COMMIT" \
    && rm -rf /opt/agentpool/.git /opt/agent-client-protocol/.git \
    && ln -s /opt/acp-adapters/codex-acp/dist/index.js /usr/local/bin/codex-acp \
    && ln -s /opt/acp-adapters/claude-agent-acp/dist/index.js /usr/local/bin/claude-agent-acp \
    && node --version | grep -Fx 'v26.3.1' \
    && python --version | grep -Fx 'Python 3.14.5'

COPY docker/agentpool/agents.yml /etc/agentpool/agents.yml
COPY docker/agentpool/mcacp-config.json /etc/mcacp/config.json

RUN useradd --create-home --uid 10001 --shell /usr/sbin/nologin agentpool \
    && mkdir -p /workspace /tmp/codex /tmp/claude \
    && chown -R agentpool:agentpool /workspace /tmp/codex /tmp/claude

USER agentpool
WORKDIR /workspace
ENV HOME=/tmp/agentpool \
    XDG_CACHE_HOME=/tmp/agentpool-cache \
    XDG_CONFIG_HOME=/tmp/agentpool-config \
    XDG_DATA_HOME=/tmp/agentpool-data \
    CODEX_HOME=/tmp/codex \
    APP_SERVER_LOGS=/tmp/codex/logs \
    NO_BROWSER=1 \
    PYTHONUNBUFFERED=1
EXPOSE 8000
CMD ["agentpool", "serve-mcp", "/etc/agentpool/agents.yml", "--transport", "streamable-http", "--host", "0.0.0.0", "--port", "8000"]
