"""Add OperatorReply table

Revision ID: b7a4f1c2e9d0
Revises: 3f2d3d2d6e45
Create Date: 2026-04-29 12:00:00.000000

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "b7a4f1c2e9d0"
down_revision = "3f2d3d2d6e45"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "operatorreply",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("queue_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("operator_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("reply_text", sa.String(length=8000), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["queue_id"], ["operatorqueue.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["operator_id"], ["user.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("queue_id"),
    )
    op.create_index(
        op.f("ix_operatorreply_queue_id"),
        "operatorreply",
        ["queue_id"],
        unique=True,
    )
    op.create_index(
        op.f("ix_operatorreply_operator_id"),
        "operatorreply",
        ["operator_id"],
        unique=False,
    )


def downgrade():
    op.drop_index(op.f("ix_operatorreply_operator_id"), table_name="operatorreply")
    op.drop_index(op.f("ix_operatorreply_queue_id"), table_name="operatorreply")
    op.drop_table("operatorreply")
