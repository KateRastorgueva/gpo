"""Merge operator-reply branch into the ticket workflow

Revision ID: 0c3e5b7a9d14
Revises: a1e9c4f72b58, b7a4f1c2e9d0
Create Date: 2026-10-08

Если в БД есть таблица `operatorreply` (применялась прежняя версия b7a4f1c2e9d0),
ответы переносятся в тикеты (`resolution`, `resolved_at`, `assigned_to`), запросы со
статусом `operator_replied` получают статус `answered`, таблица удаляется.
На новой БД миграция ничего не делает.

Обратимость: `downgrade` таблицу не восстанавливает — ответы остаются в тикетах.
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "0c3e5b7a9d14"
down_revision = ("a1e9c4f72b58", "b7a4f1c2e9d0")
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF to_regclass('public.operatorreply') IS NOT NULL THEN
                UPDATE support_ticket t
                SET resolution = COALESCE(t.resolution, left(r.reply_text, 4000)),
                    resolved_at = COALESCE(t.resolved_at, r.created_at),
                    assigned_to = COALESCE(t.assigned_to, r.operator_id)
                FROM operatorreply r
                WHERE r.queue_id = t.id;

                UPDATE request_journal j
                SET status = 'answered',
                    answered_at = COALESCE(j.answered_at, r.created_at)
                FROM support_ticket t
                JOIN operatorreply r ON r.queue_id = t.id
                WHERE t.request_id = j.id AND j.status = 'operator_replied';

                DROP TABLE operatorreply;
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    pass
