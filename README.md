# Per Me Sei Avventura — Tool Laboratori

Applicazione web per la gestione delle iscrizioni ai laboratori del convegno nazionale AGESCI **“Per Me Sei Avventura”**, settembre 2026.

Il sistema gestisce:

* anagrafica dei partecipanti;
* iscrizioni ai laboratori del sabato mattina e pomeriggio;
* disponibilità e capienza dei laboratori;
* rinuncia esplicita a una fascia;
* suddivisione A/B degli iscritti ai laboratori del sabato;
* suddivisione dei partecipanti nei 20 gruppi della domenica;
* gestione manuale delle eccezioni da parte degli amministratori;
* export Excel;
* file comunicazioni;
* import incrementali di partecipanti e laboratori.

L'applicazione è progettata per circa **400 partecipanti** e per un utilizzo operativo limitato all'evento.

---

# Stack

## Backend

* Python 3.11
* Flask
* Flask-SQLAlchemy
* Flask-Migrate / Alembic
* Flask-Login
* Gunicorn

## Database

* MariaDB 11.4
* SQLite per parte della suite di test

## Frontend

* Jinja
* Bootstrap
* Alpine.js
* JavaScript
* SheetJS/XLSX

## Deployment

* Docker
* Docker Compose

---

# Schema database

Schema corrente, coerente con i modelli SQLAlchemy e le migration fino a
`d7e3b6a90124`:

| Tabella | Contenuto principale |
| --- | --- |
| `partecipanti` | `id` (codice censimento, primary key), `nome`, `cognome`; anagrafica `gruppo`, `zona`, `regione`, `email`, `sesso`, `foca`, `ruolo`, `incarico_altro`; flag `deve_iscriversi_sabato`, `includi_domenica`; `gruppo_domenica` nullable, 1–20. |
| `iscrizioni` | `id`, `data`, `partecipante` (foreign key univoca); `scelta_mattino` e `scelta_pomeriggio` (foreign key nullable verso laboratori), `non_partecipa_mattino`, `non_partecipa_pomeriggio`; `sottogruppo_mattino` e `sottogruppo_pomeriggio` nullable, A/B. |
| `laboratori` | `id` interno, `id_lab`, `titolo`, `descrizione`, `posti`, `tipologia`. Import riconciliato per `(tipologia, id_lab)`, senza vincolo UNIQUE su questa coppia. |
| `user` | Account amministrativo: `id`, `username` univoco e `password` con hash. |
| `system_option` | Opzioni `key`/`value`: stato iscrizioni, messaggio e timestamp degli import. |

Ogni partecipante può avere al massimo una riga `Iscrizione`.
I flag del partecipante sono NOT NULL, con default sabato true e domenica false;
i nuovi campi anagrafici sono nullable nel DB. I vincoli collegano scelte ai
laboratori e impediscono scelta e rinuncia contemporanee nella stessa fascia.
La tabella tecnica `alembic_version` registra la revisione dello schema.

Per lo schema versionato consultare [migrations/versions](migrations/versions);
per invarianti e regole applicative consultare [AGENTS.md](AGENTS.md).

---

# Avvio con Docker Compose

Esempio di deployment possibile con nginx e immagine pubblicata.
Lo stack locale di test in `/opt/pmsea-test/infra/compose.yaml` usa invece solo
`web` e `db`: costruisce web dal repository ed espone direttamente la porta 5000.

Esempio di deployment:

