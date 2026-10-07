"""Add knowledge taxonomy: categories and tags

Revision ID: f2d5a8c14b60
Revises: e6b2f8a41c73
Create Date: 2026-04-02

Часть плана docs/db-schema-implementation-plan.md (M3).

Что делает:
- создаёт `knowledge_category` (категория, 1:N к источникам) и `tag` (уникальные имена);
- добавляет `knowledge_source.category_id` (nullable, `ON DELETE SET NULL`: удаление
  категории не должно удалять источники);
- создаёт связь M:N `knowledge_tag` (составной PK, оба FK с CASCADE).

Миграция аддитивная: существующие данные не трогаются, источники остаются без категории
и тэгов до явного назначения.

Фильтрация поиска по категориям и тэгам (решение D4: payload в Qdrant + payload-индексы)
в этой миграции не делается — она требует изменения индексации и ложится в шаг M4.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "f2d5a8c14b60"
down_revision = "e6b2f8a41c73"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "knowledge_category",
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_knowledge_category_name"),
        "knowledge_category",
        ["name"],
        unique=True,
    )

    op.create_table(
        "tag",
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_tag_name"), "tag", ["name"], unique=True)

    op.add_column(
        "knowledge_source",
        sa.Column("category_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_index(
        op.f("ix_knowledge_source_category_id"),
        "knowledge_source",
        ["category_id"],
        unique=False,
    )
    # Имя FK не задаём: в остальной схеме используется автоименование PostgreSQL
    # (здесь получится knowledge_source_category_id_fkey).
    op.create_foreign_key(
        None,
        "knowledge_source",
        "knowledge_category",
        ["category_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_table(
        "knowledge_tag",
        sa.Column("knowledge_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tag_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["knowledge_id"], ["knowledge_source.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["tag_id"], ["tag.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("knowledge_id", "tag_id"),
    )


def downgrade() -> None:
    op.drop_table("knowledge_tag")

    op.drop_constraint(
        "knowledge_source_category_id_fkey", "knowledge_source", type_="foreignkey"
    )
    op.drop_index(
        op.f("ix_knowledge_source_category_id"), table_name="knowledge_source"
    )
    op.drop_column("knowledge_source", "category_id")

    op.drop_index(op.f("ix_tag_name"), table_name="tag")
    op.drop_table("tag")

    op.drop_index(op.f("ix_knowledge_category_name"), table_name="knowledge_category")
    op.drop_table("knowledge_category")
