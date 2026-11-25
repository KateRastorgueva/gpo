"""Drop the template item table

Revision ID: 9e7c2b41d805
Revises: 4b8e2c6f0a13
Create Date: 2026-11-25

Таблица `item` — наследство шаблона fastapi-full-stack-template: CRUD и UI
удалены, в домене техподдержки она не используется. Решение владельца:
удалить.

`downgrade` возвращает таблицу в исходном виде (id/owner_id — UUID,
created_at nullable, FK на app_user с ON DELETE CASCADE), чтобы откат не терял
схему, хотя данные при удалении, разумеется, не восстанавливаются.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "9e7c2b41d805"
down_revision = "4b8e2c6f0a13"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_table("item")


def downgrade() -> None:
    op.create_table(
        "item",
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.String(length=255), nullable=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["app_user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
