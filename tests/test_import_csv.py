import csv
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import unittest
from datetime import datetime
from unittest.mock import patch

os.environ["DB_TYPE"] = "sqlite"
os.environ["DB_NAME"] = ":memory:"
os.environ["SECRET_KEY"] = "test-secret-key"

from sqlalchemy.exc import SQLAlchemyError
from werkzeug.security import generate_password_hash
from app import (
    app, db, COLONNE_CSV_PARTECIPANTI, Partecipante, Iscrizione, Laboratorio,
    SysOption, User, valida_import_partecipanti,
)


def riga_valida(codice=101):
    return {
        "id": codice, "nome": "Anna", "cognome": "Rossi", "gruppo": "Roma 1",
        "zona": "Roma", "regione": "Lazio", "email": "contatto@example.test",
        "sesso": "F", "foca": "CFA", "ruolo": "Altro", "incarico_altro": "Supporto",
        "deve_iscriversi_sabato": "Sì", "includi_domenica": "No",
    }


class ImportCsvTestCase(unittest.TestCase):
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

    def importa(self, righe, route="/import_iscritti"):
        return self.client.post(route, json=righe)

    def snapshot(self, modello):
        return [tuple(getattr(riga, colonna.name) for colonna in modello.__table__.columns)
                for riga in modello.query.all()]


    def test_dettaglio_nuovi_modificati_invariati(self):
        nuovo = self.importa([riga_valida()]).json
        self.assertIn("101 – Rossi Anna: nuovo", nuovo["dettaglio"])
        identico = self.importa([riga_valida()]).json
        self.assertEqual((identico["aggiornati"], identico["invariati"], identico["dettaglio"]), (0, 1, []))
        dati = riga_valida()
        dati.update(email="nuova@example.test", zona="Nuova zona")
        modificato = self.importa([dati, riga_valida(202)]).json
        self.assertEqual([modificato[k] for k in ("inseriti", "aggiornati", "invariati", "totale")], [1, 1, 0, 2])
        self.assertIn("101 – Rossi Anna: modificati Zona, Email", modificato["dettaglio"])
        pagina = self.client.get("/import_iscritti").get_data(as_text=True)
        self.assertIn("<details", pagina)
        self.assertNotIn("<details open", pagina)


    def test_preview_confronto_senza_scritture_e_conferma_dati_correnti(self):
        self.prepara_esistenti()
        self.importa([riga_valida()])
        modelli = (Partecipante, Laboratorio, Iscrizione, SysOption)
        prima = {m: self.snapshot(m) for m in modelli}
        cambiata = {**riga_valida(303), "email": "nuova@example.test"}
        righe = [riga_valida(), cambiata, riga_valida(404)]
        with patch.object(db.session, "commit", side_effect=AssertionError("preview scrive")), \
             patch.object(db.session, "add", side_effect=AssertionError("preview inserisce")):
            risposta = self.importa(righe, "/import_iscritti/valida")
        self.assertEqual(risposta.status_code, 200)
        self.assertEqual([risposta.json[k] for k in ("inseriti", "aggiornati", "invariati", "totale")], [1, 1, 1, 3])
        self.assertIn("404 – Rossi Anna: nuovo", risposta.json["dettaglio"])
        self.assertIn("Email", risposta.json["dettaglio"][0])
        self.assertEqual({m: self.snapshot(m) for m in modelli}, prima)
        # Una modifica effettuata dopo la preview deve entrare nel confronto finale.
        db.session.get(Partecipante, 101).email = "intervenuta@example.test"
        db.session.commit()
        conferma = self.importa(righe)
        self.assertEqual(conferma.status_code, 200)
        self.assertEqual([conferma.json[k] for k in ("inseriti", "aggiornati", "invariati")], [1, 2, 0])
        self.assertIn("101 – Rossi Anna: modificati Email", conferma.json["dettaglio"])
        self.assertEqual(db.session.get(Partecipante, 101).email, riga_valida()["email"])
        self.assertEqual(self.snapshot(Iscrizione), prima[Iscrizione])

    def test_preview_non_autorizza_payload_invalido_o_scritture_parziali(self):
        righe = [riga_valida(), riga_valida(202)]
        self.assertEqual(self.importa(righe, "/import_iscritti/valida").status_code, 200)
        righe[1]["includi_domenica"] = "invalido"
        self.assertEqual(self.importa(righe).status_code, 400)
        self.assertEqual(Partecipante.query.count(), 0)
        self.assertEqual(SysOption.query.count(), 0)

    def prepara_esistenti(self):
        db.session.add_all([
            Partecipante(id=101, nome="Prima", cognome="Originale", gruppo_domenica=7,
                         includi_domenica=True, email="prima@example.test"),
            Partecipante(id=303, nome="Assente", cognome="Dal CSV", gruppo_domenica=8,
                         includi_domenica=True, email="assente@example.test"),
            Laboratorio(id=1, id_lab="M01", titolo="Bosco", descrizione="Bosco",
                        posti=20, tipologia="mattino"),
            Laboratorio(id=2, id_lab="P01", titolo="Tracce", descrizione="Tracce",
                        posti=20, tipologia="pomeriggio"),
            SysOption(key="ultimo_import_partecipanti", value="2026-08-20T12:00:00+02:00"),
        ])
        db.session.commit()
        db.session.add_all([
            Iscrizione(partecipante=101, scelta_mattino=1, scelta_pomeriggio=2,
                       sottogruppo_mattino="A", sottogruppo_pomeriggio="B",
                       data=datetime(2026, 8, 20, 12)),
            Iscrizione(partecipante=303, non_partecipa_mattino=True,
                       non_partecipa_pomeriggio=True, data=datetime(2026, 8, 20, 13)),
        ])
        db.session.commit()

    def test_inserimento_mapping_e_riepilogo(self):
        riga = riga_valida()
        riga.update(EmailReferente="referente@example.test", BC="privato", PIC="privato",
                    DataNascita="privato", CAP="privato", PR="privato", **{"Città": "privato"})
        riga["gruppo_domenica"] = 19
        risposta = self.importa([riga, riga_valida(202)])
        self.assertEqual(risposta.status_code, 200)
        risultato = risposta.get_json()
        self.assertEqual((risultato["inseriti"], risultato["aggiornati"], risultato["totale"]), (2, 0, 2))
        self.assertNotEqual(risultato["ultimo_import"], "mai")
        persona = db.session.get(Partecipante, 101)
        for campo, valore in riga_valida().items():
            atteso = {"deve_iscriversi_sabato": True, "includi_domenica": False}.get(campo, valore)
            self.assertEqual(getattr(persona, campo), atteso)
        self.assertIsNone(persona.gruppo_domenica)
        self.assertNotIn("referente@example.test", str(self.snapshot(Partecipante)))
        self.assertEqual(Iscrizione.query.count(), 0)

    def test_upsert_preserva_assenti_iscrizioni_e_assegnazioni(self):
        self.prepara_esistenti()
        assente = self.snapshot(Partecipante)[1]
        iscrizioni = self.snapshot(Iscrizione)
        laboratori = self.snapshot(Laboratorio)
        riga = riga_valida()
        riga.update(deve_iscriversi_sabato="No", gruppo_domenica=19,
                    sottogruppo_mattino="B", sottogruppo_pomeriggio="A")
        risposta = self.importa([riga, riga_valida(202)])
        self.assertEqual(risposta.status_code, 200)
        risultato = risposta.get_json()
        self.assertEqual((risultato["inseriti"], risultato["aggiornati"], risultato["totale"]), (1, 1, 2))
        persona = db.session.get(Partecipante, 101)
        self.assertEqual(persona.nome, "Anna")
        self.assertEqual(persona.cognome, "Rossi")
        self.assertEqual(persona.email, "contatto@example.test")
        self.assertFalse(persona.includi_domenica)
        self.assertFalse(persona.deve_iscriversi_sabato)
        self.assertEqual(persona.gruppo_domenica, 7)
        self.assertIn(assente, self.snapshot(Partecipante))
        self.assertEqual(self.snapshot(Iscrizione), iscrizioni)
        self.assertEqual(self.snapshot(Laboratorio), laboratori)
        # Anche una rinuncia esplicita della persona reimportata resta invariata.
        self.assertEqual(self.importa([riga_valida(303)]).status_code, 200)
        self.assertEqual(self.snapshot(Iscrizione), iscrizioni)

    def test_anteprima_senza_scritture_e_stessa_validazione(self):
        self.prepara_esistenti()
        prima = self.snapshot(Partecipante)
        timestamp = self.snapshot(SysOption)
        risposta = self.importa([riga_valida()], "/import_iscritti/valida")
        self.assertEqual(risposta.status_code, 200)
        self.assertIs(risposta.get_json()["partecipanti"][0]["deve_iscriversi_sabato"], True)
        self.assertEqual(self.snapshot(Partecipante), prima)
        self.assertEqual(self.snapshot(SysOption), timestamp)
        invalida = riga_valida()
        invalida["includi_domenica"] = "forse"
        for route in ("/import_iscritti/valida", "/import_iscritti"):
            self.assertEqual(self.importa([invalida], route).status_code, 400)

    def test_flag_varianti_true_false_per_entrambi_i_campi(self):
        for campo in ("deve_iscriversi_sabato", "includi_domenica"):
            for atteso, valori in (
                (True, ("Sì", "Si", "S", "Yes", "True", "1", " SÌ ", " yEs ", True)),
                (False, ("No", "N", "False", "0", " nO ", " fAlSe ", False)),
            ):
                for valore in valori:
                    with self.subTest(campo=campo, valore=valore):
                        riga = riga_valida()
                        riga[campo] = valore
                        dati, errore = valida_import_partecipanti([riga])
                        self.assertIsNone(errore)
                        self.assertIs(dati[0][campo], atteso)

    def test_flag_vuoti_sconosciuti_o_mancanti_rifiutati(self):
        for campo in ("deve_iscriversi_sabato", "includi_domenica"):
            for valore in ("", " ", "forse", "2", None, [], 2):
                with self.subTest(campo=campo, valore=valore):
                    riga = riga_valida()
                    riga[campo] = valore
                    self.assertEqual(self.importa([riga]).status_code, 400)
            riga = riga_valida()
            del riga[campo]
            self.assertEqual(self.importa([riga]).status_code, 400)
        self.assertEqual(Partecipante.query.count(), 0)

    def test_codici_invalidi_duplicati_e_file_vuoto(self):
        for codice in (0, -1, 2147483648, 1.5, True, None, "101"):
            with self.subTest(codice=codice):
                self.assertEqual(self.importa([riga_valida(codice)]).status_code, 400)
        self.assertEqual(self.importa([riga_valida(), riga_valida()]).status_code, 400)
        self.assertEqual(self.importa([]).status_code, 400)
        self.assertEqual(self.importa([riga_valida(2147483647)]).status_code, 200)

    def test_intestazioni_payload_tutte_obbligatorie(self):
        for campo in COLONNE_CSV_PARTECIPANTI.values():
            riga = riga_valida()
            del riga[campo]
            with self.subTest(campo=campo):
                self.assertEqual(self.importa([riga]).status_code, 400)

    def test_nome_cognome_e_lunghezze(self):
        for campo, valori in (
            ("nome", ("", " ", None, "N" * 256)),
            ("cognome", ("", " ", None, "C" * 256)),
            ("sesso", ("F" * 51,)),
            ("incarico_altro", ("è" * 32768,)),
        ):
            for valore in valori:
                riga = riga_valida()
                riga[campo] = valore
                self.assertEqual(self.importa([riga]).status_code, 400)
        for campo in ("gruppo", "zona", "regione", "email", "foca", "ruolo"):
            riga = riga_valida()
            riga[campo] = "x" * 256
            self.assertEqual(self.importa([riga]).status_code, 400)

    def test_facoltativi_vuoti_azzerano_vecchi_valori(self):
        self.assertEqual(self.importa([riga_valida()]).status_code, 200)
        riga = riga_valida()
        facoltativi = ("gruppo", "zona", "regione", "email", "sesso", "foca", "ruolo", "incarico_altro")
        for campo in facoltativi:
            riga[campo] = "   "
        self.assertEqual(self.importa([riga]).status_code, 200)
        persona = db.session.get(Partecipante, 101)
        for campo in facoltativi:
            self.assertIsNone(getattr(persona, campo))

    def test_riga_invalida_non_aggiorna_ne_inserisce(self):
        self.prepara_esistenti()
        prima = self.snapshot(Partecipante)
        timestamp = self.snapshot(SysOption)
        invalida = riga_valida(404)
        invalida["includi_domenica"] = ""
        self.assertEqual(self.importa([riga_valida(), riga_valida(202), invalida]).status_code, 400)
        self.assertEqual(self.snapshot(Partecipante), prima)
        self.assertEqual(self.snapshot(SysOption), timestamp)

    def test_errore_db_rollback_aggiornamenti_inserimenti_e_timestamp(self):
        self.prepara_esistenti()
        prima = self.snapshot(Partecipante)
        iscrizioni = self.snapshot(Iscrizione)
        timestamp = self.snapshot(SysOption)
        with patch.object(db.session, "commit", side_effect=SQLAlchemyError("simulato")):
            self.assertEqual(self.importa([riga_valida(), riga_valida(202)]).status_code, 500)
        self.assertEqual(self.snapshot(Partecipante), prima)
        self.assertEqual(self.snapshot(Iscrizione), iscrizioni)
        self.assertEqual(self.snapshot(SysOption), timestamp)

    def test_anteprima_richiede_admin(self):
        self.client.get("/logout")
        self.assertEqual(self.importa([riga_valida()], "/import_iscritti/valida").status_code, 302)
        db.session.add(Partecipante(id=101, nome="Anna", cognome="Rossi"))
        db.session.commit()
        self.client.post("/verifica_iscrizione", json={"codice_socio": 101})
        self.assertEqual(self.importa([riga_valida()], "/import_iscritti/valida").status_code, 403)


