import copy
import os
import unittest
from datetime import datetime
from unittest.mock import patch

os.environ["DB_TYPE"] = "sqlite"
os.environ["DB_NAME"] = ":memory:"
os.environ["SECRET_KEY"] = "test-secret-key"

from sqlalchemy.exc import SQLAlchemyError
from werkzeug.security import generate_password_hash
from app import app, db, User, Partecipante, Laboratorio, Iscrizione, SysOption


def payload():
    return {f"lab_{fascia}": [
        {"id": "L01", "titolo": f"Titolo {fascia}", "descrizione": "Descrizione", "posti": 10}
    ] for fascia in ("mattino", "pomeriggio")}


class ImportLaboratoriTestCase(unittest.TestCase):
    def setUp(self):
        self.context = app.app_context()
        self.context.push()
        app.config.update(TESTING=True)
        db.create_all()
        db.session.add(User(username="admin", password=generate_password_hash("password")))
        db.session.commit()
        self.client = app.test_client()
        self.client.post("/login", data={"username": "admin", "passwd": "password"})

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.context.pop()

    def importa(self, dati=None):
        return self.client.post("/import_laboratori", json=payload() if dati is None else dati)

    def snapshot(self):
        return {modello.__tablename__: [
            tuple(getattr(riga, colonna.name) for colonna in modello.__table__.columns)
            for riga in modello.query.all()
        ] for modello in (Laboratorio, Partecipante, Iscrizione, SysOption)}

    def prepara_iscrizioni(self):
        self.assertEqual(self.importa().status_code, 200)
        mattino = Laboratorio.query.filter_by(tipologia="mattino").one()
        pomeriggio = Laboratorio.query.filter_by(tipologia="pomeriggio").one()
        for codice in (101, 202, 303):
            db.session.add(Partecipante(id=codice, nome="Nome", cognome="Cognome",
                                       includi_domenica=True, gruppo_domenica=7))
        db.session.commit()
        db.session.add_all([
            Iscrizione(partecipante=101, scelta_mattino=mattino.id,
                       scelta_pomeriggio=pomeriggio.id, sottogruppo_mattino="A",
                       sottogruppo_pomeriggio="B", data=datetime(2026, 8, 20, 12)),
            Iscrizione(partecipante=202, scelta_mattino=mattino.id,
                       non_partecipa_pomeriggio=True, data=datetime(2026, 8, 20, 13)),
            Iscrizione(partecipante=303, non_partecipa_mattino=True,
                       non_partecipa_pomeriggio=True, data=datetime(2026, 8, 20, 14)),
        ])
        db.session.merge(SysOption(key="ultimo_import_laboratori", value="2026-08-20T12:00:00+02:00"))
        db.session.commit()
        return mattino.id, pomeriggio.id

    def test_primo_import_e_secondo_senza_duplicazione(self):
        risposta = self.importa()
        self.assertEqual(risposta.status_code, 200)
        self.assertEqual(risposta.get_json(), {"ok": True, "inseriti": 2, "aggiornati": 0, "totale": 2})
        prima = self.snapshot()["laboratori"]
        risposta = self.importa()
        self.assertEqual(risposta.get_json(), {"ok": True, "inseriti": 0, "aggiornati": 2, "totale": 2})
        self.assertEqual(self.snapshot()["laboratori"], prima)

    def test_aggiorna_campi_preservando_pk_iscrizioni_e_partecipanti(self):
        mattino, pomeriggio = self.prepara_iscrizioni()
        prima = self.snapshot()
        dati = payload()
        dati["lab_mattino"][0].update(titolo="Nuovo titolo", descrizione="Nuova descrizione", posti=30)
        risposta = self.importa(dati)
        self.assertEqual(risposta.status_code, 200)
        laboratorio = db.session.get(Laboratorio, mattino)
        self.assertEqual((laboratorio.titolo, laboratorio.descrizione, laboratorio.posti),
                         ("Nuovo titolo", "Nuova descrizione", 30))
        self.assertEqual((laboratorio.id_lab, laboratorio.tipologia), ("L01", "mattino"))
        self.assertEqual(Laboratorio.query.filter_by(tipologia="pomeriggio").one().id, pomeriggio)
        dopo = self.snapshot()
        self.assertEqual(dopo["iscrizioni"], prima["iscrizioni"])
        self.assertEqual(dopo["partecipanti"], prima["partecipanti"])
        self.assertNotEqual(dopo["system_option"], prima["system_option"])

    def test_riduzione_fino_agli_iscritti_senza_contare_rinunce(self):
        mattino, pomeriggio = self.prepara_iscrizioni()
        dati = payload()
        dati["lab_mattino"][0]["posti"] = 2
        dati["lab_pomeriggio"][0]["posti"] = 1
        self.assertEqual(self.importa(dati).status_code, 200)
        self.assertEqual(db.session.get(Laboratorio, mattino).posti, 2)
        self.assertEqual(db.session.get(Laboratorio, pomeriggio).posti, 1)

    def test_capienza_insufficiente_blocca_tutto_prima_di_scrivere(self):
        self.prepara_iscrizioni()
        prima = self.snapshot()
        dati = payload()
        dati["lab_mattino"].insert(0, {"id": "NUOVO", "titolo": "Nuovo", "descrizione": "Nuovo", "posti": 10})
        dati["lab_mattino"][1].update(posti=1, titolo="Da non salvare")
        dati["lab_pomeriggio"][0]["titolo"] = "Da non salvare"
        with patch.object(db.session, "add", wraps=db.session.add) as aggiungi:
            risposta = self.importa(dati)
        self.assertEqual(risposta.status_code, 409)
        self.assertIn("2 iscritti", risposta.get_json()["errore"])
        aggiungi.assert_not_called()
        self.assertEqual(self.snapshot(), prima)

    def test_assenti_conservati_e_nuovi_aggiunti(self):
        self.prepara_iscrizioni()
        prima = self.snapshot()
        dati = payload()
        dati["lab_mattino"][0]["id"] = "NUOVO"
        risposta = self.importa(dati)
        self.assertEqual(risposta.get_json(), {"ok": True, "inseriti": 1, "aggiornati": 1, "totale": 2})
        dopo = self.snapshot()
        for riga in prima["laboratori"]:
            self.assertIn(riga, dopo["laboratori"])
        self.assertEqual(len(dopo["laboratori"]), 3)
        self.assertEqual(dopo["iscrizioni"], prima["iscrizioni"])

    def test_duplicati_nel_file_per_fascia_rifiutati(self):
        self.prepara_iscrizioni()
        prima = self.snapshot()
        for chiave in ("lab_mattino", "lab_pomeriggio"):
            dati = payload()
            duplicato = copy.deepcopy(dati[chiave][0])
            duplicato["id"] = " L01 "
            dati[chiave].append(duplicato)
            with self.subTest(foglio=chiave):
                risposta = self.importa(dati)
                self.assertEqual(risposta.status_code, 400)
                self.assertIn("duplicato", risposta.get_json()["errore"])
                self.assertEqual(self.snapshot(), prima)

    def test_stesso_codice_in_fasce_diverse_identifica_due_record(self):
        self.assertEqual(self.importa().status_code, 200)
        self.assertEqual(Laboratorio.query.filter_by(id_lab="L01").count(), 2)
        dati = payload()
        dati["lab_pomeriggio"][0]["titolo"] = "Solo pomeriggio"
        self.assertEqual(self.importa(dati).status_code, 200)
        self.assertEqual(Laboratorio.query.filter_by(tipologia="mattino").one().titolo, "Titolo mattino")
        self.assertEqual(Laboratorio.query.filter_by(tipologia="pomeriggio").one().titolo, "Solo pomeriggio")

    def test_duplicati_db_bloccano_senza_scegliere_record(self):
        self.prepara_iscrizioni()
        db.session.add(Laboratorio(id_lab="L01", tipologia="pomeriggio", titolo="Duplicato",
                                   descrizione="Duplicato", posti=10))
        db.session.commit()
        prima = self.snapshot()
        dati = payload()
        dati["lab_mattino"][0]["titolo"] = "Non salvare"
        risposta = self.importa(dati)
        self.assertEqual(risposta.status_code, 409)
        self.assertIn("più laboratori", risposta.get_json()["errore"])
        self.assertIn("pomeriggio", risposta.get_json()["errore"])
        self.assertEqual(self.snapshot(), prima)

    def test_duplicati_db_non_presenti_nel_file_restano_invariati(self):
        self.prepara_iscrizioni()
        for _ in range(2):
            db.session.add(Laboratorio(id_lab="ALTRO", tipologia="mattino", titolo="Duplicato",
                                       descrizione="Duplicato", posti=10))
        db.session.commit()
        prima = self.snapshot()["laboratori"]
        self.assertEqual(self.importa().status_code, 200)
        self.assertEqual(self.snapshot()["laboratori"], prima)

    def test_payload_invalido_nella_seconda_fascia_non_modifica_nulla(self):
        self.prepara_iscrizioni()
        prima = self.snapshot()
        dati = payload()
        dati["lab_mattino"][0]["titolo"] = "Non salvare"
        dati["lab_pomeriggio"][0]["posti"] = 0
        self.assertEqual(self.importa(dati).status_code, 400)
        self.assertEqual(self.snapshot(), prima)

    def test_errore_db_ripristina_inserimenti_aggiornamenti_e_timestamp(self):
        self.prepara_iscrizioni()
        prima = self.snapshot()
        dati = payload()
        dati["lab_mattino"][0]["titolo"] = "Non salvare"
        dati["lab_pomeriggio"][0]["id"] = "NUOVO"
        def errore_commit():
            db.session.flush()
            raise SQLAlchemyError("Errore dopo flush")
        with patch.object(db.session, "commit", side_effect=errore_commit):
            self.assertEqual(self.importa(dati).status_code, 500)
        self.assertEqual(self.snapshot(), prima)

    def test_pagina_mostra_nuova_semantica_e_riepilogo(self):
        pagina = self.client.get("/import_laboratori")
        self.assertEqual(pagina.status_code, 200)
        for testo in ("Import incrementale", "data.inseriti", "data.aggiornati", "data.totale",
                      "codice laboratorio duplicato nello stesso foglio", 'accept=".xlsx,.xls"'):
            self.assertIn(testo.encode(), pagina.data)


if __name__ == "__main__":
    unittest.main()
