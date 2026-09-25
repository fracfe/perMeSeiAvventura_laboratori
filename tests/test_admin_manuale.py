import os
import unittest
from datetime import datetime
from unittest.mock import patch
from html.parser import HTMLParser

os.environ["DB_TYPE"] = "sqlite"
os.environ["DB_NAME"] = ":memory:"
os.environ["SECRET_KEY"] = "test-secret-key"

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import text
from werkzeug.security import generate_password_hash
from app import app, db, User, Partecipante, Laboratorio, Iscrizione, SysOption


class AdminManualeTestCase(unittest.TestCase):
    def setUp(self):
        self.context = app.app_context()
        self.context.push()
        app.config.update(TESTING=True)
        db.create_all()
        db.session.add(User(username="admin", password=generate_password_hash("password")))
        db.session.commit()
        self.client = app.test_client()
        self.client.post('/login', data={'username': 'admin', 'passwd': 'password'})

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.context.pop()

    def persona(self, codice=101):
        return dict(id=str(codice), nome='Anna', cognome='Rossi', gruppo='Roma 1', zona='Roma',
                    regione='Lazio', email='anna@example.test', sesso='F', foca='CFA', ruolo='Altro',
                    incarico_altro='Supporto', deve_iscriversi_sabato='true', includi_domenica='false')

    def laboratorio(self, fascia='mattino'):
        return dict(tipologia=fascia, id_lab='L01', titolo='Bosco', descrizione='Descrizione', posti='10')

    def snapshot(self, modello):
        return [tuple(getattr(riga, c.name) for c in modello.__table__.columns)
                for riga in modello.query.all()]

    def prepara(self):
        for codice in (101, 202):
            self.assertEqual(self.client.post('/admin/partecipanti/nuovo', data=self.persona(codice)).status_code, 302)
        for fascia in ('mattino', 'pomeriggio'):
            self.assertEqual(self.client.post('/admin/laboratori/nuovo', data=self.laboratorio(fascia)).status_code, 302)
        mattino = Laboratorio.query.filter_by(tipologia='mattino').one().id
        pomeriggio = Laboratorio.query.filter_by(tipologia='pomeriggio').one().id
        db.session.get(Partecipante, 101).gruppo_domenica = 7
        db.session.get(Partecipante, 101).includi_domenica = True
        db.session.add_all([
            Iscrizione(partecipante=101, scelta_mattino=mattino, scelta_pomeriggio=pomeriggio,
                       sottogruppo_mattino='A', sottogruppo_pomeriggio='B', data=datetime(2026, 8, 20)),
            Iscrizione(partecipante=202, scelta_mattino=mattino, non_partecipa_pomeriggio=True,
                       data=datetime(2026, 8, 21)),
            SysOption(key='stato_iscrizioni', value='aperte'),
        ])
        db.session.commit()
        return mattino, pomeriggio


    def test_correzioni_forzate_creazione_cambio_rimozione_e_timestamp(self):
        mattino, pomeriggio = self.prepara()
        db.session.get(Laboratorio, mattino).posti = 1
        db.session.get(Laboratorio, pomeriggio).posti = 1
        db.session.commit()
        self.client.post('/admin/partecipanti/nuovo', data=self.persona(303))
        dati = {**self.persona(303), "deve_iscriversi_sabato": "false",
                "includi_domenica": "false", "scelta_mattino": str(mattino),
                "scelta_pomeriggio": str(pomeriggio), "sottogruppo_mattino": "A",
                "sottogruppo_pomeriggio": "B", "gruppo_domenica": "7"}
        url = "/admin/partecipanti/303/modifica"
        self.assertEqual(self.client.post(url, data=dati).status_code, 302)
        i = Iscrizione.query.filter_by(partecipante=303).one()
        p = db.session.get(Partecipante, 303)
        self.assertEqual((i.scelta_mattino, i.scelta_pomeriggio, i.sottogruppo_mattino, i.sottogruppo_pomeriggio),
                         (mattino, pomeriggio, "A", "B"))
        self.assertTrue(p.deve_iscriversi_sabato)
        self.assertTrue(p.includi_domenica)
        self.assertEqual(p.gruppo_domenica, 7)
        self.assertFalse(i.non_partecipa_mattino)
        self.assertFalse(i.non_partecipa_pomeriggio)
        self.assertIsNotNone(i.data)
        data = i.data
        lab = Laboratorio(id_lab="ALT", tipologia="mattino", titolo="Altro", descrizione="Altro", posti=1)
        db.session.add(lab)
        db.session.commit()
        dati.update(scelta_mattino=str(lab.id), sottogruppo_mattino="B", sottogruppo_pomeriggio="", gruppo_domenica="20")
        self.assertEqual(self.client.post(url, data=dati).status_code, 302)
        self.assertEqual((i.scelta_mattino, i.sottogruppo_mattino, i.sottogruppo_pomeriggio, p.gruppo_domenica),
                         (lab.id, "B", None, 20))
        dati.update(scelta_mattino="", scelta_pomeriggio="", gruppo_domenica="",
                    deve_iscriversi_sabato="true", includi_domenica="true")
        self.assertEqual(self.client.post(url, data=dati).status_code, 302)
        self.assertEqual((i.scelta_mattino, i.scelta_pomeriggio, i.sottogruppo_mattino, i.sottogruppo_pomeriggio),
                         (None, None, None, None))
        self.assertFalse(i.non_partecipa_mattino)
        self.assertFalse(i.non_partecipa_pomeriggio)
        self.assertEqual(i.data, data)
        self.assertIsNone(p.gruppo_domenica)
        self.assertTrue(p.includi_domenica)
        self.assertTrue(p.deve_iscriversi_sabato)
        # Il laboratorio rimane pieno: il normale utente non può forzarlo.
        self.client.get('/logout')
        self.client.post('/verifica_iscrizione', json={"codice_socio": 303})
        self.client.post('/conferma_identita')
        self.assertEqual(self.client.post('/laboratori/mattino/salva', json={"laboratorio_id": mattino}).status_code, 409)

    def test_correzione_rinuncia_e_form_nomi_domenica(self):
        mattino, pomeriggio = self.prepara()
        data = Iscrizione.query.filter_by(partecipante=202).one().data
        risposta = self.client.get("/admin/partecipanti/202/modifica").get_data(as_text=True)
        for label in ("1 – Avventura", "7 – Gradualità", "20 – Vivere"):
            self.assertIn(label, risposta)
        dati = {**self.persona(202), "scelta_pomeriggio": str(pomeriggio), "sottogruppo_pomeriggio": "A"}
        self.assertEqual(self.client.post("/admin/partecipanti/202/modifica", data=dati).status_code, 302)
        i = Iscrizione.query.filter_by(partecipante=202).one()
        self.assertFalse(i.non_partecipa_pomeriggio)
        self.assertEqual((i.scelta_mattino, i.scelta_pomeriggio, i.data), (mattino, pomeriggio, data))

    def test_validazione_manuale_preserva_form_e_database(self):
        mattino, pomeriggio = self.prepara()
        persone, iscrizioni = self.snapshot(Partecipante), self.snapshot(Iscrizione)
        for campo, valore in [*( (c, "") for c in ("nome", "cognome", "gruppo", "zona", "regione", "email", "sesso", "foca")),
                              ("email", "indirizzo-invalido"), ("incarico_altro", ""),
                              ("scelta_mattino", str(pomeriggio)), ("scelta_pomeriggio", "99999"),
                              ("sottogruppo_mattino", "C"), ("sottogruppo_pomeriggio", "a"),
                              ("gruppo_domenica", "21")]:
            with self.subTest(campo=campo, valore=valore):
                dati = {**self.persona(), "cognome": "Conservato", campo: valore}
                risposta = self.client.post("/admin/partecipanti/101/modifica", data=dati)
                self.assertEqual(risposta.status_code, 400)
                self.assertIn('value="Roma 1"' if campo == "cognome" else 'value="Conservato"', risposta.get_data(as_text=True))
                self.assertEqual(self.snapshot(Partecipante), persone)
                self.assertEqual(self.snapshot(Iscrizione), iscrizioni)

    def test_ab_solo_chiuse_conserva_assegnazioni(self):
        self.prepara()
        prima = self.snapshot(Iscrizione)
        pagina = self.client.get("/admin/iscrizioni/gruppi-ab").get_data(as_text=True)
        self.assertIn("Chiudi le iscrizioni", pagina)
        self.assertIn("disabled", pagina)
        with patch("app.ricalcola_sottogruppi_ab", side_effect=AssertionError("non calcolare")):
            risposta = self.client.post("/admin/iscrizioni/gruppi-ab/ricalcola", data={"conferma": "ricalcola"})
        self.assertEqual(risposta.status_code, 409)
        self.assertEqual(self.snapshot(Iscrizione), prima)
        db.session.get(SysOption, "stato_iscrizioni").value = "chiuse"
        db.session.commit()
        self.assertEqual(self.client.post("/admin/iscrizioni/gruppi-ab/ricalcola", data={"conferma": "ricalcola"}).status_code, 302)

    def test_aggiunta_partecipante_campi_flag_senza_iscrizione_o_gruppo(self):
        risposta = self.client.post('/admin/partecipanti/nuovo', data={**self.persona(), 'gruppo_domenica': '9'})
        self.assertEqual(risposta.status_code, 302)
        persona = db.session.get(Partecipante, 101)
        for campo, valore in self.persona().items():
            atteso = {'id': 101, 'deve_iscriversi_sabato': True, 'includi_domenica': False}.get(campo, valore)
            self.assertEqual(getattr(persona, campo), atteso)
        self.assertIsNone(persona.gruppo_domenica)
        self.assertEqual(Iscrizione.query.count(), 0)
        self.assertEqual(SysOption.query.count(), 0)

    def test_partecipante_codici_duplicati_invalidi_e_campi_obbligatori(self):
        self.client.post('/admin/partecipanti/nuovo', data=self.persona())
        prima = self.snapshot(Partecipante)
        for codice in ('101', '0', '-1', '2147483648', '1.2', '1e3', '', 'x'):
            self.assertEqual(self.client.post('/admin/partecipanti/nuovo', data=self.persona(codice)).status_code, 400)
        for campo in ('nome', 'cognome', 'gruppo', 'zona', 'regione', 'email', 'sesso', 'foca', 'deve_iscriversi_sabato', 'includi_domenica'):
            dati = self.persona(303)
            dati[campo] = ''
            self.assertEqual(self.client.post('/admin/partecipanti/nuovo', data=dati).status_code, 400)
        self.assertEqual(self.snapshot(Partecipante), prima)
        dati = self.persona(2147483647)
        for campo in ('ruolo', 'incarico_altro'):
            dati[campo] = ''
        self.assertEqual(self.client.post('/admin/partecipanti/nuovo', data=dati).status_code, 302)
        self.assertIsNone(db.session.get(Partecipante, 2147483647).ruolo)

    def test_modifica_partecipante_preserva_identita_iscrizioni_e_gruppi(self):
        self.prepara()
        iscrizioni = self.snapshot(Iscrizione)
        dati = self.persona()
        dati.update(nome='Nuovo', cognome='Cognome', email='nuovo@example.test', deve_iscriversi_sabato='false')
        risposta = self.client.post('/admin/partecipanti/101/modifica', data=dati)
        self.assertEqual(risposta.status_code, 302)
        persona = db.session.get(Partecipante, 101)
        self.assertEqual(persona.nome, 'Nuovo')
        self.assertEqual(persona.cognome, 'Cognome')
        self.assertEqual(persona.email, 'nuovo@example.test')
        self.assertFalse(persona.deve_iscriversi_sabato)
        self.assertFalse(persona.includi_domenica)
        self.assertEqual(persona.gruppo_domenica, 7)
        self.assertEqual(self.snapshot(Iscrizione), iscrizioni)
        prima = self.snapshot(Partecipante)
        dati['id'] = '999'
        self.assertEqual(self.client.post('/admin/partecipanti/101/modifica', data=dati).status_code, 400)
        self.assertEqual(self.snapshot(Partecipante), prima)

    def test_laboratori_aggiunta_due_fasce_e_duplicato_rifiutato(self):
        for fascia in ('mattino', 'pomeriggio'):
            self.assertEqual(self.client.post('/admin/laboratori/nuovo', data=self.laboratorio(fascia)).status_code, 302)
            self.assertEqual(self.client.post('/admin/laboratori/nuovo', data=self.laboratorio(fascia)).status_code, 400)
        self.assertEqual(Laboratorio.query.count(), 2)
        self.assertEqual(SysOption.query.count(), 0)

    def test_laboratorio_validazioni_e_identita_immutabile(self):
        mattino, _ = self.prepara()
        prima = self.snapshot(Laboratorio)
        for campo, valore in (('tipologia', 'pomeriggio'), ('id_lab', 'ALTRO'), ('titolo', ''),
                              ('descrizione', ''), ('posti', '0'), ('posti', '1.5'), ('posti', '2147483648')):
            dati = self.laboratorio()
            dati[campo] = valore
            self.assertEqual(self.client.post(f'/admin/laboratori/{mattino}/modifica', data=dati).status_code, 400)
        self.assertEqual(self.snapshot(Laboratorio), prima)
        for campo, valore in (('tipologia', 'domenica'), ('id_lab', ''), ('id_lab', 'x'*11)):
            dati = self.laboratorio()
            dati[campo] = valore
            self.assertEqual(self.client.post('/admin/laboratori/nuovo', data=dati).status_code, 400)

    def test_modifica_laboratorio_e_capienza_con_iscritti(self):
        mattino, pomeriggio = self.prepara()
        iscrizioni = self.snapshot(Iscrizione)
        dati = self.laboratorio()
        dati.update(titolo='Nuovo', descrizione='Aggiornata', posti='20')
        self.assertEqual(self.client.post(f'/admin/laboratori/{mattino}/modifica', data=dati).status_code, 302)
        lab = db.session.get(Laboratorio, mattino)
        self.assertEqual((lab.titolo, lab.descrizione, lab.posti), ('Nuovo', 'Aggiornata', 20))
        dati['posti'] = '2'
        self.assertEqual(self.client.post(f'/admin/laboratori/{mattino}/modifica', data=dati).status_code, 302)
        dati['posti'] = '1'
        self.assertEqual(self.client.post(f'/admin/laboratori/{mattino}/modifica', data=dati).status_code, 400)
        self.assertEqual(db.session.get(Laboratorio, mattino).posti, 2)
        dati = self.laboratorio('pomeriggio')
        dati['posti'] = '1'
        self.assertEqual(self.client.post(f'/admin/laboratori/{pomeriggio}/modifica', data=dati).status_code, 302)
        self.assertEqual(self.snapshot(Iscrizione), iscrizioni)

    def test_reset_singolo_preserva_partecipanti_altri_iscritti_e_ripartenza(self):
        mattino, _ = self.prepara()
        persone = self.snapshot(Partecipante)
        altra = Iscrizione.query.filter_by(partecipante=202).one()
        altra_prima = tuple(getattr(altra, c.name) for c in Iscrizione.__table__.columns)
        risposta = self.client.post('/admin/partecipanti/101/reset_sabato')
        self.assertEqual(risposta.status_code, 302)
        self.assertIsNone(Iscrizione.query.filter_by(partecipante=101).first())
        self.assertEqual(self.snapshot(Partecipante), persone)
        self.assertEqual(self.snapshot(Iscrizione), [altra_prima])
        # Il reset è ripetibile anche senza iscrizione.
        self.assertEqual(self.client.post('/admin/partecipanti/101/reset_sabato').status_code, 302)
        self.client.get('/logout')
        self.client.post('/verifica_iscrizione', json={'codice_socio': 101})
        self.client.post('/conferma_identita')
        self.assertTrue(self.client.get('/iscrizione').location.endswith('/laboratori/mattino'))
        self.assertEqual(self.client.post('/laboratori/mattino/salva', json={'laboratorio_id': mattino}).status_code, 200)
        self.assertEqual(Iscrizione.query.filter_by(partecipante=101).one().scelta_mattino, mattino)

    def test_reset_rimuove_anche_rinunce(self):
        self.prepara()
        iscrizione = Iscrizione.query.filter_by(partecipante=101).one()
        iscrizione.scelta_mattino = iscrizione.scelta_pomeriggio = None
        iscrizione.non_partecipa_mattino = iscrizione.non_partecipa_pomeriggio = True
        db.session.commit()
        persone = self.snapshot(Partecipante)
        self.assertEqual(self.client.post('/admin/partecipanti/101/reset_sabato').status_code, 302)
        self.assertIsNone(Iscrizione.query.filter_by(partecipante=101).first())
        self.assertEqual(self.snapshot(Partecipante), persone)

    def test_route_protette_post_reset_e_record_non_trovati(self):
        self.prepara()
        routes = ['/admin/partecipanti/nuovo', '/admin/partecipanti/101/modifica',
                  '/admin/laboratori/nuovo', '/admin/laboratori/1/modifica',
                  '/admin/partecipanti/101/reset_sabato']
        self.assertEqual(self.client.get(routes[-1]).status_code, 405)
        for route in ('/admin/partecipanti/999/modifica', '/admin/laboratori/999/modifica'):
            self.assertEqual(self.client.get(route).status_code, 404)
        self.assertEqual(self.client.post('/admin/partecipanti/999/reset_sabato').status_code, 404)
        self.client.get('/logout')
        for route in routes:
            self.assertEqual(self.client.post(route).status_code, 302)
        self.client.post('/verifica_iscrizione', json={'codice_socio': 101})
        for route in routes:
            risposta = self.client.post(route)
            self.assertEqual(risposta.status_code, 302)
            self.assertEqual(risposta.location, '/')
        self.assertEqual(Iscrizione.query.count(), 2)

    def test_rollback_modifiche_e_reset(self):
        mattino, _ = self.prepara()
        prima = {m: self.snapshot(m) for m in (Partecipante, Laboratorio, Iscrizione, SysOption)}
        dati_persona = {**self.persona(), 'nome': 'Non salvare'}
        dati_lab = {**self.laboratorio(), 'titolo': 'Non salvare'}
        for route, dati in (('/admin/partecipanti/101/modifica', dati_persona),
                            (f'/admin/laboratori/{mattino}/modifica', dati_lab),
                            ('/admin/partecipanti/101/reset_sabato', {}),
                            ('/admin/partecipanti/nuovo', self.persona(303)),
                            ('/admin/laboratori/nuovo', {**self.laboratorio(), 'id_lab': 'NUOVO'})):
            def fallisce():
                db.session.flush()
                raise SQLAlchemyError('simulato')
            with patch.object(db.session, 'commit', side_effect=fallisce):
                risposta = self.client.post(route, data=dati)
                self.assertIn(risposta.status_code, (302, 400))
            self.assertEqual({m: self.snapshot(m) for m in prima}, prima)

    def test_ui_form_e_azioni(self):
        self.prepara()
        nuova = self.client.get('/admin/partecipanti/nuovo')
        self.assertEqual(nuova.status_code, 200)
        self.assertEqual(nuova.data.count(b'Scegli s'), 2)
        self.assertIn(b'readonly', self.client.get('/admin/partecipanti/101/modifica').data)
        self.assertIn(b'readonly', self.client.get('/admin/laboratori/1/modifica').data)
        gestione = self.client.get('/admin/gestione_dati')
        self.assertIn(b'Aggiungi laboratorio', gestione.data)
        self.assertIn(b'/admin/laboratori/1/modifica', gestione.data)
        iscrizioni = self.client.get('/admin/iscrizioni')
        self.assertIn(b'/admin/partecipanti/101/modifica', iscrizioni.data)
        self.assertIn(b'onsubmit="return confirm(', iscrizioni.data)
        self.assertIn(b'Azzera iscrizioni sabato', iscrizioni.data)

    def test_elimina_partecipante_completo_preserva_altri_dati(self):
        self.prepara()
        db.session.add_all([
            SysOption(key='ultimo_import_partecipanti', value='2026-08-20'),
            SysOption(key='ultimo_ricalcolo_domenica', value='2026-08-21'),
        ])
        db.session.commit()
        prima = {m: self.snapshot(m) for m in (Partecipante, Iscrizione, Laboratorio, User, SysOption)}
        iscrizione_id = Iscrizione.query.filter_by(partecipante=101).one().id
        # Verifica l'ordine delle DELETE anche con i vincoli SQLite attivi.
        db.session.execute(text('PRAGMA foreign_keys=ON'))
        self.assertEqual(db.session.execute(text('PRAGMA foreign_keys')).scalar(), 1)
        try:
            risposta = self.client.post('/admin/partecipanti/101/elimina')
            self.assertEqual(risposta.status_code, 302)
            self.assertTrue(risposta.location.endswith('/admin/iscrizioni'))
            self.assertIsNone(db.session.get(Partecipante, 101))
            self.assertIsNone(db.session.get(Iscrizione, iscrizione_id))
            self.assertEqual(self.snapshot(Partecipante), [r for r in prima[Partecipante] if r[0] != 101])
            self.assertEqual(self.snapshot(Iscrizione), [r for r in prima[Iscrizione] if r[0] != iscrizione_id])
            for modello in (Laboratorio, User, SysOption):
                self.assertEqual(self.snapshot(modello), prima[modello])
            self.assertEqual(db.session.execute(text('PRAGMA foreign_key_check')).all(), [])
            pagina = self.client.get(risposta.location).get_data(as_text=True)
            self.assertIn('Partecipante con codice 101 eliminato definitivamente.', pagina)
            self.assertNotIn('data-codice="101"', pagina)
            self.assertIn('data-codice="202"', pagina)
            self.assertIn('id="totale-partecipanti">1<', pagina)
        finally:
            db.session.rollback()
            db.session.execute(text('PRAGMA foreign_keys=OFF'))
            db.session.commit()

    def test_elimina_partecipante_senza_iscrizione(self):
        self.client.post('/admin/partecipanti/nuovo', data=self.persona())
        risposta = self.client.post('/admin/partecipanti/101/elimina', follow_redirects=True)
        self.assertEqual(risposta.status_code, 200)
        self.assertIsNone(db.session.get(Partecipante, 101))
        self.assertEqual(Iscrizione.query.count(), 0)
        self.assertIn(b'eliminato definitivamente', risposta.data)

    def test_form_elimina_indipendente_per_ogni_partecipante(self):
        self.prepara()
        self.client.post('/admin/partecipanti/nuovo', data=self.persona(303))

        class FormParser(HTMLParser):
            def __init__(self):
                super().__init__()
                self.forms = []
                self.profondita = 0
                self.annidati = False

            def handle_starttag(self, tag, attrs):
                if tag == 'form':
                    self.annidati |= self.profondita > 0
                    self.profondita += 1
                    self.forms.append(dict(attrs))

            def handle_endtag(self, tag):
                if tag == 'form':
                    self.profondita -= 1

        parser = FormParser()
        parser.feed(self.client.get('/admin/iscrizioni').get_data(as_text=True))
        self.assertFalse(parser.annidati)
        for codice in (101, 202, 303):
            forms = [f for f in parser.forms if f.get('action') == f'/admin/partecipanti/{codice}/elimina']
            self.assertEqual(len(forms), 1)
            self.assertEqual(forms[0]['method'], 'post')
            self.assertIn('return confirm(', forms[0]['onsubmit'])
            self.assertIn(f'codice {codice}', forms[0]['onsubmit'])
            self.assertIn('non può essere annullata', forms[0]['onsubmit'])

    def test_elimina_permessi_metodo_e_id_inesistente(self):
        self.prepara()
        db.session.add(User(username='operatore', password=generate_password_hash('password')))
        db.session.commit()
        prima = {m: self.snapshot(m) for m in (Partecipante, Iscrizione, Laboratorio, User, SysOption)}
        url = '/admin/partecipanti/101/elimina'
        self.assertEqual(self.client.get(url).status_code, 405)
        self.assertEqual(self.client.post('/admin/partecipanti/999/elimina').status_code, 404)
        self.client.get('/logout')
        self.assertEqual(self.client.post(url).status_code, 302)
        self.client.post('/verifica_iscrizione', json={'codice_socio': 101})
        self.client.post('/conferma_identita')
        self.assertEqual(self.client.post(url).location, '/')
        self.client.get('/logout')
        self.client.post('/login', data={'username': 'operatore', 'passwd': 'password'})
        self.assertEqual(self.client.post(url).location, '/')
        self.assertEqual({m: self.snapshot(m) for m in prima}, prima)

    def test_elimina_rollback_dopo_delete_iscrizione_e_partecipante(self):
        self.prepara()
        prima = {m: self.snapshot(m) for m in (Partecipante, Iscrizione, Laboratorio, User, SysOption)}

        def fallisce():
            # La prima DELETE è già stata inviata dalla route.
            self.assertEqual(db.session.execute(text('SELECT COUNT(*) FROM iscrizioni WHERE partecipante = 101')).scalar(), 0)
            db.session.flush()
            self.assertEqual(db.session.execute(text('SELECT COUNT(*) FROM partecipanti WHERE id = 101')).scalar(), 0)
            raise SQLAlchemyError('dettaglio interno da non esporre')

        with patch.object(db.session, 'commit', side_effect=fallisce):
            risposta = self.client.post('/admin/partecipanti/101/elimina', follow_redirects=True)
        self.assertEqual(risposta.status_code, 200)
        self.assertIn(b'Nessuna modifica salvata.', risposta.data)
        self.assertNotIn(b'dettaglio interno', risposta.data)
        self.assertNotIn(b'eliminato definitivamente', risposta.data)
        self.assertEqual({m: self.snapshot(m) for m in prima}, prima)

    def test_sessione_eliminata_non_puo_ricreare_iscrizione(self):
        mattino, _ = self.prepara()
        partecipante_client = app.test_client()
        # Contesti separati: Flask-Login conserva current_user nel contesto applicativo.
        with app.app_context():
            partecipante_client.post('/verifica_iscrizione', json={'codice_socio': 101})
            partecipante_client.post('/conferma_identita')
            self.assertEqual(partecipante_client.get('/lista_laboratori/mattino').status_code, 200)
        with app.app_context():
            eliminazione = self.client.post('/admin/partecipanti/101/elimina')
            self.assertEqual(eliminazione.status_code, 302)
            self.assertTrue(eliminazione.location.endswith('/admin/iscrizioni'))
            self.assertIsNone(db.session.get(Partecipante, 101))
        with app.app_context():
            risposta = partecipante_client.post('/laboratori/mattino/salva', json={'laboratorio_id': mattino})
        self.assertEqual(risposta.status_code, 401)
        self.assertIsNone(db.session.get(Partecipante, 101))
        self.assertIsNone(Iscrizione.query.filter_by(partecipante=101).first())


if __name__ == '__main__':
    unittest.main()
