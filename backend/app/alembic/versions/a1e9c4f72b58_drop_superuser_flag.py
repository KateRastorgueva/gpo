"""Drop the legacy is_superuser flag

Revision ID: a1e9c4f72b58
Revises: f5c8a2d64b19
Create Date: 2026-04-02

Часть плана docs/db-schema-implementation-plan.md (M10; решение V2).

Что делает:
- удаляет колонку `app_user.is_superuser`.

К этому моменту права полностью определяет роль (`role_id`), а API продолжает отдавать
`is_superuser` как ПРОИЗВОДНОЕ поле (True, если у роли есть wildcard-разрешение),
чтобы фронтенд не пришлось менять.

Бэкфилл не нужен: миграция M1 уже раздала роли по этому признаку (`is_superuser=true` ->
роль `admin`). Перед применением стоит убедиться, что пользователей без роли не осталось
(проверка ниже), иначе такой пользователь потеряет доступ — это ожидаемо и безопасно.

Обратимость: `upgrade` невосстановим по данным (значения флага утеряны осознанно).
`downgrade` возвращает колонку со значением по признаку роли, чтобы старый код работал.
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "a1e9c4f72b58"
down_revision = "f5c8a2d64b19"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        DECLARE without_role int;
        BEGIN
            SELECT count(*) INTO without_role FROM app_user WHERE role_id IS NULL;

            IF without_role > 0 THEN
                RAISE WARNING 'app_user: % user(s) have no role and will lose access '
                              'after is_superuser is dropped', without_role;
            END IF;
        END $$;
        """
    )
    op.drop_column("app_user", "is_superuser")


def downgrade() -> None:
    op.add_column(
        "app_user",
        sa.Column(
            "is_superuser",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    # Признак восстанавливается по роли: администратор = роль с wildcard-разрешением
    op.execute(
        """
        UPDATE app_user
        SET is_superuser = true
        WHERE role_id IN (
            SELECT id FROM role WHERE permissions::text LIKE '%"*"%'
        )
        """
    )
    op.alter_column("app_user", "is_superuser", server_default=None)
