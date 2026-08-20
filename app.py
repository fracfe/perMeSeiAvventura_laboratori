from flask import Flask, render_template, redirect, jsonify, request, url_for, flash, send_from_directory, send_file, session
from flask_login import UserMixin, login_user, LoginManager, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.utils import secure_filename
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import aliased
from openpyxl import Workbook
from datetime import datetime
from zoneinfo import ZoneInfo
import pandas as pd
import string
import json
import io
import os

drivers = {
    "sqlite": "sqlite:///",
    "mariadb": "mysql+pymysql://",
}

# Inizializza app e servizi
app = Flask(__name__)
db_type = os.environ["DB_TYPE"]

if db_type not in drivers:
    app.logger.info("Tipo di database non supportato")
    raise RuntimeError("Tipo di database non supportato")

if db_type == "sqlite":
    uri = f"{drivers[db_type]}{os.environ['DB_NAME']}"
else:
    uri = (
        f"{drivers[db_type]}"
        f"{os.environ['DB_USER']}:"
        f"{os.environ['DB_PASSWORD']}@"
        f"{os.environ['DB_HOST']}:"
        f"{os.environ['DB_PORT']}/"
        f"{os.environ['DB_NAME']}"
    )
app.config["SQLALCHEMY_DATABASE_URI"] =  uri
app.config["SECRET_KEY"] = os.environ['SECRET_KEY']
if db_type == "mariadb":
    app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {"isolation_level": "READ COMMITTED"}
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
db = SQLAlchemy(app)

login_manager = LoginManager(app)
login_manager.login_view = "index"
login_manager.login_message = u"Sessione scaduta!"

# Classi Database
class User(db.Model, UserMixin):
    __tablename__ = "user"
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(255), nullable=False, unique=True)
    password = db.Column(db.String(255), nullable=False)

class Iscrizione(db.Model):
    __tablename__ = "iscrizioni"
    __table_args__ = (
        db.UniqueConstraint("partecipante", name="uq_iscrizioni_partecipante"),
    )
    id = db.Column(db.Integer, primary_key=True)
    data = db.Column(db.DateTime, nullable=False)
    partecipante = db.Column(db.Integer, db.ForeignKey("partecipanti.id", name="fk_iscrizioni_partecipanti_id"), nullable=False)
    scelta_mattino = db.Column(db.Integer, db.ForeignKey("laboratori.id", name="fk_iscrizioni_laboratori_mattino_id"), nullable=True)
    scelta_pomeriggio = db.Column(db.Integer, db.ForeignKey("laboratori.id", name="fk_iscrizioni_laboratori_pomeriggio_id"), nullable=True)

class Partecipante(db.Model):
    __tablename__ = "partecipanti"
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(255), nullable=False)
    cognome = db.Column(db.String(255), nullable=False)

class Laboratorio(db.Model):
    __tablename__ = "laboratori"
    id = db.Column(db.Integer, primary_key=True)
    id_lab = db.Column(db.String(10), nullable=False)
    titolo = db.Column(db.String(255), nullable=False)
    descrizione = db.Column(db.Text, nullable=False)
    posti = db.Column(db.Integer, nullable=False)
    tipologia = db.Column(db.String(10), nullable=False)

class SysOption(db.Model):
    __tablename__ = "system_option"
    key = db.Column(db.String(128), primary_key=True)
    value = db.Column(db.String(128), nullable=False)

migrate = Migrate(app, db)

STATO_ISCRIZIONI_KEY = "stato_iscrizioni"
MESSAGGIO_ISCRIZIONI_KEY = "messaggio_iscrizioni"
ULTIMO_IMPORT_PARTECIPANTI_KEY = "ultimo_import_partecipanti"
ULTIMO_IMPORT_LABORATORI_KEY = "ultimo_import_laboratori"
STATI_ISCRIZIONI_VALIDI = ("aperte", "chiuse")
MAX_INTEGER_DATABASE = 2147483647
MAX_TESTO_DATABASE = 65535

def get_stato_iscrizioni():
    opzione = db.session.get(SysOption, STATO_ISCRIZIONI_KEY)
    if opzione is None or opzione.value not in STATI_ISCRIZIONI_VALIDI:
        return "chiuse"
    return opzione.value

def get_messaggio_iscrizioni():
    opzione = db.session.get(SysOption, MESSAGGIO_ISCRIZIONI_KEY)
    if opzione is None:
        return ""
    return opzione.value