@unittest.skipUnless(shutil.which("node") and os.environ.get("SHEETJS_TEST_PATH"),
                     "richiede Node e SHEETJS_TEST_PATH (SheetJS 0.18.5)")
class ParserCsvBrowserTestCase(unittest.TestCase):
    def genera_csv(self, righe=None, intestazioni=None, newline="\r\n"):
        intestazioni = intestazioni or list(COLONNE_CSV_PARTECIPANTI) + ["EmailReferente", "PIC"]
        buffer = io.StringIO()
        writer = csv.writer(buffer, delimiter=";", lineterminator=newline)
        writer.writerow(intestazioni)
        for riga in righe if righe is not None else [riga_valida()]:
            writer.writerow([riga.get(COLONNE_CSV_PARTECIPANTI.get(nome), "IGNORATO") for nome in intestazioni])
        return buffer.getvalue()

    def parse(self, contenuto, **opzioni):
        risultato = subprocess.run(
            [shutil.which("node"), str(Path(__file__).with_name("csv_browser_runner.js"))],
            input=json.dumps({"mapping": COLONNE_CSV_PARTECIPANTI, "csv": contenuto, **opzioni}),
            text=True, capture_output=True, timeout=20,
        )
        self.assertEqual(risultato.returncode, 0, risultato.stderr)
        return json.loads(risultato.stdout)

    def test_pagina_valida_prima_di_importare_e_mostra_riepilogo(self):
        validati, errore = valida_import_partecipanti([riga_valida()])
        self.assertIsNone(errore)
        risultato = self.parse(self.genera_csv(), mode="flow",
                               anteprima={"ok": True, "partecipanti": validati, "inseriti": 1, "aggiornati": 0,
                                          "invariati": 0, "totale": 1, "dettaglio": ["101 – Rossi Anna: nuovo"]})
        self.assertTrue(risultato["ok"], risultato)
        self.assertEqual(risultato["prima"]["chiamate"], 1)
        self.assertEqual(risultato["prima"]["dettaglio"], ["101 – Rossi Anna: nuovo"])
        self.assertIn("1 nuovi, 0 modificati, 0 invariati, 1", risultato["prima"]["riepilogo"])
        self.assertTrue(risultato["prima"]["puoCaricare"])
        self.assertEqual(risultato["prima"]["rows"], validati)
        self.assertEqual(risultato["prima"]["fileInput"], "")
        self.assertEqual([c["url"] for c in risultato["chiamate"]],
                         ["/import_iscritti/valida", "/import_iscritti"])
        self.assertEqual(risultato["chiamate"][1]["payload"], validati)
        self.assertNotIn("IGNORATO", json.dumps(risultato["chiamate"]))
        self.assertEqual(risultato["riepilogo"],
                         "Import completato: 1 nuovi inseriti, 0 modificati, 0 invariati, 1 righe elaborate.")
        self.assertEqual(risultato["ultimoImport"], "06/09/2026 16:00")
        self.assertFalse(risultato["puoCaricare"])

    def test_pagina_blocca_import_se_anteprima_non_valida(self):
        risultato = self.parse(self.genera_csv(), mode="flow",
                               anteprima={"ok": False, "errore": "Flag non valido"})
        self.assertTrue(risultato["ok"], risultato)
        self.assertEqual(len(risultato["chiamate"]), 1)
        self.assertFalse(risultato["prima"]["puoCaricare"])
        self.assertEqual(risultato["prima"]["rows"], [])
        self.assertEqual(risultato["errore"], "Flag non valido")
        self.assertEqual(risultato["riepilogo"], "")

    def test_csv_bom_accenti_virgolette_delimitatore_e_newline(self):
        riga = riga_valida()
        riga.update(nome="Niccolò", cognome="D’Angiò", gruppo='Roma; gruppo "Avventura"',
                    incarico_altro="Prima riga\nSeconda riga")
        for newline in ("\n", "\r\n"):
            with self.subTest(newline=newline):
                risultato = self.parse("\ufeff" + self.genera_csv([riga], newline=newline))
                self.assertTrue(risultato["ok"], risultato)
                self.assertEqual(risultato["rows"], [riga])
                dati, errore = valida_import_partecipanti(risultato["rows"])
                self.assertIsNone(errore)
                self.assertEqual(dati[0]["email"], "contatto@example.test")
                self.assertNotIn("IGNORATO", json.dumps(dati))

    def test_csv_vuoto_solo_intestazioni_colonna_mancante_o_duplicata(self):
        headers = list(COLONNE_CSV_PARTECIPANTI)
        for contenuto in ("", "\ufeff \n", self.genera_csv([]),
                          self.genera_csv(intestazioni=headers[1:]),
                          self.genera_csv(intestazioni=headers + ["Nome"])):
            self.assertFalse(self.parse(contenuto)["ok"])

    def test_codici_csv_invalidi_e_duplicati(self):
        for codice in ("", "1.5", "1e2", "0x10", "-1", "0", "2147483648"):
            with self.subTest(codice=codice):
                self.assertFalse(self.parse(self.genera_csv([riga_valida(codice)]))["ok"])
        self.assertFalse(self.parse(self.genera_csv([riga_valida(), riga_valida()]))["ok"])

    def test_csv_intestazioni_riordinate_e_righe_vuote(self):
        riga = riga_valida()
        risultato = self.parse(self.genera_csv([riga], list(reversed(COLONNE_CSV_PARTECIPANTI))) + "\r\n;;\r\n")
        self.assertTrue(risultato["ok"], risultato)
        self.assertEqual(risultato["rows"], [riga])


if __name__ == "__main__":
    unittest.main()
