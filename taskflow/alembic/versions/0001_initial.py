"""initial schema: users and tasks

Revision ID: 0001
Revises:
Create Date: 2026-07-20

"""
from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

task_status = sa.Enum("pending", "in_progress", "done", name="taskstatus")


def upgrade():
    op.create_table(
        "users",
        sa.Column("id", sa.Integer, primary_key=True, index=True),
        sa.Column("email", sa.String, unique=True, index=True, nullable=False),
        sa.Column("hashed_password", sa.String, nullable=False),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )

    op.create_table(
        "tasks",
        sa.Column("id", sa.Integer, primary_key=True, index=True),
        sa.Column("title", sa.String, nullable=False),
        sa.Column("description", sa.String, nullable=True),
        sa.Column("status", task_status, nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("owner_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    )


def downgrade():
    op.drop_table("tasks")
    task_status.drop(op.get_bind(), checkfirst=True)
    op.drop_table("users")
