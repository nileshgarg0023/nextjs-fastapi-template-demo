"""Add Gmail connections

Revision ID: b7c2f0a18d41
Revises: a0de1e28652c
Create Date: 2026-06-03 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import fastapi_users_db_sqlalchemy
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "b7c2f0a18d41"
down_revision: Union[str, None] = "a0de1e28652c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "gmail_connections",
        sa.Column(
            "id", fastapi_users_db_sqlalchemy.generics.GUID(), nullable=False
        ),
        sa.Column(
            "user_id", fastapi_users_db_sqlalchemy.generics.GUID(), nullable=False
        ),
        sa.Column("email_address", sa.String(), nullable=False),
        sa.Column("access_token", sa.String(), nullable=False),
        sa.Column("refresh_token", sa.String(), nullable=True),
        sa.Column("history_id", sa.String(), nullable=True),
        sa.Column("watch_expiration", sa.String(), nullable=True),
        sa.Column("categories", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_gmail_connections_email_address"),
        "gmail_connections",
        ["email_address"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_gmail_connections_email_address"),
        table_name="gmail_connections",
    )
    op.drop_table("gmail_connections")
