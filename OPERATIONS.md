# Operazioni durante l’evento

## Scopo

Riferimento rapido per gestire iscrizioni, import, assegnazioni e recupero da errori
durante le settimane dell’evento. Usare prima la console admin.
Le procedure infrastrutturali sotto si riferiscono all’ambiente di test verificato;
prima di usarle in produzione identificare host, percorsi e database corretti.
Panoramica in [README.md](README.md), regole tecniche in [AGENTS.md](AGENTS.md),
sequenza operativa in [CHECKLIST_EVENTO.md](CHECKLIST_EVENTO.md).

## Percorsi e configurazione

| Voce | Ambiente verificato |
|---|---|
| Repository | `/opt/pmsea-test/app` |
| Infrastruttura | `/opt/pmsea-test/infra` |
| Configurazione | `/opt/pmsea-test/infra/compose.yaml` |
| Branch di sviluppo | `dev` |
| Servizi Compose | `web`, `db` |
| Database applicativo | `app_db` |
| Dati persistenti | volume Compose `mariadb_data`, montato su `/var/lib/mysql` |
| Accesso test | porta host `5000` → web `8000` |
| Backup proposti | `/opt/pmsea-test/backups/` |

Il Compose reale costruisce `web` da `../app`; il codice non è montato come volume.
Il README contiene anche un **esempio** con immagine GHCR e nginx: non è lo stack
locale attuale. Il repository contiene backend `app.py`, servizi per gruppi e
comunicazioni, `templates/`, `static/`, `migrations/` e `tests/`.

Variabili richieste da web: `DB_TYPE=mariadb`, `DB_HOST=db`, `DB_PORT=3306`,
`DB_NAME=app_db`, `DB_USER`, `DB_PASSWORD`, `SECRET_KEY`.
Il container db usa `MARIADB_DATABASE`, `MARIADB_USER`, `MARIADB_PASSWORD`,
`MARIADB_ROOT_PASSWORD` e `TZ=Europe/Rome`.
Non copiare credenziali o dump nel repository.
`SESSION_COOKIE_SECURE` è opzionale e non impostata nel Compose locale:
verificarla per un deployment HTTPS. Le variabili MariaDB di inizializzazione
non cambiano automaticamente credenziali di un volume già popolato.

## Comandi base

Eseguire i comandi Compose dalla directory infrastruttura:

```bash
cd /opt/pmsea-test/infra
docker compose ps
docker compose logs --tail=100 web
docker compose logs --tail=100 db
```

Per seguire il web in tempo reale (Ctrl-C termina solo la lettura):

```bash
docker compose logs -f web
```

Quando il workspace contiene codice più recente del container:

```bash
cd /opt/pmsea-test/infra
docker compose build web
docker compose up -d web
```

Il rebuild non è un backup. La ricreazione di web interrompe brevemente il servizio.
L’entrypoint `docker-entrypoint.sh` esegue `flask db upgrade` prima di avviare
Gunicorn con tre worker; se l’upgrade fallisce, web non parte.

### Migrazioni

```bash
cd /opt/pmsea-test/infra
docker compose exec web flask db current
docker compose exec web flask db heads
```

La revisione corrente deve coincidere con la head. Al momento della verifica:
`d7e3b6a90124`. Per applicare esplicitamente le migrazioni, solo dopo backup e
conferma dell’intervento sul database corretto:

```bash
docker compose exec web flask db upgrade
```

Normalmente basta l’upgrade già previsto all’avvio. Non usare `flask db migrate`
per riparare un ambiente durante l’evento.

I comandi personalizzati esistenti sono `flask init_db` e `flask reset`:
il primo crea l’admin con password predefinita (non è un reset password);
il secondo cancella iscrizioni, partecipanti e laboratori.
**Non usare questi comandi per tentativi di recupero su un ambiente popolato.**

## Accesso admin e stato iscrizioni

Accedere da `/login`. Dalla console usare **Cambia password**
(`/admin/cambia_password`) per sostituire la password iniziale.

Dal menu **Iscrizioni → Stato iscrizioni** (`/admin/stato_iscrizioni`):
scegliere aperte/chiuse, aggiornare il messaggio informativo e salvare.
Verificare poi la homepage in una sessione partecipante.
Il messaggio è solo testo: non programma aperture o chiusure.
Con iscrizioni chiuse resta possibile identificarsi e consultare il riepilogo,
ma il partecipante non può salvare scelte. L’admin può ancora correggere i dati.

## Import partecipanti

