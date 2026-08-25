"""aggiunta scelta non partecipa

Revision ID: c4f92a1d8e73
Revises: b3f1a7d92c10
Create Date: 2026-08-25 17:10:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "c4f92a1d8e73"
down_revision = "b3f1a7d92c10"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("iscrizioni", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "non_partecipa_mattino",
                sa.Boolean(),
                server_default=sa.false(),
                nullable=False,
            )
        )
        batch_op.add_column(
            sa.Column(
                "non_partecipa_pomeriggio",
                sa.Boolean(),
                server_default=sa.false(),
                nullable=False,
            )
        )
        batch_op.create_check_constraint(
            "ck_iscrizioni_scelta_mattino_esclusiva",
            "scelta_mattino IS NULL OR non_partecipa_mattino = 0",
        )
        batch_op.create_check_constraint(
            "ck_iscrizioni_scelta_pomeriggio_esclusiva",
            "scelta_pomeriggio IS NULL OR non_partecipa_pomeriggio = 0",
        )


def downgrade():
    with op.batch_alter_table("iscrizioni", schema=None) as batch_op:
        batch_op.drop_constraint(
            "ck_iscrizioni_scelta_pomeriggio_esclusiva",
            type_="check",
        )
        batch_op.drop_constraint(
            "ck_iscrizioni_scelta_mattino_esclusiva",
            type_="check",
        )
        batch_op.drop_column("non_partecipa_pomeriggio")
        batch_op.drop_column("non_partecipa_mattino")
