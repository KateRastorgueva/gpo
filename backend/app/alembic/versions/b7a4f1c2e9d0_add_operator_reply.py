"""Add OperatorReply table (superseded)

Revision ID: b7a4f1c2e9d0
Revises: 3f2d3d2d6e45
Create Date: 2026-04-29 12:00:00.000000

Ветка до слияния с M0-M10. Ответ оператора теперь хранится в `support_ticket.resolution`
(M7), поэтому на новой БД миграция ничего не делает. Ревизия сохранена, чтобы БД, где
она уже применена, оставались совместимы; таблицу `operatorreply` переносит и удаляет
`0c3e5b7a9d14_merge_operator_reply`.
"""


# revision identifiers, used by Alembic.
revision = "b7a4f1c2e9d0"
down_revision = "3f2d3d2d6e45"
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
