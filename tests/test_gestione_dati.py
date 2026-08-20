import os
import unittest
from datetime import datetime
from unittest.mock import patch

os.environ["DB_TYPE"] = "sqlite"
os.environ["DB_NAME"] = ":memory:"
os.environ["SECRET_KEY"] = "test-secret-key"

from sqlalchemy.exc import SQLAlchemyError
from werkzeug.security import generate_password_hash

from app import (
    Iscrizione,
    Laboratorio,
    MESSAGGIO_ISCRIZIONI_KEY,
    Partecipante,
    STATO_ISCRIZIONI_KEY,
    SysOption,
    ULTIMO_IMPORT_LABORATORI_KEY,
    ULTIMO_IMPORT_PARTECIPANTI_KEY,
    User,
    app,
    db,
)


class GestioneDatiTestCase(unittest.TestCase):
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

    def crea_dati(self, con_iscrizione=True):
        db.session.add_all(
            [
                Partecipante(id=101, nome="Mario", cognome="Rossi"),
                Partecipante(id=202, nome="Anna", cognome="Bianchi"),
                Laboratorio(
                    id=1,
                    id_lab="M01",
                    titolo="Bosco",
                    descrizione="Mattino uno",
                    posti=20,
                    tipologia="mattino",
                ),
                Laboratorio(
                    id=2,
                    id_lab="P01",
                    titolo="Sentieri",
                    descrizione="Pomeriggio uno",
                    posti=20,
                    tipologia="pomeriggio",
                ),
                SysOption(key=STATO_ISCRIZIONI_KEY, value="aperte"),
                SysOption(
                    key=MESSAGGIO_ISCRIZIONI_KEY,
                    value="Messaggio operativo",
                ),
                SysOption(
                    key=ULTIMO_IMPORT_PARTECIPANTI_KEY,
                    value="2026-08-20T12:00:00+02:00",
                ),
                SysOption(
                    key=ULTIMO_IMPORT_LABORATORI_KEY,
                    value="2026-08-20T13:00:00+02:00",
                ),
            ]
        )
        db.session.commit()
        if con_iscrizione:
            db.session.add(
                Iscrizione(
                    data=datetime(2026, 8, 20, 20, 45),
                    partecipante=101,
                    scelta_mattino=1,
                    scelta_pomeriggio=2,
                )
            )
            db.session.commit()

    def istantanea_dati(self):
        return {
            "partecipanti": Partecipante.query.count(),
            "laboratori": Laboratorio.query.count(),
            "iscrizioni": Iscrizione.query.count(),
            "opzioni": {
                opzione.key: opzione.value
                for opzione in SysOption.query.order_by(SysOption.key).all()
            },
        }

    def post_reset(
        self,
        azione,
        password="password",
        conferma=None,
        follow_redirects=True,
    ):
        if conferma is None:
            conferma = azione
        return self.client.post(
            f"/admin/gestione_dati/reset_{azione}",
            data={
                "password_attuale": password,
                "conferma": conferma,
            },
            follow_redirects=follow_redirects,
        )

    def test_pagina_mostra_tre_reset_separati_e_link_navigazione(self):
        self.login_admin()

        pagina = self.client.get("/admin/gestione_dati")
        pagina_import = self.client.get("/import_iscritti")

        self.assertEqual(pagina.status_code, 200)
        self.assertIn(b"Gestione dati", pagina.data)
        self.assertIn(b"Torna alla console amministrativa", pagina.data)
        self.assertIn(b'href="/import_iscritti"', pagina.data)
        self.assertIn(b"Reset iscrizioni", pagina.data)
        self.assertIn(b"Reset partecipanti", pagina.data)
        self.assertIn(b"Reset laboratori", pagina.data)
        self.assertIn(
            b"Partecipanti e laboratori\n            rimarranno disponibili",
            pagina.data,
        )
        self.assertIn(b"I laboratori non verranno modificati", pagina.data)
        self.assertIn(b"I partecipanti non verranno modificati", pagina.data)
        self.assertEqual(pagina.data.count(b'method="post"'), 3)
        self.assertEqual(pagina.data.count(b'name="password_attuale"'), 3)
        self.assertEqual(pagina.data.count(b'name="conferma"'), 3)
        self.assertEqual(pagina.data.count(b'class="btn btn-danger"'), 3)
        self.assertNotIn(b"Cancella tutto", pagina.data)
        for azione in ("iscrizioni", "partecipanti", "laboratori"):
            self.assertIn(
                f'action="/admin/gestione_dati/reset_{azione}"'.encode(),
                pagina.data,
            )
        self.assertIn(b'href="/admin/gestione_dati"', pagina_import.data)

    def test_reset_iscrizioni_cancella_solo_iscrizioni_e_aggiorna_dashboard(self):
        self.crea_dati()
        db.session.add(
            Iscrizione(
                data=datetime(2026, 8, 20, 21, 0),
                partecipante=202,
                scelta_mattino=1,
                scelta_pomeriggio=None,
            )
        )
        db.session.commit()
        opzioni_prima = self.istantanea_dati()["opzioni"]
        self.login_admin()

        risposta = self.post_reset("iscrizioni")

        self.assertEqual(risposta.status_code, 200)
        self.assertIn(
            b"Tutte le iscrizioni registrate sono state cancellate.",
            risposta.data,
        )
        self.assertEqual(Iscrizione.query.count(), 0)
        self.assertEqual(Partecipante.query.count(), 2)
        self.assertEqual(Laboratorio.query.count(), 2)
        self.assertEqual(self.istantanea_dati()["opzioni"], opzioni_prima)

        dashboard = self.client.get("/admin/iscrizioni")
        self.assertIn(b'id="iscrizioni-complete">0</div>', dashboard.data)
        self.assertIn(b'id="iscrizioni-incomplete">0</div>', dashboard.data)
        self.assertIn(b'id="partecipanti-non-iniziati">2</div>', dashboard.data)
        self.assertIn(b"Non sono ancora presenti iscrizioni.", dashboard.data)

    def test_password_errata_non_modifica_nessuno_dei_tre_insiemi(self):
        self.crea_dati()
        self.login_admin()
        dati_prima = self.istantanea_dati()

        for azione in ("iscrizioni", "partecipanti", "laboratori"):
            with self.subTest(azione=azione):
                risposta = self.post_reset(azione, password="errata")
                self.assertIn(
                    b"Password non corretta. Nessun dato \xc3\xa8 stato cancellato.",
                    risposta.data,
                )
                self.assertEqual(self.istantanea_dati(), dati_prima)

    def test_conferma_esplicita_mancante_non_cancella_dati(self):
        self.crea_dati()
        self.login_admin()
        dati_prima = self.istantanea_dati()

        risposta = self.client.post(
            "/admin/gestione_dati/reset_iscrizioni",
            data={"password_attuale": "password"},
            follow_redirects=True,
        )

        self.assertIn(b"Conferma esplicitamente", risposta.data)
        self.assertEqual(self.istantanea_dati(), dati_prima)

    def test_reset_partecipanti_cancella_solo_partecipanti_e_timestamp(self):
        self.crea_dati(con_iscrizione=False)
        self.login_admin()

        risposta = self.post_reset("partecipanti")

        self.assertIn(
            b"Tutti i partecipanti importati sono stati cancellati.",
            risposta.data,
        )
        self.assertEqual(Partecipante.query.count(), 0)
        self.assertEqual(Laboratorio.query.count(), 2)
        self.assertEqual(Iscrizione.query.count(), 0)
        self.assertIsNone(
            db.session.get(SysOption, ULTIMO_IMPORT_PARTECIPANTI_KEY)
        )
        self.assertEqual(
            db.session.get(SysOption, ULTIMO_IMPORT_LABORATORI_KEY).value,
            "2026-08-20T13:00:00+02:00",
        )
        self.assertEqual(
            db.session.get(SysOption, STATO_ISCRIZIONI_KEY).value,
            "aperte",
        )
        self.assertEqual(
            db.session.get(SysOption, MESSAGGIO_ISCRIZIONI_KEY).value,
            "Messaggio operativo",
        )

        pagina_partecipanti = self.client.get("/import_iscritti")
        pagina_laboratori = self.client.get("/import_laboratori")
        self.assertIn(b"Ultimo import:</strong> mai", pagina_partecipanti.data)
        self.assertIn(b"20/08/2026 13:00", pagina_laboratori.data)

    def test_reset_laboratori_cancella_solo_laboratori_e_timestamp(self):
        self.crea_dati(con_iscrizione=False)
        self.login_admin()

        risposta = self.post_reset("laboratori")

        self.assertIn(
            b"Tutti i laboratori importati sono stati cancellati.",
            risposta.data,
        )
        self.assertEqual(Laboratorio.query.count(), 0)
        self.assertEqual(Partecipante.query.count(), 2)
        self.assertEqual(Iscrizione.query.count(), 0)
        self.assertIsNone(
            db.session.get(SysOption, ULTIMO_IMPORT_LABORATORI_KEY)
        )
        self.assertEqual(
            db.session.get(SysOption, ULTIMO_IMPORT_PARTECIPANTI_KEY).value,
            "2026-08-20T12:00:00+02:00",
        )
        self.assertEqual(
            db.session.get(SysOption, STATO_ISCRIZIONI_KEY).value,
            "aperte",
        )
        self.assertEqual(
            db.session.get(SysOption, MESSAGGIO_ISCRIZIONI_KEY).value,
            "Messaggio operativo",
        )

        pagina_laboratori = self.client.get("/import_laboratori")
        pagina_partecipanti = self.client.get("/import_iscritti")
        self.assertIn(b"Ultimo import:</strong> mai", pagina_laboratori.data)
        self.assertIn(b"20/08/2026 12:00", pagina_partecipanti.data)

    def test_reset_partecipanti_e_laboratori_bloccati_da_iscrizioni(self):
        self.crea_dati()
        iscrizione = Iscrizione.query.one()
        iscrizione.scelta_pomeriggio = None
        db.session.commit()
        self.login_admin()
        dati_prima = self.istantanea_dati()

        casi = (
            (
                "partecipanti",
                b"Non \xc3\xa8 possibile cancellare i partecipanti perch\xc3\xa9 esistono",
            ),
            (
                "laboratori",
                b"Non \xc3\xa8 possibile cancellare i laboratori perch\xc3\xa9 esistono",
            ),
        )
        for azione, messaggio in casi:
            with self.subTest(azione=azione):
                risposta = self.post_reset(azione)
                self.assertIn(messaggio, risposta.data)
                self.assertIn(b"Esegui prima il reset delle iscrizioni", risposta.data)
                self.assertEqual(self.istantanea_dati(), dati_prima)

    def test_anonimo_partecipante_e_utente_non_admin_non_possono_resettare(self):
        self.crea_dati()
        dati_prima = self.istantanea_dati()
        endpoint = "/admin/gestione_dati"

        self.assertEqual(self.client.get(endpoint).status_code, 302)
        for azione in ("iscrizioni", "partecipanti", "laboratori"):
            risposta = self.post_reset(azione, follow_redirects=False)
            self.assertEqual(risposta.status_code, 302)
        self.assertEqual(self.istantanea_dati(), dati_prima)

        self.client.post("/verifica_iscrizione", json={"codice_socio": 101})
        self.assertEqual(self.client.get(endpoint).headers["Location"], "/")
        for azione in ("iscrizioni", "partecipanti", "laboratori"):
            risposta = self.post_reset(azione, follow_redirects=False)
            self.assertEqual(risposta.headers["Location"], "/")
        self.assertEqual(self.istantanea_dati(), dati_prima)

        self.client.get("/logout")
        db.session.add(
            User(username="operatore", password=generate_password_hash("password"))
        )
        db.session.commit()
        self.client.post(
            "/login",
            data={"username": "operatore", "passwd": "password"},
        )
        self.assertEqual(self.client.get(endpoint).headers["Location"], "/")
        for azione in ("iscrizioni", "partecipanti", "laboratori"):
            risposta = self.post_reset(azione, follow_redirects=False)
            self.assertEqual(risposta.headers["Location"], "/")
        self.assertEqual(self.istantanea_dati(), dati_prima)

    def test_endpoint_distruttivi_non_accettano_get(self):
        self.crea_dati()
        self.login_admin()
        dati_prima = self.istantanea_dati()

        for azione in ("iscrizioni", "partecipanti", "laboratori"):
            with self.subTest(azione=azione):
                risposta = self.client.get(
                    f"/admin/gestione_dati/reset_{azione}"
                )
                self.assertEqual(risposta.status_code, 405)
                self.assertEqual(self.istantanea_dati(), dati_prima)

    def test_rollback_reset_iscrizioni_ripristina_tutti_i_dati(self):
        self.crea_dati()
        self.login_admin()
        dati_prima = self.istantanea_dati()

        with patch.object(
            db.session,
            "commit",
            side_effect=SQLAlchemyError("errore simulato"),
        ):
            risposta = self.post_reset(
                "iscrizioni",
                follow_redirects=False,
            )

        self.assertEqual(risposta.status_code, 302)
        self.assertEqual(self.istantanea_dati(), dati_prima)
        pagina = self.client.get(risposta.headers["Location"])
        self.assertIn(b"Nessun dato \xc3\xa8 stato cancellato", pagina.data)
        self.assertNotIn(b"errore simulato", pagina.data)
        self.assertNotIn(b"Traceback", pagina.data)

    def test_rollback_reset_partecipanti_ripristina_dati_e_timestamp(self):
        self.crea_dati(con_iscrizione=False)
        self.login_admin()
        dati_prima = self.istantanea_dati()

        with patch.object(
            db.session,
            "commit",
            side_effect=SQLAlchemyError("errore simulato"),
        ):
            risposta = self.post_reset(
                "partecipanti",
                follow_redirects=False,
            )

        self.assertEqual(risposta.status_code, 302)
        self.assertEqual(self.istantanea_dati(), dati_prima)
        pagina = self.client.get(risposta.headers["Location"])
        self.assertIn(b"Nessun dato \xc3\xa8 stato cancellato", pagina.data)
        self.assertNotIn(b"errore simulato", pagina.data)
        self.assertNotIn(b"Traceback", pagina.data)

    def test_rollback_reset_laboratori_ripristina_dati_e_timestamp(self):
        self.crea_dati(con_iscrizione=False)
        self.login_admin()
        dati_prima = self.istantanea_dati()

        with patch.object(
            db.session,
            "commit",
            side_effect=SQLAlchemyError("errore simulato"),
        ):
            risposta = self.post_reset(
                "laboratori",
                follow_redirects=False,
            )

        self.assertEqual(risposta.status_code, 302)
        self.assertEqual(self.istantanea_dati(), dati_prima)
        pagina = self.client.get(risposta.headers["Location"])
        self.assertIn(b"Nessun dato \xc3\xa8 stato cancellato", pagina.data)
        self.assertNotIn(b"errore simulato", pagina.data)
        self.assertNotIn(b"Traceback", pagina.data)


if __name__ == "__main__":
    unittest.main()
