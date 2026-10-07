"""Rename legacy tables to snake_case

Revision ID: 8f4c1a2b7d90
Revises: 3f2d3d2d6e45
Create Date: 2026-04-02

Механическая миграция: только переименования, структура не меняется.
Часть плана docs/db-schema-implementation-plan.md (M0, решение D6).

`supportrequest` переименовывается сразу в финальное `request_journal`
(решение D10: журнал — архив всех запросов, источник правды), потому что
промежуточное имя `support_request` всё равно было бы переименовано следом.

ВАЖНО про имена constraints: PostgreSQL при ALTER TABLE RENAME не переименовывает
ни PK/FK/UNIQUE, ни их имена. Поэтому после этой миграции в БД остаются, например,
`supportanswer_request_id_key` (UNIQUE) и `user_pkey`. Индексы переименовываются
явно ниже. Последующие миграции снимают UNIQUE по фактическим именам:
M6 `answer_journal_steps` и M7 `ticket_workflow`.

Классы SQLModel на этом шаге сохраняют старые имена (`SupportAnswer`, `OperatorQueue`),
меняется только `__tablename__`: переименование классов делается вместе с изменением
логики журнала, чтобы не смешивать косметику и поведение.
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "8f4c1a2b7d90"
down_revision = "3f2d3d2d6e45"
branch_labels = None
depends_on = None


TABLE_RENAMES: tuple[tuple[str, str], ...] = (
    ("user", "app_user"),
    ("knowledgesource", "knowledge_source"),
    ("knowledgechunk", "knowledge_chunk"),
    ("supportrequest", "request_journal"),
    ("supportanswer", "answer_journal"),
    ("operatorqueue", "support_ticket"),
)

INDEX_RENAMES: tuple[tuple[str, str], ...] = (
    ("ix_user_email", "ix_app_user_email"),
    ("ix_knowledgechunk_chunk_index", "ix_knowledge_chunk_chunk_index"),
    ("ix_knowledgechunk_source_id", "ix_knowledge_chunk_source_id"),
    ("ix_knowledgechunk_vector_id", "ix_knowledge_chunk_vector_id"),
    ("ix_supportrequest_session_id", "ix_request_journal_session_id"),
    ("ix_supportrequest_user_id", "ix_request_journal_user_id"),
    ("ix_supportanswer_request_id", "ix_answer_journal_request_id"),
    ("ix_operatorqueue_request_id", "ix_support_ticket_request_id"),
)


def upgrade() -> None:
    for old_name, new_name in TABLE_RENAMES:
        op.rename_table(old_name, new_name)

    for old_name, new_name in INDEX_RENAMES:
        op.execute(f'ALTER INDEX "{old_name}" RENAME TO "{new_name}"')


def downgrade() -> None:
    for old_name, new_name in reversed(INDEX_RENAMES):
        op.execute(f'ALTER INDEX "{new_name}" RENAME TO "{old_name}"')

    for old_name, new_name in reversed(TABLE_RENAMES):
        op.rename_table(new_name, old_name)
