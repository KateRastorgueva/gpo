"""Add roles and user role assignment

Revision ID: c5a9e3d1b746
Revises: 8f4c1a2b7d90
Create Date: 2026-04-02

Часть плана docs/db-schema-implementation-plan.md (M1, решения V2 и D2):
вводится RBAC, роль администратора выдаётся по признаку `is_superuser`.

Колонка `app_user.is_superuser` на этом шаге НЕ удаляется: она объявлена NOT NULL без
server default, поэтому её можно убрать из модели и БД только одновременно и после того,
как код перестанет её читать (миграция M10 `drop_superuser_flag`).

Матрица ролей зашита здесь намеренно: миграция должна оставаться самодостаточной и не
зависеть от кода приложения. Источник правды во время выполнения — `app/core/permissions.py`,
поэтому изменение матрицы требует отдельной миграции синхронизации ролей.
"""

import uuid
from datetime import datetime, timezone

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "c5a9e3d1b746"
down_revision = "8f4c1a2b7d90"
branch_labels = None
depends_on = None


ROLE_SEED: tuple[tuple[str, list[str]], ...] = (
    ("admin", ["*"]),
    ("operator", ["knowledge:read", "ticket:read", "ticket:resolve", "metrics:read"]),
    ("user", []),
)

ROLE_FK_NAME = "app_user_role_id_fkey"


def upgrade() -> None:
    op.create_table(
        "role",
        sa.Column("name", sa.String(length=50), nullable=False),
        sa.Column("permissions", sa.JSON(), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_role_name"), "role", ["name"], unique=True)

    now = datetime.now(timezone.utc)
    role_table = sa.table(
        "role",
        sa.column("id", postgresql.UUID(as_uuid=True)),
        sa.column("name", sa.String(length=50)),
        sa.column("permissions", sa.JSON()),
        sa.column("created_at", sa.DateTime(timezone=True)),
    )
    op.bulk_insert(
        role_table,
        [
            {
                "id": uuid.uuid4(),
                "name": name,
                "permissions": permissions,
                "created_at": now,
            }
            for name, permissions in ROLE_SEED
        ],
    )

    op.add_column("app_user", sa.Column("phone", sa.String(length=32), nullable=True))
    op.add_column(
        "app_user",
        sa.Column("role_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_index(op.f("ix_app_user_role_id"), "app_user", ["role_id"], unique=False)
    # Имя FK не задаём: остальные связи в схеме используют автоименование PostgreSQL.
    op.create_foreign_key(None, "app_user", "role", ["role_id"], ["id"])

    # Бэкфилл: администраторы получают роль admin, остальные — user.
    op.execute(
        """
        UPDATE app_user
        SET role_id = (
            SELECT id FROM role
            WHERE role.name = CASE
                WHEN app_user.is_superuser THEN 'admin'
                ELSE 'user'
            END
        )
        WHERE role_id IS NULL
        """
    )
    # nullable=False здесь сознательно НЕ ставится: пользователей создают и в обход
    # crud.create_user (например /private/users в локальном режиме), и NOT NULL ломал бы
    # такие пути. Роль по умолчанию назначает сервисный слой, а отсутствие роли
    # трактуется как «нет прав» (app/core/permissions.py:has_permission).


def downgrade() -> None:
    op.drop_constraint(ROLE_FK_NAME, "app_user", type_="foreignkey")
    op.drop_index(op.f("ix_app_user_role_id"), table_name="app_user")
    op.drop_column("app_user", "role_id")
    op.drop_column("app_user", "phone")

    op.drop_index(op.f("ix_role_name"), table_name="role")
    op.drop_table("role")