def set_sys_option(key, value):
    opzione = db.session.get(SysOption, key)
    if opzione is None:
        db.session.add(SysOption(key=key, value=value))
    else:
        opzione.value = value

def registra_ultimo_import(key):
    data_import = datetime.now(ZoneInfo("Europe/Rome")).isoformat()
    set_sys_option(key, data_import)

def get_ultimo_import(key):
    opzione = db.session.get(SysOption, key)
    if opzione is None:
        return "mai"
    try:
        data_import = datetime.fromisoformat(opzione.value)
    except ValueError:
        return "mai"
    return data_import.strftime("%d/%m/%Y %H:%M")

def valida_import_partecipanti(dati):
    if not isinstance(dati, list):
        return None, "Il payload deve contenere una lista di partecipanti."
    if not dati:
        return None, "Il file deve contenere almeno un partecipante."

    partecipanti_validati = []
    codici_visti = set()
    for indice, riga in enumerate(dati, start=1):
        if not isinstance(riga, dict):
            return None, f"La riga {indice} non contiene un partecipante valido."

        for campo in ("id", "nome", "cognome"):
            if campo not in riga:
                return None, f'Manca il campo "{campo}" nella riga {indice}.'

        partecipante_id = riga["id"]
        if (
            isinstance(partecipante_id, bool)
            or not isinstance(partecipante_id, int)
            or partecipante_id <= 0
            or partecipante_id > MAX_INTEGER_DATABASE
        ):
            return None, f"La riga {indice} contiene un codice censimento non valido."
        if partecipante_id in codici_visti:
            return None, (
                f"La riga {indice} contiene il codice censimento "
                f"duplicato {partecipante_id}."
            )
        codici_visti.add(partecipante_id)

        nome = riga["nome"]
        if not isinstance(nome, str) or not nome.strip():
            return None, f"Manca il nome nella riga {indice}."
        nome = nome.strip()
        if len(nome) > 255:
            return None, f"Il nome nella riga {indice} supera 255 caratteri."

        cognome = riga["cognome"]
        if not isinstance(cognome, str) or not cognome.strip():
            return None, f"Manca il cognome nella riga {indice}."
        cognome = cognome.strip()
        if len(cognome) > 255:
            return None, f"Il cognome nella riga {indice} supera 255 caratteri."

        partecipanti_validati.append(
            {
                "id": partecipante_id,
                "nome": nome,
                "cognome": cognome,
            }
        )

    return partecipanti_validati, None

def valida_import_laboratori(dati):
    if not isinstance(dati, dict):
        return None, "Il payload dei laboratori non è valido."

    laboratori_validati = {}
    for chiave, fascia in (
        ("lab_mattino", "mattino"),
        ("lab_pomeriggio", "pomeriggio"),
    ):
        if chiave not in dati:
            return None, f'Manca l\'elenco "{chiave}".'

        righe = dati[chiave]
        if not isinstance(righe, list):
            return None, f'L\'elenco "{chiave}" deve essere una lista.'
        if not righe:
            return None, (
                "Il file deve contenere almeno un laboratorio del mattino "
                "e uno del pomeriggio."
            )

        righe_validate = []
        for indice, riga in enumerate(righe, start=1):
            riferimento = f"riga {indice} dei laboratori del {fascia}"
            if not isinstance(riga, dict):
                return None, f"La {riferimento} non è valida."

            for campo in ("id", "titolo", "descrizione", "posti"):
                if campo not in riga:
                    return None, f'Manca il campo "{campo}" nella {riferimento}.'

            id_lab = riga["id"]
            if not isinstance(id_lab, str) or not id_lab.strip():
                return None, f"Manca il codice laboratorio nella {riferimento}."
            id_lab = id_lab.strip()
            if len(id_lab) > 10:
                return None, f"Il codice laboratorio nella {riferimento} supera 10 caratteri."

            titolo = riga["titolo"]
            if not isinstance(titolo, str) or not titolo.strip():
                return None, f"Manca il titolo nella {riferimento}."
            titolo = titolo.strip()
            if len(titolo) > 255:
                return None, f"Il titolo nella {riferimento} supera 255 caratteri."

            descrizione = riga["descrizione"]
            if not isinstance(descrizione, str) or not descrizione.strip():
                return None, f"Manca la descrizione nella {riferimento}."
            descrizione = descrizione.strip()
            if len(descrizione.encode("utf-8")) > MAX_TESTO_DATABASE:
                return None, f"La descrizione nella {riferimento} è troppo lunga."

            posti = riga["posti"]
            if (
                isinstance(posti, bool)
                or not isinstance(posti, int)
                or posti <= 0
                or posti > MAX_INTEGER_DATABASE
            ):
                return None, f"Il laboratorio {id_lab} ha una capienza non valida."

            righe_validate.append(
                {
                    "id": id_lab,
                    "titolo": titolo,
                    "descrizione": descrizione,
                    "posti": posti,
                }
            )

        laboratori_validati[chiave] = righe_validate

    return laboratori_validati, None