```yaml
services:
  web:
    image: ghcr.io/calminaro/permeseiavventura_laboratori:latest
    restart: unless-stopped
    environment:
      DB_TYPE: mariadb
      DB_USER: app_user
      DB_PASSWORD: app_password
      DB_HOST: db
      DB_PORT: 3306
      DB_NAME: app_db
      SECRET_KEY: secret_key
    depends_on:
      db:
        condition: service_healthy

  db:
    image: mariadb:11.4
    container_name: mariadb
    restart: unless-stopped
    environment:
      MARIADB_ROOT_PASSWORD: rootpassword
      MARIADB_DATABASE: app_db
      MARIADB_USER: app_user
      MARIADB_PASSWORD: app_password
      TZ: Europe/Rome
    volumes:
      - mariadb_data:/var/lib/mysql
    healthcheck:
      test:
        [
          "CMD",
          "mariadb-admin",
          "ping",
          "-h",
          "localhost",
          "-uroot",
          "-prootpassword"
        ]
      interval: 5s
      timeout: 3s
      retries: 5

  nginx:
    image: nginx:alpine
    restart: unless-stopped
    ports:
      - "5000:80"
    volumes:
      - ./nginx.conf:/etc/nginx/nginx.conf:ro
    depends_on:
      - web

volumes:
  mariadb_data:
```

Esempio `nginx.conf`:

```nginx
events {}

http {
    upstream backend {
        server web:8000;
    }

    server {
        listen 80;

        location / {
            proxy_pass http://backend;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
        }
    }
}
```

Le credenziali mostrate sopra sono esempi e devono essere sostituite prima dell'utilizzo reale.

Le variabili realmente usate sono riepilogate in [.env.example](.env.example),
con valori fittizi per web e inizializzazione MariaDB. Il file è un modello:
l'applicazione non lo carica automaticamente e il Compose locale attuale usa
valori espliciti in `environment`, senza interpolazione da `.env`.
Configurare quindi le variabili nei servizi/processi effettivamente avviati;
la sola copia del modello in `.env` non modifica il deployment.

---

# Ambiente di sviluppo

Repository:

```text
/opt/pmsea-test/app
```

Infrastruttura Docker:

```text
/opt/pmsea-test/infra
```

Applicazione di test:

```text
http://192.168.10.51:5000
```

Per ricostruire il servizio web con il codice corrente:

```bash
cd /opt/pmsea-test/infra
docker compose build web
docker compose up -d web
```

Per verificare lo stack:

```bash
docker compose ps
```

---

# Partecipanti

Ogni partecipante contiene:

* codice censimento;
* nome;
* cognome;
* gruppo scout;
* zona;
* regione;
* email;
* sesso;
* FoCa;
* ruolo / “Partecipo in qualità di”;
* eventuale incarico altro;
* flag partecipazione sabato;
* flag partecipazione domenica;
* eventuale gruppo domenicale assegnato.

L'email applicativa proviene da `EmailContatto`.

`EmailReferente` non viene persistita.

---

# Import partecipanti CSV

Dall'admin scegliere **Importa partecipanti**.

Il formato richiesto è:

* CSV UTF-8;
* separatore `;`;
* intestazioni nella prima riga.

Il vecchio formato Excel degli iscritti non è più supportato.

Il file viene letto nel browser tramite SheetJS.

Sono supportati:

* BOM UTF-8;
* accenti;
* campi quotati;
* `;` all'interno di campi quotati;
* newline Windows e Linux.

---

## Campi importati

| CSV                                                     | Campo applicativo |
| ------------------------------------------------------- | ----------------- |
| `Codice`                                                | codice censimento |
| `Nome`                                                  | nome              |
| `Cognome`                                               | cognome           |
| `Gruppo`                                                | gruppo            |
| `Zona`                                                  | zona              |
| `Regione`                                               | regione           |
| `EmailContatto`                                         | email             |
| `Sesso`                                                 | sesso             |
| `FoCa`                                                  | FoCa              |
| `Partecipo in qualità di:`                              | ruolo             |
| `Se hai indicato "altro" specifica incarico:`           | incarico altro    |
| `Partecipa ai laboratori di sabato come partecipante`   | flag sabato       |
| `Partecipa ai laboratori di domenica come partecipante` | flag domenica     |

Le altre colonne del file vengono ignorate.

Il CSV originale non viene salvato sul server.

---

# Anteprima import partecipanti

L'import avviene in due passaggi.

