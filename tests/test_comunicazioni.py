import io
import os
import unittest
from datetime import datetime
from unittest.mock import patch

os.environ["DB_TYPE"] = "sqlite"
os.environ["DB_NAME"] = ":memory:"
os.environ["SECRET_KEY"] = "test-secret-key"

from openpyxl import Workbook, load_workbook
from werkzeug.security import generate_password_hash

from app import (
    Iscrizione,
    Laboratorio,
    Partecipante,
    SysOption,
    User,
    app,
    db,
)
from comunicazioni_service import COLONNE_OUTPUT_COMUNICAZIONI


def crea_excel_domenica(righe, nome_foglio="Suddivisione"):
    workbook = Workbook()
    foglio = workbook.active
    foglio.title = nome_foglio
    foglio.append(
        [
            "Codice censimento",
            "Nome",
            "Cognome",
            "Email",
            "Regione",
            "Partecipo in qualità di",
            "FoCa",
            "Sesso",
            "Gruppo",
        ]
    )
    for codice, nome, cognome, email, gruppo in righe:
        foglio.append(
            [
                codice,
                nome,
                cognome,
                email,
                "Lazio",
                "Capo",
                "Sistema",
                "M",
                gruppo,
            ]
        )
    contenuto = io.BytesIO()
    workbook.save(contenuto)
    contenuto.seek(0)
    return contenuto


