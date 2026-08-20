"""iscrizione progressiva

Revision ID: b3f1a7d92c10
Revises: 84028c5fc5ed
Create Date: 2026-08-20 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "b3f1a7d92c10"
down_revision = "84028c5fc5ed"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("iscrizioni", schema=None) as batch_op:
        batch_op.alter_column(
            "scelta_mattino",
            existing_type=sa.Integer(),
            nullable=True,
        )
        batch_op.alter_column(
            "scelta_pomeriggio",
            existing_type=sa.Integer(),
            nullable=True,
        )
        batch_op.create_unique_constraint(
            "uq_iscrizioni_partecipante",
            ["partecipante"],
        )


def downgrade():
    with op.batch_alter_table("iscrizioni", schema=None) as batch_op:
        batch_op.drop_constraint(
            "uq_iscrizioni_partecipante",
            type_="unique",
        )
        batch_op.alter_column(
            "scelta_pomeriggio",
            existing_type=sa.Integer(),
            nullable=False,
        )
        batch_op.alter_column(
            "scelta_mattino",
            existing_type=sa.Integer(),
            nullable=False,
        )
