import os
import unittest
from collections import Counter
from datetime import datetime
from unittest.mock import patch

os.environ["DB_TYPE"] = "sqlite"
os.environ["DB_NAME"] = ":memory:"
os.environ["SECRET_KEY"] = "test-secret-key"

from werkzeug.security import generate_password_hash
from sqlalchemy.exc import SQLAlchemyError
from app import (
    app, db, Partecipante, Iscrizione, Laboratorio, User, SysOption,
    ULTIMO_RICALCOLO_DOMENICA_KEY, leggi_distribuzione_domenica,
    ricalcola_gruppi_domenica,
)
from suddivisione_gruppi_service import (
    calcola_gruppi_domenica, prepara_partecipanti_domenica, crea_suddivisione,
)


class DomenicaDatabaseTestCase(unittest.TestCase):
    def setUp(self):
        app.config.update(TESTING=True)
        self.context = app.app_context()
        self.context.push()
        db.create_all()
        self.client = app.test_client()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.context.pop()

    def persone(self, numero):
        persone = [Partecipante(
            id=i, nome=f"Nome {i}", cognome="Rossi", includi_domenica=True,
            gruppo_domenica=20, regione=f"Regione {i % 4}", ruolo=f"Ruolo {i % 3}",
            foca=("Nomina", "CFA", "CFM", None)[i % 4], sesso="F" if i % 2 else "M",
        ) for i in range(1, numero + 1)]
        db.session.add_all(persone)
        db.session.commit()
        return persone

    def assegnazioni(self):
        db.session.expire_all()
        return {p.id: p.gruppo_domenica for p in Partecipante.query.order_by(Partecipante.id)}

    def login_admin(self):
        db.session.add(User(username="admin", password=generate_password_hash("password")))
        db.session.commit()
        self.client.post("/login", data={"username": "admin", "passwd": "password"})

    def test_quaranta_due_per_gruppo_e_sovrascrittura(self):
        self.persone(40)
        self.assertEqual(ricalcola_gruppi_domenica(), 40)
        self.assertEqual(Counter(self.assegnazioni().values()), {i: 2 for i in range(1, 21)})
        self.assertIsNotNone(db.session.get(SysOption, ULTIMO_RICALCOLO_DOMENICA_KEY))

    def test_quarantuno_bilanciati_e_deterministici(self):
        persone = self.persone(41)
        attese = calcola_gruppi_domenica(list(reversed(persone)))
        ricalcola_gruppi_domenica()
        prima = self.assegnazioni()
        self.assertEqual(prima, attese)
        ricalcola_gruppi_domenica()
        self.assertEqual(prima, self.assegnazioni())
        riepilogo = leggi_distribuzione_domenica()
        self.assertEqual(len(riepilogo["gruppi"]), 20)
        self.assertEqual((riepilogo["dimensione_minima"], riepilogo["dimensione_massima"]), (2, 3))
        self.assertTrue(all(1 <= gruppo <= 20 for gruppo in prima.values()))

    def test_solo_inclusi_meno_di_venti_e_pulizia_esclusi(self):
        persone = self.persone(5)
        persone[1].includi_domenica = False
        persone[3].includi_domenica = False
        db.session.commit()
        self.assertEqual(ricalcola_gruppi_domenica(), 3)
        self.assertEqual(self.assegnazioni(), {1: 1, 2: None, 3: 2, 4: None, 5: 3})
        riepilogo = leggi_distribuzione_domenica()
        self.assertEqual(list(riepilogo["gruppi"].values()), [1] * 3 + [0] * 17)
        self.assertEqual(riepilogo["dimensione_minima"], 0)

    def test_zero_inclusi_cancella_assegnazioni_precedenti(self):
        for persona in self.persone(3):
            persona.includi_domenica = False
        db.session.commit()
        self.assertEqual(ricalcola_gruppi_domenica(), 0)
        self.assertEqual(self.assegnazioni(), {1: None, 2: None, 3: None})
        self.assertEqual(list(leggi_distribuzione_domenica()["gruppi"].values()), [0] * 20)

    def test_database_senza_partecipanti(self):
        self.assertEqual(ricalcola_gruppi_domenica(), 0)
        self.assertEqual(leggi_distribuzione_domenica()["totale_assegnati"], 0)

    def test_normalizzazione_solo_per_calcolo_e_riuso_criteri(self):
        persone = self.persone(40)
        persone[0].regione, persone[1].regione = "  LAZIO  ", "lazio"
        persone[0].ruolo, persone[1].ruolo = " Capo   Gruppo ", "capo gruppo"
        persone[0].foca, persone[0].sesso = " cFa ", " m "
        persone[2].regione, persone[2].ruolo = None, " "
        persone[2].foca, persone[2].sesso = "altro", "X"
        db.session.commit()
        campi = ("regione", "ruolo", "foca", "sesso", "nome", "cognome", "deve_iscriversi_sabato")
        prima = [tuple(getattr(p, c) for c in campi) for p in persone]
        dati = prepara_partecipanti_domenica(persone)
        self.assertEqual(dati[0]["regione"], dati[1]["regione"])
        self.assertEqual(dati[0]["ruolo"], dati[1]["ruolo"])
        self.assertEqual((dati[0]["foca"], dati[0]["sesso"]), ("CFA", "M"))
        self.assertEqual(tuple(dati[2][c] for c in ("regione", "ruolo", "foca", "sesso")),
                         ("Non indicato", "Non indicato", "Sistema", "Non indicato"))
        attese, _ = crea_suddivisione(dati, 20)
        ricalcola_gruppi_domenica()
        self.assertEqual(list(self.assegnazioni().values()), attese)
        self.assertEqual([tuple(getattr(p, c) for c in campi) for p in persone], prima)

    def test_regioni_e_categoria_rara_distribuite(self):
        persone = self.persone(60)
        for i, p in enumerate(persone):
            p.regione = f"R{i // 20}"
            p.ruolo = "Raro" if i < 20 else "Comune"
        db.session.commit()
        ricalcola_gruppi_domenica()
        for gruppo in range(1, 21):
            membri = Partecipante.query.filter_by(gruppo_domenica=gruppo).all()
            self.assertEqual({p.regione for p in membri}, {"R0", "R1", "R2"})
            self.assertEqual(sum(p.ruolo == "Raro" for p in membri), 1)

    def test_sabato_iscrizioni_rinunce_ab_e_timestamp_intatti(self):
        self.persone(2)
        db.session.add(Laboratorio(id=1, id_lab="M", titolo="Bosco", descrizione="", posti=5, tipologia="mattino"))
        db.session.commit()
        db.session.add_all([
            Iscrizione(id=1, partecipante=1, scelta_mattino=1, non_partecipa_pomeriggio=True,
                       sottogruppo_mattino="A", sottogruppo_pomeriggio="B", data=datetime(2026, 8, 20)),
            Iscrizione(id=2, partecipante=2, non_partecipa_mattino=True, data=datetime(2026, 8, 21)),
        ])
        db.session.commit()
        def stato():
            return [tuple(getattr(i, c.name) for c in Iscrizione.__table__.columns)
                    for i in Iscrizione.query.order_by(Iscrizione.id)]
        prima = stato()
        ricalcola_gruppi_domenica()
        db.session.expire_all()
        self.assertEqual(stato(), prima)

    def test_rollback_dopo_flush_conserva_assegnazioni_e_timestamp(self):
        self.persone(4)
        db.session.add(SysOption(key=ULTIMO_RICALCOLO_DOMENICA_KEY, value="2026-08-20T10:00:00"))
        db.session.commit()
        prima = self.assegnazioni()
        def errore_commit():
            db.session.flush()
            raise SQLAlchemyError("errore dopo scrittura")
        with patch.object(db.session, "commit", side_effect=errore_commit):
            with self.assertRaises(SQLAlchemyError):
                ricalcola_gruppi_domenica()
        self.assertEqual(self.assegnazioni(), prima)
        self.assertEqual(db.session.get(SysOption, ULTIMO_RICALCOLO_DOMENICA_KEY).value, "2026-08-20T10:00:00")

    def test_riepilogo_legge_persistenza_senza_calcolo(self):
        self.persone(3)
        with patch("app.calcola_gruppi_domenica", side_effect=AssertionError("non ricalcolare")):
            riepilogo = leggi_distribuzione_domenica()
            self.login_admin()
            self.assertEqual(self.client.get("/admin/suddivisione-gruppi").status_code, 200)
        self.assertEqual(riepilogo["gruppi"][20], 3)
        self.assertEqual(riepilogo["totale_assegnati"], 3)

    def test_route_conferma_e_ricalcolo_con_riepilogo(self):
        self.persone(2)
        self.login_admin()
        url = "/admin/suddivisione-gruppi/ricalcola"
        self.assertEqual(self.client.get(url).status_code, 405)
        self.assertEqual(self.client.post(url).status_code, 400)
        self.assertEqual(set(self.assegnazioni().values()), {20})
        risposta = self.client.post(url, data={"conferma": "ricalcola", "numero_laboratori": "1"}, follow_redirects=True)
        self.assertEqual(risposta.status_code, 200)
        self.assertIn(b"2 partecipanti assegnati", risposta.data)
        self.assertIn(b"Assegnazioni salvate", risposta.data)
        self.assertIn("1 – Avventura".encode(), risposta.data)
        self.assertIn("7 – Gradualità".encode(), risposta.data)
        self.assertIn("20 – Vivere".encode(), risposta.data)
        self.assertEqual(self.assegnazioni(), {1: 1, 2: 2})

    def test_route_protetta_anonimo_operatore_partecipante(self):
        self.persone(1)
        url = "/admin/suddivisione-gruppi/ricalcola"
        self.assertEqual(self.client.post(url, data={"conferma": "ricalcola"}).status_code, 302)
        db.session.add(User(username="operatore", password=generate_password_hash("password")))
        db.session.commit()
        self.client.post("/login", data={"username": "operatore", "passwd": "password"})
        self.assertEqual(self.client.post(url, data={"conferma": "ricalcola"}).status_code, 403)
        with self.client.session_transaction() as sessione:
            sessione.clear()
            sessione["_user_id"] = "temp:1"
        self.assertEqual(self.client.post(url, data={"conferma": "ricalcola"}).status_code, 403)
        self.assertEqual(self.assegnazioni(), {1: 20})

    def test_errore_algoritmo_mostra_errore_e_preserva_dati(self):
        self.persone(2)
        self.login_admin()
        with patch("app.calcola_gruppi_domenica", side_effect=RuntimeError("simulato")):
            risposta = self.client.post("/admin/suddivisione-gruppi/ricalcola", data={"conferma": "ricalcola"})
        self.assertEqual(risposta.status_code, 500)
        self.assertIn(b"assegnazioni precedenti sono state conservate", risposta.data)
        self.assertNotIn(b"simulato", risposta.data)
        self.assertEqual(self.assegnazioni(), {1: 20, 2: 20})
