"""Per-user prompt template overrides.

Revision ID: 0017_prompt_templates
Revises: 0016_artifacts
"""

import sqlalchemy as sa
from alembic import op

revision = "0017_prompt_templates"
down_revision = "0016_artifacts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "prompt_templates",
        sa.Column("tenant_id", sa.String(length=64), primary_key=True),
        sa.Column("user_id", sa.String(length=128), primary_key=True),
        sa.Column("key", sa.String(length=64), primary_key=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("prompt_templates")
