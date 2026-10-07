"""Add support ticket workflow: assignment, resolution, reopening

Revision ID: e2b7d5a91f38
Revises: c9f3b1e64d07
Create Date: 2026-04-02

Часть плана docs/db-schema-implementation-plan.md (M7; решение V8).

Что делает:
- снимает UNIQUE с `support_ticket.request_id`: переоткрытие создаёт новый тикет вместо
  правки прежнего, поэтому на запрос их может быть несколько;
- добавляет `assigned_to` (агент), `resolution` (итоговое решение), `reopened_from_id`
  (ссылка на переоткрытый тикет) и `resolved_at`;
- вводит ЧАСТИЧНЫЙ уникальный индекс `uq_support_ticket_active`: одновременно активным
  (open/in_progress) может быть только один тикет на запрос.

Имя легаси-констрейнта ищется динамически: M0 переименовала таблицу `operatorqueue` →
`support_ticket`, но имя констрейнта PostgreSQL сохранил (`operatorqueue_request_id_key`).

Обратимость: если у запроса больше одного тикета, `downgrade` падает с явной ошибкой —
UNIQUE(request_id) не восстановить без потери истории переоткрытий.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "e2b7d5a91f38"
down_revision = "c9f3b1e64d07"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        DECLARE cname text;
        BEGIN
            SELECT conname INTO cname
            FROM pg_constraint
            WHERE conrelid = 'support_ticket'::regclass AND contype = 'u';

            IF cname IS NOT NULL THEN
                EXECUTE format('ALTER TABLE support_ticket DROP CONSTRAINT %I', cname);
            END IF;
        END $$;
        """
    )
    op.execute("DROP INDEX IF EXISTS ix_support_ticket_request_id")

    op.add_column(
        "support_ticket",
        sa.Column("assigned_to", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "support_ticket",
        sa.Column("resolution", sa.String(length=4000), nullable=True),
    )
    op.add_column(
        "support_ticket",
        sa.Column("reopened_from_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "support_ticket",
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_index(
        op.f("ix_support_ticket_assigned_to"),
        "support_ticket",
        ["assigned_to"],
        unique=False,
    )
    op.create_index(
        op.f("ix_support_ticket_request_id"),
        "support_ticket",
        ["request_id"],
        unique=False,
    )
    op.create_foreign_key(None, "support_ticket", "app_user", ["assigned_to"], ["id"])
    op.create_foreign_key(
        None, "support_ticket", "support_ticket", ["reopened_from_id"], ["id"]
    )
    op.create_index(
        "uq_support_ticket_active",
        "support_ticket",
        ["request_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('open', 'in_progress')"),
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        DECLARE duplicated int;
        BEGIN
            SELECT count(*) INTO duplicated FROM (
                SELECT request_id FROM support_ticket GROUP BY request_id HAVING count(*) > 1
            ) AS d;

            IF duplicated > 0 THEN
                RAISE EXCEPTION
                    'Cannot downgrade: % request(s) have multiple tickets; '
                    'UNIQUE(request_id) cannot be restored without data loss', duplicated;
            END IF;
        END $$;
        """
    )

    op.drop_index("uq_support_ticket_active", table_name="support_ticket")
    op.drop_constraint(
        "support_ticket_reopened_from_id_fkey", "support_ticket", type_="foreignkey"
    )
    op.drop_constraint(
        "support_ticket_assigned_to_fkey", "support_ticket", type_="foreignkey"
    )
    op.drop_index(op.f("ix_support_ticket_request_id"), table_name="support_ticket")
    op.create_index(
        op.f("ix_support_ticket_request_id"),
        "support_ticket",
        ["request_id"],
        unique=True,
    )
    op.drop_index(op.f("ix_support_ticket_assigned_to"), table_name="support_ticket")
    op.drop_column("support_ticket", "resolved_at")
    op.drop_column("support_ticket", "reopened_from_id")
    op.drop_column("support_ticket", "resolution")
    op.drop_column("support_ticket", "assigned_to")
