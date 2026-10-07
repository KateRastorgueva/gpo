"""Merge FAQ entries into the knowledge base

Revision ID: e6b2f8a41c73
Revises: a7c4e1b93d52
Create Date: 2026-04-02

Часть плана docs/db-schema-implementation-plan.md (M9; решение V1 «FAQ — это и есть база знаний»).

Что делает:
- переносит строки `faqentry` в `knowledge_source` с `source_type='faq'`
  (`question -> title`, `answer -> content`);
- удаляет таблицу `faqentry`.

UUID переносятся как есть: исторические `sources_json` в `answer_journal` ссылаются на эти id
и продолжают резолвиться в записи базы знаний.

Публичный API не меняется: `/admin/faq*` остаётся фасадом над базой знаний (см. §D8 плана),
меняется только хранилище, поэтому фронтенд и тесты правок не требуют.

Колонка `normalized_title` из плана сознательно НЕ добавлена: `faq_similarity` нормализует
обе строки сама, а хранимая копия только рисковала бы разойтись с заголовком.

Перенесённые записи получают `status='pending'`: автоматически они не индексируются,
но при следующем reindex попадут в векторный индекс на общих основаниях.

ВНИМАНИЕ: `knowledge_source.title` короче `faqentry.question` (255 против 500), а
`faqentry.answer` короче `knowledge_source.content` (4000 против TEXT). Если данные
не влезают, миграция пишет WARNING в лог и обрезает значение — проверьте вывод `alembic`.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "e6b2f8a41c73"
down_revision = "a7c4e1b93d52"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        DECLARE long_questions int;
        BEGIN
            SELECT count(*) INTO long_questions
            FROM faqentry
            WHERE char_length(question) > 255;

            IF long_questions > 0 THEN
                RAISE WARNING 'faqentry: % question(s) longer than 255 chars; '
                              'title will be truncated in knowledge_source', long_questions;
            END IF;
        END $$;
        """
    )

    op.execute(
        """
        INSERT INTO knowledge_source (
            id, title, source_type, source_ref, is_active, content, status,
            last_indexed_at, created_at, updated_at
        )
        SELECT id, LEFT(question, 255), 'faq', NULL, is_active, answer, 'pending',
               NULL, created_at, updated_at
        FROM faqentry
        """
    )

    op.drop_index(op.f("ix_faqentry_normalized_question"), table_name="faqentry")
    op.drop_table("faqentry")


def downgrade() -> None:
    op.create_table(
        "faqentry",
        sa.Column("question", sa.String(length=500), nullable=False),
        sa.Column("answer", sa.String(length=4000), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("normalized_question", sa.String(length=500), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_faqentry_normalized_question"),
        "faqentry",
        ["normalized_question"],
        unique=False,
    )

    # normalized_question восстанавливается приблизительно (lower+trim): точное значение
    # считалось кодом приложения. Векторы Qdrant для перенесённых записей не удаляются —
    # после downgrade нужен reindex.
    op.execute(
        """
        INSERT INTO faqentry (
            id, question, answer, is_active, normalized_question, created_at, updated_at
        )
        SELECT id, LEFT(title, 500), LEFT(content, 4000), is_active,
               lower(btrim(LEFT(title, 500))), created_at, updated_at
        FROM knowledge_source
        WHERE source_type = 'faq'
        """
    )
    op.execute("DELETE FROM knowledge_source WHERE source_type = 'faq'")
