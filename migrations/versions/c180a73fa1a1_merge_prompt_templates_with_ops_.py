"""merge prompt templates with ops workspaces

Revision ID: c180a73fa1a1
Revises: 0017_prompt_templates, 0020_inbox_assignment
Create Date: 2026-11-24 16:04:55.775239
"""
import sqlalchemy as sa
from alembic import op


revision = 'c180a73fa1a1'
down_revision = ('0017_prompt_templates', '0020_inbox_assignment')
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