def get_partecipante_corrente(richiedi_conferma=True):
    if not current_user.is_authenticated:
        return None
    if richiedi_conferma and not session.get("identita_confermata", False):
        return None
    user_id = str(current_user.get_id())
    if not user_id.startswith("temp:"):
        return None
    try:
        partecipante_id = int(user_id.removeprefix("temp:"))
    except ValueError:
        return None
    return db.session.get(Partecipante, partecipante_id)

def get_iscrizione_partecipante(partecipante_id):
    return Iscrizione.query.filter_by(partecipante=partecipante_id).first()

def iscrizione_completa(iscrizione):
    return (
        iscrizione is not None
        and iscrizione.scelta_mattino is not None
        and iscrizione.scelta_pomeriggio is not None
    )

def ora_roma():
    return datetime.now(ZoneInfo("Europe/Rome")).replace(tzinfo=None)

class TemporaryUser(UserMixin):
    def __init__(self, id):
        self.id = id
        self.username = id

@app.cli.command("init_db")
def init_db():
    try:
        db.session.add(User(username="admin", password=generate_password_hash("password")))
        print("Utente 'admin' creato con password: 'password'")
        db.session.commit()
        print("Operazione terminata correttamente!")
    except Exception as e:
        print("Qualcosa è andato storto!")
        print(e)

@app.cli.command("reset")
def reset_tool():
    Iscrizione.query.delete()
    Partecipante.query.delete()
    Laboratorio.query.delete()
    db.session.commit()
    print("Reset tool!")

@login_manager.user_loader
def load_user(user_id):
    # Utente temporaneo
    if user_id.startswith("temp:"):
        temp_data = session.get("temp_user")
        if temp_data and temp_data["id"] == user_id:
            return TemporaryUser(
                temp_data["id"]
            )
        return None

    # Utente permanente
    return User.query.get(int(user_id))

@app.route("/")
def index():
    return render_template(
        "index.html",
        stato_iscrizioni=get_stato_iscrizioni(),
        messaggio_iscrizioni=get_messaggio_iscrizioni(),
    )

@app.route("/verifica_iscrizione", methods=["POST"])
def verifica_iscrizione():
    dati = request.get_json(silent=True)
    output = {
        "stato_verifica": False,
        "nome": "",
        "cognome": "",
    }
    if not dati or "codice_socio" not in dati:
        return {**output, "errore": "Inserisci un codice censimento valido."}, 400

    try:
        partecipante_id = int(dati["codice_socio"])
    except (TypeError, ValueError):
        partecipante_id = None

    partecipante = db.session.get(Partecipante, partecipante_id)
    if partecipante is None:
        if str(session.get("_user_id", "")).startswith("temp:"):
            logout_user()
        session.pop("temp_user", None)
        session.pop("identita_confermata", None)
        return {**output, "errore": "Codice censimento non trovato."}, 404

    output["stato_verifica"] = True
    output["nome"] = partecipante.nome
    output["cognome"] = partecipante.cognome

    temp_id = f"temp:{partecipante.id}"
    session["temp_user"] = {
        "id": temp_id
    }
    session["identita_confermata"] = False
    login_user(
        TemporaryUser(
            temp_id
        )
    )
    return output

@app.route("/conferma_identita", methods=["POST"])
def conferma_identita():
    partecipante = get_partecipante_corrente(richiedi_conferma=False)
    if partecipante is None:
        return redirect(url_for("index"))
    session["identita_confermata"] = True
    return redirect(url_for("percorso_iscrizione"))

