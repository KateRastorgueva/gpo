"""Add intent (topic) columns to the request journal

Revision ID: 4b8e2c6f0a13
Revises: 7d3b9e5f1a26
Create Date: 2026-11-04

Тема вопроса от классификатора Кати (intent_service) и его уверенность.
Аддитивная миграция: старые запросы остаются без темы (NULL).
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "4b8e2c6f0a13"
down_revision = "7d3b9e5f1a26"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "request_journal",
        sa.Column("intent", sa.String(length=50), nullable=True),
    )
    op.add_column(
        "request_journal",
        sa.Column("intent_confidence", sa.Float(), nullable=True),
    )
    op.create_index(
        op.f("ix_request_journal_intent"), "request_journal", ["intent"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_request_journal_intent"), table_name="request_journal")
    op.drop_column("request_journal", "intent_confidence")
    op.drop_column("request_journal", "intent")
