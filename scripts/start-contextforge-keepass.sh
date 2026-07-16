#!/usr/bin/env bash
# Resolves ContextForge's secrets from KeePassXC via jarvis-secret and starts
# the stack. Docker's own POSTGRES_PASSWORD_FILE handles the DB container
# (written to ~/.docker-secrets/contextforge/); the app container itself has
# no secrets_dir wired in, so its secrets go through a generated .env file
# instead (env_file:, not Docker secrets).
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SECRET_DIR="${HOME}/.docker-secrets/contextforge"

mkdir -p "$SECRET_DIR"
chmod 700 "$SECRET_DIR"
umask 077

printf '%s' "$(jarvis-secret get CONTEXTFORGE_DB_PASSWORD)" > "$SECRET_DIR/db_password"

DB_PW="$(jarvis-secret get CONTEXTFORGE_DB_PASSWORD)"
{
  echo "DATABASE_URL=postgresql+psycopg://contextforge:${DB_PW}@contextforge-core-db:5432/contextforge"
  echo "JWT_SECRET_KEY=$(jarvis-secret get CONTEXTFORGE_JWT_SECRET)"
  echo "AUTH_ENCRYPTION_SECRET=$(jarvis-secret get CONTEXTFORGE_AUTH_ENCRYPTION_SECRET)"
  echo "PLATFORM_ADMIN_PASSWORD=$(jarvis-secret get CONTEXTFORGE_ADMIN_PASSWORD)"
  echo "SSO_GENERIC_CLIENT_ID=$(jarvis-secret get CONTEXTFORGE_SSO_CLIENT_ID)"
  echo "SSO_GENERIC_CLIENT_SECRET=$(jarvis-secret get CONTEXTFORGE_SSO_CLIENT_SECRET)"
  echo "SSO_API_TOKEN_AUTH_ENABLED=true"
  echo "CONTEXTFORGE_PORT=4444"
  # azmcp (the azure-mcp container's .NET AOT binary) cold-starts its
  # runtime/DI/OpenTelemetry stack in ~4s on every new MCP session, leaving
  # no margin under the 5s default for check_health_of_gateways()'s
  # reactivation round-trip. No per-gateway override exists in this
  # ContextForge version — see gateway/mcp-servers/azure-mcp-servers/README.md.
  echo "GATEWAY_HEALTH_CHECK_TIMEOUT=15"
} > "$PROJECT_DIR/.env"
chmod 600 "$PROJECT_DIR/.env"

export CONTEXTFORGE_SECRET_DIR="$SECRET_DIR"
cd "$PROJECT_DIR"
docker compose up -d "$@"