@app.route("/iscrizione")
def percorso_iscrizione():
    partecipante = get_partecipante_corrente()
    if partecipante is None:
        return redirect(url_for("index"))

    iscrizione = get_iscrizione_partecipante(partecipante.id)
    if get_stato_iscrizioni() == "chiuse":
        return redirect(url_for("riepilogo_iscrizione"))
    if iscrizione is None or iscrizione.scelta_mattino is None:
        return redirect(url_for("scelta_laboratorio", tipologia="mattino"))
    if iscrizione.scelta_pomeriggio is None:
        return redirect(url_for("scelta_laboratorio", tipologia="pomeriggio"))
    return redirect(url_for("riepilogo_iscrizione"))

@app.route("/laboratori")
def laboratori():
    return redirect(url_for("percorso_iscrizione"))

@app.route("/laboratori/<tipologia>")
def scelta_laboratorio(tipologia):
    if tipologia not in ("mattino", "pomeriggio"):
        return render_template("errore_generico.html"), 404

    partecipante = get_partecipante_corrente()
    if partecipante is None:
        return redirect(url_for("index"))
    if get_stato_iscrizioni() != "aperte":
        return redirect(url_for("riepilogo_iscrizione"))

    iscrizione = get_iscrizione_partecipante(partecipante.id)
    modifica = request.args.get("modifica") == "1"

    if tipologia == "pomeriggio" and (
        iscrizione is None or iscrizione.scelta_mattino is None
    ):
        return redirect(url_for("scelta_laboratorio", tipologia="mattino"))

    scelta_corrente = None
    if iscrizione is not None:
        scelta_corrente = getattr(iscrizione, f"scelta_{tipologia}")

    if modifica:
        if not iscrizione_completa(iscrizione) or scelta_corrente is None:
            return redirect(url_for("percorso_iscrizione"))
    elif scelta_corrente is not None:
        return redirect(url_for("percorso_iscrizione"))

    return render_template(
        "laboratori.html",
        tipologia=tipologia,
        scelta_corrente=scelta_corrente,
        modifica=modifica,
    )

@app.route("/lista_laboratori/<tipologia>")
def lista_laboratori(tipologia):
    if tipologia not in ("mattino", "pomeriggio"):
        return {"ok": False, "errore": "Tipologia laboratorio non valida."}, 400

    partecipante = get_partecipante_corrente()
    if partecipante is None:
        return {"ok": False, "errore": "Sessione scaduta."}, 401
    if get_stato_iscrizioni() != "aperte":
        return {"ok": False, "errore": "Le iscrizioni sono chiuse."}, 403

    iscrizione = get_iscrizione_partecipante(partecipante.id)
    scelta_corrente = (
        getattr(iscrizione, f"scelta_{tipologia}") if iscrizione else None
    )
    colonna_scelta = getattr(Iscrizione, f"scelta_{tipologia}")
    conteggi = dict(
        db.session.query(colonna_scelta, func.count(Iscrizione.id))
        .filter(colonna_scelta.is_not(None))
        .group_by(colonna_scelta)
        .all()
    )

    laboratori_output = []
    for laboratorio in Laboratorio.query.filter_by(tipologia=tipologia).order_by(
        Laboratorio.id_lab
    ):
        occupati = conteggi.get(laboratorio.id, 0)
        posseduto = scelta_corrente == laboratorio.id
        posti_disponibili = max(laboratorio.posti - occupati, 0)
        laboratori_output.append(
            {
                "id": laboratorio.id,
                "id_lab": laboratorio.id_lab,
                "titolo": laboratorio.titolo,
                "descrizione": laboratorio.descrizione,
                "posti": laboratorio.posti,
                "posti_disponibili": posti_disponibili,
                "posseduto": posseduto,
                "selezionabile": posseduto or posti_disponibili > 0,
            }
        )
    return {"ok": True, "laboratori": laboratori_output}

