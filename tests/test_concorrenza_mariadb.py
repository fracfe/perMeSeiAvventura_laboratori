import os
import re
import subprocess
import sys
import threading
import unittest


RUN_MARIADB_TESTS = os.environ.get("RUN_MARIADB_TESTS") == "1"

def nome_database_chiaramente_di_test(nome_database):
    return bool(
        re.search(
            r"(^|[_-])test([_-]|$)",
            nome_database.strip().lower(),
        )
    )

def destinazione_mariadb_chiaramente_di_test(backend, nome_database):
    return backend in ("mysql", "mariadb") and nome_database_chiaramente_di_test(
        nome_database
    )

if RUN_MARIADB_TESTS and (
    os.environ.get("DB_TYPE") != "mariadb"
    or not nome_database_chiaramente_di_test(os.environ.get("DB_NAME", ""))
):
    raise RuntimeError(
        "Test MariaDB rifiutati: usa DB_TYPE=mariadb e un DB_NAME "
        "chiaramente di test (per esempio pmsea_test_concorrenza)."
    )

if not RUN_MARIADB_TESTS:
    os.environ["DB_TYPE"] = "sqlite"
    os.environ["DB_NAME"] = ":memory:"
    os.environ.setdefault("SECRET_KEY", "test-secret-key")

from sqlalchemy import inspect

from app import Iscrizione, Laboratorio, Partecipante, SysOption, app, db


