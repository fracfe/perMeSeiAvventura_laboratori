# Per Me Sei Avventura - Tool Laboratori
Tool iscrizione laboratori convegno nazionale Per Me Sei Avventura

### Schema DB

<img title="Schema DB" src="./static/schema_db.png" alt="" data-align="center">

### Deploy
Docker compose: 
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
      test: ["CMD", "mariadb-admin", "ping", "-h", "localhost", "-uroot", "-prootpassword"]
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
nginx.conf
```
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

### Import partecipanti CSV

Dall'admin scegliere **Importa partecipanti**, selezionare un `.csv` UTF-8 con
separatore `;` e intestazioni alla prima riga, verificare l'anteprima e premere
**Importa partecipanti**. Il vecchio Excel iscritti non è più accettato.
Le intestazioni richieste e il mapping sono documentati in [AGENTS.md](AGENTS.md#import-partecipanti-csv).

Il file originale viene letto nel browser; soltanto i 13 campi necessari sono
inviati al server. Codice, Nome, Cognome e i due flag sono obbligatori;
i valori anagrafici facoltativi vuoti diventano NULL.
Per i flag sono ammessi `Sì/Si/S/Yes/True/1` e `No/N/False/0`, ignorando
maiuscole/minuscole e spazi iniziali/finali. Flag vuoti o sconosciuti bloccano
l'intero import. Sono supportati BOM, accenti e campi CSV quotati.

Il reimport aggiorna i dati CSV dei codici esistenti e inserisce quelli nuovi.
Chi manca dal file resta invariato. Iscrizioni, rinunce, timestamp delle
iscrizioni, gruppo domenicale e sottogruppi A/B sono conservati.
Il riepilogo riporta nuovi inseriti, esistenti aggiornati e righe elaborate;
"aggiornati" include anche i codici già presenti con dati identici.

### Test import CSV

Test backend: `python -m unittest discover -s tests -p test_import_csv.py -v`.
Per includere i test del parser browser servono Node.js nel PATH e
`SHEETJS_TEST_PATH` impostato al percorso assoluto di una copia di
`xlsx@0.18.5/dist/xlsx.full.min.js`, la stessa versione caricata da `admin.html`.
La suite non scarica dipendenze e salta questi test se l'ambiente non è pronto.

```sh
SHEETJS_TEST_PATH=/percorso/xlsx.full.min.js python -m unittest discover -s tests -v
```


### Import laboratori incrementale

Il formato resta Excel con fogli `mattino` e `pomeriggio` e colonne `id`,
`titolo`, `descrizione`, `posti`. Entrambi i fogli sono obbligatori e non vuoti.
La coppia fascia/codice identifica il laboratorio: quelli nuovi sono inseriti;
quelli esistenti mantengono ID e iscrizioni e aggiornano titolo, descrizione e
posti. Quelli assenti dal file restano invariati.

Duplicati nello stesso foglio o più corrispondenze nel DB bloccano tutto.
Lo stesso codice può essere usato in entrambe le fasce. Le riduzioni sotto gli
iscritti effettivi sono rifiutate; le rinunce non vengono conteggiate.
Ogni errore annulla l'import e conserva il timestamp precedente.
Il riepilogo mostra nuovi, aggiornati e totale. Non è stato aggiunto un UNIQUE:
eseguire gli import amministrativi uno alla volta.


### Gestione manuale admin

Dalla gestione iscrizioni è possibile aggiungere un partecipante o modificarne
l'anagrafica. Il codice censimento resta immutabile; i due flag richiedono una
scelta esplicita. Le modifiche non cambiano iscrizioni o gruppi già assegnati.
Da Gestione dati è possibile aggiungere laboratori e modificare titolo,
descrizione e posti, mantenendo immutabili codice e fascia. La capienza viene
verificata rispetto agli iscritti effettivi sotto lock al salvataggio.

Il pulsante **Azzera iscrizioni sabato**, con conferma JavaScript, elimina via
POST la sola riga Iscrizione della persona, comprese rinunce e A/B. Anagrafica,
flag del partecipante e gruppo domenicale rimangono invariati. A iscrizioni
aperte la persona può ripartire dalla scelta del mattino.
Le operazioni sono riservate all'admin; non aggiornano i timestamp degli import.
Non sono state aggiunte eliminazioni individuali di partecipanti o laboratori.
Le creazioni laboratorio, senza UNIQUE DB, vanno eseguite una alla volta,
anche rispetto agli import amministrativi.