class ComunicazioniTestCase(unittest.TestCase):
    def setUp(self):
        app.config.update(TESTING=True)
        self.app_context = app.app_context()
        self.app_context.push()
        db.create_all()
        db.session.add(
            User(username="admin", password=generate_password_hash("password"))
        )
        db.session.commit()
        self.client = app.test_client()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    def login_admin(self):
        self.client.post("/login", data={"username": "admin", "passwd": "password"})

    def crea_dati_database(self):
        db.session.add_all(
            [
                Partecipante(id=101, nome="Mario ufficiale", cognome="Rossi"),
                Partecipante(id=202, nome="Anna ufficiale", cognome="Bianchi"),
                Partecipante(id=303, nome="Luca ufficiale", cognome="Verdi"),
                Laboratorio(
                    id=1,
                    id_lab="M01",
                    titolo="Bosco",
                    descrizione="Mattino",
                    posti=20,
                    tipologia="mattino",
                ),
                Laboratorio(
                    id=2,
                    id_lab="P01",
                    titolo="Sentieri",
                    descrizione="Pomeriggio",
                    posti=20,
                    tipologia="pomeriggio",
                ),
            ]
        )
        db.session.commit()
        db.session.add_all(
            [
                Iscrizione(
                    data=datetime(2026, 8, 25, 10, 0),
                    partecipante=101,
                    scelta_mattino=1,
                    scelta_pomeriggio=2,
                ),
                Iscrizione(
                    data=datetime(2026, 8, 25, 10, 5),
                    partecipante=202,
                    scelta_mattino=1,
                    scelta_pomeriggio=None,
                ),
            ]
        )
        db.session.commit()

    def file_valido_con_anomalie(self):
        return (
            crea_excel_domenica(
                [
                    (101, "Mario Excel", "Rossi Excel", "mario@example.test", 2),
                    (202, "Anna Excel", "Bianchi Excel", "anna@example.test", 1),
                    (999, "Fuori", "Database", "fuori@example.test", 3),
                ]
            ),
            "suddivisione_domenica.xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    def istantanea_database(self):
        return {
            modello.__tablename__: modello.query.count()
            for modello in (User, Partecipante, Laboratorio, Iscrizione, SysOption)
        }

    def test_route_protette_e_navigazione_admin(self):
        for percorso, metodo in (
            ("/admin/comunicazioni", "get"),
            ("/admin/comunicazioni/valida", "post"),
            ("/admin/comunicazioni/genera", "post"),
        ):
            with self.subTest(percorso=percorso):
                risposta = getattr(self.client, metodo)(percorso)
                self.assertEqual(risposta.status_code, 302)

        db.session.add(
            User(username="operatore", password=generate_password_hash("password"))
        )
        db.session.commit()
        self.client.post(
            "/login",
            data={"username": "operatore", "passwd": "password"},
        )
        self.assertEqual(self.client.get("/admin/comunicazioni").headers["Location"], "/")
        self.assertEqual(
            self.client.post("/admin/comunicazioni/valida").status_code,
            403,
        )
        self.assertEqual(
            self.client.post("/admin/comunicazioni/genera").status_code,
            403,
        )
        self.client.get("/logout")

        self.login_admin()
        pagina = self.client.get("/admin/comunicazioni")
        console = self.client.get("/admin/iscrizioni")
        self.assertEqual(pagina.status_code, 200)
        self.assertIn(b"Genera file comunicazioni", pagina.data)
        self.assertNotIn(b"Torna alle iscrizioni", pagina.data)
        self.assertIn(b'href="/admin/iscrizioni"', pagina.data)
        self.assertIn(b'href="/admin/comunicazioni"', console.data)
        for testo, percorso in (
            (b"Home", b'href="/"'),
            (b"Iscrizioni", b'href="/admin/iscrizioni"'),
            (b"Suddivisione gruppi", b'href="/admin/suddivisione-gruppi"'),
            (b"Genera file comunicazioni", b'href="/admin/comunicazioni"'),
            (b"Gestione dati", b'href="/admin/gestione_dati"'),
            (b"Cambia password", b'href="/admin/cambia_password"'),
            (b"Esci", b'href="/logout"'),
        ):
            with self.subTest(voce=testo):
                self.assertIn(testo, pagina.data)
                self.assertIn(percorso, pagina.data)
        self.assertEqual(
            pagina.data.count(b'aria-label="Navigazione amministrativa"'),
            1,
        )
        self.assertIn(b'aria-current="page"', pagina.data)
        self.assertIn(b'x-if="validazione"', pagina.data)
        self.assertIn(b'x-if="elaborazione"', pagina.data)

    def test_verifica_mostra_codici_non_trovati_mancanti_e_iscrizioni_incomplete(self):
        self.crea_dati_database()
        self.login_admin()

        risposta = self.client.post(
            "/admin/comunicazioni/valida",
            data={"file": self.file_valido_con_anomalie()},
        )

        self.assertEqual(risposta.status_code, 200)
        esito = risposta.get_json()
        self.assertTrue(esito["ok"])
        self.assertEqual(esito["partecipanti_esportabili"], 4)
        self.assertEqual(esito["assegnazioni_domenica"], 3)
        self.assertEqual(esito["anomalie"]["codici_excel_non_database"], [999])
        self.assertEqual(esito["anomalie"]["partecipanti_senza_domenica"], [303])
        self.assertEqual(
            esito["anomalie"]["iscrizioni_sabato_incomplete"],
            [202, 303],
        )
        self.assertEqual(esito["anomalie"]["duplicati"], [])

    def test_merge_e_output_excel_sono_corretti_e_non_modificano_database(self):
        self.crea_dati_database()
        stato_prima = self.istantanea_database()
        self.login_admin()

        risposta = self.client.post(
            "/admin/comunicazioni/genera",
            data={"file": self.file_valido_con_anomalie()},
        )

        self.assertEqual(risposta.status_code, 200)
        self.assertEqual(
            risposta.content_type,
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        self.assertEqual(risposta.headers["X-Partecipanti-Esportati"], "4")
        self.assertEqual(risposta.headers["X-Anomalie-Totali"], "4")
        workbook = load_workbook(io.BytesIO(risposta.data), read_only=True)
        self.assertEqual(workbook.sheetnames, ["Comunicazioni"])
        righe = list(workbook["Comunicazioni"].iter_rows(values_only=True))
        self.assertEqual(righe[0], COLONNE_OUTPUT_COMUNICAZIONI)
        per_codice = {riga[0]: riga for riga in righe[1:]}
        codici_unione = {101, 202, 303, 999}
        self.assertEqual(set(per_codice), codici_unione)
        self.assertEqual(len(righe) - 1, len(codici_unione))
        self.assertEqual(len(per_codice), len(codici_unione))
        self.assertEqual(
            per_codice[101],
            (
                101,
                "Mario ufficiale",
                "Rossi",
                "mario@example.test",
                "M01 — Bosco",
                "P01 — Sentieri",
                2,
            ),
        )
        self.assertEqual(
            per_codice[202],
            (
                202,
                "Anna ufficiale",
                "Bianchi",
                "anna@example.test",
                "M01 — Bosco",
                None,
                1,
            ),
        )
        self.assertEqual(
            per_codice[303],
            (303, "Luca ufficiale", "Verdi", None, None, None, None),
        )
        self.assertEqual(
            per_codice[999],
            (
                999,
                "Fuori",
                "Database",
                "fuori@example.test",
                None,
                None,
                3,
            ),
        )
        self.assertEqual(self.istantanea_database(), stato_prima)

    def test_codice_duplicato_nell_excel_blocca_validazione_e_generazione(self):
        self.crea_dati_database()
        self.login_admin()
        righe_duplicate = [
            (101, "Mario", "Rossi", "uno@example.test", 1),
            (101, "Mario", "Rossi", "due@example.test", 2),
        ]

        for percorso in (
            "/admin/comunicazioni/valida",
            "/admin/comunicazioni/genera",
        ):
            with self.subTest(percorso=percorso):
                risposta = self.client.post(
                    percorso,
                    data={
                        "file": (
                            crea_excel_domenica(righe_duplicate),
                            "duplicati.xlsx",
                        )
                    },
                )
                self.assertEqual(risposta.status_code, 400)
                esito = risposta.get_json()
                self.assertFalse(esito["ok"])
                self.assertEqual(esito["anomalie"]["duplicati"], [101])
                self.assertIn("duplicati", esito["errore"])

    def test_codice_censimento_deve_essere_intero_positivo(self):
        self.login_admin()

        for codice in ("non numerico", 0, -1):
            with self.subTest(codice=codice):
                risposta = self.client.post(
                    "/admin/comunicazioni/valida",
                    data={
                        "file": (
                            crea_excel_domenica(
                                [
                                    (
                                        codice,
                                        "Mario",
                                        "Rossi",
                                        "mario@example.test",
                                        1,
                                    )
                                ]
                            ),
                            "codice_non_valido.xlsx",
                        )
                    },
                )

                self.assertEqual(risposta.status_code, 400)
                self.assertIn(
                    "Codice censimento",
                    risposta.get_json()["errore"],
                )

    def test_file_senza_foglio_suddivisione_e_codice_vuoto_sono_rifiutati(self):
        self.crea_dati_database()
        self.login_admin()

        senza_foglio = self.client.post(
            "/admin/comunicazioni/valida",
            data={
                "file": (
                    crea_excel_domenica([(101, "Mario", "Rossi", "m@example.test", 1)], "Altro"),
                    "senza_suddivisione.xlsx",
                )
            },
        )
        self.assertEqual(senza_foglio.status_code, 400)
        self.assertIn("Suddivisione", senza_foglio.get_json()["errore"])

        codice_vuoto = self.client.post(
            "/admin/comunicazioni/valida",
            data={
                "file": (
                    crea_excel_domenica([(None, "Mario", "Rossi", "m@example.test", 1)]),
                    "codice_vuoto.xlsx",
                )
            },
        )
        self.assertEqual(codice_vuoto.status_code, 400)
        self.assertIn("Codice censimento", codice_vuoto.get_json()["errore"])

    def test_errori_interni_non_sono_mascherati_come_input_non_valido(self):
        self.login_admin()

        for percorso in (
            "/admin/comunicazioni/valida",
            "/admin/comunicazioni/genera",
        ):
            with self.subTest(percorso=percorso), patch(
                "app.carica_excel_comunicazioni",
                side_effect=RuntimeError("errore interno simulato"),
            ):
                risposta = self.client.post(percorso)
                self.assertEqual(risposta.status_code, 500)
                esito = risposta.get_json()
                self.assertFalse(esito["ok"])
                self.assertNotIn("simulato", esito["errore"])


if __name__ == "__main__":
    unittest.main()
