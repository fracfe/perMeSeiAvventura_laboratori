"""Anagrafica partecipanti e assegnazioni dei gruppi.

Revision ID: d7e3b6a90124
Revises: c4f92a1d8e73
"""
from alembic import op
import sqlalchemy as sa


revision = "d7e3b6a90124"
down_revision = "c4f92a1d8e73"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("partecipanti", schema=None) as batch_op:
        for nome in ("gruppo", "zona", "regione", "email", "foca", "ruolo"):
            batch_op.add_column(sa.Column(nome, sa.String(255), nullable=True))
        batch_op.add_column(sa.Column("sesso", sa.String(50), nullable=True))
        batch_op.add_column(sa.Column("incarico_altro", sa.Text(), nullable=True))
        # I default DB valorizzano anche le righe esistenti e mantengono
        # compatibili gli inserimenti del vecchio import a tre campi.
        batch_op.add_column(sa.Column(
            "deve_iscriversi_sabato", sa.Boolean(),
            server_default=sa.true(), nullable=False,
        ))
        batch_op.add_column(sa.Column(
            "includi_domenica", sa.Boolean(),
            server_default=sa.false(), nullable=False,
        ))
        batch_op.add_column(sa.Column("gruppo_domenica", sa.SmallInteger(), nullable=True))
        batch_op.create_check_constraint(
            "ck_partecipanti_gruppo_domenica",
            "gruppo_domenica IS NULL OR gruppo_domenica BETWEEN 1 AND 20",
        )

    with op.batch_alter_table("iscrizioni", schema=None) as batch_op:
        for fascia in ("mattino", "pomeriggio"):
            campo = f"sottogruppo_{fascia}"
            batch_op.add_column(sa.Column(campo, sa.String(1), nullable=True))
            batch_op.create_check_constraint(
                f"ck_iscrizioni_{campo}",
                f"{campo} IS NULL OR {campo} IN ('A', 'B')",
            )


def downgrade():
    with op.batch_alter_table("iscrizioni", schema=None) as batch_op:
        for fascia in ("pomeriggio", "mattino"):
            campo = f"sottogruppo_{fascia}"
            batch_op.drop_constraint(f"ck_iscrizioni_{campo}", type_="check")
            batch_op.drop_column(campo)

    with op.batch_alter_table("partecipanti", schema=None) as batch_op:
        batch_op.drop_constraint("ck_partecipanti_gruppo_domenica", type_="check")
        for nome in (
            "gruppo_domenica", "includi_domenica", "deve_iscriversi_sabato",
            "incarico_altro", "sesso", "ruolo", "foca", "email",
            "regione", "zona", "gruppo",
        ):
            batch_op.drop_column(nome)
