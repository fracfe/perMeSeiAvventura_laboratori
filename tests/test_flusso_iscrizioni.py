import copy
import html
import os
import re
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
    stato_iscrizione,
)


def righe_dashboard(contenuto):
    testo = contenuto.decode("utf-8")
    pattern = re.compile(
        r'<tr\s+data-riga-iscrizione\s+'
        r'data-codice="([^"]*)"\s+'
        r'data-persona="([^"]*)"\s+'
        r'data-stato="([^"]*)"'
    )
    return [
        {
            "codice": html.unescape(codice),
            "persona": html.unescape(persona),
            "stato": html.unescape(stato),
        }
        for codice, persona, stato in pattern.findall(testo)
    ]


def filtra_righe_dashboard(righe, codice="", persona="", stati=None):
    def normalizza(valore):
        return " ".join(valore.casefold().split())

    if stati is None:
        stati = {"completo", "incompleto", "non_iniziato"}
    codice = normalizza(codice)
    persona = normalizza(persona)
    return {
        int(riga["codice"])
        for riga in righe
        if codice in normalizza(riga["codice"])
        and persona in normalizza(riga["persona"])
        and riga["stato"] in stati
    }


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

    def crea_iscrizione(
        self,
        partecipante_id=123,
        mattino=1,
        pomeriggio=2,
        non_partecipa_mattino=False,
        non_partecipa_pomeriggio=False,
    ):
        iscrizione = Iscrizione(
            data=datetime(2026, 8, 20, 20, 45),
            partecipante=partecipante_id,
            scelta_mattino=mattino,
            scelta_pomeriggio=pomeriggio,
            non_partecipa_mattino=non_partecipa_mattino,
            non_partecipa_pomeriggio=non_partecipa_pomeriggio,
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

    def salva_non_partecipa(self, tipologia):
        return self.client.post(
            f"/laboratori/{tipologia}/salva",
            json={"non_partecipa": True},
        )

    def login_admin(self, password="password"):
        return self.client.post(
            "/login",
            data={"username": "admin", "passwd": password},
        )

    def completa_payload_partecipanti(self, righe):
        return [dict(
            gruppo=None, zona=None, regione=None, email=None, sesso=None,
            foca=None, ruolo=None, incarico_altro=None,
            deve_iscriversi_sabato="Sì", includi_domenica="No", **riga,
        ) for riga in righe]

    def payload_partecipanti(self):
        return self.completa_payload_partecipanti([
            {"id": 101, "nome": "Mario", "cognome": "Rossi"},
            {"id": 202, "nome": "Anna", "cognome": "Bianchi"},
        ])

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

    def test_non_partecipa_e_sempre_disponibile_anche_senza_laboratori(self):
        self.imposta_stato()
        self.crea_partecipante()
        self.verifica()

        for tipologia in ("mattino", "pomeriggio"):
            with self.subTest(tipologia=tipologia):
                risposta = self.client.get(f"/lista_laboratori/{tipologia}")
                opzione = risposta.get_json()["laboratori"][0]
                self.assertEqual(opzione["id"], "non_partecipa")
                self.assertEqual(
                    opzione["titolo"],
                    "Non partecipo a nessun laboratorio",
                )
                self.assertTrue(opzione["speciale"])
                self.assertTrue(opzione["selezionabile"])
                self.assertIsNone(opzione["posti"])
                self.assertIsNone(opzione["posti_disponibili"])

        pagina = self.client.get("/laboratori/mattino")
        self.assertIn(b"Sempre disponibile", pagina.data)
        self.assertIn(b"{ non_partecipa: true }", pagina.data)

    def test_non_partecipa_in_entrambe_le_fasce_completa_iscrizione(self):
        self.imposta_stato()
        self.crea_partecipante()
        self.verifica()

        mattino = self.salva_non_partecipa("mattino")
        iscrizione = Iscrizione.query.one()
        self.assertEqual(mattino.status_code, 200)
        self.assertTrue(iscrizione.non_partecipa_mattino)
        self.assertIsNone(iscrizione.scelta_mattino)
        self.assertEqual(stato_iscrizione(iscrizione), "incompleto")

        pomeriggio = self.salva_non_partecipa("pomeriggio")
        db.session.refresh(iscrizione)
        self.assertEqual(pomeriggio.status_code, 200)
        self.assertTrue(iscrizione.non_partecipa_pomeriggio)
        self.assertIsNone(iscrizione.scelta_pomeriggio)
        self.assertEqual(stato_iscrizione(iscrizione), "completo")
        self.assertEqual(
            pomeriggio.get_json()["redirect"],
            "/iscrizione/riepilogo",
        )

        riepilogo = self.client.get("/iscrizione/riepilogo")
        self.assertEqual(
            riepilogo.data.count(b"Non partecipa a nessun laboratorio"),
            2,
        )
        self.assertIn(b"Hai completato l'iscrizione", riepilogo.data)

    def test_laboratorio_e_non_partecipa_si_possono_combinare_e_modificare(self):
        self.prepara_partecipante()

        self.salva("mattino", 1)
        self.salva_non_partecipa("pomeriggio")
        iscrizione = Iscrizione.query.one()
        self.assertEqual(stato_iscrizione(iscrizione), "completo")
        self.assertEqual(iscrizione.scelta_mattino, 1)
        self.assertTrue(iscrizione.non_partecipa_pomeriggio)
        self.assertEqual(
            Iscrizione.query.filter_by(scelta_mattino=1).count(),
            1,
        )

        verso_non_partecipa = self.salva_non_partecipa("mattino")
        db.session.refresh(iscrizione)
        self.assertEqual(verso_non_partecipa.status_code, 200)
        self.assertIsNone(iscrizione.scelta_mattino)
        self.assertTrue(iscrizione.non_partecipa_mattino)
        self.assertEqual(
            Iscrizione.query.filter_by(scelta_mattino=1).count(),
            0,
        )

        lista = self.client.get("/lista_laboratori/pomeriggio").get_json()
        opzione = next(
            elemento
            for elemento in lista["laboratori"]
            if elemento["id"] == "non_partecipa"
        )
        self.assertTrue(opzione["posseduto"])
        self.assertTrue(opzione["selezionabile"])

        pomeriggio_reale = self.salva("pomeriggio", 2)
        db.session.refresh(iscrizione)
        self.assertEqual(pomeriggio_reale.status_code, 200)
        self.assertTrue(iscrizione.non_partecipa_mattino)
        self.assertEqual(iscrizione.scelta_pomeriggio, 2)
        self.assertFalse(iscrizione.non_partecipa_pomeriggio)

        verso_laboratorio = self.salva("mattino", 1)
        db.session.refresh(iscrizione)
        self.assertEqual(verso_laboratorio.status_code, 200)
        self.assertEqual(iscrizione.scelta_mattino, 1)
        self.assertFalse(iscrizione.non_partecipa_mattino)
        self.assertEqual(iscrizione.scelta_pomeriggio, 2)

    def test_non_partecipa_non_occupa_posti_ne_ha_un_limite(self):
        self.imposta_stato()
        self.crea_laboratori(posti=1)
        for partecipante_id in range(1000, 1020):
            self.crea_partecipante(
                partecipante_id,
                f"Nome{partecipante_id}",
                "Senza laboratorio",
            )
            client = app.test_client()
            client.post(
                "/verifica_iscrizione",
                json={"codice_socio": partecipante_id},
            )
            client.post("/conferma_identita")
            risposta = client.post(
                "/laboratori/mattino/salva",
                json={"non_partecipa": True},
            )
            self.assertEqual(risposta.status_code, 200)

        self.assertEqual(Iscrizione.query.count(), 20)
        self.assertEqual(
            Iscrizione.query.filter(Iscrizione.scelta_mattino.is_not(None)).count(),
            0,
        )

    def test_opzione_non_partecipa_non_dipende_dall_import_laboratori(self):
        self.login_admin()
        importazione = self.client.post(
            "/import_laboratori",
            json=self.payload_laboratori(),
        )
        self.assertEqual(importazione.status_code, 200)
        self.client.get("/logout")
        self.imposta_stato()
        self.crea_partecipante()
        self.verifica()

        for tipologia in ("mattino", "pomeriggio"):
            laboratori = self.client.get(
                f"/lista_laboratori/{tipologia}"
            ).get_json()["laboratori"]
            speciali = [elemento for elemento in laboratori if elemento["speciale"]]
            self.assertEqual(len(speciali), 1)
            self.assertEqual(speciali[0]["id"], "non_partecipa")

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
            self.assertIn(b"Home", pagina.data)
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
        stati = [riga["stato"] for riga in righe_dashboard(pagina.data)]
        self.assertEqual(stati.count("completo"), 1)
        self.assertEqual(stati.count("incompleto"), 2)
        self.assertEqual(stati.count("non_iniziato"), 1)

    def test_dashboard_mostra_campi_e_filtri_stato_inizialmente_attivi(self):
        self.crea_partecipante()
        self.login_admin()

        pagina = self.client.get("/admin/iscrizioni")

        self.assertIn(b'id="filtro-codice"', pagina.data)
        self.assertIn(b'>Codice censimento</label>', pagina.data)
        self.assertIn(b'id="filtro-persona"', pagina.data)
        self.assertIn(b'>Nome o cognome</label>', pagina.data)
        for stato in (b"completo", b"incompleto", b"non_iniziato"):
            self.assertRegex(
                pagina.data,
                rb'data-filtro-stato="' + stato + rb'"[\s\S]*?aria-pressed="true"',
            )
        self.assertIn(b'addEventListener("input", aggiornaElenco)', pagina.data)
        self.assertIn(b'statiAttivi.has(riga.dataset.stato)', pagina.data)

    def test_dashboard_classifica_e_mostra_non_partecipa(self):
        self.crea_partecipante(611, "Entrambe", "Speciali")
        self.crea_iscrizione(
            611,
            mattino=None,
            pomeriggio=None,
            non_partecipa_mattino=True,
            non_partecipa_pomeriggio=True,
        )
        self.crea_partecipante(612, "Solo", "Mattino")
        self.crea_iscrizione(
            612,
            mattino=None,
            pomeriggio=None,
            non_partecipa_mattino=True,
        )
        self.crea_partecipante(613, "Non", "Iniziato")
        self.login_admin()

        pagina = self.client.get("/admin/iscrizioni")

        self.assertIn(b'id="iscrizioni-complete">1</div>', pagina.data)
        self.assertIn(b'id="iscrizioni-incomplete">1</div>', pagina.data)
        self.assertIn(b'id="partecipanti-non-iniziati">1</div>', pagina.data)
        self.assertEqual(pagina.data.count(b"Non partecipa"), 3)
        stati = {
            int(riga["codice"]): riga["stato"]
            for riga in righe_dashboard(pagina.data)
        }
        self.assertEqual(stati[611], "completo")
        self.assertEqual(stati[612], "incompleto")
        self.assertEqual(stati[613], "non_iniziato")

    def test_filtri_dashboard_combinano_ricerche_in_and_e_stati_in_or(self):
        self.crea_laboratori()
        self.crea_partecipante(111, "Mario", "Rossi")
        self.crea_iscrizione(111, mattino=1, pomeriggio=2)
        self.crea_partecipante(212, "Maria", "Rossi")
        self.crea_iscrizione(212, mattino=3, pomeriggio=None)
        self.crea_partecipante(312, "Luca", "Rossi")
        self.crea_partecipante(412, "Anna", "Bianchi")
        self.crea_iscrizione(412, mattino=1, pomeriggio=4)
        self.crea_partecipante(512, "Vuoto", "Stato")
        self.crea_iscrizione(512, mattino=None, pomeriggio=None)
        self.login_admin()

        pagina = self.client.get("/admin/iscrizioni")
        righe = righe_dashboard(pagina.data)

        self.assertEqual(
            filtra_righe_dashboard(righe, persona="  ROSSI   mario "),
            {111},
        )
        self.assertEqual(
            filtra_righe_dashboard(
                righe,
                codice="12",
                persona="Rossi",
                stati={"completo", "incompleto"},
            ),
            {212},
        )
        self.assertEqual(
            filtra_righe_dashboard(
                righe,
                stati={"completo", "incompleto"},
            ),
            {111, 212, 412},
        )
        self.assertEqual(
            filtra_righe_dashboard(
                righe,
                codice="12",
                persona="rossi",
                stati={"incompleto", "non_iniziato"},
            ),
            {212, 312},
        )
        self.assertEqual(
            filtra_righe_dashboard(righe),
            {111, 212, 312, 412, 512},
        )
        self.assertEqual(filtra_righe_dashboard(righe, stati=set()), set())
        riga_vuota = next(riga for riga in righe if riga["codice"] == "512")
        self.assertEqual(riga_vuota["stato"], "non_iniziato")

    def test_reimport_laboratori_consentito_se_esistono_iscrizioni(self):
        self.crea_laboratori()
        self.crea_partecipante()
        self.crea_iscrizione(mattino=1, pomeriggio=None)
        self.login_admin()

        risposta = self.client.post(
            "/import_laboratori",
            json=self.payload_laboratori(),
        )

        self.assertEqual(risposta.status_code, 200)
        self.assertEqual(Laboratorio.query.count(), 6)
        self.assertEqual(Iscrizione.query.one().scelta_mattino, 1)

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
                if isinstance(payload, list) and all(isinstance(riga, dict) for riga in payload):
                    payload = self.completa_payload_partecipanti(payload)
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
            json=self.completa_payload_partecipanti([
                {"id": 101, "nome": "Valido", "cognome": "Uno"},
                {"id": 202, "nome": "", "cognome": "Non valido"},
                {"id": 303, "nome": "Valido", "cognome": "Tre"},
            ]),
        )

        self.assertEqual(risposta.status_code, 400)
        self.assertEqual(Partecipante.query.count(), 0)
        self.assertEqual(
            db.session.get(SysOption, "ultimo_import_partecipanti").value,
            valore_timestamp,
        )

    def test_import_partecipanti_valido_aggiorna_timestamp_e_anagrafica(self):
        self.crea_partecipante(101, "Nome esistente", "Cognome esistente")
        self.login_admin()

        risposta = self.client.post(
            "/import_iscritti",
            json=self.completa_payload_partecipanti([
                {"id": 101, "nome": "Nome nuovo", "cognome": "Cognome nuovo"},
                {"id": 202, "nome": "  Anna ", "cognome": " Bianchi  "},
            ]),
        )

        self.assertEqual(risposta.status_code, 200)
        self.assertEqual(Partecipante.query.count(), 2)
        self.assertEqual(db.session.get(Partecipante, 101).nome, "Nome nuovo")
        self.assertEqual(db.session.get(Partecipante, 202).nome, "Anna")
        self.assertEqual(db.session.get(Partecipante, 202).cognome, "Bianchi")
        self.assertIsNotNone(
            db.session.get(SysOption, "ultimo_import_partecipanti")
        )

    def test_import_partecipanti_ignora_e_non_persiste_campi_extra(self):
        self.login_admin()

        risposta = self.client.post(
            "/import_iscritti",
            json=self.completa_payload_partecipanti([
                {
                    "id": 303,
                    "nome": "Mario",
                    "cognome": "Rossi",
                    "Email": "dato-non-necessario@example.test",
                    "Cell": "+390000000000",
                    "Gruppo": "Dato non necessario",
                }
            ]),
        )

        self.assertEqual(risposta.status_code, 200)
        partecipante = db.session.get(Partecipante, 303)
        self.assertEqual(partecipante.nome, "Mario")
        self.assertEqual(partecipante.cognome, "Rossi")
        self.assertFalse(hasattr(partecipante, "Email"))
        self.assertFalse(hasattr(partecipante, "Cell"))
        self.assertFalse(hasattr(partecipante, "Gruppo"))
        self.assertEqual(
            (partecipante.email, partecipante.gruppo),
            (None, None),
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

    def test_import_laboratori_valido_aggiunge_dati_e_aggiorna_timestamp(self):
        self.crea_laboratori()
        self.login_admin()

        risposta = self.client.post(
            "/import_laboratori",
            json=self.payload_laboratori(),
        )

        self.assertEqual(risposta.status_code, 200)
        self.assertEqual(Laboratorio.query.count(), 6)
        self.assertIsNotNone(Laboratorio.query.filter_by(id_lab="M01").first())
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

    def test_template_import_laboratori_mantiene_validazione_e_messaggi(self):
        self.login_admin()
        pagina = self.client.get("/import_laboratori")
        self.assertEqual(pagina.status_code, 200)
        for testo in (b"righeNonValide", b"data.errore", b"data.ok !== true",
                      b"response.redirected", b"puoCaricare", b"blankrows: true",
                      b"fogliMancanti", b"pomeriggio"):
            self.assertIn(testo, pagina.data)

    def test_template_import_partecipanti_csv_con_anteprima(self):
        self.login_admin()
        pagina = self.client.get("/import_iscritti")
        self.assertEqual(pagina.status_code, 200)
        self.assertIn(b'accept=".csv"', pagina.data)
        self.assertIn(b"import_iscritti.js", pagina.data)
        self.assertIn(b"Anteprima validata", pagina.data)
        self.assertNotIn(b"EventLeadsOfAge", pagina.data)
        self.assertEqual(pagina.data.count(b'<th scope="col">'), 9)
        for colonna in ("Codice", "Nome", "Cognome", "Gruppo", "Zona", "Regione",
                        "Email", "Sabato", "Domenica"):
            self.assertIn(f'<th scope="col">{colonna}</th>'.encode(), pagina.data)
        for colonna in ("EmailReferente", "DataNascita", "PIC", "CAP"):
            self.assertNotIn(colonna.encode(), pagina.data)

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
