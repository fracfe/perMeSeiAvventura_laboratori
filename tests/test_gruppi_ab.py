import os
import unittest
from collections import Counter
from datetime import datetime
from unittest.mock import patch

os.environ["DB_TYPE"] = "sqlite"
os.environ["DB_NAME"] = ":memory:"
os.environ["SECRET_KEY"] = "test-secret-key"

from sqlalchemy.exc import SQLAlchemyError
from werkzeug.security import generate_password_hash
from app import app, db, Partecipante, Laboratorio, Iscrizione, User, ricalcola_sottogruppi_ab, leggi_distribuzione_ab
from suddivisione_gruppi_service import calcola_sottogruppi_ab, prepara_partecipanti_suddivisione, crea_suddivisione


class GruppiABTestCase(unittest.TestCase):
    def setUp(self):
        app.config.update(TESTING=True)
        self.context = app.app_context()
        self.context.push()
        db.create_all()
        db.session.add_all([
            Laboratorio(id=i, id_lab=f"L{i}", titolo=f"Laboratorio {i}", descrizione="", posti=50,
                        tipologia="mattino" if i in (1, 3) else "pomeriggio")
            for i in range(1, 5)
        ])
        db.session.commit()
        self.client = app.test_client()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.context.pop()

    def iscritti(self, numero):
        db.session.add_all([Partecipante(
            id=i, nome=f"Nome {i}", cognome="Rossi", regione=f"R{i % 4}", ruolo=f"Ruolo {i % 3}",
            foca="CFA" if i % 2 else "Nomina", sesso="M" if i % 2 else "F",
            includi_domenica=False, gruppo_domenica=7, deve_iscriversi_sabato=False,
        ) for i in range(1, numero + 1)])
        db.session.commit()
        db.session.add_all([Iscrizione(
            id=i, partecipante=i, scelta_mattino=1, scelta_pomeriggio=2,
            sottogruppo_mattino="B", sottogruppo_pomeriggio="B", data=datetime(2026, 8, 20, 10, 30),
        ) for i in range(1, numero + 1)])
        db.session.commit()

    def assegnazioni(self):
        db.session.expire_all()
        return [(i.sottogruppo_mattino, i.sottogruppo_pomeriggio) for i in Iscrizione.query.order_by(Iscrizione.id)]

    def login_admin(self):
        db.session.add(User(username="admin", password=generate_password_hash("password")))
        db.session.commit()
        self.client.post("/login", data={"username": "admin", "passwd": "password"})

    def test_dimensioni_40_39_17_2_1_0_determinismo_e_maiuscole(self):
        self.iscritti(40)
        for numero in (40, 39, 17, 2, 1, 0):
            with self.subTest(numero=numero):
                for i in Iscrizione.query.all():
                    i.scelta_mattino = 1 if i.id <= numero else None
                    i.scelta_pomeriggio = 2 if i.id <= numero else None
                db.session.commit()
                ricalcola_sottogruppi_ab()
                prima = self.assegnazioni()
                for colonna in (0, 1):
                    conteggi = Counter(riga[colonna] for riga in prima)
                    self.assertEqual(conteggi["A"], (numero + 1) // 2)
                    self.assertEqual(conteggi["B"], numero // 2)
                    self.assertEqual(conteggi[None], 40 - numero)
                    self.assertTrue(set(conteggi) <= {"A", "B", None})
                ricalcola_sottogruppi_ab()
                self.assertEqual(self.assegnazioni(), prima)

    def test_zero_iscrizioni_e_laboratori_vuoti(self):
        ricalcola_sottogruppi_ab()
        self.assertEqual(Iscrizione.query.count(), 0)
        riepilogo = leggi_distribuzione_ab()
        self.assertEqual(len(riepilogo), 4)
        self.assertTrue(all((r["totale"], r["A"], r["B"]) == (0, 0, 0) for r in riepilogo))
        Laboratorio.query.delete()
        db.session.commit()
        ricalcola_sottogruppi_ab()
        self.assertEqual(leggi_distribuzione_ab(), [])

    def test_indipendenza_laboratori_fasce_e_stessa_persona_a_b(self):
        self.iscritti(3)
        for p in Partecipante.query.all():
            p.regione, p.ruolo, p.foca, p.sesso = None, None, None, None
        db.session.get(Iscrizione, 1).scelta_mattino = 3
        db.session.get(Iscrizione, 3).scelta_pomeriggio = 4
        db.session.commit()
        ricalcola_sottogruppi_ab()
        self.assertEqual(self.assegnazioni(), [("A", "A"), ("A", "B"), ("B", "A")])
        riepilogo = {r["laboratorio"].id: (r["totale"], r["A"], r["B"]) for r in leggi_distribuzione_ab()}
        self.assertEqual(riepilogo, {1: (2, 1, 1), 2: (2, 1, 1), 3: (1, 1, 0), 4: (1, 1, 0)})

    def test_pulizia_rinunce_null_e_spostamento(self):
        self.iscritti(3)
        ricalcola_sottogruppi_ab()
        db.session.get(Iscrizione, 1).scelta_mattino = None
        db.session.get(Iscrizione, 1).non_partecipa_mattino = True
        db.session.get(Iscrizione, 2).scelta_pomeriggio = None
        db.session.get(Iscrizione, 2).non_partecipa_pomeriggio = True
        db.session.get(Iscrizione, 3).scelta_mattino = None
        db.session.get(Iscrizione, 1).scelta_pomeriggio = None
        db.session.get(Iscrizione, 2).scelta_mattino = 3
        # Assegnazione ormai vecchia: il nuovo laboratorio ha un solo iscritto.
        db.session.get(Iscrizione, 2).sottogruppo_mattino = "B"
        db.session.commit()
        self.assertEqual(db.session.get(Iscrizione, 2).sottogruppo_mattino, "B")
        ricalcola_sottogruppi_ab()
        self.assertEqual(self.assegnazioni(), [(None, None), ("A", None), (None, "A")])

    def test_scelte_flag_timestamp_anagrafica_e_domenica_intatti(self):
        self.iscritti(5)
        def stato():
            return {m.__tablename__: [tuple(getattr(r, c.name) for c in m.__table__.columns
                    if c.name not in ("sottogruppo_mattino", "sottogruppo_pomeriggio"))
                    for r in m.query.order_by(m.id)] for m in (Iscrizione, Partecipante, Laboratorio)}
        prima = stato()
        ricalcola_sottogruppi_ab()
        db.session.expire_all()
        self.assertEqual(stato(), prima)

    def test_normalizzazione_e_nucleo_criteri_riutilizzati(self):
        self.iscritti(6)
        persone = Partecipante.query.order_by(Partecipante.id).all()
        persone[0].regione, persone[1].regione = " LAZIO ", "lazio"
        persone[0].ruolo, persone[1].ruolo = " Capo   Gruppo ", "capo gruppo"
        persone[0].foca, persone[0].sesso = " cFa ", " f "
        persone[2].regione, persone[2].ruolo = None, " "
        persone[2].foca, persone[2].sesso = "altro", "X"
        db.session.commit()
        dati = prepara_partecipanti_suddivisione(persone)
        self.assertEqual(dati[0]["regione"], dati[1]["regione"])
        self.assertEqual(dati[0]["ruolo"], dati[1]["ruolo"])
        self.assertEqual((dati[0]["foca"], dati[0]["sesso"]), ("CFA", "F"))
        self.assertEqual(tuple(dati[2][c] for c in ("regione", "ruolo", "foca", "sesso")),
                         ("Non indicato", "Non indicato", "Sistema", "Non indicato"))
        attese, _ = crea_suddivisione(dati, 2)
        self.assertEqual(calcola_sottogruppi_ab(reversed(persone)),
                         {p.id: ("A", "B")[gruppo - 1] for p, gruppo in zip(persone, attese)})
        ricalcola_sottogruppi_ab()
        self.assertEqual([r[0] for r in self.assegnazioni()], [("A", "B")[g - 1] for g in attese])

    def test_regioni_e_categorie_rare_bilanciate(self):
        self.iscritti(40)
        for p in Partecipante.query.all():
            p.regione = "Lazio" if p.id <= 20 else "Veneto"
            p.ruolo = "Raro" if p.id <= 2 else "Comune"
        db.session.commit()
        ricalcola_sottogruppi_ab()
        for gruppo in ("A", "B"):
            persone = db.session.query(Partecipante).join(Iscrizione, Iscrizione.partecipante == Partecipante.id).filter(Iscrizione.sottogruppo_mattino == gruppo).all()
            self.assertEqual(Counter(p.regione for p in persone), {"Lazio": 10, "Veneto": 10})
            self.assertEqual(sum(p.ruolo == "Raro" for p in persone), 1)

    def test_rollback_se_fallisce_pomeriggio_dopo_flush_mattino(self):
        self.iscritti(4)
        prima = self.assegnazioni()
        chiamate = 0
        def calcola(persone):
            nonlocal chiamate
            chiamate += 1
            if chiamate == 3:  # Dopo entrambi i laboratori mattino.
                db.session.flush()
                raise RuntimeError("errore laboratorio pomeriggio")
            return calcola_sottogruppi_ab(persone)
        with patch("app.calcola_sottogruppi_ab", side_effect=calcola):
            with self.assertRaises(RuntimeError):
                ricalcola_sottogruppi_ab()
        self.assertEqual(self.assegnazioni(), prima)

    def test_rollback_errore_commit(self):
        self.iscritti(3)
        prima = self.assegnazioni()
        def errore():
            db.session.flush()
            raise SQLAlchemyError("errore commit")
        with patch.object(db.session, "commit", side_effect=errore):
            with self.assertRaises(SQLAlchemyError):
                ricalcola_sottogruppi_ab()
        self.assertEqual(self.assegnazioni(), prima)

    def test_riepilogo_persistito_route_conferma_e_protezioni(self):
        self.iscritti(3)
        url = "/admin/iscrizioni/gruppi-ab"
        self.assertEqual(self.client.get(url).status_code, 302)
        self.assertEqual(self.client.post(url + "/ricalcola", data={"conferma": "ricalcola"}).status_code, 302)
        self.client.post("/verifica_iscrizione", json={"codice_socio": 1})
        self.client.post("/conferma_identita")
        self.assertEqual(self.client.post(url + "/ricalcola", data={"conferma": "ricalcola"}).status_code, 403)
        db.session.add(User(username="operatore", password=generate_password_hash("password")))
        db.session.commit()
        self.client.post("/login", data={"username": "operatore", "passwd": "password"})
        self.assertEqual(self.client.post(url + "/ricalcola", data={"conferma": "ricalcola"}).status_code, 403)
        self.assertEqual(self.client.get(url).headers["Location"], "/")
        self.login_admin()
        prima = self.assegnazioni()
        with patch("app.calcola_sottogruppi_ab", side_effect=AssertionError("non ricalcolare")):
            righe = leggi_distribuzione_ab()
            pagina = self.client.get(url)
        self.assertEqual(pagina.status_code, 200)
        self.assertEqual([(r["A"], r["B"]) for r in righe if r["totale"]], [(0, 3), (0, 3)])
        self.assertEqual(self.client.get(url + "/ricalcola").status_code, 405)
        self.assertEqual(self.client.post(url + "/ricalcola").status_code, 400)
        self.assertEqual(self.assegnazioni(), prima)
        risposta = self.client.post(url + "/ricalcola", data={"conferma": "ricalcola"}, follow_redirects=True)
        self.assertEqual(risposta.status_code, 200)
        self.assertIn(b"ricalcolati per tutti i laboratori", risposta.data)
        self.assertIn(b"Iscritti totali", risposta.data)
        self.assertNotEqual(self.assegnazioni(), prima)

    def test_errore_route_conserva_assegnazioni(self):
        self.iscritti(3)
        self.login_admin()
        prima = self.assegnazioni()
        with patch("app.calcola_sottogruppi_ab", side_effect=RuntimeError("simulato")):
            risposta = self.client.post("/admin/iscrizioni/gruppi-ab/ricalcola", data={"conferma": "ricalcola"})
        self.assertEqual(risposta.status_code, 500)
        self.assertIn(b"assegnazioni A/B precedenti sono state conservate", risposta.data)
        self.assertEqual(self.assegnazioni(), prima)
