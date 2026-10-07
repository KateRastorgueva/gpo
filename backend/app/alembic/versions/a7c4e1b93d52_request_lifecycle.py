"""Add request lifecycle and the hot active-requests queue

Revision ID: a7c4e1b93d52
Revises: c5a9e3d1b746
Create Date: 2026-04-02

Часть плана docs/db-schema-implementation-plan.md (M2; решения V3, D10, §0.3).

Что делает:
1. Добавляет в `request_journal` (источник правды по запросам) поля жизненного цикла
   `updated_at`, `answered_at`, `closed_at` и приводит `status` к словарю
   `queued | in_progress | answered | closed`.
2. Создаёт `active_request` — горячую таблицу очереди (только запросы, которые сейчас
   висят в очереди) с денормализованными `user_id`/`question`/`channel`.
3. Заполняет `active_request` существующими незавершёнными запросами.

Строки между `request_journal` и `active_request` не переносятся: постановка в очередь —
INSERT, завершение — DELETE. Поэтому FK дочерних таблиц (`answer_journal`, `support_ticket`)
на журнал никогда не рвутся, и каскадное удаление ничего не теряет.

Прежние значения `status` ('escalated'/'completed') заменяются безвозвратно; downgrade
восстанавливает их приблизительно (queued -> 'escalated', answered -> 'completed').
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "a7c4e1b93d52"
down_revision = "c5a9e3d1b746"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "request_journal",
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "request_journal",
        sa.Column("answered_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "request_journal",
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
    )

    # Бэкфилл: запрос, у которого есть ответ, считается answered (answered_at — время
    # первого ответа); остальные остаются в очереди.
    op.execute(
        """
        UPDATE request_journal AS r
        SET status = 'answered',
            answered_at = a.answered_at,
            updated_at = a.answered_at
        FROM (
            SELECT request_id, MIN(created_at) AS answered_at
            FROM answer_journal
            GROUP BY request_id
        ) AS a
        WHERE a.request_id = r.id
        """
    )
    op.execute(
        """
        UPDATE request_journal
        SET status = 'queued',
            updated_at = COALESCE(updated_at, created_at)
        WHERE answered_at IS NULL
        """
    )

    op.create_index(
        op.f("ix_request_journal_status"), "request_journal", ["status"], unique=False
    )
    op.create_index(
        op.f("ix_request_journal_user_created"),
        "request_journal",
        ["user_id", sa.text("created_at DESC")],
        unique=False,
    )
    op.create_index(
        op.f("ix_request_journal_created_at"),
        "request_journal",
        [sa.text("created_at DESC")],
        unique=False,
    )
    # Одиночный индекс по user_id становится избыточным: его роль берёт на себя
    # составной (user_id, created_at DESC), у которого user_id — префикс.
    op.drop_index(op.f("ix_request_journal_user_id"), table_name="request_journal")

    op.create_table(
        "active_request",
        sa.Column("request_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("question", sa.String(length=4000), nullable=False),
        sa.Column("channel", sa.String(length=20), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("assigned_to", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("queued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["request_id"], ["request_journal.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["app_user.id"]),
        sa.ForeignKeyConstraint(["assigned_to"], ["app_user.id"]),
        sa.PrimaryKeyConstraint("request_id"),
    )
    op.create_index(
        op.f("ix_active_request_assigned_to"),
        "active_request",
        ["assigned_to"],
        unique=False,
    )
    op.create_index(
        op.f("ix_active_request_priority_queued_at"),
        "active_request",
        ["priority", "queued_at"],
        unique=False,
    )

    op.execute(
        """
        INSERT INTO active_request (
            request_id, user_id, question, channel, priority, queued_at, updated_at
        )
        SELECT id, user_id, question, channel, 0, created_at,
               COALESCE(updated_at, created_at)
        FROM request_journal
        WHERE status = 'queued'
        """
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_active_request_priority_queued_at"), table_name="active_request"
    )
    op.drop_index(op.f("ix_active_request_assigned_to"), table_name="active_request")
    op.drop_table("active_request")

    op.create_index(
        op.f("ix_request_journal_user_id"),
        "request_journal",
        ["user_id"],
        unique=False,
    )
    op.drop_index(op.f("ix_request_journal_created_at"), table_name="request_journal")
    op.drop_index(
        op.f("ix_request_journal_user_created"), table_name="request_journal"
    )
    op.drop_index(op.f("ix_request_journal_status"), table_name="request_journal")

    # Возврат к прежнему словарю статусов (точное исходное значение невосстановимо).
    op.execute(
        """
        UPDATE request_journal
        SET status = CASE
            WHEN answered_at IS NULL THEN 'escalated'
            ELSE 'completed'
        END
        """
    )

    op.drop_column("request_journal", "closed_at")
    op.drop_column("request_journal", "answered_at")
    op.drop_column("request_journal", "updated_at")
