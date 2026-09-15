import os
import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch

os.environ["DB_TYPE"] = "sqlite"
os.environ["DB_NAME"] = ":memory:"
os.environ["SECRET_KEY"] = "test-secret-key"

from werkzeug.security import generate_password_hash
from app import app, db, Partecipante, Iscrizione, Laboratorio, SysOption, User, stato_iscrizione


class FlussoFlagPartecipantiTestCase(unittest.TestCase):
    def setUp(self):
        app.config.update(TESTING=True)
        self.context = app.app_context()
        self.context.push()
        db.create_all()
        db.session.add_all([
            Partecipante(id=1, nome="Mario", cognome="Rossi", deve_iscriversi_sabato=False),
            Laboratorio(id=1, id_lab="M1", titolo="Bosco", descrizione="", posti=5, tipologia="mattino"),
            Laboratorio(id=2, id_lab="P1", titolo="Sentieri", descrizione="", posti=5, tipologia="pomeriggio"),
            SysOption(key="stato_iscrizioni", value="aperte"),
            User(username="admin", password=generate_password_hash("password")),
        ])
        db.session.commit()
        self.client = app.test_client()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.context.pop()

    def conferma(self):
        self.assertEqual(self.client.post("/verifica_iscrizione", json={"codice_socio": 1}).status_code, 200)
        return self.client.post("/conferma_identita")

    def imposta(self, **campi):
        persona = db.session.get(Partecipante, 1)
        for campo, valore in campi.items():
            setattr(persona, campo, valore)
        db.session.commit()

    def vecchia_iscrizione(self, completa=False):
        db.session.add(Iscrizione(
            id=1, partecipante=1, scelta_mattino=1,
            scelta_pomeriggio=2 if completa else None,
            sottogruppo_mattino="A", sottogruppo_pomeriggio="B",
            data=datetime(2026, 8, 20, 12, 30),
        ))
        db.session.commit()

    def stato_db(self):
        db.session.expire_all()
        return {modello.__tablename__: [tuple(getattr(riga, c.name) for c in modello.__table__.columns)
                for riga in modello.query.order_by(modello.id)]
                for modello in (Partecipante, Iscrizione, Laboratorio)}

    def sezione_sabato(self, pagina, fascia):
        fascia = "mattina" if fascia == "mattino" else fascia
        return pagina.split(f'<h2 class="h4">Sabato {fascia}</h2>', 1)[1].split('</section>', 1)[0]

    def test_riepilogo_ab_associati_alla_fascia_senza_scritture(self):
        self.imposta(deve_iscriversi_sabato=True)
        self.vecchia_iscrizione(completa=True)
        self.conferma()
        for stato in ("aperte", "chiuse"):
            with self.subTest(stato=stato):
                db.session.get(SysOption, "stato_iscrizioni").value = stato
                db.session.commit()
                prima = self.stato_db()
                with patch("app.ricalcola_sottogruppi_ab", side_effect=AssertionError("non ricalcolare")), \
                     patch.object(db.session, "commit", side_effect=AssertionError("non scrivere")):
                    risposta = self.client.get("/iscrizione/riepilogo")
                self.assertEqual(risposta.status_code, 200)
                pagina = risposta.get_data(as_text=True)
                mattino = self.sezione_sabato(pagina, "mattino")
                pomeriggio = self.sezione_sabato(pagina, "pomeriggio")
                self.assertIn("M1", mattino)
                self.assertIn("Bosco", mattino)
                self.assertIn("Gruppo A", mattino)
                self.assertNotIn("Gruppo B", mattino)
                self.assertIn("P1", pomeriggio)
                self.assertIn("Sentieri", pomeriggio)
                self.assertIn("Gruppo B", pomeriggio)
                self.assertNotIn("Gruppo A", pomeriggio)
                self.assertEqual(self.stato_db(), prima)

    def test_riepilogo_ab_non_ancora_assegnato_per_ogni_fascia(self):
        self.imposta(deve_iscriversi_sabato=True)
        self.vecchia_iscrizione(completa=True)
        i = db.session.get(Iscrizione, 1)
        i.sottogruppo_mattino = i.sottogruppo_pomeriggio = None
        db.session.commit()
        self.conferma()
        pagina = self.client.get("/iscrizione/riepilogo").get_data(as_text=True)
        for fascia in ("mattino", "pomeriggio"):
            self.assertIn("Gruppo Non ancora assegnato", self.sezione_sabato(pagina, fascia))

    def test_riepilogo_ab_assente_senza_scelta_o_partecipazione(self):
        self.imposta(deve_iscriversi_sabato=True)
        self.vecchia_iscrizione(completa=True)
        db.session.get(SysOption, "stato_iscrizioni").value = "chiuse"
        db.session.commit()
        self.conferma()
        for fascia in ("mattino", "pomeriggio"):
            for rinuncia in (True, False):
                with self.subTest(fascia=fascia, rinuncia=rinuncia):
                    i = db.session.get(Iscrizione, 1)
                    i.scelta_mattino, i.scelta_pomeriggio = 1, 2
                    i.non_partecipa_mattino = i.non_partecipa_pomeriggio = False
                    setattr(i, "scelta_" + fascia, None)
                    setattr(i, "non_partecipa_" + fascia, rinuncia)
                    db.session.commit()
                    pagina = self.client.get("/iscrizione/riepilogo").get_data(as_text=True)
                    sezione = self.sezione_sabato(pagina, fascia)
                    self.assertIn("Non partecipa" if rinuncia else "Nessun laboratorio salvato", sezione)
                    self.assertNotIn("Gruppo", sezione)
                    altra = "pomeriggio" if fascia == "mattino" else "mattino"
                    self.assertIn("Gruppo", self.sezione_sabato(pagina, altra))
        i = db.session.get(Iscrizione, 1)
        i.scelta_mattino, i.scelta_pomeriggio = 1, 2
        i.non_partecipa_mattino = i.non_partecipa_pomeriggio = False
        db.session.commit()
        self.imposta(deve_iscriversi_sabato=False)
        pagina = self.client.get("/iscrizione/riepilogo").get_data(as_text=True)
        self.assertIn("Iscrizione ai laboratori del sabato: non richiesta", pagina)
        self.assertNotIn("Gruppo A", pagina)
        self.assertNotIn("Gruppo B", pagina)
        self.assertNotIn("Gruppo Non ancora assegnato", pagina)

    def test_sabato_non_richiesto_aperto_e_chiuso_senza_creazione(self):
        for stato in ("aperte", "chiuse"):
            with self.subTest(stato=stato):
                db.session.get(SysOption, "stato_iscrizioni").value = stato
                db.session.commit()
                self.assertEqual(self.conferma().headers["Location"], "/iscrizione/riepilogo")
                for url in ("/iscrizione", "/laboratori", "/iscrizione/riepilogo"):
                    risposta = self.client.get(url, follow_redirects=True)
                    self.assertEqual(risposta.status_code, 200)
                    self.assertIn(b"Iscrizione ai laboratori del sabato: non richiesta", risposta.data)
                    self.assertNotIn(b"non ancora completa", risposta.data)
                    self.assertNotIn(b"Continua l'iscrizione", risposta.data)
                    self.assertNotIn(b"Modifica mattino", risposta.data)
                self.assertEqual(Iscrizione.query.count(), 0)

    def test_accessi_diretti_bloccati_con_e_senza_vecchia_iscrizione(self):
        self.imposta(includi_domenica=True, gruppo_domenica=17)
        self.conferma()
        for vecchia in (False, True):
            if vecchia:
                self.vecchia_iscrizione(completa=True)
            prima = self.stato_db()
            for fascia in ("mattino", "pomeriggio"):
                for suffisso in ("", "?modifica=1"):
                    risposta = self.client.get(f"/laboratori/{fascia}{suffisso}")
                    self.assertEqual(risposta.headers["Location"], "/iscrizione/riepilogo")
                self.assertEqual(self.client.get(f"/lista_laboratori/{fascia}").status_code, 403)
                for payload in ({"laboratorio_id": 1 if fascia == "mattino" else 2}, {"non_partecipa": True}):
                    risposta = self.client.post(f"/laboratori/{fascia}/salva", json=payload)
                    self.assertEqual(risposta.status_code, 403)
                    self.assertFalse(risposta.get_json()["ok"])
                    self.assertIn("non richiesta", risposta.get_json()["errore"])
            self.assertEqual(self.stato_db(), prima)

    def test_flag_riverificato_sotto_lock(self):
        self.conferma()
        with patch("app.get_partecipante_corrente", return_value=SimpleNamespace(id=1, deve_iscriversi_sabato=True)):
            risposta = self.client.post("/laboratori/mattino/salva", json={"laboratorio_id": 1})
        self.assertEqual(risposta.status_code, 403)
        self.assertEqual(Iscrizione.query.count(), 0)

    def test_sabato_richiesto_routing_ripresa_e_completamento(self):
        self.imposta(deve_iscriversi_sabato=True)
        self.conferma()
        self.assertEqual(self.client.get("/iscrizione").headers["Location"], "/laboratori/mattino")
        risposta = self.client.post("/laboratori/mattino/salva", json={"laboratorio_id": 1})
        self.assertEqual(risposta.status_code, 200)
        self.assertEqual(self.client.get("/iscrizione").headers["Location"], "/laboratori/pomeriggio")
        risposta = self.client.post("/laboratori/pomeriggio/salva", json={"non_partecipa": True})
        self.assertEqual(risposta.status_code, 200)
        self.assertEqual(self.client.get("/iscrizione").headers["Location"], "/iscrizione/riepilogo")
        pagina = self.client.get("/iscrizione/riepilogo").data
        self.assertIn(b"Bosco", pagina)
        self.assertIn(b"Non partecipa a nessun laboratorio", pagina)
        self.assertIn(b"Modifica mattino", pagina)

    def test_tre_stati_domenica_letti_senza_modifiche(self):
        self.vecchia_iscrizione(completa=True)
        self.conferma()
        for sabato in (False, True):
            for inclusa, gruppo, testo in (
                (False, None, "Partecipazione ai gruppi della domenica: non richiesta"),
                (False, 17, "Partecipazione ai gruppi della domenica: non richiesta"),
                (True, None, "Gruppo domenica: non ancora assegnato"),
                (True, 17, "Gruppo domenica: Sfida"),
                (True, 1, "Gruppo domenica: Avventura"),
                (True, 7, "Gruppo domenica: Gradualità"),
                (True, 20, "Gruppo domenica: Vivere"),
                (False, 1, "Partecipazione ai gruppi della domenica: non richiesta"),
                (False, 7, "Partecipazione ai gruppi della domenica: non richiesta"),
                (False, 20, "Partecipazione ai gruppi della domenica: non richiesta"),
            ):
                with self.subTest(sabato=sabato, inclusa=inclusa, gruppo=gruppo):
                    self.imposta(deve_iscriversi_sabato=sabato, includi_domenica=inclusa, gruppo_domenica=gruppo)
                    prima = self.stato_db()
                    with patch("app.calcola_gruppi_domenica", side_effect=AssertionError("non ricalcolare")):
                        risposta = self.client.get("/iscrizione/riepilogo")
                    self.assertEqual(risposta.status_code, 200)
                    self.assertIn(testo.encode(), risposta.data)
                    if not inclusa:
                        self.assertNotIn(b"Gruppo domenica:", risposta.data)
                        for nome in ("Avventura", "Gradualità", "Vivere", "Sfida"):
                            self.assertNotIn(nome.encode(), risposta.data)
                    if not sabato:
                        self.assertNotIn(b"Modifica", risposta.data)
                        self.assertNotIn("non è ancora completa".encode(), risposta.data)
                    self.assertEqual(self.stato_db(), prima)

    def test_chiuse_incompleto_richiesto_e_vecchia_iscrizione_non_richiesta(self):
        self.vecchia_iscrizione()
        db.session.get(SysOption, "stato_iscrizioni").value = "chiuse"
        db.session.commit()
        for sabato in (False, True):
            self.imposta(deve_iscriversi_sabato=sabato, includi_domenica=True, gruppo_domenica=9)
            self.conferma()
            prima = self.stato_db()
            risposta = self.client.get("/iscrizione", follow_redirects=True)
            self.assertEqual(risposta.status_code, 200)
            self.assertIn(b"Gruppo domenica: Incontro", risposta.data)
            if sabato:
                self.assertIn("L'iscrizione non è ancora completa.".encode(), risposta.data)
            else:
                self.assertIn(b"Iscrizione ai laboratori del sabato: non richiesta", risposta.data)
                self.assertNotIn("L'iscrizione non è ancora completa.".encode(), risposta.data)
            self.assertEqual(self.client.post("/laboratori/mattino/salva", json={"non_partecipa": True}).status_code, 403)
            self.assertEqual(self.stato_db(), prima)

    def test_dashboard_contatori_solo_sabato_e_non_richiesti_visibili(self):
        from flask import template_rendered
        for i in range(2, 7):
            db.session.add(Partecipante(id=i, nome=f"Nome {i}", cognome="Rossi", deve_iscriversi_sabato=i <= 4))
        db.session.commit()
        for i, completo in ((2, True), (3, False), (5, True), (6, False)):
            db.session.add(Iscrizione(partecipante=i, scelta_mattino=1, scelta_pomeriggio=2 if completo else None, data=datetime(2026, 8, 20)))
        db.session.commit()
        self.client.post("/login", data={"username": "admin", "passwd": "password"})
        contesti = []
        def acquisisci(sender, template, context, **extra):
            contesti.append(context)
        with template_rendered.connected_to(acquisisci, app):
            risposta = self.client.get("/admin/iscrizioni")
        self.assertEqual(risposta.status_code, 200)
        contesto = contesti[-1]
        self.assertEqual(contesto["totale_partecipanti"], 6)
        self.assertEqual(contesto["totale_sabato"], 3)
        for chiave in ("iscrizioni_complete", "iscrizioni_incomplete", "partecipanti_non_iniziati"):
            self.assertEqual(contesto[chiave], 1)
        self.assertAlmostEqual(contesto["percentuale_completamento"], 100 / 3)
        stati = {p.id: stato for _, p, _, _, stato in contesto["iscrizioni"]}
        self.assertEqual(stati, {1: "non_richiesta", 2: "completo", 3: "incompleto", 4: "non_iniziato", 5: "non_richiesta", 6: "non_richiesta"})
        self.assertIn(b'data-filtro-stato="non_richiesta"', risposta.data)
        self.assertIn(b"Non richiesta (3)", risposta.data)

    def test_dashboard_senza_obbligati_nessuna_divisione_per_zero(self):
        self.vecchia_iscrizione()
        self.assertEqual(stato_iscrizione(db.session.get(Iscrizione, 1), db.session.get(Partecipante, 1)), "non_richiesta")
        self.client.post("/login", data={"username": "admin", "passwd": "password"})
        risposta = self.client.get("/admin/iscrizioni")
        self.assertEqual(risposta.status_code, 200)
        self.assertIn(b"Completamento: 0,0%", risposta.data)
        self.assertNotIn(b'class="progress mb-2"', risposta.data)
