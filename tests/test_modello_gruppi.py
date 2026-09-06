import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

os.environ["DB_TYPE"] = "sqlite"
os.environ["DB_NAME"] = ":memory:"
os.environ["SECRET_KEY"] = "test-secret-key"

from sqlalchemy import inspect, text
from sqlalchemy.exc import DataError, IntegrityError, OperationalError

from app import Iscrizione, Laboratorio, Partecipante, app, db, iscrizione_completa


CAMPI_ANAGRAFICI = (
    "gruppo", "zona", "regione", "email", "sesso", "foca", "ruolo", "incarico_altro",
)
REVISIONE_PRECEDENTE = "c4f92a1d8e73"
REVISIONE_NUOVA = "d7e3b6a90124"
ROOT = Path(__file__).resolve().parents[1]


class ModelloGruppiTestCase(unittest.TestCase):
    def setUp(self):
        self.context = app.app_context()
        self.context.push()
        db.create_all()
        db.session.add(Partecipante(id=101, nome="Anna", cognome="Rossi"))
        db.session.add_all([
            Laboratorio(id=1, id_lab="M01", titolo="Bosco", descrizione="Mattino",
                        posti=20, tipologia="mattino"),
            Laboratorio(id=2, id_lab="P01", titolo="Tracce", descrizione="Pomeriggio",
                        posti=20, tipologia="pomeriggio"),
        ])
        db.session.commit()
        db.session.add(Iscrizione(
            id=1, partecipante=101, data=datetime(2026, 8, 20, 10, 30),
            scelta_mattino=1, scelta_pomeriggio=2,
        ))
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.context.pop()

    def test_nuovo_partecipante_con_tutti_i_campi(self):
        dati = dict(zip(CAMPI_ANAGRAFICI, (
            "Roma 1", "Roma", "Lazio", "anna@example.test", "F", "CFA",
            "Altro", "Supporto organizzativo",
        )))
        db.session.add(Partecipante(
            id=202, nome="Anna", cognome="Bianchi", **dati,
            deve_iscriversi_sabato=False, includi_domenica=True, gruppo_domenica=20,
        ))
        db.session.commit()
        db.session.expire_all()
        persona = db.session.get(Partecipante, 202)
        for campo, valore in dati.items():
            self.assertEqual(getattr(persona, campo), valore)
        self.assertIs(persona.deve_iscriversi_sabato, False)
        self.assertIs(persona.includi_domenica, True)
        self.assertEqual(persona.gruppo_domenica, 20)

    def test_default_compatibili_con_vecchi_inserimenti_orm_e_sql(self):
        db.session.execute(text(
            "INSERT INTO partecipanti (id, nome, cognome) VALUES (202, 'Luca', 'Verdi')"
        ))
        db.session.commit()
        for codice in (101, 202):
            persona = db.session.get(Partecipante, codice)
            self.assertIs(persona.deve_iscriversi_sabato, True)
            self.assertIs(persona.includi_domenica, False)
            self.assertIsNone(persona.gruppo_domenica)
            for campo in CAMPI_ANAGRAFICI:
                self.assertIsNone(getattr(persona, campo))

    def test_boolean_non_nullable(self):
        for campo in ("deve_iscriversi_sabato", "includi_domenica"):
            with self.subTest(campo=campo):
                with self.assertRaises(IntegrityError):
                    db.session.execute(text(f"UPDATE partecipanti SET {campo} = NULL"))
                    db.session.commit()
                db.session.rollback()

    @contextmanager
    def violazione_check(self, nome_vincolo, colonna_troppo_lunga=None):
        mariadb_pymysql = (
            db.engine.dialect.name in ("mysql", "mariadb")
            and db.engine.dialect.is_mariadb
            and db.engine.dialect.driver == "pymysql"
        )
        errori_attesi = (IntegrityError, OperationalError) if mariadb_pymysql else IntegrityError
        if mariadb_pymysql and colonna_troppo_lunga:
            errori_attesi += (DataError,)
        try:
            with self.assertRaises(errori_attesi) as errore:
                yield
            if isinstance(errore.exception, DataError):
                # MariaDB può rifiutare AB per lunghezza prima di valutare il CHECK.
                self.assertEqual(errore.exception.orig.args[0], 1406)
                self.assertIn(colonna_troppo_lunga, str(errore.exception.orig))
            else:
                if isinstance(errore.exception, OperationalError):
                    self.assertEqual(errore.exception.orig.args[0], 4025)
                self.assertIn(nome_vincolo, str(errore.exception))
        finally:
            db.session.rollback()

    def test_gruppo_domenica_limiti_e_null(self):
        for valore in (None, 1, 20):
            persona = db.session.get(Partecipante, 101)
            persona.gruppo_domenica = valore
            db.session.commit()
            self.assertEqual(persona.gruppo_domenica, valore)
        for valore in (0, 21, -1):
            with self.subTest(valore=valore):
                db.session.get(Partecipante, 101).gruppo_domenica = valore
                with self.violazione_check("ck_partecipanti_gruppo_domenica"):
                    db.session.commit()
                self.assertEqual(db.session.get(Partecipante, 101).gruppo_domenica, 20)

    def test_sottogruppi_indipendenti_e_iscrizione_preservata(self):
        iscrizione = db.session.get(Iscrizione, 1)
        campi_precedenti = (
            "partecipante", "scelta_mattino", "scelta_pomeriggio",
            "non_partecipa_mattino", "non_partecipa_pomeriggio", "data",
        )
        prima = tuple(getattr(iscrizione, campo) for campo in campi_precedenti)
        self.assertIsNone(iscrizione.sottogruppo_mattino)
        self.assertIsNone(iscrizione.sottogruppo_pomeriggio)
        for mattino, pomeriggio in (("A", "B"), ("B", "A"), (None, None)):
            iscrizione.sottogruppo_mattino = mattino
            iscrizione.sottogruppo_pomeriggio = pomeriggio
            db.session.commit()
            self.assertEqual((iscrizione.sottogruppo_mattino,
                              iscrizione.sottogruppo_pomeriggio), (mattino, pomeriggio))
            self.assertEqual(tuple(getattr(iscrizione, campo) for campo in campi_precedenti), prima)
            self.assertTrue(iscrizione_completa(iscrizione))

    def test_sottogruppi_invalidi_rifiutati_dal_database(self):
        for campo in ("sottogruppo_mattino", "sottogruppo_pomeriggio"):
            for valore in ("C", "X", "", "AB"):
                with self.subTest(campo=campo, valore=valore):
                    setattr(db.session.get(Iscrizione, 1), campo, valore)
                    with self.violazione_check(
                        f"ck_iscrizioni_{campo}",
                        colonna_troppo_lunga=campo if valore == "AB" else None,
                    ):
                        db.session.commit()
                    self.assertIsNone(getattr(db.session.get(Iscrizione, 1), campo))

    def test_sottogruppi_minuscoli_secondo_collation(self):
        mariadb = (
            db.engine.dialect.name in ("mysql", "mariadb")
            and db.engine.dialect.is_mariadb
        )
        # La collation MariaDB attuale accetta a; il futuro algoritmo scriverà A/B maiuscoli.
        for campo in ("sottogruppo_mattino", "sottogruppo_pomeriggio"):
            with self.subTest(campo=campo):
                setattr(db.session.get(Iscrizione, 1), campo, "a")
                if mariadb:
                    db.session.commit()
                    db.session.expire_all()
                    self.assertEqual(getattr(db.session.get(Iscrizione, 1), campo), "a")
                else:
                    with self.violazione_check(f"ck_iscrizioni_{campo}"):
                        db.session.commit()
                    self.assertIsNone(getattr(db.session.get(Iscrizione, 1), campo))


