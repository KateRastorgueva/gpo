"""Add support and RAG models

Revision ID: 3f2d3d2d6e45
Revises: fe56fa70289e
Create Date: 2026-04-01 13:25:00.000000

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "3f2d3d2d6e45"
down_revision = "fe56fa70289e"
branch_labels = None
depends_on = None


def upgrade():
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

    op.create_table(
        "knowledgesource",
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("source_type", sa.String(length=20), nullable=False),
        sa.Column("source_ref", sa.String(length=1024), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("last_indexed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "knowledgechunk",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("vector_id", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["source_id"], ["knowledgesource.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_knowledgechunk_chunk_index"),
        "knowledgechunk",
        ["chunk_index"],
        unique=False,
    )
    op.create_index(
        op.f("ix_knowledgechunk_source_id"),
        "knowledgechunk",
        ["source_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_knowledgechunk_vector_id"),
        "knowledgechunk",
        ["vector_id"],
        unique=True,
    )

    op.create_table(
        "supportrequest",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("session_id", sa.String(length=255), nullable=False),
        sa.Column("channel", sa.String(length=20), nullable=False),
        sa.Column("question", sa.String(length=4000), nullable=False),
        sa.Column("mode", sa.String(length=20), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("fallback_used", sa.Boolean(), nullable=False),
        sa.Column("escalated", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_supportrequest_session_id"),
        "supportrequest",
        ["session_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_supportrequest_user_id"),
        "supportrequest",
        ["user_id"],
        unique=False,
    )

    op.create_table(
        "supportanswer",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("request_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("answer", sa.String(length=8000), nullable=False),
        sa.Column("sources_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["request_id"], ["supportrequest.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("request_id"),
    )
    op.create_index(
        op.f("ix_supportanswer_request_id"),
        "supportanswer",
        ["request_id"],
        unique=True,
    )

    op.create_table(
        "operatorqueue",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("request_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("reason", sa.String(length=500), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["request_id"], ["supportrequest.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("request_id"),
    )
    op.create_index(
        op.f("ix_operatorqueue_request_id"),
        "operatorqueue",
        ["request_id"],
        unique=True,
    )


def downgrade():
    op.drop_index(op.f("ix_operatorqueue_request_id"), table_name="operatorqueue")
    op.drop_table("operatorqueue")

    op.drop_index(op.f("ix_supportanswer_request_id"), table_name="supportanswer")
    op.drop_table("supportanswer")

    op.drop_index(op.f("ix_supportrequest_user_id"), table_name="supportrequest")
    op.drop_index(op.f("ix_supportrequest_session_id"), table_name="supportrequest")
    op.drop_table("supportrequest")

    op.drop_index(op.f("ix_knowledgechunk_vector_id"), table_name="knowledgechunk")
    op.drop_index(op.f("ix_knowledgechunk_source_id"), table_name="knowledgechunk")
    op.drop_index(op.f("ix_knowledgechunk_chunk_index"), table_name="knowledgechunk")
    op.drop_table("knowledgechunk")

    op.drop_table("knowledgesource")

    op.drop_index(op.f("ix_faqentry_normalized_question"), table_name="faqentry")
    op.drop_table("faqentry")