## 1. Anteprima

Il file viene:

1. letto;
2. validato;
3. confrontato con il database.

**Nessuna modifica viene ancora applicata.**

L'admin vede:

* nuovi;
* modificati;
* invariati;
* totale elaborati.

È disponibile anche un dettaglio espandibile.

Esempio:

```text
12345 – Rossi Mario: nuovo
67890 – Bianchi Luca: modificati Email, Regione, Zona
```

Vengono mostrati solo i campi che cambierebbero realmente.

## 2. Conferma

Solo premendo **Conferma import** i dati vengono scritti.

Prima della scrittura il backend ripete la validazione e il confronto sullo stato corrente del database.

---

# Reimport partecipanti

L'import è incrementale.

## Codice nuovo

Il partecipante viene inserito.

## Codice già presente

Vengono aggiornati i dati provenienti dal CSV.

## Codice assente dal nuovo file

Il partecipante rimane invariato.

Il reimport non cancella né modifica:

* iscrizioni del sabato;
* rinunce;
* timestamp delle iscrizioni;
* gruppi A/B;
* gruppo domenicale già persistito.

L'import è atomico: in caso di errore non vengono applicate modifiche parziali.

---

# Flag CSV

Valori considerati `true`:

```text
Sì
Si
S
Yes
True
1
```

Valori considerati `false`:

```text
No
N
False
0
```

Il confronto ignora maiuscole/minuscole e spazi esterni.

Valori vuoti o sconosciuti bloccano l'import.

---

# Import laboratori

L'import laboratori continua a utilizzare Excel.

Il file deve contenere due fogli:

```text
mattino
pomeriggio
```

Entrambi devono contenere le colonne:

```text
id
titolo
descrizione
posti
```

La chiave logica del laboratorio è:

```text
(tipologia, id_lab)
```

dove `tipologia` è `mattino` o `pomeriggio`.

---

# Anteprima import laboratori

Anche l'import laboratori avviene in due fasi.

Prima della scrittura il sistema mostra:

* nuovi;
* modificati;
* invariati;
* totale.

Il dettaglio espandibile indica i campi realmente cambiati.

Esempio:

```text
mattino / L01 – nuovo
pomeriggio / L05 – modificati Titolo, Posti
```

Solo dopo la conferma vengono applicate le modifiche.

---

# Reimport laboratori

Il reimport è incrementale.

* laboratorio nuovo → inserimento;
* laboratorio esistente → aggiornamento di titolo, descrizione e posti;
* laboratorio assente dal file → invariato.

La primary key interna del laboratorio esistente viene preservata, quindi le iscrizioni continuano a riferirsi allo stesso record.

Il reimport è consentito anche quando esistono già iscrizioni.

Una riduzione della capienza è consentita solo se il nuovo valore resta almeno pari al numero di iscritti effettivi.

Le rinunce non occupano posti.

Duplicati o ambiguità bloccano l'intero import.

Gli import amministrativi dei laboratori devono essere eseguiti uno alla volta.

---

# Flusso partecipante

Il partecipante:

1. inserisce il codice censimento;
2. verifica nome e cognome;
3. conferma la propria identità;
4. viene indirizzato automaticamente al punto corretto del percorso.

---

# Partecipazione al sabato

Ogni partecipante possiede un flag che indica se deve iscriversi ai laboratori del sabato.

## Sabato richiesto

Il flusso è:

1. laboratorio mattino;
2. salvataggio;
3. laboratorio pomeriggio;
4. salvataggio;
5. riepilogo.

Le scelte vengono registrate immediatamente nel database.

Non esiste una conferma globale finale.

## Sabato non richiesto

La persona:

* non deve scegliere laboratori;
* non viene considerata incompleta;
* viene portata direttamente al riepilogo.

Nel sistema viene mostrato:

```text
Iscrizione non richiesta
```

---

# Rinuncia a una fascia

Per ciascuna fascia è possibile scegliere esplicitamente di non partecipare.