class MigrazioneGruppiTestCase(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="pmsea-migrazione-")
        self.addCleanup(self.directory.cleanup)
        self.database = str(Path(self.directory.name) / "test.sqlite")
        self.env = {
            **os.environ, "DB_TYPE": "sqlite", "DB_NAME": self.database,
            "SECRET_KEY": "test-migrazione", "PYTHONDONTWRITEBYTECODE": "1",
        }

    def migra(self, comando, revisione):
        risultato = subprocess.run(
            [sys.executable, "-m", "flask", "--app", "app", "db", comando, revisione],
            cwd=ROOT, env=self.env, capture_output=True, text=True, timeout=60,
        )
        self.assertEqual(risultato.returncode, 0, risultato.stdout + risultato.stderr)

    def connetti(self):
        connessione = sqlite3.connect(self.database)
        self.addCleanup(connessione.close)
        return connessione

    def test_upgrade_database_vuoto_schema_coerente_con_modelli(self):
        self.migra("upgrade", "head")
        connessione = self.connetti()
        self.assertEqual(connessione.execute("SELECT version_num FROM alembic_version").fetchone(),
                         (REVISIONE_NUOVA,))
        from sqlalchemy import create_engine
        engine = create_engine(f"sqlite:///{self.database}")
        self.addCleanup(engine.dispose)
        schema = inspect(engine)
        for modello in (Partecipante, Iscrizione, Laboratorio):
            colonne = schema.get_columns(modello.__tablename__)
            self.assertEqual({c["name"] for c in colonne}, set(modello.__table__.columns.keys()))
            for colonna in colonne:
                self.assertEqual(colonna["nullable"], modello.__table__.c[colonna["name"]].nullable)
        self.assertFalse(schema.get_unique_constraints("laboratori"))

    def test_upgrade_downgrade_preservano_dati_e_vincoli_precedenti(self):
        self.migra("upgrade", REVISIONE_PRECEDENTE)
        connessione = self.connetti()
        connessione.executescript("""
            INSERT INTO partecipanti VALUES (101, 'Anna', 'Rossi'), (202, 'Luca', 'Verdi');
            INSERT INTO laboratori (id, posti, titolo, descrizione, id_lab, tipologia)
                VALUES (1, 20, 'Bosco', 'Mattino', 'DUP', 'mattino'),
                       (2, 20, 'Tracce', 'Mattino', 'DUP', 'mattino');
            INSERT INTO iscrizioni
                (id, data, partecipante, scelta_mattino, scelta_pomeriggio,
                 non_partecipa_mattino, non_partecipa_pomeriggio)
                VALUES (1, '2026-08-20 10:30:00', 101, 1, NULL, 0, 1),
                       (2, '2026-08-21 11:00:00', 202, 2, NULL, 0, 0);
        """)
        tabelle = ("partecipanti", "iscrizioni", "laboratori")
        colonne = {t: [r[1] for r in connessione.execute(f"PRAGMA table_info({t})")] for t in tabelle}

        def dati_precedenti():
            return {t: connessione.execute(
                f"SELECT {', '.join(colonne[t])} FROM {t} ORDER BY id"
            ).fetchall() for t in tabelle}

        prima = dati_precedenti()
        def foreign_key():
            # La ricostruzione batch SQLite può rinumerare i vincoli.
            return sorted(riga[1:] for riga in connessione.execute(
                "PRAGMA foreign_key_list(iscrizioni)"
            ))

        foreign_key_precedenti = foreign_key()
        self.migra("upgrade", "head")
        self.assertEqual(dati_precedenti(), prima)
        self.assertEqual(foreign_key(), foreign_key_precedenti)
        self.assertEqual(connessione.execute("PRAGMA foreign_key_check").fetchall(), [])
        for riga in connessione.execute(
            "SELECT deve_iscriversi_sabato, includi_domenica, gruppo_domenica, "
            + ", ".join(CAMPI_ANAGRAFICI) + " FROM partecipanti"
        ):
            self.assertEqual(riga, (1, 0, None) + (None,) * len(CAMPI_ANAGRAFICI))
        self.assertEqual(connessione.execute(
            "SELECT sottogruppo_mattino, sottogruppo_pomeriggio FROM iscrizioni"
        ).fetchall(), [(None, None), (None, None)])
        for sql in (
            "UPDATE partecipanti SET gruppo_domenica = 21 WHERE id = 101",
            "UPDATE partecipanti SET deve_iscriversi_sabato = NULL WHERE id = 101",
            "UPDATE partecipanti SET includi_domenica = NULL WHERE id = 101",
            "UPDATE iscrizioni SET sottogruppo_mattino = 'C' WHERE id = 1",
            "UPDATE iscrizioni SET sottogruppo_pomeriggio = 'C' WHERE id = 1",
            "UPDATE iscrizioni SET non_partecipa_mattino = 1 WHERE id = 1",
            "UPDATE iscrizioni SET partecipante = 101 WHERE id = 2",
        ):
            with self.subTest(sql=sql):
                with self.assertRaises(sqlite3.IntegrityError):
                    connessione.execute(sql)
                connessione.rollback()
        connessione.execute("UPDATE partecipanti SET gruppo_domenica = 20 WHERE id = 101")
        connessione.execute("UPDATE iscrizioni SET sottogruppo_mattino = 'A' WHERE id = 1")
        connessione.commit()
        self.migra("downgrade", REVISIONE_PRECEDENTE)
        self.assertEqual(dati_precedenti(), prima)
        self.assertEqual(foreign_key(), foreign_key_precedenti)
        for tabella in tabelle:
            self.assertEqual([r[1] for r in connessione.execute(f"PRAGMA table_info({tabella})")],
                             colonne[tabella])
        self.assertEqual(connessione.execute("PRAGMA foreign_key_check").fetchall(), [])
        # Verifica anche che il downgrade permetta un nuovo upgrade.
        self.migra("upgrade", "head")
        self.assertEqual(dati_precedenti(), prima)


if __name__ == "__main__":
    unittest.main()
