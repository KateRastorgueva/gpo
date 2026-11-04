"""Add app settings and ingest jobs for external RAG engines

Revision ID: 7d3b9e5f1a26
Revises: 0c3e5b7a9d14
Create Date: 2026-10-22

Что делает:
- `app_setting` — ключ/значение, которые админ меняет на лету (активный RAG-движок);
- `ingest_job` / `ingest_item` — пакетная загрузка файлов в Gemini File Search и
  AnythingLLM с прогрессом по каждому файлу.

Аддитивная миграция: существующие данные не затрагиваются.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "7d3b9e5f1a26"
down_revision = "0c3e5b7a9d14"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "app_setting",
        sa.Column("key", sa.String(length=100), nullable=False),
        sa.Column("value", sa.String(length=1000), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("key"),
    )
    op.create_table(
        "ingest_job",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("target", sa.String(length=20), nullable=False),
        sa.Column("total", sa.Integer(), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["app_user.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "ingest_item",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("filename", sa.String(length=500), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("gemini_status", sa.String(length=20), nullable=True),
        sa.Column("anythingllm_status", sa.String(length=20), nullable=True),
        sa.Column("error", sa.String(length=2000), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["job_id"], ["ingest_job.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_ingest_item_job_id"), "ingest_item", ["job_id"], unique=False
    )
    op.create_index(
        op.f("ix_ingest_item_status"), "ingest_item", ["status"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_ingest_item_status"), table_name="ingest_item")
    op.drop_index(op.f("ix_ingest_item_job_id"), table_name="ingest_item")
    op.drop_table("ingest_item")
    op.drop_table("ingest_job")
    op.drop_table("app_setting")
