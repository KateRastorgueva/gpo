"""Turn answer journal into per-step entries (1:N per request)

Revision ID: c9f3b1e64d07
Revises: d4a1f7c83e26
Create Date: 2026-04-02

Часть плана docs/db-schema-implementation-plan.md (M6; решения D1 и D8).

Что делает:
- снимает UNIQUE с `answer_journal.request_id` — на запрос теперь приходится несколько
  записей (шагов обработки), вместо одной;
- добавляет поля шага: `step`, `step_index`, `performed_by`, `knowledge_id`,
  `knowledge_chunk_id`, `is_final`, `response_time_ms`;
- вводит уникальность `(request_id, step_index)`.

Бэкфилл: у существующих записей `step = mode` соответствующего запроса, `step_index = 0`,
`is_final = true` (старая модель считала запись финальным ответом).

Имя UNIQUE-констрейнта снимается динамически: M0 переименовала таблицу
`supportanswer` -> `answer_journal`, но имя констрейнта PostgreSQL сохранил прежним
(`supportanswer_request_id_key`), поэтому искать его по литералу нельзя.

Обратимость: после появления у запроса больше одной записи `downgrade` невозможен без потери
данных (UNIQUE не восстановить) — в этом случае миграция падает с явной ошибкой, и это
ожидаемое поведение, а не сюрприз.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "c9f3b1e64d07"
down_revision = "d4a1f7c83e26"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Снять UNIQUE с request_id (имя констрейнта могло остаться от прежней таблицы)
    op.execute(
        """
        DO $$
        DECLARE cname text;
        BEGIN
            SELECT conname INTO cname
            FROM pg_constraint
            WHERE conrelid = 'answer_journal'::regclass AND contype = 'u';

            IF cname IS NOT NULL THEN
                EXECUTE format('ALTER TABLE answer_journal DROP CONSTRAINT %I', cname);
            END IF;
        END $$;
        """
    )
    op.execute("DROP INDEX IF EXISTS ix_answer_journal_request_id")

    # 2. Поля шага
    op.add_column(
        "answer_journal",
        sa.Column("step", sa.String(length=20), nullable=False, server_default="rag"),
    )
    op.add_column(
        "answer_journal",
        sa.Column("step_index", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "answer_journal",
        sa.Column("performed_by", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "answer_journal",
        sa.Column("knowledge_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "answer_journal",
        sa.Column("knowledge_chunk_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "answer_journal",
        sa.Column("is_final", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column(
        "answer_journal", sa.Column("response_time_ms", sa.Integer(), nullable=True)
    )

    op.create_foreign_key(
        None, "answer_journal", "app_user", ["performed_by"], ["id"]
    )
    op.create_foreign_key(
        None,
        "answer_journal",
        "knowledge_source",
        ["knowledge_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        None,
        "answer_journal",
        "knowledge_chunk",
        ["knowledge_chunk_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # 3. Бэкфилл: шаг = режим запроса, единственная запись была финальной
    op.execute(
        """
        UPDATE answer_journal AS a
        SET step = r.mode,
            step_index = 0,
            is_final = true
        FROM request_journal AS r
        WHERE r.id = a.request_id
        """
    )

    op.create_index(
        op.f("ix_answer_journal_request_id"),
        "answer_journal",
        ["request_id"],
        unique=False,
    )
    op.create_unique_constraint(
        "uq_answer_journal_step", "answer_journal", ["request_id", "step_index"]
    )

    # server_default был нужен только для бэкфилла
    op.alter_column("answer_journal", "step", server_default=None)
    op.alter_column("answer_journal", "step_index", server_default=None)
    op.alter_column("answer_journal", "is_final", server_default=None)


def downgrade() -> None:
    op.execute(
        """
        DO $$
        DECLARE duplicated int;
        BEGIN
            SELECT count(*) INTO duplicated FROM (
                SELECT request_id FROM answer_journal GROUP BY request_id HAVING count(*) > 1
            ) AS d;

            IF duplicated > 0 THEN
                RAISE EXCEPTION
                    'Cannot downgrade: % request(s) have multiple journal entries; '
                    'UNIQUE(request_id) cannot be restored without data loss', duplicated;
            END IF;
        END $$;
        """
    )

    op.drop_constraint("uq_answer_journal_step", "answer_journal", type_="unique")
    op.drop_index(op.f("ix_answer_journal_request_id"), table_name="answer_journal")
    op.create_index(
        op.f("ix_answer_journal_request_id"),
        "answer_journal",
        ["request_id"],
        unique=True,
    )

    op.drop_constraint(
        "answer_journal_knowledge_chunk_id_fkey", "answer_journal", type_="foreignkey"
    )
    op.drop_constraint(
        "answer_journal_knowledge_id_fkey", "answer_journal", type_="foreignkey"
    )
    op.drop_constraint(
        "answer_journal_performed_by_fkey", "answer_journal", type_="foreignkey"
    )

    op.drop_column("answer_journal", "response_time_ms")
    op.drop_column("answer_journal", "is_final")
    op.drop_column("answer_journal", "knowledge_chunk_id")
    op.drop_column("answer_journal", "knowledge_id")
    op.drop_column("answer_journal", "performed_by")
    op.drop_column("answer_journal", "step_index")
    op.drop_column("answer_journal", "step")