Gli stati possibili sono quindi:

* laboratorio scelto;
* `Non partecipa`;
* `Non iscritto`;
* `Iscrizione non richiesta`.

Questi stati vengono mantenuti distinti anche negli export.

---

# Capienza e concorrenza

Nel normale flusso utente la capienza viene controllata dal backend.

Le assegnazioni utilizzano:

* transazioni MariaDB;
* lock `SELECT ... FOR UPDATE`;
* ricontrollo della disponibilità dopo il lock.

La disponibilità visualizzata nel browser è soltanto informativa.

In caso di contesa sull'ultimo posto un solo partecipante deve ottenere il posto.

---

# Disponibilità dinamica

Durante la scelta dei laboratori il browser aggiorna periodicamente la disponibilità.

Un laboratorio pieno:

* rimane visibile;
* mostra lo stato completo;
* non può essere selezionato da nuovi utenti.

Chi possiede già quel laboratorio può mantenerlo anche se nel frattempo risulta pieno.

---

# Gestione manuale partecipanti

L'admin può:

* aggiungere un partecipante;
* modificarne l'anagrafica;
* modificare i flag sabato/domenica;
* assegnare manualmente laboratori;
* impostare manualmente A/B;
* assegnare manualmente il gruppo domenicale.

Il codice censimento non è modificabile dopo la creazione.

---

# Campi obbligatori nella gestione manuale

Sono obbligatori:

* codice censimento in creazione;
* nome;
* cognome;
* gruppo;
* zona;
* regione;
* email valida;
* sesso;
* FoCa;
* flag sabato;
* flag domenica.

`Partecipo in qualità di` è facoltativo.

`Incarico altro` è richiesto quando viene indicato un ruolo “Altro”.

---

# Override amministrativo dei laboratori

L'admin può assegnare manualmente una persona a un laboratorio anche se il laboratorio è già pieno.

Questa eccezione vale esclusivamente per l'amministratore.

Il normale flusso partecipante continua a rispettare la capienza.

Nel form del partecipante è possibile modificare separatamente:

* laboratorio mattino;
* A/B mattino;
* laboratorio pomeriggio;
* A/B pomeriggio.

---

# Reset iscrizioni sabato

Dalla gestione iscrizioni è disponibile:

**Azzera iscrizioni sabato**

L'operazione elimina esclusivamente la riga `Iscrizione` della persona.

Vengono quindi rimossi:

* laboratorio mattino;
* laboratorio pomeriggio;
* rinunce;
* A/B.

Rimangono invariati:

* anagrafica;
* flag partecipante;
* gruppo domenicale.

Se le iscrizioni sono aperte, la persona può ricominciare il normale percorso.

---

# Gestione laboratori

L'admin può:

* aggiungere un laboratorio;
* modificare titolo;
* modificare descrizione;
* modificare posti.

Non sono modificabili:

* codice laboratorio;
* fascia.

La riduzione della capienza tramite modifica del laboratorio non può scendere sotto il numero degli iscritti effettivi.

---

# Gruppi della domenica

La domenica utilizza **20 gruppi fissi**.

Le assegnazioni sono persistite nel database come numero da 1 a 20.

I nomi sono:

|  # | Gruppo         |
| -: | -------------- |
|  1 | Avventura      |
|  2 | Bisogno        |
|  3 | Cura           |
|  4 | Dio            |
|  5 | Esperienza     |
|  6 | Fuori          |
|  7 | Gradualità     |
|  8 | Habitus        |
|  9 | Incontro       |
| 10 | Linguaggio     |
| 11 | Mistero        |
| 12 | Natura         |
| 13 | Occasione      |
| 14 | Progettualità  |
| 15 | Quotidiano     |
| 16 | Responsabilità |
| 17 | Sfida          |
| 18 | Tempo          |
| 19 | Unicità        |
| 20 | Vivere         |

La mappa applicativa è definita in:

```text
NOMI_GRUPPI_DOMENICA
```

---

# Ricalcolo gruppi domenica

L'admin può eseguire:

**Ricalcola gruppi domenica**

Vengono considerate esclusivamente le persone con partecipazione domenica attiva.

I criteri di bilanciamento, in ordine di priorità, sono:

1. Regione;
2. ruolo / “Partecipo in qualità di”;
3. FoCa;
4. Sesso.

L'algoritmo utilizza:

* priorità alle categorie rare;
* assegnazione greedy;
* scambi locali;
* bilanciamento numerico.

Le assegnazioni vengono salvate nel database.

Il ricalcolo:

* sovrascrive le precedenti assegnazioni domenicali;
* non modifica il sabato;
* è atomico.

L'admin può anche modificare manualmente il gruppo di una singola persona.

Un successivo ricalcolo può sovrascrivere questa modifica manuale.

---

# Visualizzazione gruppo domenica

Il riepilogo partecipante distingue:

## Partecipazione non richiesta

```text
Partecipazione ai gruppi della domenica: non richiesta
```

## Partecipazione richiesta ma non ancora assegnata

```text
Gruppo domenica: non ancora assegnato
```

## Gruppo assegnato

Viene mostrato il nome, per esempio:

```text
Gruppo domenica: Gradualità
```

---

# Gruppi A/B del sabato

Gli iscritti a ogni laboratorio vengono divisi in due sottogruppi:

```text
A
B
```

Il calcolo viene eseguito:

* separatamente per ciascun laboratorio;
* separatamente per mattino e pomeriggio.

Una persona può quindi essere, ad esempio:

```text
A al mattino
B al pomeriggio
```

I criteri sono gli stessi della domenica:

1. Regione;
2. ruolo;
3. FoCa;
4. Sesso.

Le dimensioni A/B differiscono al massimo di una persona.

---

# Quando calcolare A/B

Il ricalcolo A/B è consentito solamente quando le iscrizioni sono:

```text
chiuse
```

Con iscrizioni aperte:

* il pulsante non è utilizzabile;
* il backend rifiuta comunque il ricalcolo.

Procedura operativa consigliata:

```text
chiusura iscrizioni
→ ricalcolo gruppi A/B
```

Un successivo ricalcolo può sovrascrivere eventuali modifiche manuali A/B.

---

# Dashboard admin

La gestione iscrizioni mostra:

* totale partecipanti;
* completi;
* incompleti;
* non iniziati;
* non richiesti;
* percentuale di completamento;
* elenco partecipanti.

Per le statistiche del sabato vengono considerati solo i partecipanti con iscrizione sabato richiesta.

Chi non deve partecipare al sabato non viene contato tra incompleti o non iniziati.

---

# Export iscrizioni

Sono disponibili due export.

## Elenco generale

Nome file:

```text
iscrizioni_generali_<data>.xlsx
```

Contiene tutti i partecipanti.

## Per laboratorio

Nome file:

```text
iscrizioni_per_laboratorio_<data>.xlsx
```

Contiene:

* foglio `Tutti i partecipanti`;
* fogli dei singoli laboratori;
* fogli `Non partecipa`.

---

# Colonne del foglio generale

Sono presenti almeno:

* codice censimento;
* nome;
* cognome;
* gruppo;
* zona;
* regione;
* email;
* laboratorio mattino;
* A/B mattino;
* laboratorio pomeriggio;
* A/B pomeriggio.

Il laboratorio viene rappresentato come:

```text
id_lab - titolo
```

---

# Stati negli export

Non vengono lasciate celle ambigue.

| Stato fascia                          | Laboratorio                | A/B                        |
| ------------------------------------- | -------------------------- | -------------------------- |
| iscrizione non richiesta              | `Iscrizione non richiesta` | `Iscrizione non richiesta` |
| scelta non effettuata                 | `Non iscritto`             | `Non iscritto`             |
| rinuncia                              | `Non partecipa`            | `Non partecipa`            |
| laboratorio scelto, A/B non calcolato | laboratorio                | `Non assegnato`            |
| laboratorio scelto, A/B calcolato     | laboratorio                | `A` oppure `B`             |