@app.route("/laboratori/<tipologia>/salva", methods=["POST"])
def salva_laboratorio(tipologia):
    if tipologia not in ("mattino", "pomeriggio"):
        return {"ok": False, "errore": "Tipologia laboratorio non valida."}, 400
    if get_stato_iscrizioni() != "aperte":
        return {"ok": False, "errore": "Le iscrizioni sono chiuse."}, 403

    partecipante_sessione = get_partecipante_corrente()
    if partecipante_sessione is None:
        return {"ok": False, "errore": "Sessione scaduta."}, 401

    dati = request.get_json(silent=True)
    if not dati or "laboratorio_id" not in dati:
        return {"ok": False, "errore": "Seleziona un laboratorio valido."}, 400
    try:
        laboratorio_id = int(dati["laboratorio_id"])
    except (TypeError, ValueError):
        return {"ok": False, "errore": "Laboratorio non valido."}, 400

    try:
        partecipante = db.session.execute(
            db.select(Partecipante)
            .where(Partecipante.id == partecipante_sessione.id)
            .with_for_update()
        ).scalar_one_or_none()
        if partecipante is None:
            db.session.rollback()
            return {"ok": False, "errore": "Partecipante non valido."}, 400

        iscrizione = get_iscrizione_partecipante(partecipante.id)
        if tipologia == "pomeriggio" and (
            iscrizione is None or iscrizione.scelta_mattino is None
        ):
            db.session.rollback()
            return {
                "ok": False,
                "errore": "Prima devi scegliere il laboratorio del mattino.",
            }, 409

        campo_scelta = f"scelta_{tipologia}"
        scelta_precedente = getattr(iscrizione, campo_scelta) if iscrizione else None
        laboratori_da_bloccare = {laboratorio_id}
        if scelta_precedente is not None:
            laboratori_da_bloccare.add(scelta_precedente)

        laboratori_bloccati = db.session.execute(
            db.select(Laboratorio)
            .where(Laboratorio.id.in_(laboratori_da_bloccare))
            .order_by(Laboratorio.id)
            .with_for_update()
        ).scalars().all()
        laboratorio = next(
            (item for item in laboratori_bloccati if item.id == laboratorio_id),
            None,
        )
        if laboratorio is None:
            db.session.rollback()
            return {"ok": False, "errore": "Laboratorio non valido."}, 400
        if laboratorio.tipologia != tipologia:
            db.session.rollback()
            return {
                "ok": False,
                "errore": "Il laboratorio appartiene a una fascia diversa.",
            }, 400

        if scelta_precedente != laboratorio.id:
            colonna_scelta = getattr(Iscrizione, campo_scelta)
            occupati = Iscrizione.query.filter(
                colonna_scelta == laboratorio.id
            ).count()
            if occupati >= laboratorio.posti:
                db.session.rollback()
                return {
                    "ok": False,
                    "errore": "Il laboratorio si è appena riempito. Scegline un altro.",
                }, 409

        if iscrizione is None:
            iscrizione = Iscrizione(
                data=ora_roma(),
                partecipante=partecipante.id,
                scelta_mattino=None,
                scelta_pomeriggio=None,
            )
            db.session.add(iscrizione)

        setattr(iscrizione, campo_scelta, laboratorio.id)
        iscrizione.data = ora_roma()
        db.session.commit()

        completa = iscrizione_completa(iscrizione)
        if completa:
            destinazione = url_for("riepilogo_iscrizione")
        else:
            destinazione = url_for("scelta_laboratorio", tipologia="pomeriggio")
        if scelta_precedente is None:
            messaggio = f"Laboratorio del sabato {tipologia} salvato."
        else:
            messaggio = f"Laboratorio del sabato {tipologia} modificato."
        flash(messaggio, "success")
        return {"ok": True, "messaggio": messaggio, "redirect": destinazione}
    except IntegrityError:
        db.session.rollback()
        return {
            "ok": False,
            "errore": "La richiesta è già stata elaborata. Ricarica la pagina.",
        }, 409
    except SQLAlchemyError:
        db.session.rollback()
        app.logger.exception("Errore durante il salvataggio del laboratorio")
        return {
            "ok": False,
            "errore": "Non è stato possibile salvare la scelta. Riprova.",
        }, 500

@app.route("/iscrizione/riepilogo")
def riepilogo_iscrizione():
    partecipante = get_partecipante_corrente()
    if partecipante is None:
        return redirect(url_for("index"))

    iscrizione = get_iscrizione_partecipante(partecipante.id)
    if get_stato_iscrizioni() == "aperte" and not iscrizione_completa(iscrizione):
        return redirect(url_for("percorso_iscrizione"))

    laboratorio_mattino = (
        db.session.get(Laboratorio, iscrizione.scelta_mattino)
        if iscrizione and iscrizione.scelta_mattino is not None
        else None
    )
    laboratorio_pomeriggio = (
        db.session.get(Laboratorio, iscrizione.scelta_pomeriggio)
        if iscrizione and iscrizione.scelta_pomeriggio is not None
        else None
    )
    return render_template(
        "riepilogo.html",
        partecipante=partecipante,
        iscrizione=iscrizione,
        laboratorio_mattino=laboratorio_mattino,
        laboratorio_pomeriggio=laboratorio_pomeriggio,
        completa=iscrizione_completa(iscrizione),
        iscrizioni_aperte=get_stato_iscrizioni() == "aperte",
    )

