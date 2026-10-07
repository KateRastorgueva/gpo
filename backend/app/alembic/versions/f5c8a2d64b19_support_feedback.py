"""Add support feedback (one review per request)

Revision ID: f5c8a2d64b19
Revises: e2b7d5a91f38
Create Date: 2026-04-02

Часть плана docs/db-schema-implementation-plan.md (M8; решение V7).

Что делает:
- создаёт `support_feedback`: оценка 1..5, комментарий, время отправки;
- `request_id` уникален (один отзыв на запрос) и удаляется вместе с запросом (CASCADE);
- CHECK `rating BETWEEN 1 AND 5` дублирует проверку схемы на уровне БД.

Аддитивная миграция: существующие данные не затрагиваются.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "f5c8a2d64b19"
down_revision = "e2b7d5a91f38"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "support_feedback",
        sa.Column("request_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("rating", sa.Integer(), nullable=False),
        sa.Column("comment", sa.String(length=2000), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.CheckConstraint("rating BETWEEN 1 AND 5", name="ck_support_feedback_rating"),
        sa.ForeignKeyConstraint(
            ["request_id"], ["request_journal.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["app_user.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("request_id"),
    )
    op.create_index(
        op.f("ix_support_feedback_request_id"),
        "support_feedback",
        ["request_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_support_feedback_request_id"), table_name="support_feedback"
    )
    op.drop_table("support_feedback")