class ProtezioneDatabaseMariaDBTestCase(unittest.TestCase):
    def test_riconosce_solo_nomi_database_chiaramente_di_test(self):
        for nome_sicuro in (
            "test",
            "pmsea_test",
            "pmsea-test-concorrenza",
            "test_pmsea",
        ):
            with self.subTest(nome=nome_sicuro):
                self.assertTrue(nome_database_chiaramente_di_test(nome_sicuro))

        for nome_non_sicuro in (
            "",
            "app_db",
            "produzione",
            "contest",
            "testo",
        ):
            with self.subTest(nome=nome_non_sicuro):
                self.assertFalse(nome_database_chiaramente_di_test(nome_non_sicuro))

    def test_rifiuta_database_non_test_prima_di_importare_app(self):
        ambiente = os.environ.copy()
        ambiente.update(
            {
                "RUN_MARIADB_TESTS": "1",
                "DB_TYPE": "mariadb",
                "DB_NAME": "app_db",
            }
        )

        risultato = subprocess.run(
            [sys.executable, os.path.abspath(__file__)],
            env=ambiente,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertNotEqual(risultato.returncode, 0)
        self.assertIn("Test MariaDB rifiutati", risultato.stderr)

    def test_senza_flag_mariadb_forza_sqlite_in_memoria(self):
        ambiente = os.environ.copy()
        ambiente.pop("RUN_MARIADB_TESTS", None)
        ambiente.update(
            {
                "DB_TYPE": "mariadb",
                "DB_NAME": "app_db",
            }
        )
        programma = (
            "import os, runpy; "
            f"runpy.run_path({os.path.abspath(__file__)!r}, run_name='guard_probe'); "
            "print(os.environ['DB_TYPE'], os.environ['DB_NAME'])"
        )

        risultato = subprocess.run(
            [sys.executable, "-c", programma],
            env=ambiente,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(risultato.returncode, 0, risultato.stderr)
        self.assertIn("sqlite :memory:", risultato.stdout)

    def test_controlla_engine_effettivo_prima_dei_delete(self):
        self.assertTrue(
            destinazione_mariadb_chiaramente_di_test(
                "mysql",
                "pmsea_test_concorrenza",
            )
        )
        self.assertFalse(
            destinazione_mariadb_chiaramente_di_test("mysql", "app_db")
        )
        self.assertFalse(
            destinazione_mariadb_chiaramente_di_test("sqlite", "pmsea_test")
        )


@unittest.skipUnless(RUN_MARIADB_TESTS, "richiede il database MariaDB temporaneo")
class ConcorrenzaMariaDBTestCase(unittest.TestCase):
    def setUp(self):
        app.config.update(TESTING=True)
        self.app_context = app.app_context()
        self.app_context.push()
        url_database = db.engine.url
        if not destinazione_mariadb_chiaramente_di_test(
            url_database.get_backend_name(),
            url_database.database or "",
        ):
            self.app_context.pop()
            raise RuntimeError(
                "Operazioni distruttive rifiutate: l'engine non è collegato "
                "a un database MariaDB chiaramente di test."
            )
        Iscrizione.query.delete()
        Partecipante.query.delete()
        Laboratorio.query.delete()
        SysOption.query.delete()
        db.session.commit()

    def tearDown(self):
        db.session.rollback()
        Iscrizione.query.delete()
        Partecipante.query.delete()
        Laboratorio.query.delete()
        SysOption.query.delete()
        db.session.commit()
        db.session.remove()
        self.app_context.pop()

    def test_schema_nullable_e_vincolo_univoco(self):
        inspector = inspect(db.engine)
        colonne = {
            colonna["name"]: colonna
            for colonna in inspector.get_columns("iscrizioni")
        }
        vincoli_univoci = inspector.get_unique_constraints("iscrizioni")
        vincoli_check = {
            vincolo["name"]
            for vincolo in inspector.get_check_constraints("iscrizioni")
        }

        self.assertTrue(colonne["scelta_mattino"]["nullable"])
        self.assertTrue(colonne["scelta_pomeriggio"]["nullable"])
        self.assertFalse(colonne["non_partecipa_mattino"]["nullable"])
        self.assertFalse(colonne["non_partecipa_pomeriggio"]["nullable"])
        self.assertTrue(
            any(
                vincolo["name"] == "uq_iscrizioni_partecipante"
                and vincolo["column_names"] == ["partecipante"]
                for vincolo in vincoli_univoci
            )
        )
        self.assertIn(
            "ck_iscrizioni_scelta_mattino_esclusiva",
            vincoli_check,
        )
        self.assertIn(
            "ck_iscrizioni_scelta_pomeriggio_esclusiva",
            vincoli_check,
        )

    def test_due_utenti_non_ottengono_entrambi_ultimo_posto(self):
        db.session.add(SysOption(key="stato_iscrizioni", value="aperte"))
        db.session.add(
            Laboratorio(
                id=1,
                id_lab="M01",
                titolo="Ultimo posto",
                descrizione="Test concorrenza",
                posti=1,
                tipologia="mattino",
            )
        )
        db.session.add_all(
            [
                Partecipante(id=101, nome="Primo", cognome="Utente"),
                Partecipante(id=202, nome="Secondo", cognome="Utente"),
            ]
        )
        db.session.commit()

        barriera = threading.Barrier(2)
        risultati = []
        errori = []
        lock_risultati = threading.Lock()

        def conferma(partecipante_id):
            try:
                with app.test_client() as client:
                    client.post(
                        "/verifica_iscrizione",
                        json={"codice_socio": partecipante_id},
                    )
                    client.post("/conferma_identita")
                    barriera.wait(timeout=5)
                    risposta = client.post(
                        "/laboratori/mattino/salva",
                        json={"laboratorio_id": 1},
                    )
                    with lock_risultati:
                        risultati.append(risposta.status_code)
            except Exception as errore:
                with lock_risultati:
                    errori.append(errore)

        threads = [
            threading.Thread(target=conferma, args=(101,)),
            threading.Thread(target=conferma, args=(202,)),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)

        db.session.expire_all()
        self.assertEqual(errori, [])
        self.assertEqual(sorted(risultati), [200, 409])
        self.assertEqual(
            Iscrizione.query.filter_by(scelta_mattino=1).count(),
            1,
        )


if __name__ == "__main__":
    unittest.main()