@app.route("/import_iscritti", methods=["GET", "POST"])
@login_required
def import_iscritti():
    if current_user.username != "admin":
        return redirect(url_for("index"))
    if request.method == "POST":
        dati, errore = valida_import_partecipanti(request.get_json(silent=True))
        if errore:
            return {"ok": False, "errore": errore}, 400

        try:
            for riga in dati:
                partecipante = Partecipante.query.get(riga["id"])
                if partecipante is None:
                    db.session.add(
                        Partecipante(
                            id=riga["id"],
                            nome=riga["nome"],
                            cognome=riga["cognome"],
                        )
                    )

            registra_ultimo_import(ULTIMO_IMPORT_PARTECIPANTI_KEY)
            db.session.commit()
            return {"ok": True}
        except SQLAlchemyError:
            db.session.rollback()
            app.logger.exception("Errore durante l'import dei partecipanti")
            return {
                "ok": False,
                "errore": "Non è stato possibile completare l'import dei partecipanti.",
            }, 500
    return render_template(
        "import_iscritti.html",
        ultimo_import=get_ultimo_import(ULTIMO_IMPORT_PARTECIPANTI_KEY),
    )

@app.route("/import_laboratori", methods=["GET", "POST"])
@login_required
def import_laboratori():
    if current_user.username != "admin":
        return redirect(url_for("index"))
    if request.method == "POST":
        if Iscrizione.query.first() is not None:
            return {
                "ok": False,
                "errore": (
                    "Non è possibile reimportare i laboratori perché esistono "
                    "già delle iscrizioni."
                ),
            }, 409

        dati, errore = valida_import_laboratori(request.get_json(silent=True))
        if errore:
            return {"ok": False, "errore": errore}, 400

        try:
            Laboratorio.query.delete()

            for tipologia, chiave in (
                ("mattino", "lab_mattino"),
                ("pomeriggio", "lab_pomeriggio"),
            ):
                for riga in dati[chiave]:
                    db.session.add(
                        Laboratorio(
                            id_lab=riga["id"],
                            titolo=riga["titolo"],
                            descrizione=riga["descrizione"],
                            posti=riga["posti"],
                            tipologia=tipologia,
                        )
                    )

            registra_ultimo_import(ULTIMO_IMPORT_LABORATORI_KEY)
            db.session.commit()
            return {"ok": True}
        except SQLAlchemyError:
            db.session.rollback()
            app.logger.exception("Errore durante l'import dei laboratori")
            return {
                "ok": False,
                "errore": "Non è stato possibile completare l'import dei laboratori.",
            }, 500
    return render_template(
        "import_lab.html",
        ultimo_import=get_ultimo_import(ULTIMO_IMPORT_LABORATORI_KEY),
    )

@app.route("/admin/stato_iscrizioni", methods=["GET", "POST"])
@login_required
def stato_iscrizioni():
    if current_user.username != "admin":
        return redirect(url_for("index"))

    if request.method == "POST":
        nuovo_stato = request.form.get("stato")
        if nuovo_stato not in STATI_ISCRIZIONI_VALIDI:
            flash("Stato iscrizioni non valido.", "warning")
            return render_template(
                "stato_iscrizioni.html",
                stato_corrente=get_stato_iscrizioni(),
                stati_validi=STATI_ISCRIZIONI_VALIDI,
                messaggio_iscrizioni=get_messaggio_iscrizioni(),
            ), 400

        messaggio_iscrizioni = request.form.get("messaggio_iscrizioni", "").strip()
        if len(messaggio_iscrizioni) > 128:
            flash("Il messaggio non può superare 128 caratteri.", "warning")
            return render_template(
                "stato_iscrizioni.html",
                stato_corrente=get_stato_iscrizioni(),
                stati_validi=STATI_ISCRIZIONI_VALIDI,
                messaggio_iscrizioni=get_messaggio_iscrizioni(),
            ), 400

        set_sys_option(STATO_ISCRIZIONI_KEY, nuovo_stato)
        set_sys_option(MESSAGGIO_ISCRIZIONI_KEY, messaggio_iscrizioni)

        db.session.commit()
        flash("Stato iscrizioni salvato correttamente.", "success")
        return redirect(url_for("stato_iscrizioni"))

    return render_template(
        "stato_iscrizioni.html",
        stato_corrente=get_stato_iscrizioni(),
        stati_validi=STATI_ISCRIZIONI_VALIDI,
        messaggio_iscrizioni=get_messaggio_iscrizioni(),
    )

