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
        for campo in ('nome', 'cognome', 'deve_iscriversi_sabato', 'includi_domenica'):
            dati = self.persona(303)
            dati[campo] = ''
            self.assertEqual(self.client.post('/admin/partecipanti/nuovo', data=dati).status_code, 400)
        self.assertEqual(self.snapshot(Partecipante), prima)
        dati = self.persona(2147483647)
        for campo in ('gruppo', 'zona', 'regione', 'email', 'sesso', 'foca', 'ruolo', 'incarico_altro'):
            dati[campo] = ''
        self.assertEqual(self.client.post('/admin/partecipanti/nuovo', data=dati).status_code, 302)
        self.assertIsNone(db.session.get(Partecipante, 2147483647).email)

    def test_modifica_partecipante_preserva_identita_iscrizioni_e_gruppi(self):
        self.prepara()
        iscrizioni = self.snapshot(Iscrizione)
        dati = self.persona()
        dati.update(nome='Nuovo', cognome='Cognome', email='', deve_iscriversi_sabato='false', gruppo_domenica='2')
        risposta = self.client.post('/admin/partecipanti/101/modifica', data=dati)
        self.assertEqual(risposta.status_code, 302)
        persona = db.session.get(Partecipante, 101)
        self.assertEqual(persona.nome, 'Nuovo')
        self.assertEqual(persona.cognome, 'Cognome')
        self.assertIsNone(persona.email)
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


if __name__ == '__main__':
    unittest.main()
