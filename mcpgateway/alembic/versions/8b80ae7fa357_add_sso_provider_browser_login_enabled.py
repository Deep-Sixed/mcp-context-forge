"""add_sso_provider_browser_login_enabled

Adds sso_providers.browser_login_enabled so API-only/M2M provider rows
(trusted_for_api_auth=True, client_credentials-only inbound identities) can
be excluded from the interactive login page's provider-button list, while
remaining trusted for bearer-token validation. Existing rows default to
True (unchanged visible behavior) -- callers must explicitly opt specific
rows out.

Revision ID: 8b80ae7fa357
Revises: a6d4e2f9c8b1
Create Date: 2026-07-15 00:49:22.632298

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8b80ae7fa357'
down_revision: Union[str, Sequence[str], None] = 'a6d4e2f9c8b1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "sso_providers" not in inspector.get_table_names():
        return

    columns = [col["name"] for col in inspector.get_columns("sso_providers")]
    if "browser_login_enabled" in columns:
        return

    op.add_column(
        "sso_providers",
        sa.Column("browser_login_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
    )


def downgrade() -> None:
    """Downgrade schema."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "sso_providers" not in inspector.get_table_names():
        return

    columns = [col["name"] for col in inspector.get_columns("sso_providers")]
    if "browser_login_enabled" not in columns:
        return

    op.drop_column("sso_providers", "browser_login_enabled")