@app.route("/admin/iscrizioni")
@login_required
def gestione_iscrizioni():
    if current_user.username != "admin":
        return redirect(url_for("index"))

    laboratorio_mattino = aliased(Laboratorio)
    laboratorio_pomeriggio = aliased(Laboratorio)
    iscrizioni = (
        db.session.query(
            Iscrizione,
            Partecipante,
            laboratorio_mattino,
            laboratorio_pomeriggio,
        )
        .join(Partecipante, Iscrizione.partecipante == Partecipante.id)
        .outerjoin(
            laboratorio_mattino,
            Iscrizione.scelta_mattino == laboratorio_mattino.id,
        )
        .outerjoin(
            laboratorio_pomeriggio,
            Iscrizione.scelta_pomeriggio == laboratorio_pomeriggio.id,
        )
        .order_by(Partecipante.cognome, Partecipante.nome)
        .all()
    )

    totale_partecipanti = Partecipante.query.count()
    iscrizioni_complete = Iscrizione.query.filter(
        Iscrizione.scelta_mattino.is_not(None),
        Iscrizione.scelta_pomeriggio.is_not(None),
    ).count()
    iscrizioni_incomplete = Iscrizione.query.filter(
        or_(
            Iscrizione.scelta_mattino.is_(None),
            Iscrizione.scelta_pomeriggio.is_(None),
        )
    ).count()
    iscrizioni_iniziate = iscrizioni_complete + iscrizioni_incomplete
    partecipanti_non_iniziati = max(
        totale_partecipanti - iscrizioni_iniziate,
        0,
    )
    percentuale_completamento = (
        (iscrizioni_complete / totale_partecipanti * 100)
        if totale_partecipanti
        else 0
    )

    return render_template(
        "gestione_iscrizioni.html",
        iscrizioni=iscrizioni,
        totale_partecipanti=totale_partecipanti,
        iscrizioni_complete=iscrizioni_complete,
        iscrizioni_incomplete=iscrizioni_incomplete,
        partecipanti_non_iniziati=partecipanti_non_iniziati,
        percentuale_completamento=percentuale_completamento,
    )

@app.route("/admin/cambia_password", methods=["GET", "POST"])
@login_required
def cambia_password():
    if current_user.username != "admin":
        return redirect(url_for("index"))

    if request.method == "POST":
        password_attuale = request.form.get("password_attuale", "")
        nuova_password = request.form.get("nuova_password", "")
        conferma_password = request.form.get("conferma_password", "")

        if not check_password_hash(current_user.password, password_attuale):
            flash("La password attuale non è corretta.", "warning")
        elif not nuova_password:
            flash("La nuova password non può essere vuota.", "warning")
        elif nuova_password != conferma_password:
            flash("La nuova password e la conferma non coincidono.", "warning")
        else:
            current_user.password = generate_password_hash(nuova_password)
            db.session.commit()
            flash("Password aggiornata correttamente.", "success")
            return redirect(url_for("cambia_password"))

    return render_template("cambia_password.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        utente = User.query.filter_by(username=request.form["username"]).first()
        if utente:
            if check_password_hash(utente.password, request.form["passwd"]):
                login_user(utente)
                return redirect(url_for("import_iscritti"))
            else:
                flash("Username o Password errati!", "warning")
        else:
            flash("Utente inesistente!", "warning")
    return render_template("login.html")

@app.route("/logout")
@login_required
def logout():
    logout_user()
    session.pop("temp_user", None)
    session.pop("identita_confermata", None)
    return redirect(url_for("index"))

@app.errorhandler(404)
def page_not_found(e):
    return render_template("errore_generico.html"), 404

@app.errorhandler(405)
def internal_error(e):
    return render_template("errore_generico.html"), 405

@app.errorhandler(500)
def internal_error(e):
    return render_template("errore_generico.html"), 500

if __name__ == "__main__":
    app.run(port=8000, host="0.0.0.0")
