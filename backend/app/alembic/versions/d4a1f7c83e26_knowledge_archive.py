"""Add knowledge archive (snapshots of previous versions)

Revision ID: d4a1f7c83e26
Revises: b8e4c7d29a51
Create Date: 2026-04-02

Часть плана docs/db-schema-implementation-plan.md (M5; решения V5, V6, D5).

Что делает:
- создаёт `knowledge_archive` — снапшоты предыдущих версий знания (заголовок, содержание,
  категория, тэги, тип источника), уникальные по `(knowledge_id, version)`;
- `knowledge_id` ссылается на источник с `ON DELETE CASCADE`: жёсткое удаление источника
  уничтожает его историю (решение владельца V6), а мягкое удаление — сохраняет.

Снапшоты пишет сервисный слой (`archive_knowledge`) перед изменением метаданных и при мягком
удалении, а не триггеры БД: так логика тестируется и не требует спецправ (D5).
Ретенция по числу версий — настройка `KNOWLEDGE_ARCHIVE_MAX_VERSIONS`.

`category_id` и `tags_json` намеренно без FK: снапшот остаётся читаемым после удаления
категории или тэгов.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "d4a1f7c83e26"
down_revision = "b8e4c7d29a51"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "knowledge_archive",
        sa.Column("knowledge_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("category_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("tags_json", sa.JSON(), nullable=False),
        sa.Column("source_type", sa.String(length=20), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("archived_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["knowledge_id"], ["knowledge_source.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["archived_by"], ["app_user.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "knowledge_id", "version", name="uq_knowledge_archive_version"
        ),
    )
    op.create_index(
        op.f("ix_knowledge_archive_knowledge_id"),
        "knowledge_archive",
        ["knowledge_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_knowledge_archive_knowledge_id"), table_name="knowledge_archive"
    )
    op.drop_table("knowledge_archive")
