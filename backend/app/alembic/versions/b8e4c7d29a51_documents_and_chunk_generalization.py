"""Add independent document corpus and generalize chunks

Revision ID: b8e4c7d29a51
Revises: f2d5a8c14b60
Create Date: 2026-04-02

Часть плана docs/db-schema-implementation-plan.md (M4; решения V4 и D9).

Что делает:
- создаёт `knowledge_doc` — независимый корпус документов (ссылка + название, БЕЗ FK на
  источник базы знаний) и связь `doc_tag`;
- обобщает `knowledge_chunk`: `source_id` становится nullable, добавляется `doc_id`,
  CHECK `num_nonnulls(source_id, doc_id) = 1` — чанк принадлежит ровно одному корпусу.

Документы индексируются отдельным путём (`index_doc`), но чанки живут в одной таблице:
так сохраняется единая логика чанкинга, очистки сирот и гибридного объединения результатов
(ключ `chunk_id` уникален глобально).

ВНИМАНИЕ по downgrade: чанки документов в старой схеме существовать не могут, поэтому они
удаляются (вместе со строками таблицы). Векторы этих чанков в Qdrant остаются сиротами —
после отката нужен `POST /admin/sources/reindex` с очисткой сирот.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "b8e4c7d29a51"
down_revision = "f2d5a8c14b60"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "knowledge_doc",
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("url", sa.String(length=1024), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("last_indexed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "doc_tag",
        sa.Column("doc_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tag_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(["doc_id"], ["knowledge_doc.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tag_id"], ["tag.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("doc_id", "tag_id"),
    )

    op.alter_column("knowledge_chunk", "source_id", nullable=True)
    op.add_column(
        "knowledge_chunk",
        sa.Column("doc_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_index(
        op.f("ix_knowledge_chunk_doc_id"),
        "knowledge_chunk",
        ["doc_id"],
        unique=False,
    )
    op.create_foreign_key(
        None,
        "knowledge_chunk",
        "knowledge_doc",
        ["doc_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_check_constraint(
        "ck_knowledge_chunk_owner",
        "knowledge_chunk",
        "num_nonnulls(source_id, doc_id) = 1",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_knowledge_chunk_owner", "knowledge_chunk", type_="check"
    )
    op.drop_constraint(
        "knowledge_chunk_doc_id_fkey", "knowledge_chunk", type_="foreignkey"
    )
    op.drop_index(op.f("ix_knowledge_chunk_doc_id"), table_name="knowledge_chunk")
    # Чанки документов несовместимы со старой схемой (source_id NOT NULL)
    op.execute("DELETE FROM knowledge_chunk WHERE doc_id IS NOT NULL")
    op.drop_column("knowledge_chunk", "doc_id")
    op.alter_column("knowledge_chunk", "source_id", nullable=False)

    op.drop_table("doc_tag")
    op.drop_table("knowledge_doc")