Gli export leggono esclusivamente le assegnazioni persistite.

Non viene effettuato alcun ricalcolo durante la generazione.

---

# File comunicazioni

La pagina admin **Comunicazioni** genera un file Excel direttamente dal database.

Non è più necessario caricare l'Excel della domenica.

Il foglio contiene:

* codice censimento;
* nome;
* cognome;
* email;
* sabato mattino;
* A/B mattino;
* sabato pomeriggio;
* A/B pomeriggio;
* domenica.

Tutti i partecipanti vengono inclusi una sola volta.

---

# Stato domenica nel file comunicazioni

## Partecipazione non richiesta

```text
Iscrizione non richiesta
```

## Partecipazione richiesta ma gruppo non ancora calcolato

```text
Non assegnato
```

## Gruppo presente

Viene esportato il nome del gruppo:

```text
Gradualità
```

Il file comunicazioni utilizza esclusivamente i dati persistiti nel database.

---

# Atomicità

Gli import e i ricalcoli devono evitare stati parziali.

In caso di errore:

* rollback;
* nessun aggiornamento parziale;
* nessuna cancellazione parziale;
* dati precedenti conservati.

---

# Migration

Lo schema viene gestito tramite Flask-Migrate / Alembic.

Il container applicativo esegue le migration secondo l'entrypoint configurato.

Per verificare la migration corrente:

```bash
cd /opt/pmsea-test/infra
docker compose exec web flask db current
```

Per vedere la head disponibile:

```bash
docker compose exec web flask db heads
```

---

# Test

## Suite generale

Dalla root del repository:

```bash
python -m unittest discover -s tests -v
```

Gran parte della logica applicativa viene verificata con SQLite.

---

# Test browser CSV

I test del parser CSV utilizzano Node.js e la stessa versione SheetJS dell'applicazione.

Serve:

```text
SHEETJS_TEST_PATH
```

con il percorso a:

```text
xlsx@0.18.5/dist/xlsx.full.min.js
```

Esempio:

```bash
SHEETJS_TEST_PATH=/percorso/xlsx.full.min.js \
python -m unittest discover -s tests -v
```

Se Node/SheetJS non sono disponibili, i test browser vengono saltati.

---

# Test MariaDB

Le funzionalità che dipendono dal database reale vengono verificate anche su MariaDB.

In particolare:

* migration;
* lock;
* concorrenza;
* ultimo posto;
* capienza;
* CHECK;
* comportamento delle transazioni.

I test distruttivi devono essere eseguiti esclusivamente su database/container temporanei.

**Non utilizzare `app_db` per suite distruttive.**

---

# Verifica finale raccomandata

Prima di un deploy significativo verificare almeno:

```bash
git status
git diff --check
```

Poi:

1. suite SQLite;
2. test browser;
3. suite MariaDB pertinente;
4. migration su MariaDB temporaneo;
5. apertura degli XLSX generati;
6. flussi HTTP principali.

---

# Git

Branch di sviluppo:

```text
dev
```

Branch stabile:

```text
main
```

Remote di sviluppo:

```text
origin
```

Repository fork:

```text
fracfe/perMeSeiAvventura_laboratori
```

Repository upstream:

```text
calminaro/perMeSeiAvventura_laboratori
```

---

# Obiettivo operativo

L'applicazione non è progettata come piattaforma permanente.

L'obiettivo è fornire agli organizzatori del convegno uno strumento semplice e affidabile per:

* importare e correggere i partecipanti;
* raccogliere le iscrizioni;
* gestire eccezioni manuali;
* distribuire i partecipanti;
* produrre gli elenchi necessari;
* affrontare eventuali problemi durante l'evento senza intervenire direttamente sul database.