1. Aprire **Iscrizioni → Importa partecipanti** (`/import_iscritti`).
2. Selezionare il CSV UTF-8 separato da `;`, con tutte le intestazioni previste
   nel [README](README.md#campi-importati).
3. Attendere **Anteprima import — nessuna modifica è stata ancora applicata**.
4. Controllare nuovi, modificati, invariati e totale.
5. Aprire **Espandi dettaglio modifiche** e verificare i campi cambiati.
6. Premere **Conferma import**; controllare riepilogo finale e ultimo import.

Scegliere un altro file prima della conferma non modifica il DB.
L’anteprima (`POST /import_iscritti/valida`) non scrive né aggiorna timestamp.
La conferma ripete validazione e confronto sul DB corrente: i conteggi finali
possono differire dall’anteprima se nel frattempo qualcuno ha corretto i dati.

Gli assenti dal CSV non vengono cancellati. Si aggiornano i campi CSV, inclusi
i flag; si conservano iscrizioni, rinunce, timestamp iscrizione, A/B e gruppo
domenica persistito. Un flag domenica false nasconde un vecchio gruppo senza
cancellarlo fino al ricalcolo. L’email proviene da `EmailContatto`.
In caso di errore correggere il file e ripartire dalla preview: niente scritture
parziali. Eseguire gli import amministrativi uno alla volta.

## Import laboratori

1. Aprire **Iscrizioni → Importa laboratori** (`/import_laboratori`).
2. Selezionare Excel con fogli `mattino` e `pomeriggio`, entrambi non vuoti;
   colonne `id`, `titolo`, `descrizione`, `posti`.
3. Controllare l’anteprima, i quattro conteggi e il dettaglio espandibile.
4. Verificare soprattutto capienze e fascia/codice; poi **Conferma import**.
5. Controllare riepilogo finale e ultimo import.

La preview (`POST /import_laboratori/valida`) è senza scritture.
La conferma ricontrolla il DB e la capienza sotto lock: nuove iscrizioni possono
rendere non più valida una riduzione prima accettabile.
L’import è incrementale per `(tipologia, id_lab)`: mantiene primary key,
iscrizioni e laboratori assenti dal file. Duplicati/ambiguità bloccano l’import.
Una riduzione non può scendere sotto gli iscritti effettivi.
Eseguire **un solo import amministrativo alla volta**.

## Eccezioni manuali e problemi di un partecipante

Da **Iscrizioni** (`/admin/iscrizioni`) individuare codice/nome, verificare flag
e scelte, quindi usare **Modifica** (`/admin/partecipanti/<codice>/modifica`).
Se necessario usare **Aggiungi partecipante**. Le assegnazioni si correggono
nel form di un partecipante già esistente.

- Correggere anagrafica e flag. Il codice è immutabile; i campi manuali obbligatori
  sono elencati nel README. Ruolo facoltativo, incarico richiesto con “Altro”.
- Assegnare/cambiare mattino e pomeriggio; impostare A/B come nessuno, A o B.
  **L’admin può forzare un laboratorio oltre capienza**: verificare poi il numero
  degli iscritti. Il normale utente continua a rispettare la capienza.
- Assegnare un laboratorio attiva il flag sabato e rimuove la rinuncia nella fascia.
  Rimuovere la scelta pulisce anche A/B, senza introdurre una rinuncia.
  L’iscrizione viene creata se necessaria; un timestamp esistente è conservato.
- Impostare **Gruppo domenica** con numero e nome; un gruppo attiva il flag domenica.
  Rimuoverlo non disattiva automaticamente il flag.
- Usare **Azzera iscrizioni sabato** solo per far ricominciare la persona:
  dopo conferma elimina la sua iscrizione, scelte, rinunce e A/B.
  Anagrafica, flag e domenica restano invariati. Per reiscriversi autonomamente
  servono iscrizioni aperte e sabato richiesto.

Per aggiungere/modificare laboratori usare **Gestione dati**
(`/admin/gestione_dati`); codice e fascia non si cambiano.
Non usare i reset globali per risolvere problemi individuali.
Preferire sempre la UI alle modifiche SQL dirette.

## Gruppi domenica

1. Verificare `includi_domenica` e i dati anagrafici utili alla distribuzione.
2. Aprire **Suddivisione gruppi** (`/admin/suddivisione-gruppi`).
3. Eseguire **Ricalcola gruppi domenica**, confermare e controllare i 20 gruppi.
4. Applicare eventuali eccezioni manuali **dopo** il ricalcolo e rigenerare gli export.

Il ricalcolo pulisce gli esclusi, persiste i gruppi e non modifica il sabato.
Può sovrascrivere assegnazioni manuali precedenti. Con pochi partecipanti
alcuni gruppi possono essere vuoti. Non richiede di chiudere le iscrizioni.
I nomi derivano dalla mappa unica `NOMI_GRUPPI_DOMENICA`, documentata nel README.

## Gruppi A/B sabato

1. Chiudere le iscrizioni da **Stato iscrizioni**.
2. Verificare lo stato nella homepage e l’impossibilità di salvare scelte come utente.
3. Da **Iscrizioni → Gruppi A/B sabato** (`/admin/iscrizioni/gruppi-ab`)
   eseguire **Ricalcola gruppi A/B sabato** e confermare.
4. Controllare distribuzione per laboratorio e fascia; rigenerare gli export.

Il backend rifiuta il calcolo a iscrizioni aperte.
Il ricalcolo globale sostituisce gli A/B precedenti, anche manuali, preservando
scelte e domenica. Se si correggono successivamente le scelte, sistemare A/B
manualmente o ricalcolare consapevolmente tutti i gruppi.

## Export e comunicazioni

| Funzione | Accesso | File |
|---|---|---|
| Generale | **Iscrizioni → Esporta iscrizioni**, elenco | `iscrizioni_generali_YYYY-MM-DD.xlsx` |
| Per laboratorio | stessa pagina, per laboratorio | `iscrizioni_per_laboratorio_YYYY-MM-DD.xlsx` |
| Comunicazioni | **Genera file comunicazioni**, genera file | `comunicazioni_partecipanti_YYYY-MM-DD.xlsx` |

Pagina export: `/admin/iscrizioni/esporta`; download:
`/admin/iscrizioni/esporta/elenco` e `/admin/iscrizioni/esporta/laboratori`.
Comunicazioni: `/admin/comunicazioni`, generazione via pulsante
(`POST /admin/comunicazioni/genera`). La data è quella di Roma.

Il generale include tutti i partecipanti. Il file per laboratorio include
**Tutti i partecipanti**, fogli dei laboratori e fogli **Non partecipa**.
Comunicazioni usa email DB, sabato, A/B e nome domenica: non richiede vecchi Excel.
Gli export leggono dati persistiti, senza ricalcolare gruppi.
Le celle A/B riportano A/B, **Non assegnato** oppure lo stesso stato della fascia:
**Iscrizione non richiesta**, **Non iscritto**, **Non partecipa**.
Aprire sempre gli XLSX prima di consegnarli e rigenerarli dopo le correzioni.

## Backup database

**Procedura da eseguire quando serve, non eseguita durante la redazione.**
Prima di interventi importanti fare un dump e conservarne una copia fuori dalla VM.
Durante il dump evitare import, ricalcoli e migrazioni; `--single-transaction`
produce una fotografia coerente delle tabelle InnoDB, ma non protegge da DDL.

In una shell Bash sul server:

```bash
cd /opt/pmsea-test/infra
umask 077
mkdir -p /opt/pmsea-test/backups
backup_file="/opt/pmsea-test/backups/app_db_$(date +%Y%m%d_%H%M%S).sql"
if docker compose exec -T db sh -c '
  MYSQL_PWD="$MARIADB_ROOT_PASSWORD" exec mariadb-dump     --user=root --single-transaction --quick --hex-blob     --databases "$MARIADB_DATABASE"
' > "$backup_file.partial"; then
  mv "$backup_file.partial" "$backup_file"
  test -s "$backup_file" && ls -lh "$backup_file"
  sha256sum "$backup_file" > "$backup_file.sha256"
else
  echo "Backup fallito: non usare il file .partial" >&2
fi
```

Le password restano nelle variabili del container; non digitarle nella riga comando.
Il dump include schema, dati e revisione Alembic, non gli account globali MariaDB.
Il file contiene dati personali: accesso riservato agli operatori.
Per controllarlo nella stessa shell:

```bash
test -s "$backup_file"
tail -n 1 "$backup_file"
sha256sum -c "$backup_file.sha256"
```

Verificare l’esito positivo del dump e la riga finale di completamento.
Dimensione e checksum non garantiscono da soli la ripristinabilità:
prima di affidarsi al backup, provarne il restore in un MariaDB temporaneo isolato,
mai su `app_db`. Annotare anche il commit del codice associato al dump.

## Ripristino database

> **OPERAZIONE DISTRUTTIVA — eseguire solo con backup verificato e dopo conferma esplicita.**
> Il restore sostituisce le tabelle contenute nel dump e perde le modifiche successive.
> Non è una prova e non è una procedura automatica.

1. Identificare dump, commit associato e destinazione; il dump precedente contiene
   `CREATE DATABASE/USE app_db`. Su un ambiente temporaneo serve un server isolato,
   non basta indicare un nome differente sulla riga comando.
2. Avvisare gli operatori, chiudere iscrizioni, sospendere tutte le operazioni admin.
   Salvare e verificare anche un backup dello stato corrente.
3. Dopo conferma esplicita, selezionare il file reale e fermare web:

```bash
cd /opt/pmsea-test/infra
backup_file="/opt/pmsea-test/backups/app_db_YYYYMMDD_HHMMSS.sql"
test -s "$backup_file"
sha256sum -c "$backup_file.sha256"
docker compose stop web
```

4. Solo se le verifiche sono riuscite, eseguire il restore:

```bash
docker compose exec -T db sh -c '
  MYSQL_PWD="$MARIADB_ROOT_PASSWORD" exec mariadb --user=root
' < "$backup_file"
```

5. Se fallisce, lasciare web fermo: il restore SQL non è atomico.
   Non riavviare né ripetere tentativi casuali. Tabelle aggiunte dopo il dump
   potrebbero restare presenti: un dump precedente non equivale a un downgrade.
6. Dopo restore riuscito verificare compatibilità del codice e dello schema.
   Avviare web solo dopo aver valutato le migrazioni che l’entrypoint applicherà:

```bash
docker compose up -d web
docker compose exec web flask db current
docker compose exec web flask db heads
```

7. Controllare accesso admin, stato iscrizioni ripristinato, conteggi, scelte,
   gruppi ed export. Un dump può ripristinare anche lo stato **aperte**:
   mantenere l’accesso pubblico sospeso fino alla verifica e all’eventuale chiusura.

## Rollback del codice

Salvare prima il DB. Richiede un working tree pulito: non eliminare le modifiche
locali per ottenere questo risultato; se presenti, fermarsi e concordarne la conservazione.
Individuare un commit stabile e verificarne la compatibilità con lo schema corrente.

```bash
cd /opt/pmsea-test/app
git status
git log -10 --oneline --decorate
```

Dopo aver scelto l’hash reale, creare un branch dedicato (il comando è un esempio
da completare, non da incollare con il segnaposto):

```bash
git switch -c rollback-evento HASH_COMMIT_STABILE
cd /opt/pmsea-test/infra
docker compose build web
docker compose up -d web
```

Nessuna cronologia viene cancellata. Il rollback codice **non** retrocede il DB;
se lo schema è incompatibile, fermarsi e pianificare il recupero con backup.
Per tornare a dev, sempre con working tree pulito:

```bash
cd /opt/pmsea-test/app
git switch dev
cd /opt/pmsea-test/infra
docker compose build web
docker compose up -d web
```

## Se il sito non risponde

1. Eseguire `docker compose ps` dalla directory infra.
2. Leggere `docker compose logs --tail=100 web`.
3. Leggere `docker compose logs --tail=100 db`.
4. Verificare che db sia **healthy**. Il servizio web non ha un healthcheck:
   “Up” non basta; aprire anche la homepage. Per il controllo DB in lettura:

   ```bash
   docker inspect --format '{{.State.Health.Status}}' "$(docker compose ps -q db)"
   ```

5. Se web usa codice vecchio, ricostruirlo con i comandi sopra.
6. Confrontare `flask db current` e `flask db heads`; se web non parte,
   controllare nei log l’upgrade dell’entrypoint prima di qualsiasi intervento.
7. Evitare modifiche casuali al DB. Se i container funzionano ma il sito non è
   raggiungibile, verificare porta/rete e l’eventuale proxy del deployment reale.

## Regole di sicurezza operativa

> - Mai test distruttivi su `app_db`.
> - Mai cancellare dati per “riprovare”, né usare `docker compose down -v`.
> - Backup prima degli interventi importanti; conservarne copia fuori dalla VM.
> - Import seriali e preview controllata prima della conferma.
> - Niente modifiche manuali dello schema; preferire UI admin e migrazioni versionate.
> - Commit verificato prima di deploy significativi, previa autorizzazione.

## Fine evento

Chiudere definitivamente le iscrizioni, fare backup ed export finali e aprire gli
XLSX per verificarli. Conservare dump, checksum, file consegnati e riferimento
del commit in un luogo riservato fuori dalla VM. Annotare le correzioni manuali
significative. Quando la consultazione non serve più, valutare la disattivazione
del servizio senza eliminare i dati persistenti.
