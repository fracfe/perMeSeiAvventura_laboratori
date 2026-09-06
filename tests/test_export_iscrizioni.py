import io
import os
import re
import unittest
from datetime import datetime
from unittest.mock import patch

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
            r'attachment; filename=iscrizioni_generali_\d{4}-\d{2}-\d{2}\.xlsx',
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
                "Gruppo", "Zona", "Regione", "Email",
                "Laboratorio mattino", "Gruppo A/B mattino",
                "Laboratorio pomeriggio", "Gruppo A/B pomeriggio",
            ),
        )
        righe_per_codice = {riga[0]: riga for riga in righe[1:]}
        self.assertEqual(
            righe_per_codice[101],
            (101, "Mario", "Rossi", None, None, None, None, "M01 - Bosco", "Non assegnato", "P01 - Sentieri", "Non assegnato"),
        )
        self.assertEqual(
            righe_per_codice[202],
            (202, "Anna", "Bianchi", None, None, None, None, "M01 - Bosco", "Non assegnato", "Non iscritto", "Non iscritto"),
        )
        self.assertEqual(
            righe_per_codice[303],
            (303, "Luca", "Verdi", None, None, None, None, "Non iscritto", "Non iscritto", "P01 - Sentieri", "Non assegnato"),
        )
        self.assertEqual(righe_per_codice[404][7:], ("Non iscritto", "Non iscritto", "Non iscritto", "Non iscritto"))
        self.assertEqual(righe_per_codice[505][7:], ("Non iscritto", "Non iscritto", "Non iscritto", "Non iscritto"))

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
            r'attachment; filename=iscrizioni_per_laboratorio_\d{4}-\d{2}-\d{2}\.xlsx',
        )
        self.assertEqual(
            set(workbook.sheetnames),
            {
                "Tutti i partecipanti",
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
        intestazioni = ("Codice censimento", "Nome", "Cognome", "Gruppo")
        self.assertEqual(righe_mattino[0], intestazioni)
        self.assertEqual(righe_pomeriggio[0], intestazioni)
        self.assertEqual(righe_senza_iscritti, [intestazioni])
        self.assertEqual(
            righe_mattino[1:],
            [(202, "Anna", "Bianchi", "Non assegnato"), (101, "Mario", "Rossi", "Non assegnato")],
        )
        self.assertEqual(
            righe_pomeriggio[1:],
            [(101, "Mario", "Rossi", "Non assegnato"), (303, "Luca", "Verdi", "Non assegnato")],
        )
        self.assertEqual(
            list(workbook["M - Non partecipa"].iter_rows(values_only=True)),
            [intestazioni[:3]],
        )
        self.assertEqual(
            list(workbook["P - Non partecipa"].iter_rows(values_only=True)),
            [intestazioni[:3]],
        )
        codici_esportati = {
            riga[0]
            for nome_foglio in workbook.sheetnames
            for riga in list(
                workbook[nome_foglio].iter_rows(min_row=2, values_only=True)
            )
        }
        self.assertIn(404, codici_esportati)
        self.assertIn(505, codici_esportati)

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
        self.assertEqual(len(workbook.sheetnames), 5)
        self.assertEqual(len(nomi_duplicati), 2)
        self.assertEqual(len({nome.casefold() for nome in workbook.sheetnames}), 5)
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
            (606, "Nessun", "Laboratorio", None, None, None, None, "Non partecipa", "Non partecipa", "Non partecipa", "Non partecipa"),
        )
        self.assertEqual(
            righe_per_codice[707],
            (707, "Scelta", "Mista", None, None, None, None, "M01 - Bosco", "Non assegnato", "Non partecipa", "Non partecipa"),
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

    def test_tutti_partecipanti_anagrafica_stati_ab_e_nessuna_modifica(self):
        self.crea_dati()
        persona = db.session.get(Partecipante, 101)
        persona.gruppo, persona.zona, persona.regione, persona.email = "Roma 1", "Roma", "Lazio", "mario@example.test"
        iscrizione = Iscrizione.query.filter_by(partecipante=101).one()
        iscrizione.sottogruppo_mattino, iscrizione.sottogruppo_pomeriggio = "B", "A"
        escluso = db.session.get(Partecipante, 202)
        escluso.deve_iscriversi_sabato = False
        iscrizione_escluso = Iscrizione.query.filter_by(partecipante=202).one()
        iscrizione_escluso.non_partecipa_pomeriggio = True
        iscrizione_escluso.sottogruppo_mattino = "A"
        iscrizione_escluso.sottogruppo_pomeriggio = "B"
        Iscrizione.query.filter_by(partecipante=303).one().non_partecipa_mattino = True
        Iscrizione.query.filter_by(partecipante=303).one().sottogruppo_mattino = "B"
        Iscrizione.query.filter_by(partecipante=505).one().sottogruppo_mattino = "A"
        db.session.commit()
        self.login_admin()
        def stato():
            db.session.expire_all()
            return {m.__tablename__: [tuple(getattr(r, c.name) for c in m.__table__.columns)
                    for r in m.query.order_by(m.id)] for m in (Partecipante, Iscrizione, Laboratorio)}
        prima = stato()
        for modalita, nome_foglio in (("elenco", "Iscrizioni"), ("laboratori", "Tutti i partecipanti")):
            with self.subTest(modalita=modalita), patch("app.calcola_sottogruppi_ab", side_effect=AssertionError("non ricalcolare")), patch("app.ricalcola_sottogruppi_ab", side_effect=AssertionError("non ricalcolare")):
                risposta = self.client.get(f"/admin/iscrizioni/esporta/{modalita}")
                self.assertEqual(risposta.status_code, 200)
                workbook = self.leggi_workbook(risposta)
                righe = list(workbook[nome_foglio].iter_rows(min_row=2, values_only=True))
                self.assertEqual(len(righe), 5)
                per_codice = {r[0]: r for r in righe}
                self.assertEqual(set(per_codice), {101, 202, 303, 404, 505})
                self.assertEqual(per_codice[101][3:], ("Roma 1", "Roma", "Lazio", "mario@example.test", "M01 - Bosco", "B", "P01 - Sentieri", "A"))
                self.assertEqual(per_codice[202][7:], ("Iscrizione non richiesta", "Iscrizione non richiesta", "Iscrizione non richiesta", "Iscrizione non richiesta"))
                self.assertEqual(per_codice[303][7:], ("Non partecipa", "Non partecipa", "P01 - Sentieri", "Non assegnato"))
                for codice in (404, 505):
                    self.assertEqual(per_codice[codice][7:], ("Non iscritto", "Non iscritto", "Non iscritto", "Non iscritto"))
                if modalita == "laboratori":
                    self.assertEqual(workbook.sheetnames[0], "Tutti i partecipanti")
                    mattino = list(workbook["M - M01 - Bosco"].iter_rows(min_row=2, values_only=True))
                    self.assertEqual(mattino, [(202, "Anna", "Bianchi", "A"), (101, "Mario", "Rossi", "B")])
                    self.assertEqual(list(workbook["P - P01 - Sentieri"].iter_rows(min_row=2, values_only=True)),
                                     [(101, "Mario", "Rossi", "A"), (303, "Luca", "Verdi", "Non assegnato")])
                    self.assertEqual(list(workbook["P - Non partecipa"].iter_rows(min_row=2, values_only=True)), [])
                    self.assertEqual(list(workbook["M - Non partecipa"].iter_rows(min_row=2, values_only=True)), [(303, "Luca", "Verdi")])
                self.assertEqual(stato(), prima)

    def test_export_zero_iscrizioni_con_partecipanti_e_database_vuoto(self):
        self.login_admin()
        for con_partecipanti in (False, True):
            if con_partecipanti:
                db.session.add_all([Partecipante(id=1, nome="Uno", cognome="Rossi"),
                                    Partecipante(id=2, nome="Due", cognome="Verdi", deve_iscriversi_sabato=False)])
                db.session.commit()
            for modalita, nome_foglio in (("elenco", "Iscrizioni"), ("laboratori", "Tutti i partecipanti")):
                workbook = self.leggi_workbook(self.client.get(f"/admin/iscrizioni/esporta/{modalita}"))
                righe = list(workbook[nome_foglio].iter_rows(min_row=2, values_only=True))
                self.assertEqual(len(righe), 2 if con_partecipanti else 0)
                if con_partecipanti:
                    self.assertEqual(righe[0][7:], ("Non iscritto", "Non iscritto", "Non iscritto", "Non iscritto"))
                    self.assertEqual(righe[1][7:], ("Iscrizione non richiesta", "Iscrizione non richiesta", "Iscrizione non richiesta", "Iscrizione non richiesta"))
            self.assertEqual(Iscrizione.query.count(), 0)

    def test_export_e_disponibile_dalla_navigazione_iscrizioni(self):
        self.login_admin()

        pagina = self.client.get("/admin/iscrizioni")

        posizione_gestione = pagina.data.index(b">Iscrizioni</a>")
        posizione_export = pagina.data.index(b">Esporta iscrizioni</a>")
        self.assertGreater(posizione_export, posizione_gestione)
        self.assertIn(b'href="/admin/iscrizioni/esporta"', pagina.data)


if __name__ == "__main__":
    unittest.main()
