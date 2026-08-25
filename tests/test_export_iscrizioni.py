import io
import os
import re
import unittest
from datetime import datetime

os.environ["DB_TYPE"] = "sqlite"
os.environ["DB_NAME"] = ":memory:"
os.environ["SECRET_KEY"] = "test-secret-key"

from openpyxl import load_workbook
from werkzeug.security import generate_password_hash

from app import Iscrizione, Laboratorio, Partecipante, User, app, db


class ExportIscrizioniTestCase(unittest.TestCase):
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
        return self.client.post(
            "/login",
            data={"username": "admin", "passwd": "password"},
        )

    def crea_dati(self):
        db.session.add_all(
            [
                Partecipante(id=101, nome="Mario", cognome="Rossi"),
                Partecipante(id=202, nome="Anna", cognome="Bianchi"),
                Partecipante(id=303, nome="Luca", cognome="Verdi"),
                Partecipante(id=404, nome="Non", cognome="Iniziato"),
                Partecipante(id=505, nome="Riga", cognome="Vuota"),
                Laboratorio(
                    id=1,
                    id_lab="M01",
                    titolo="Bosco",
                    descrizione="Laboratorio del mattino",
                    posti=20,
                    tipologia="mattino",
                ),
                Laboratorio(
                    id=2,
                    id_lab="P01",
                    titolo="Sentieri",
                    descrizione="Laboratorio del pomeriggio",
                    posti=20,
                    tipologia="pomeriggio",
                ),
                Laboratorio(
                    id=3,
                    id_lab="M02",
                    titolo="Tracce",
                    descrizione="Laboratorio senza iscritti",
                    posti=20,
                    tipologia="mattino",
                ),
            ]
        )
        db.session.commit()
        db.session.add_all(
            [
                Iscrizione(
                    data=datetime(2026, 8, 20, 10, 0),
                    partecipante=101,
                    scelta_mattino=1,
                    scelta_pomeriggio=2,
                ),
                Iscrizione(
                    data=datetime(2026, 8, 20, 10, 5),
                    partecipante=202,
                    scelta_mattino=1,
                    scelta_pomeriggio=None,
                ),
                Iscrizione(
                    data=datetime(2026, 8, 20, 10, 10),
                    partecipante=303,
                    scelta_mattino=None,
                    scelta_pomeriggio=2,
                ),
                Iscrizione(
                    data=datetime(2026, 8, 20, 10, 15),
                    partecipante=505,
                    scelta_mattino=None,
                    scelta_pomeriggio=None,
                ),
            ]
        )
        db.session.commit()

    def leggi_workbook(self, risposta):
        return load_workbook(io.BytesIO(risposta.data), read_only=True)

    def leggi_righe(self, risposta):
        workbook = self.leggi_workbook(risposta)
        self.assertEqual(workbook.sheetnames, ["Iscrizioni"])
        return list(workbook["Iscrizioni"].iter_rows(values_only=True))

    def test_admin_puo_aprire_la_pagina_con_le_due_modalita(self):
        self.login_admin()

        risposta = self.client.get("/admin/iscrizioni/esporta")

        self.assertEqual(risposta.status_code, 200)
        self.assertIn(b"Esporta elenco iscrizioni", risposta.data)
        self.assertIn(b"Esporta per laboratorio", risposta.data)
        self.assertIn(b'href="/admin/iscrizioni/esporta/elenco"', risposta.data)
        self.assertIn(
            b'href="/admin/iscrizioni/esporta/laboratori"',
            risposta.data,
        )

    def test_admin_puo_scaricare_un_vero_file_xlsx(self):
        self.login_admin()

        risposta = self.client.get("/admin/iscrizioni/esporta/elenco")

        self.assertEqual(risposta.status_code, 200)
        self.assertEqual(
            risposta.content_type,
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        self.assertTrue(risposta.data.startswith(b"PK"))
        self.assertRegex(
            risposta.headers["Content-Disposition"],
            r'attachment; filename=iscrizioni_per_me_sei_avventura_\d{4}-\d{2}-\d{2}\.xlsx',
        )
        self.assertEqual(len(self.leggi_righe(risposta)), 1)

    def test_export_non_disponibile_senza_autenticazione_admin(self):
        endpoint = (
            "/admin/iscrizioni/esporta",
            "/admin/iscrizioni/esporta/elenco",
            "/admin/iscrizioni/esporta/laboratori",
        )
        for percorso in endpoint:
            with self.subTest(percorso=percorso, utente="anonimo"):
                self.assertEqual(self.client.get(percorso).status_code, 302)

        db.session.add(Partecipante(id=999, nome="Utente", cognome="Temporaneo"))
        db.session.commit()
        self.client.post("/verifica_iscrizione", json={"codice_socio": 999})

        for percorso in endpoint:
            with self.subTest(percorso=percorso, utente="partecipante"):
                partecipante = self.client.get(percorso)
                self.assertEqual(partecipante.status_code, 302)
                self.assertEqual(partecipante.headers["Location"], "/")

        self.client.get("/logout")
        db.session.add(
            User(
                username="operatore",
                password=generate_password_hash("password"),
            )
        )
        db.session.commit()
        self.client.post(
            "/login",
            data={"username": "operatore", "passwd": "password"},
        )
        for percorso in endpoint:
            with self.subTest(percorso=percorso, utente="non_admin"):
                operatore = self.client.get(percorso)
                self.assertEqual(operatore.status_code, 302)
                self.assertEqual(operatore.headers["Location"], "/")

    def test_export_contiene_intestazioni_iscrizioni_complete_e_parziali(self):
        self.crea_dati()
        self.login_admin()

        risposta = self.client.get("/admin/iscrizioni/esporta/elenco")
        righe = self.leggi_righe(risposta)

        self.assertEqual(
            righe[0],
            (
                "Codice censimento",
                "Nome",
                "Cognome",
                "Codice laboratorio mattutino",
                "Laboratorio mattutino",
                "Codice laboratorio pomeridiano",
                "Laboratorio pomeridiano",
            ),
        )
        righe_per_codice = {riga[0]: riga for riga in righe[1:]}
        self.assertEqual(
            righe_per_codice[101],
            (101, "Mario", "Rossi", "M01", "Bosco", "P01", "Sentieri"),
        )
        self.assertEqual(
            righe_per_codice[202],
            (202, "Anna", "Bianchi", "M01", "Bosco", None, None),
        )
        self.assertEqual(
            righe_per_codice[303],
            (303, "Luca", "Verdi", None, None, "P01", "Sentieri"),
        )
        self.assertNotIn(404, righe_per_codice)
        self.assertNotIn(505, righe_per_codice)

    def test_export_per_laboratorio_crea_un_foglio_per_ogni_laboratorio(self):
        self.crea_dati()
        self.login_admin()

        risposta = self.client.get("/admin/iscrizioni/esporta/laboratori")
        workbook = self.leggi_workbook(risposta)

        self.assertEqual(risposta.status_code, 200)
        self.assertEqual(
            risposta.content_type,
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        self.assertTrue(risposta.data.startswith(b"PK"))
        self.assertRegex(
            risposta.headers["Content-Disposition"],
            r'attachment; filename=iscrizioni_per_laboratorio_per_me_sei_avventura_\d{4}-\d{2}-\d{2}\.xlsx',
        )
        self.assertEqual(
            set(workbook.sheetnames),
            {
                "M - M01 - Bosco",
                "M - M02 - Tracce",
                "P - P01 - Sentieri",
                "M - Non partecipa",
                "P - Non partecipa",
            },
        )

        righe_mattino = list(
            workbook["M - M01 - Bosco"].iter_rows(values_only=True)
        )
        righe_pomeriggio = list(
            workbook["P - P01 - Sentieri"].iter_rows(values_only=True)
        )
        righe_senza_iscritti = list(
            workbook["M - M02 - Tracce"].iter_rows(values_only=True)
        )
        intestazioni = ("Codice censimento", "Nome", "Cognome")
        self.assertEqual(righe_mattino[0], intestazioni)
        self.assertEqual(righe_pomeriggio[0], intestazioni)
        self.assertEqual(righe_senza_iscritti, [intestazioni])
        self.assertEqual(
            righe_mattino[1:],
            [(202, "Anna", "Bianchi"), (101, "Mario", "Rossi")],
        )
        self.assertEqual(
            righe_pomeriggio[1:],
            [(101, "Mario", "Rossi"), (303, "Luca", "Verdi")],
        )
        self.assertEqual(
            list(workbook["M - Non partecipa"].iter_rows(values_only=True)),
            [intestazioni],
        )
        self.assertEqual(
            list(workbook["P - Non partecipa"].iter_rows(values_only=True)),
            [intestazioni],
        )
        codici_esportati = {
            riga[0]
            for nome_foglio in workbook.sheetnames
            for riga in list(
                workbook[nome_foglio].iter_rows(min_row=2, values_only=True)
            )
        }
        self.assertNotIn(404, codici_esportati)
        self.assertNotIn(505, codici_esportati)

    def test_nomi_foglio_lunghi_non_validi_e_duplicati_restano_univoci(self):
        db.session.add_all(
            [
                Laboratorio(
                    id=10,
                    id_lab="DUP",
                    titolo="Titolo/estremamente lungo che continua primo",
                    descrizione="Primo",
                    posti=10,
                    tipologia="mattino",
                ),
                Laboratorio(
                    id=11,
                    id_lab="DUP",
                    titolo="Titolo?estremamente lungo che continua secondo",
                    descrizione="Secondo",
                    posti=10,
                    tipologia="mattino",
                ),
            ]
        )
        db.session.commit()
        self.login_admin()

        risposta = self.client.get("/admin/iscrizioni/esporta/laboratori")
        workbook = self.leggi_workbook(risposta)

        nomi_duplicati = [
            nome for nome in workbook.sheetnames if nome.startswith("M - DUP")
        ]
        self.assertEqual(len(workbook.sheetnames), 4)
        self.assertEqual(len(nomi_duplicati), 2)
        self.assertEqual(len({nome.casefold() for nome in workbook.sheetnames}), 4)
        self.assertTrue(any(nome.endswith(" (2)") for nome in nomi_duplicati))
        for nome in workbook.sheetnames:
            self.assertLessEqual(len(nome), 31)
            self.assertIsNone(re.search(r"[\\/*?:\[\]]", nome))

    def test_export_rappresenta_non_partecipa_nell_elenco_e_nei_fogli(self):
        self.crea_dati()
        db.session.add_all(
            [
                Partecipante(id=606, nome="Nessun", cognome="Laboratorio"),
                Partecipante(id=707, nome="Scelta", cognome="Mista"),
            ]
        )
        db.session.commit()
        db.session.add_all(
            [
                Iscrizione(
                    data=datetime(2026, 8, 20, 11, 0),
                    partecipante=606,
                    scelta_mattino=None,
                    scelta_pomeriggio=None,
                    non_partecipa_mattino=True,
                    non_partecipa_pomeriggio=True,
                ),
                Iscrizione(
                    data=datetime(2026, 8, 20, 11, 5),
                    partecipante=707,
                    scelta_mattino=1,
                    scelta_pomeriggio=None,
                    non_partecipa_pomeriggio=True,
                ),
            ]
        )
        db.session.commit()
        self.login_admin()

        elenco = self.leggi_righe(
            self.client.get("/admin/iscrizioni/esporta/elenco")
        )
        righe_per_codice = {riga[0]: riga for riga in elenco[1:]}
        self.assertEqual(
            righe_per_codice[606],
            (606, "Nessun", "Laboratorio", None, "Non partecipa", None, "Non partecipa"),
        )
        self.assertEqual(
            righe_per_codice[707],
            (707, "Scelta", "Mista", "M01", "Bosco", None, "Non partecipa"),
        )

        workbook = self.leggi_workbook(
            self.client.get("/admin/iscrizioni/esporta/laboratori")
        )
        mattino_non_partecipa = list(
            workbook["M - Non partecipa"].iter_rows(min_row=2, values_only=True)
        )
        pomeriggio_non_partecipa = list(
            workbook["P - Non partecipa"].iter_rows(min_row=2, values_only=True)
        )
        self.assertEqual(mattino_non_partecipa, [(606, "Nessun", "Laboratorio")])
        self.assertEqual(
            pomeriggio_non_partecipa,
            [(606, "Nessun", "Laboratorio"), (707, "Scelta", "Mista")],
        )

    def test_export_e_disponibile_dalla_navigazione_iscrizioni(self):
        self.login_admin()

        pagina = self.client.get("/admin/iscrizioni")

        posizione_gestione = pagina.data.index(b">Iscrizioni</a>")
        posizione_export = pagina.data.index(b">Esporta iscrizioni</a>")
        self.assertGreater(posizione_export, posizione_gestione)
        self.assertIn(b'href="/admin/iscrizioni/esporta"', pagina.data)


if __name__ == "__main__":
    unittest.main()
