import copy
import os
import unittest
from datetime import datetime
from unittest.mock import patch

os.environ["DB_TYPE"] = "sqlite"
os.environ["DB_NAME"] = ":memory:"
os.environ["SECRET_KEY"] = "test-secret-key"

from werkzeug.security import check_password_hash, generate_password_hash
from sqlalchemy.exc import SQLAlchemyError

from app import (
    Iscrizione,
    Laboratorio,
    Partecipante,
    SysOption,
    User,
    app,
    db,
)


class FlussoIscrizioniTestCase(unittest.TestCase):
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

    def imposta_stato(self, stato="aperte", messaggio=""):
        db.session.merge(SysOption(key="stato_iscrizioni", value=stato))
        db.session.merge(SysOption(key="messaggio_iscrizioni", value=messaggio))
        db.session.commit()

    def crea_partecipante(self, partecipante_id=123, nome="Mario", cognome="Rossi"):
        partecipante = Partecipante(
            id=partecipante_id,
            nome=nome,
            cognome=cognome,
        )
        db.session.add(partecipante)
        db.session.commit()
        return partecipante

    def crea_laboratori(self, posti=2):
        laboratori = [
            Laboratorio(id=1, id_lab="M01", titolo="Bosco", descrizione="Mattino uno", posti=posti, tipologia="mattino"),
            Laboratorio(id=2, id_lab="P01", titolo="Sentieri", descrizione="Pomeriggio uno", posti=posti, tipologia="pomeriggio"),
            Laboratorio(id=3, id_lab="M02", titolo="Tracce", descrizione="Mattino due", posti=posti, tipologia="mattino"),
            Laboratorio(id=4, id_lab="P02", titolo="Avventura", descrizione="Pomeriggio due", posti=posti, tipologia="pomeriggio"),
        ]
        db.session.add_all(laboratori)
        db.session.commit()
        return laboratori

    def crea_iscrizione(self, partecipante_id=123, mattino=1, pomeriggio=2):
        iscrizione = Iscrizione(
            data=datetime(2026, 8, 20, 20, 45),
            partecipante=partecipante_id,
            scelta_mattino=mattino,
            scelta_pomeriggio=pomeriggio,
        )
        db.session.add(iscrizione)
        db.session.commit()
        return iscrizione

    def verifica(self, codice=123, conferma=True):
        risposta = self.client.post(
            "/verifica_iscrizione",
            json={"codice_socio": codice},
        )
        if risposta.status_code == 200 and conferma:
            self.client.post("/conferma_identita")
        return risposta

    def salva(self, tipologia, laboratorio_id):
        return self.client.post(
            f"/laboratori/{tipologia}/salva",
            json={"laboratorio_id": laboratorio_id},
        )

    def login_admin(self, password="password"):
        return self.client.post(
            "/login",
            data={"username": "admin", "passwd": password},
        )

    def payload_partecipanti(self):
        return [
            {"id": 101, "nome": "Mario", "cognome": "Rossi"},
            {"id": 202, "nome": "Anna", "cognome": "Bianchi"},
        ]

    def payload_laboratori(self):
        return {
            "lab_mattino": [
                {
                    "id": "NM01",
                    "titolo": "Nuovo mattino",
                    "descrizione": "Descrizione mattino",
                    "posti": 20,
                }
            ],
            "lab_pomeriggio": [
                {
                    "id": "NP01",
                    "titolo": "Nuovo pomeriggio",
                    "descrizione": "Descrizione pomeriggio",
                    "posti": 20,
                }
            ],
        }

    def prepara_partecipante(self, stato="aperte"):
        self.imposta_stato(stato)
        self.crea_partecipante()
        self.crea_laboratori()
        self.verifica()

    def test_codice_valido_e_conferma_identita(self):
        self.crea_partecipante()

        risposta = self.verifica(conferma=False)
        homepage = self.client.get("/")
        prima_della_conferma = self.client.get("/iscrizione")
        conferma = self.client.post("/conferma_identita")

        self.assertEqual(risposta.status_code, 200)
        self.assertEqual(risposta.get_json()["nome"], "Mario")
        self.assertIn(b"S\xc3\xac, sono io", homepage.data)
        self.assertIn(b"Cambia codice", homepage.data)
        self.assertEqual(prima_della_conferma.headers["Location"], "/")
        self.assertEqual(conferma.headers["Location"], "/iscrizione")

    def test_stato_default_e_messaggio_generale(self):
        homepage_chiusa = self.client.get("/")
        self.assertIn(b"Iscrizioni chiuse", homepage_chiusa.data)

        self.login_admin()
        self.client.post(
            "/admin/stato_iscrizioni",
            data={
                "stato": "aperte",
                "messaggio_iscrizioni": "Le iscrizioni chiuderanno domenica.",
            },
        )
        homepage_aperta = self.client.get("/")

        self.assertIn(b"Iscrizioni aperte", homepage_aperta.data)
        self.assertIn(b"Le iscrizioni chiuderanno domenica.", homepage_aperta.data)

    def test_codice_non_valido_elimina_sessione_temporanea_precedente(self):
        self.crea_partecipante()
        self.verifica()

        risposta = self.verifica(999)

        self.assertEqual(risposta.status_code, 404)
        with self.client.session_transaction() as sessione:
            self.assertNotIn("_user_id", sessione)
            self.assertNotIn("temp_user", sessione)
            self.assertNotIn("identita_confermata", sessione)

    def test_chiuse_impediscono_nuova_scelta_ma_permettono_consultazione(self):
        self.prepara_partecipante(stato="chiuse")

        percorso = self.client.get("/iscrizione")
        riepilogo = self.client.get("/iscrizione/riepilogo")
        salvataggio = self.salva("mattino", 1)

        self.assertEqual(percorso.headers["Location"], "/iscrizione/riepilogo")
        self.assertIn(b"Non risulta ancora alcuna iscrizione", riepilogo.data)
        self.assertEqual(salvataggio.status_code, 403)

    def test_iscrizione_salvata_consultabile_quando_chiuse(self):
        self.prepara_partecipante(stato="chiuse")
        self.crea_iscrizione()

        riepilogo = self.client.get("/iscrizione/riepilogo")

        self.assertIn(b"Bosco", riepilogo.data)
        self.assertIn(b"Sentieri", riepilogo.data)
        self.assertNotIn(b"Modifica mattino", riepilogo.data)

    def test_prima_scelta_mattino_crea_riga_incompleta(self):
        self.prepara_partecipante()

        risposta = self.salva("mattino", 1)
        iscrizione = Iscrizione.query.filter_by(partecipante=123).one()

        self.assertEqual(risposta.status_code, 200)
        self.assertEqual(iscrizione.scelta_mattino, 1)
        self.assertIsNone(iscrizione.scelta_pomeriggio)
        self.assertEqual(risposta.get_json()["redirect"], "/laboratori/pomeriggio")

    def test_mattino_pieno_e_tipologia_errata_sono_rifiutati(self):
        self.imposta_stato()
        self.crea_laboratori(posti=1)
        self.crea_partecipante(111, "Primo", "Utente")
        self.crea_iscrizione(111, mattino=1, pomeriggio=None)
        self.crea_partecipante()
        self.verifica()

        pieno = self.salva("mattino", 1)
        tipologia_errata = self.salva("mattino", 2)

        self.assertEqual(pieno.status_code, 409)
        self.assertIn("appena riempito", pieno.get_json()["errore"])
        self.assertEqual(tipologia_errata.status_code, 400)
        self.assertIsNone(Iscrizione.query.filter_by(partecipante=123).first())

    def test_doppio_invio_mattino_non_crea_doppia_iscrizione(self):
        self.prepara_partecipante()

        prima = self.salva("mattino", 1)
        seconda = self.salva("mattino", 1)

        self.assertEqual(prima.status_code, 200)
        self.assertEqual(seconda.status_code, 200)
        self.assertEqual(Iscrizione.query.filter_by(partecipante=123).count(), 1)

    def test_pomeriggio_completa_la_stessa_riga(self):
        self.prepara_partecipante()
        self.salva("mattino", 1)

        risposta = self.salva("pomeriggio", 2)
        iscrizione = Iscrizione.query.filter_by(partecipante=123).one()

        self.assertEqual(risposta.status_code, 200)
        self.assertEqual(iscrizione.scelta_pomeriggio, 2)
        self.assertEqual(Iscrizione.query.filter_by(partecipante=123).count(), 1)
        self.assertEqual(risposta.get_json()["redirect"], "/iscrizione/riepilogo")

    def test_pomeriggio_senza_mattino_pieno_o_di_tipo_errato_e_rifiutato(self):
        self.prepara_partecipante()

        senza_mattino = self.salva("pomeriggio", 2)
        tipo_errato = self.salva("pomeriggio", 1)

        self.assertEqual(senza_mattino.status_code, 409)
        self.assertEqual(tipo_errato.status_code, 409)

        self.salva("mattino", 1)
        self.crea_partecipante(456, "Anna", "Bianchi")
        self.crea_iscrizione(456, mattino=3, pomeriggio=2)
        db.session.get(Laboratorio, 2).posti = 1
        db.session.commit()
        pieno = self.salva("pomeriggio", 2)
        tipo_errato = self.salva("pomeriggio", 1)

        self.assertEqual(pieno.status_code, 409)
        self.assertEqual(tipo_errato.status_code, 400)

    def test_router_riprende_dal_pomeriggio_e_completo_va_al_riepilogo(self):
        self.prepara_partecipante()
        self.salva("mattino", 1)

        dopo_mattino = self.client.get("/iscrizione")
        self.salva("pomeriggio", 2)
        dopo_completamento = self.client.get("/iscrizione")
        riepilogo = self.client.get("/iscrizione/riepilogo")

        self.assertEqual(dopo_mattino.headers["Location"], "/laboratori/pomeriggio")
        self.assertEqual(dopo_completamento.headers["Location"], "/iscrizione/riepilogo")
        self.assertIn(b"Hai completato l'iscrizione", riepilogo.data)
        self.assertIn(b"Bosco", riepilogo.data)
        self.assertIn(b"Sentieri", riepilogo.data)

    def test_nuovo_login_di_partecipante_completo_porta_al_riepilogo(self):
        self.imposta_stato()
        self.crea_laboratori()
        self.crea_partecipante()
        self.crea_iscrizione()
        self.verifica()

        risposta = self.client.get("/iscrizione")

        self.assertEqual(risposta.headers["Location"], "/iscrizione/riepilogo")

    def test_riepilogo_torna_alla_home_e_non_cambia_partecipante(self):
        self.imposta_stato()
        self.crea_laboratori()
        self.crea_partecipante()
        self.crea_iscrizione()
        self.verifica()

        riepilogo = self.client.get("/iscrizione/riepilogo")

        self.assertNotIn(b"Cambia partecipante", riepilogo.data)
        self.assertIn(b"Torna alla homepage", riepilogo.data)
        self.assertIn(b'href="/"', riepilogo.data)

    def test_pagine_principali_hanno_collegamento_home(self):
        login = self.client.get("/login")

        self.imposta_stato()
        self.crea_laboratori()
        self.crea_partecipante()
        self.crea_iscrizione()
        self.verifica()
        laboratori = self.client.get("/laboratori/mattino?modifica=1")
        riepilogo = self.client.get("/iscrizione/riepilogo")

        self.client.get("/logout")
        self.login_admin()
        area_admin = self.client.get("/admin/stato_iscrizioni")

        for pagina in (login, laboratori, riepilogo, area_admin):
            self.assertEqual(pagina.status_code, 200)
            self.assertIn(b">Home</a>", pagina.data)
            self.assertIn(b'href="/"', pagina.data)

    def test_modifica_mattino_e_pomeriggio_riuscita(self):
        self.imposta_stato()
        self.crea_laboratori()
        self.crea_partecipante()
        self.crea_iscrizione()
        self.verifica()

        mattino = self.salva("mattino", 3)
        pomeriggio = self.salva("pomeriggio", 4)
        iscrizione = Iscrizione.query.filter_by(partecipante=123).one()

        self.assertEqual(mattino.status_code, 200)
        self.assertEqual(pomeriggio.status_code, 200)
        self.assertEqual(iscrizione.scelta_mattino, 3)
        self.assertEqual(iscrizione.scelta_pomeriggio, 4)

    def test_modifica_verso_pieno_lascia_vecchia_scelta(self):
        self.imposta_stato()
        self.crea_laboratori(posti=1)
        self.crea_partecipante()
        self.crea_iscrizione()
        self.crea_partecipante(456, "Anna", "Bianchi")
        self.crea_iscrizione(456, mattino=3, pomeriggio=4)
        self.verifica()

        risposta = self.salva("mattino", 3)
        iscrizione = Iscrizione.query.filter_by(partecipante=123).one()

        self.assertEqual(risposta.status_code, 409)
        self.assertEqual(iscrizione.scelta_mattino, 1)

    def test_laboratorio_posseduto_pieno_puo_essere_mantenuto(self):
        self.imposta_stato()
        self.crea_laboratori(posti=1)
        self.crea_partecipante()
        self.crea_iscrizione()
        self.verifica()

        lista = self.client.get("/lista_laboratori/mattino").get_json()
        posseduto = next(item for item in lista["laboratori"] if item["id"] == 1)
        risposta = self.salva("mattino", 1)

        self.assertTrue(posseduto["posseduto"])
        self.assertTrue(posseduto["selezionabile"])
        self.assertEqual(posseduto["posti_disponibili"], 0)
        self.assertEqual(risposta.status_code, 200)

    def test_payload_non_valido_restituisce_errore_coerente(self):
        self.prepara_partecipante()

        mancante = self.client.post("/laboratori/mattino/salva", json={})
        inesistente = self.salva("mattino", 999)

        self.assertEqual(mancante.status_code, 400)
        self.assertEqual(inesistente.status_code, 400)
        self.assertIn("errore", mancante.get_json())

    def test_sessione_scaduta_restituisce_errore_coerente(self):
        self.imposta_stato()

        risposta = self.salva("mattino", 1)

        self.assertEqual(risposta.status_code, 401)
        self.assertEqual(risposta.get_json()["errore"], "Sessione scaduta.")

    def test_template_mobile_polling_e_doppio_invio(self):
        self.prepara_partecipante()

        pagina = self.client.get("/laboratori/mattino")

        self.assertIn(b"card shadow-sm", pagina.data)
        self.assertIn(b"8000", pagina.data)
        self.assertIn("Salvataggio in corso…".encode(), pagina.data)
        self.assertIn(b":disabled=\"!scelta || salvataggio\"", pagina.data)

    def test_dashboard_conta_completi_incompleti_e_non_iniziati(self):
        self.crea_laboratori()
        self.crea_partecipante(111, "Completo", "Uno")
        self.crea_iscrizione(111, mattino=1, pomeriggio=2)
        self.crea_partecipante(222, "Incompleto", "Due")
        self.crea_iscrizione(222, mattino=3, pomeriggio=None)
        self.crea_partecipante(333, "Non", "Iniziato")
        self.crea_partecipante(444, "Solo", "Pomeriggio")
        self.crea_iscrizione(444, mattino=None, pomeriggio=4)
        self.login_admin()

        pagina = self.client.get("/admin/iscrizioni")

        self.assertIn(b'id="totale-partecipanti">4</div>', pagina.data)
        self.assertIn(b'id="iscrizioni-complete">1</div>', pagina.data)
        self.assertIn(b'id="iscrizioni-incomplete">2</div>', pagina.data)
        self.assertIn(b'id="partecipanti-non-iniziati">1</div>', pagina.data)
        self.assertIn(b"25,0%", pagina.data)
        self.assertIn(b"Non scelto", pagina.data)
        self.assertIn(b"Ultimo aggiornamento", pagina.data)
        self.assertNotIn(b"<th>Data</th>", pagina.data)

    def test_reimport_laboratori_bloccato_se_esistono_iscrizioni(self):
        self.crea_laboratori()
        self.crea_partecipante()
        self.crea_iscrizione(mattino=1, pomeriggio=None)
        self.login_admin()

        risposta = self.client.post(
            "/import_laboratori",
            json=self.payload_laboratori(),
        )

        self.assertEqual(risposta.status_code, 409)
        self.assertIn("esistono già", risposta.get_json()["errore"])
        self.assertEqual(Laboratorio.query.count(), 4)

    def test_import_partecipanti_rifiuta_payload_e_campi_non_validi(self):
        self.login_admin()

        risposta_json_invalido = self.client.post(
            "/import_iscritti",
            data="{",
            content_type="application/json",
        )
        self.assertEqual(risposta_json_invalido.status_code, 400)
        self.assertIn("errore", risposta_json_invalido.get_json())

        casi_non_validi = [
            ("payload non lista", {"id": 1}, "lista"),
            ("lista vuota", [], "almeno un partecipante"),
            ("record non oggetto", ["record"], "riga 1"),
            (
                "codice mancante",
                [{"nome": "Mario", "cognome": "Rossi"}],
                'campo "id"',
            ),
            (
                "codice stringa",
                [{"id": "101", "nome": "Mario", "cognome": "Rossi"}],
                "codice censimento",
            ),
            (
                "codice decimale",
                [{"id": 101.5, "nome": "Mario", "cognome": "Rossi"}],
                "codice censimento",
            ),
            (
                "codice booleano",
                [{"id": True, "nome": "Mario", "cognome": "Rossi"}],
                "codice censimento",
            ),
            (
                "codice zero",
                [{"id": 0, "nome": "Mario", "cognome": "Rossi"}],
                "codice censimento",
            ),
            (
                "codice negativo",
                [{"id": -1, "nome": "Mario", "cognome": "Rossi"}],
                "codice censimento",
            ),
            (
                "codice duplicato",
                [
                    {"id": 101, "nome": "Mario", "cognome": "Rossi"},
                    {"id": 101, "nome": "Anna", "cognome": "Bianchi"},
                ],
                "duplicato",
            ),
            (
                "nome mancante",
                [{"id": 101, "cognome": "Rossi"}],
                'campo "nome"',
            ),
            (
                "nome vuoto",
                [{"id": 101, "nome": "  ", "cognome": "Rossi"}],
                "nome",
            ),
            (
                "cognome mancante",
                [{"id": 101, "nome": "Mario"}],
                'campo "cognome"',
            ),
            (
                "cognome vuoto",
                [{"id": 101, "nome": "Mario", "cognome": "  "}],
                "cognome",
            ),
            (
                "nome troppo lungo",
                [{"id": 101, "nome": "N" * 256, "cognome": "Rossi"}],
                "255",
            ),
            (
                "cognome troppo lungo",
                [{"id": 101, "nome": "Mario", "cognome": "C" * 256}],
                "255",
            ),
        ]

        for nome_caso, payload, messaggio in casi_non_validi:
            with self.subTest(caso=nome_caso):
                risposta = self.client.post("/import_iscritti", json=payload)
                self.assertEqual(risposta.status_code, 400)
                self.assertFalse(risposta.get_json()["ok"])
                self.assertIn(messaggio, risposta.get_json()["errore"])

        self.assertEqual(Partecipante.query.count(), 0)
        self.assertIsNone(
            db.session.get(SysOption, "ultimo_import_partecipanti")
        )

    def test_import_partecipanti_invalido_non_effettua_import_parziale(self):
        self.login_admin()
        valore_timestamp = "2026-08-20T12:00:00+02:00"
        db.session.add(
            SysOption(
                key="ultimo_import_partecipanti",
                value=valore_timestamp,
            )
        )
        db.session.commit()

        risposta = self.client.post(
            "/import_iscritti",
            json=[
                {"id": 101, "nome": "Valido", "cognome": "Uno"},
                {"id": 202, "nome": "", "cognome": "Non valido"},
                {"id": 303, "nome": "Valido", "cognome": "Tre"},
            ],
        )

        self.assertEqual(risposta.status_code, 400)
        self.assertEqual(Partecipante.query.count(), 0)
        self.assertEqual(
            db.session.get(SysOption, "ultimo_import_partecipanti").value,
            valore_timestamp,
        )

    def test_import_partecipanti_valido_aggiorna_timestamp_e_non_sovrascrive(self):
        self.crea_partecipante(101, "Nome esistente", "Cognome esistente")
        self.login_admin()

        risposta = self.client.post(
            "/import_iscritti",
            json=[
                {"id": 101, "nome": "Nome nuovo", "cognome": "Cognome nuovo"},
                {"id": 202, "nome": "  Anna ", "cognome": " Bianchi  "},
            ],
        )

        self.assertEqual(risposta.status_code, 200)
        self.assertEqual(Partecipante.query.count(), 2)
        self.assertEqual(db.session.get(Partecipante, 101).nome, "Nome esistente")
        self.assertEqual(db.session.get(Partecipante, 202).nome, "Anna")
        self.assertEqual(db.session.get(Partecipante, 202).cognome, "Bianchi")
        self.assertIsNotNone(
            db.session.get(SysOption, "ultimo_import_partecipanti")
        )

    def test_import_partecipanti_ignora_e_non_persiste_campi_extra(self):
        self.login_admin()

        risposta = self.client.post(
            "/import_iscritti",
            json=[
                {
                    "id": 303,
                    "nome": "Mario",
                    "cognome": "Rossi",
                    "Email": "dato-non-necessario@example.test",
                    "Cell": "+390000000000",
                    "Gruppo": "Dato non necessario",
                }
            ],
        )

        self.assertEqual(risposta.status_code, 200)
        partecipante = db.session.get(Partecipante, 303)
        self.assertEqual(partecipante.nome, "Mario")
        self.assertEqual(partecipante.cognome, "Rossi")
        self.assertFalse(hasattr(partecipante, "Email"))
        self.assertFalse(hasattr(partecipante, "Cell"))
        self.assertFalse(hasattr(partecipante, "Gruppo"))
        self.assertEqual(
            set(Partecipante.__table__.columns.keys()),
            {"id", "nome", "cognome"},
        )

    def test_import_partecipanti_errore_database_esegue_rollback(self):
        self.login_admin()
        valore_timestamp = "2026-08-20T12:00:00+02:00"
        db.session.add(
            SysOption(
                key="ultimo_import_partecipanti",
                value=valore_timestamp,
            )
        )
        db.session.commit()

        with patch.object(
            db.session,
            "commit",
            side_effect=SQLAlchemyError("errore simulato"),
        ):
            risposta = self.client.post(
                "/import_iscritti",
                json=self.payload_partecipanti(),
            )

        self.assertEqual(risposta.status_code, 500)
        self.assertIn("errore", risposta.get_json())
        self.assertEqual(Partecipante.query.count(), 0)
        self.assertEqual(
            db.session.get(SysOption, "ultimo_import_partecipanti").value,
            valore_timestamp,
        )

    def test_import_laboratori_rifiuta_strutture_e_righe_non_valide(self):
        self.crea_laboratori()
        self.login_admin()
        valore_timestamp = "2026-08-20T12:00:00+02:00"
        db.session.add(
            SysOption(
                key="ultimo_import_laboratori",
                value=valore_timestamp,
            )
        )
        db.session.commit()

        risposta_json_invalido = self.client.post(
            "/import_laboratori",
            data="{",
            content_type="application/json",
        )
        self.assertEqual(risposta_json_invalido.status_code, 400)

        payload_base = self.payload_laboratori()
        payload_senza_mattino = {"lab_pomeriggio": payload_base["lab_pomeriggio"]}
        payload_senza_pomeriggio = {"lab_mattino": payload_base["lab_mattino"]}
        payload_mattino_vuoto = copy.deepcopy(payload_base)
        payload_mattino_vuoto["lab_mattino"] = []
        payload_pomeriggio_vuoto = copy.deepcopy(payload_base)
        payload_pomeriggio_vuoto["lab_pomeriggio"] = []
        payload_mattino_non_lista = copy.deepcopy(payload_base)
        payload_mattino_non_lista["lab_mattino"] = {}

        casi_non_validi = [
            ("payload non oggetto", [], "payload"),
            ("manca mattino", payload_senza_mattino, "lab_mattino"),
            ("manca pomeriggio", payload_senza_pomeriggio, "lab_pomeriggio"),
            ("mattino vuoto", payload_mattino_vuoto, "almeno un laboratorio"),
            ("pomeriggio vuoto", payload_pomeriggio_vuoto, "almeno un laboratorio"),
            ("mattino non lista", payload_mattino_non_lista, "deve essere una lista"),
        ]

        modifiche_riga = [
            ("riga non oggetto", "record", "non è valida"),
            ("id mancante", {"titolo": "T", "descrizione": "D", "posti": 2}, 'campo "id"'),
            ("id non stringa", {"id": 1, "titolo": "T", "descrizione": "D", "posti": 2}, "codice laboratorio"),
            ("id troppo lungo", {"id": "L" * 11, "titolo": "T", "descrizione": "D", "posti": 2}, "10 caratteri"),
            ("titolo mancante", {"id": "M01", "descrizione": "D", "posti": 2}, 'campo "titolo"'),
            ("titolo troppo lungo", {"id": "M01", "titolo": "T" * 256, "descrizione": "D", "posti": 2}, "255 caratteri"),
            ("descrizione mancante", {"id": "M01", "titolo": "T", "posti": 2}, 'campo "descrizione"'),
            ("descrizione troppo lunga", {"id": "M01", "titolo": "T", "descrizione": "D" * 65536, "posti": 2}, "troppo lunga"),
            ("posti mancanti", {"id": "M01", "titolo": "T", "descrizione": "D"}, 'campo "posti"'),
            ("posti zero", {"id": "M01", "titolo": "T", "descrizione": "D", "posti": 0}, "capienza"),
            ("posti negativi", {"id": "M01", "titolo": "T", "descrizione": "D", "posti": -1}, "capienza"),
            ("posti decimali", {"id": "M01", "titolo": "T", "descrizione": "D", "posti": 1.5}, "capienza"),
            ("posti stringa", {"id": "M01", "titolo": "T", "descrizione": "D", "posti": "2"}, "capienza"),
            ("posti booleani", {"id": "M01", "titolo": "T", "descrizione": "D", "posti": True}, "capienza"),
        ]
        for nome_caso, riga, messaggio in modifiche_riga:
            payload = copy.deepcopy(payload_base)
            payload["lab_mattino"] = [riga]
            casi_non_validi.append((nome_caso, payload, messaggio))

        payload_parzialmente_invalido = copy.deepcopy(payload_base)
        payload_parzialmente_invalido["lab_mattino"].append(
            {"id": "M02", "titolo": "", "descrizione": "D", "posti": 2}
        )
        casi_non_validi.append(
            ("payload parzialmente invalido", payload_parzialmente_invalido, "titolo")
        )

        for nome_caso, payload, messaggio in casi_non_validi:
            with self.subTest(caso=nome_caso):
                risposta = self.client.post("/import_laboratori", json=payload)
                self.assertEqual(risposta.status_code, 400)
                self.assertFalse(risposta.get_json()["ok"])
                self.assertIn(messaggio, risposta.get_json()["errore"])
                self.assertEqual(Laboratorio.query.count(), 4)

        self.assertEqual(
            db.session.get(SysOption, "ultimo_import_laboratori").value,
            valore_timestamp,
        )

    def test_import_laboratori_valido_sostituisce_dati_e_aggiorna_timestamp(self):
        self.crea_laboratori()
        self.login_admin()

        risposta = self.client.post(
            "/import_laboratori",
            json=self.payload_laboratori(),
        )

        self.assertEqual(risposta.status_code, 200)
        self.assertEqual(Laboratorio.query.count(), 2)
        self.assertIsNone(Laboratorio.query.filter_by(id_lab="M01").first())
        self.assertEqual(
            Laboratorio.query.filter_by(id_lab="NM01").one().tipologia,
            "mattino",
        )
        self.assertEqual(
            Laboratorio.query.filter_by(id_lab="NP01").one().tipologia,
            "pomeriggio",
        )
        self.assertIsNotNone(
            db.session.get(SysOption, "ultimo_import_laboratori")
        )

    def test_import_laboratori_errore_database_ripristina_dati_e_timestamp(self):
        self.crea_laboratori()
        self.login_admin()
        valore_timestamp = "2026-08-20T12:00:00+02:00"
        db.session.add(
            SysOption(
                key="ultimo_import_laboratori",
                value=valore_timestamp,
            )
        )
        db.session.commit()

        with patch.object(
            db.session,
            "commit",
            side_effect=SQLAlchemyError("errore simulato"),
        ):
            risposta = self.client.post(
                "/import_laboratori",
                json=self.payload_laboratori(),
            )

        self.assertEqual(risposta.status_code, 500)
        self.assertIn("errore", risposta.get_json())
        self.assertEqual(Laboratorio.query.count(), 4)
        self.assertIsNotNone(Laboratorio.query.filter_by(id_lab="M01").first())
        self.assertIsNone(Laboratorio.query.filter_by(id_lab="NM01").first())
        self.assertEqual(
            db.session.get(SysOption, "ultimo_import_laboratori").value,
            valore_timestamp,
        )

    def test_template_import_mostrano_validazione_e_messaggi_backend(self):
        self.login_admin()

        pagina_partecipanti = self.client.get("/import_iscritti")
        pagina_laboratori = self.client.get("/import_laboratori")

        for pagina in (pagina_partecipanti, pagina_laboratori):
            self.assertEqual(pagina.status_code, 200)
            self.assertIn(b"righeNonValide", pagina.data)
            self.assertIn(b"data.errore", pagina.data)
            self.assertIn(b"data.ok !== true", pagina.data)
            self.assertIn(b"response.redirected", pagina.data)
            self.assertIn(b"puoCaricare", pagina.data)
            self.assertIn(b"blankrows: true", pagina.data)
            self.assertNotIn(b"console.log", pagina.data)
        self.assertIn(b"colonneRichieste", pagina_partecipanti.data)
        self.assertIn(b"EventLeadsOfAge", pagina_partecipanti.data)
        self.assertNotIn(b"totali", pagina_partecipanti.data)
        self.assertIn(b"fogliMancanti", pagina_laboratori.data)
        self.assertIn(b"pomeriggio", pagina_laboratori.data)

    def test_template_import_partecipanti_supporta_formato_excel_bc(self):
        self.login_admin()

        pagina = self.client.get("/import_iscritti")

        self.assertEqual(pagina.status_code, 200)
        self.assertIn(b"workbook.Sheets[nomeFoglio]", pagina.data)
        self.assertIn(b"const nomeFoglio = 'EventLeadsOfAge'", pagina.data)
        self.assertNotIn(b"totali", pagina.data)
        self.assertIn(b"const numeroRigaIntestazioni = 6", pagina.data)
        self.assertIn(
            b"const indiceRigaIntestazioni = numeroRigaIntestazioni - 1",
            pagina.data,
        )
        self.assertIn(b"righe[indiceRigaIntestazioni]", pagina.data)
        self.assertIn(b"indiceRigaIntestazioni + 1", pagina.data)
        self.assertIn(b"blankrows: true", pagina.data)
        self.assertIn(b"range: 0", pagina.data)
        self.assertIn(b"['Codice', 'Nome', 'Cognome']", pagina.data)
        self.assertIn(b"intestazioni.indexOf('Codice')", pagina.data)
        self.assertIn(b"intestazioni.indexOf('Nome')", pagina.data)
        self.assertIn(b"intestazioni.indexOf('Cognome')", pagina.data)
        self.assertIn(b"valoriPartecipante.every", pagina.data)
        self.assertIn(b"valore === undefined", pagina.data)
        self.assertIn(b"if (rigaSenzaDatiPartecipante)", pagina.data)
        self.assertIn(b"this.righeNonValide += 1", pagina.data)
        self.assertIn(b"Riga Excel ${indice + 1}", pagina.data)
        self.assertIn(b"id: codice", pagina.data)
        self.assertIn(b"nome: nome.trim()", pagina.data)
        self.assertIn(b"cognome: cognome.trim()", pagina.data)
        self.assertIn(
            b'Il file non contiene il foglio "EventLeadsOfAge".',
            pagina.data,
        )
        self.assertIn(b"mancano le colonne", pagina.data)
        self.assertIn(
            b"Il file non contiene partecipanti da importare.",
            pagina.data,
        )

    def test_template_import_partecipanti_minimizza_dati_personali(self):
        self.login_admin()

        pagina = self.client.get("/import_iscritti")

        self.assertEqual(pagina.status_code, 200)
        self.assertIn(b"file.arrayBuffer()", pagina.data)
        self.assertIn(
            b"""const payload = this.rows.map(row => ({
                    id: row.id,
                    nome: row.nome,
                    cognome: row.cognome
                }));""",
            pagina.data,
        )
        self.assertIn(b"body: JSON.stringify(payload)", pagina.data)
        self.assertIn(b"'Content-Type': 'application/json'", pagina.data)
        self.assertNotIn(b"body: JSON.stringify(this.rows)", pagina.data)
        self.assertNotIn(b"FormData", pagina.data)
        self.assertNotIn(b"multipart/form-data", pagina.data)
        self.assertNotIn(b"this.workbook", pagina.data)
        self.assertNotIn(b"this.righe =", pagina.data)
        self.assertNotIn(b"localStorage", pagina.data)
        self.assertNotIn(b"sessionStorage", pagina.data)
        self.assertNotIn(b"console.", pagina.data)
        self.assertIn(b"event.target.value = ''", pagina.data)

        self.assertEqual(pagina.data.count(b'<th scope="col">'), 3)
        for intestazione in ("Codice Socio", "Nome", "Cognome"):
            self.assertIn(
                f'<th scope="col">{intestazione}</th>'.encode(),
                pagina.data,
            )
        for colonna_non_necessaria in (
            "SubID",
            "PIC",
            "Gruppo",
            "Città",
            "PR",
            "Regione",
            "Status",
            "Email",
            "Cell",
            "Email Capo",
            "Cell Capo",
        ):
            self.assertNotIn(
                f'<th scope="col">{colonna_non_necessaria}</th>'.encode(),
                pagina.data,
            )

    def test_utente_temporaneo_viene_reindirizzato_alla_home_dagli_import(self):
        self.crea_partecipante()
        self.verifica(conferma=False)

        for route in ("/import_iscritti", "/import_laboratori"):
            with self.subTest(route=route):
                risposta = self.client.get(route)
                self.assertEqual(risposta.status_code, 302)
                self.assertEqual(risposta.headers["Location"], "/")

    def test_cambio_password_frontend_e_backend(self):
        self.login_admin()
        pagina = self.client.get("/admin/cambia_password")

        self.assertIn(b'x-model="nuovaPassword"', pagina.data)
        self.assertIn(b"nuovaPassword !== confermaPassword", pagina.data)
        risposta = self.client.post(
            "/admin/cambia_password",
            data={
                "password_attuale": "password",
                "nuova_password": "nuova-password",
                "conferma_password": "nuova-password",
            },
        )

        self.assertEqual(risposta.status_code, 302)
        self.assertTrue(
            check_password_hash(
                User.query.filter_by(username="admin").one().password,
                "nuova-password",
            )
        )

    def test_cambio_password_rifiuta_password_attuale_errata_e_conferma_diversa(self):
        self.login_admin()

        password_errata = self.client.post(
            "/admin/cambia_password",
            data={
                "password_attuale": "errata",
                "nuova_password": "nuova-password",
                "conferma_password": "nuova-password",
            },
        )
        conferma_diversa = self.client.post(
            "/admin/cambia_password",
            data={
                "password_attuale": "password",
                "nuova_password": "nuova-password",
                "conferma_password": "diversa",
            },
        )

        self.assertIn(b"password attuale non \xc3\xa8 corretta", password_errata.data)
        self.assertIn(b"non coincidono", conferma_diversa.data)
        self.assertTrue(
            check_password_hash(
                User.query.filter_by(username="admin").one().password,
                "password",
            )
        )


if __name__ == "__main__":
    unittest.main()
