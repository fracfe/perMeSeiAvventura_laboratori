# AGENTS.md

## 1. Scopo del progetto

Questo repository contiene l’applicazione web per la gestione delle iscrizioni ai laboratori del convegno nazionale AGESCI **“Per Me Sei Avventura”**, settembre 2026.

Il sistema è destinato a circa **400 partecipanti**, con un possibile picco iniziale di circa **50–100 utenti contemporanei**.

La vita operativa dell’applicazione è breve: deve funzionare bene per le settimane dell’evento e non è destinata a diventare una piattaforma permanente.

Le priorità, in ordine, sono:

1. integrità dei dati;
2. affidabilità dei flussi;
3. semplicità operativa;
4. chiarezza per utenti e admin;
5. facilità di verifica;
6. rapidità di intervento;
7. codice comprensibile.

**Non introdurre complessità che non risolve un problema concreto dell’evento.**

---

# 2. Principio fondamentale

Il progetto è nella fase finale.

Quando esistono più soluzioni corrette, preferire quella:

* più semplice;
* meno invasiva;
* coerente con il codice esistente;
* facile da testare;
* facile da correggere durante l’evento.

Non sono obiettivi:

* grandi refactoring;
* architetture enterprise;
* microservizi;
* repository pattern generalizzati;
* service layer introdotti solo per principio;
* code asincrone;
* Redis;
* websocket;
* caching sofisticato;
* nuove infrastrutture;
* generalizzazioni per futuri casi d’uso ipotetici.

Una funzione semplice nel punto giusto è spesso preferibile a una nuova astrazione.

---

# 3. Modalità di lavoro agentica

Ogni task deve essere trattata come un intervento circoscritto su un sistema già funzionante.

## Prima di modificare

1. leggere la richiesta completa;
2. leggere le parti pertinenti di questo file;
3. controllare:

```bash
git branch --show-current
git status
```

4. individuare i file e le invarianti coinvolte;
5. verificare il comportamento esistente prima di cambiarlo;
6. distinguere chiaramente:

   * comportamento da mantenere;
   * comportamento da modificare;
   * comportamento fuori scope.

Quando la richiesta è di sola analisi:

**non modificare file.**

---

## Durante la modifica

* intervenire solo sui file necessari;
* non correggere incidentalmente problemi non richiesti;
* non fare refactoring estetici;
* riutilizzare funzioni e algoritmi già presenti quando adeguati;
* evitare duplicazione della logica di business;
* mantenere le transazioni brevi;
* preservare i dati non interessati dalla task;
* aggiungere test mirati per il nuovo comportamento.

Se emerge un problema estraneo:

1. segnalarlo;
2. indicarne gravità e impatto;
3. non correggerlo automaticamente salvo sia indispensabile per completare la task.

---

## Dopo la modifica

Verificare almeno:

1. test mirati;
2. suite generale pertinente;
3. `git diff --check`;
4. assenza di file temporanei/debug;
5. `git status`.

Nel report finale indicare:

* file modificati;
* comportamento precedente;
* comportamento nuovo;
* invarianti preservate;
* test eseguiti;
* eventuali limiti o problemi rimasti.

---

# 4. Autonomia operativa

Codex può autonomamente:

* leggere e modificare il repository;
* eseguire test;
* ricostruire il container `web`;
* riallineare lo stack Docker;
* creare e rimuovere database/container MariaDB temporanei per i test;
* chiedere approvazione per uscire dalla sandbox quando serve Docker.

Quando il codice nel container può essere vecchio rispetto al workspace, riallinearlo autonomamente:

```bash
cd /opt/pmsea-test/infra
docker compose build web
docker compose up -d web
```

Non considerare valido un test sul container prima di aver verificato che il codice sia aggiornato.

---

# 5. Operazioni vietate senza richiesta esplicita

Non eseguire autonomamente:

* commit;
* push;
* merge;
* rebase;
* reset Git;
* modifica del branch `main`;
* cancellazione di dati persistenti;
* test distruttivi su database reali;
* modifiche di configurazione produzione;
* migrazioni sul database reale se non richieste.

Branch ordinario:

```text
dev
```

Branch stabile:

```text
main
```

---

# 6. Stack

## Backend

* Python 3.11
* Flask
* Flask-SQLAlchemy
* Flask-Migrate / Alembic
* Flask-Login
* Gunicorn

## Database

Database di riferimento:

* MariaDB 11.4

SQLite viene usato per molti test applicativi.

Le funzionalità relative a:

* `SELECT ... FOR UPDATE`;
* concorrenza;
* transazioni;
* CHECK;
* migration;
* comportamento specifico del driver;

devono essere verificate anche su MariaDB quando pertinenti.

## Frontend

* Jinja
* Bootstrap
* Alpine.js
* JavaScript semplice
* SheetJS/XLSX

Non introdurre framework frontend aggiuntivi.

---

# 7. Ambiente

Repository:

```text
/opt/pmsea-test/app
```

Docker Compose:

```text
/opt/pmsea-test/infra
```

Applicazione test:

```text
http://192.168.10.51:5000
```

Il database persistente dell’ambiente è:

```text
app_db
```

**Non usare `app_db` per test distruttivi.**

Quando servono test MariaDB distruttivi, creare un database/container temporaneo dedicato e rimuoverlo al termine.

---

# 8. Modello dati attuale

## Partecipante

La primary key `Partecipante.id` è il **codice censimento AGESCI**.

Campi persistiti:

* `id`
* `nome`
* `cognome`
* `gruppo`
* `zona`
* `regione`
* `email`
* `sesso`
* `foca`
* `ruolo`
* `incarico_altro`
* `deve_iscriversi_sabato`
* `includi_domenica`
* `gruppo_domenica`

`gruppo` indica il gruppo scout.

`gruppo_domenica` indica invece l’assegnazione all’attività della domenica.

Non confondere i due campi.

---

## Laboratorio

Campi principali:

* primary key interna `id`;
* `id_lab`;
* `titolo`;
* `descrizione`;
* `posti`;
* `tipologia`.

Tipologie:

```text
mattino
pomeriggio
```

La chiave logica usata per import e gestione è:

```text
(tipologia, id_lab)
```

Non esiste volutamente un vincolo UNIQUE DB su questa coppia.

Le operazioni amministrative di import/creazione vanno considerate seriali.

---

## Iscrizione

Ogni partecipante può avere al massimo una riga `Iscrizione`.

Contiene:

* partecipante;
* scelta mattino;
* scelta pomeriggio;
* `non_partecipa_mattino`;
* `non_partecipa_pomeriggio`;
* `sottogruppo_mattino`;
* `sottogruppo_pomeriggio`;
* `data`.

I sottogruppi sono:

```text
A
B
NULL
```

`data` rappresenta l’ultimo aggiornamento dell’iscrizione ordinaria.

Le operazioni amministrative manuali devono preservare il timestamp quando previsto dal comportamento attuale.

---

# 9. Stato iscrizioni

Stati consentiti:

```text
aperte
chiuse
```

Conservati in `system_option` / `SysOption` con chiave:

```text
stato_iscrizioni
```

Valori mancanti o invalidi devono comportarsi in modo sicuro come:

```text
chiuse
```

Il testo:

```text
messaggio_iscrizioni
```

è solo un messaggio libero.

Non interpretarlo come scheduler, data o configurazione temporale.

---

# 10. Flusso partecipante

## Identificazione

Il partecipante inserisce il codice censimento.

Il codice può essere verificato anche con iscrizioni chiuse.

Il sistema mostra nome e cognome e richiede conferma esplicita dell’identità.

L’identità confermata viene registrata nella sessione.

---

# 11. Flag sabato

## `deve_iscriversi_sabato = false`

La persona:

* non deve scegliere laboratori;
* non deve scegliere “non partecipo”;
* non deve essere considerata incompleta;
* deve andare direttamente al riepilogo;
* non deve poter forzare le route di scelta tramite GET/POST.

Non creare automaticamente una riga `Iscrizione`.

Nei riepiloghi/export mostrare:

```text
Iscrizione non richiesta
```

---

## `deve_iscriversi_sabato = true`

Flusso ordinario:

1. scelta mattino;
2. salvataggio;
3. scelta pomeriggio;
4. salvataggio;
5. riepilogo.

Il flusso progressivo, la ripresa da stato incompleto e la modifica delle scelte devono continuare a funzionare.

---

# 12. Stato di una fascia del sabato

Ogni fascia può trovarsi in uno dei seguenti stati.

## Laboratorio scelto

```text
scelta != NULL
non_partecipa = false
```

## Rinuncia esplicita

```text
scelta = NULL
non_partecipa = true
```

Visualizzazione:

```text
Non partecipa
```

## Scelta non ancora effettuata

```text
scelta = NULL
non_partecipa = false
```

Visualizzazione:

```text
Non iscritto
```

## Iscrizione non richiesta

Quando:

```text
deve_iscriversi_sabato = false
```

Visualizzazione:

```text
Iscrizione non richiesta
```

Non confondere questi stati.

---

# 13. Capienza e concorrenza

Nel normale flusso partecipante il server è l’autorità finale.

La disponibilità mostrata dal frontend è informativa.

Per il salvataggio:

* usare transazioni brevi;
* bloccare le righe necessarie con `FOR UPDATE`;
* ricontare gli occupanti dopo il lock;
* verificare nuovamente la capienza.

Un laboratorio pieno:

* rimane visibile;
* non è selezionabile da nuovi utenti;
* può essere mantenuto da chi lo possiede già.

In contesa sull’ultimo posto, un solo partecipante deve ottenerlo.

---

# 14. Override amministrativo

L’admin può modificare un partecipante e forzare manualmente:

* laboratorio mattino;
* A/B mattino;
* laboratorio pomeriggio;
* A/B pomeriggio;
* gruppo domenica.

Queste sono operazioni amministrative straordinarie.

## Laboratori sabato

L’admin può assegnare un laboratorio anche oltre la capienza.

Questo NON modifica il comportamento del normale partecipante.

Se viene assegnato almeno un laboratorio:

```text
deve_iscriversi_sabato = true
```

Se viene assegnato un laboratorio nella fascia:

```text
non_partecipa_* = false
```

Se il laboratorio viene rimosso:

* scelta → `NULL`;
* relativo A/B → `NULL`.

A/B può essere:

```text
NULL
A
B
```

e può essere modificato anche dopo il calcolo automatico.

---

## Domenica

L’admin può:

* assegnare;
* cambiare;
* rimuovere

il gruppo domenicale.

Quando viene assegnato un gruppo:

```text
includi_domenica = true
```

La rimozione del gruppo non modifica automaticamente il flag.

Un successivo ricalcolo può sovrascrivere l’override manuale.

---

# 15. Campi obbligatori nella gestione manuale

Per creazione/modifica manuale sono obbligatori:

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

`ruolo` / “Partecipo in qualità di” è facoltativo.

`incarico_altro` è obbligatorio solo quando il ruolo indica “Altro”.

Gli errori devono preservare i valori compilati nel form.

---

# 16. Reset sabato singolo

L’admin può azzerare il sabato di una singola persona.

L’azione:

* è POST;
* richiede `admin_required`;
* elimina la riga `Iscrizione`.

Vengono quindi rimossi:

* scelta mattino;
* scelta pomeriggio;
* rinunce;
* A/B.

Restano invariati:

* Partecipante;
* anagrafica;
* flag;
* gruppo domenica.

---

# 17. Import partecipanti

Formato:

* CSV UTF-8;
* separatore `;`;
* intestazioni nella prima riga.

Il vecchio Excel partecipanti non è supportato.

Il CSV viene letto nel browser tramite SheetJS.

Non usare:

```javascript
split(';')
```

Il parser deve supportare:

* BOM UTF-8;
* accenti;
* virgolette;
* `;` dentro campi quotati;
* newline Windows/Linux.

---

# 18. Campi importati dal CSV

Mapping:

| CSV                                                   | Partecipante           |
| ----------------------------------------------------- | ---------------------- |
| Codice                                                | id                     |
| Nome                                                  | nome                   |
| Cognome                                               | cognome                |
| Gruppo                                                | gruppo                 |
| Zona                                                  | zona                   |
| Regione                                               | regione                |
| EmailContatto                                         | email                  |
| Sesso                                                 | sesso                  |
| FoCa                                                  | foca                   |
| Partecipo in qualità di:                              | ruolo                  |
| Se hai indicato "altro" specifica incarico:           | incarico_altro         |
| Partecipa ai laboratori di sabato come partecipante   | deve_iscriversi_sabato |
| Partecipa ai laboratori di domenica come partecipante | includi_domenica       |

Non persistono:

* BC;
* PIC;
* DataNascita;
* CAP;
* Città;
* PR;
* EmailReferente;
* altre colonne.

L’email applicativa proviene esclusivamente da:

```text
EmailContatto
```

---

# 19. Preview import partecipanti

L’import è un processo a due fasi.

## Preview

1. selezione CSV;
2. parsing;
3. validazione;
4. confronto con DB;
5. anteprima.

Durante la preview:

* nessuna scrittura;
* nessun timestamp aggiornato;
* nessuna modifica a iscrizioni o gruppi.

Mostrare:

* nuovi;
* modificati;
* invariati;
* totale.

Il dettaglio deve indicare i campi realmente cambiati.

Esempio:

```text
12345 – Rossi Mario: nuovo
67890 – Bianchi Luca: modificati Email, Regione, Zona
```

Il dettaglio lungo deve essere collassabile.

---

## Conferma import

Solo dopo:

```text
Conferma import
```

il backend ripete validazione e confronto usando lo stato DB corrente e applica la transazione.

Non fidarsi del risultato della preview salvato nel browser.

---

# 20. Semantica import partecipanti

Il comportamento è UPSERT incrementale.

## Codice nuovo

Inserimento.

## Codice esistente

Aggiornare esclusivamente i campi provenienti dal CSV.

## Codice assente dal CSV

Non modificare e non eliminare.

L’import NON deve modificare:

* scelte sabato;
* rinunce;
* timestamp iscrizione;
* A/B;
* gruppo domenica.

Anche se `includi_domenica` diventa `false`, un gruppo domenicale esistente rimane fino al successivo ricalcolo.

L’import è atomico.

---

# 21. Flag CSV

Valori true accettati, ignorando maiuscole/minuscole e spazi:

```text
Sì
Si
S
Yes
True
1
```

Valori false:

```text
No
N
False
0
```

Vuoto o sconosciuto:

**errore bloccante.**

---

# 22. Import laboratori

Formato Excel con due fogli:

```text
mattino
pomeriggio
```

Colonne:

```text
id
titolo
descrizione
posti
```

La chiave di riconciliazione è:

```text
(tipologia, id_lab)
```

Comportamento:

* zero corrispondenze → nuovo;
* una → aggiornamento preservando primary key;
* più di una → errore;
* assente dal file → invariato.

Non cancellare laboratori durante il reimport.

---

# 23. Preview import laboratori

Anche l’import laboratori è a due fasi.

Prima della scrittura mostra:

* nuovi;
* modificati;
* invariati;
* totale;
* dettaglio campi realmente cambiati.

Esempio:

```text
mattino / L01 – nuovo
pomeriggio / L05 – modificati Titolo, Posti
```

La preview non modifica il database.

La conferma ripete validazioni e confronto lato server.

---

# 24. Capienza negli import laboratori

Una riduzione di capienza è consentita solo se:

```text
nuovi_posti >= iscritti effettivi
```

Le rinunce non occupano posto.

L’admin può superare manualmente la capienza assegnando una persona, ma questo non autorizza un import a ridurre indiscriminatamente la capienza sotto gli iscritti.

---

# 25. Atomicità degli import

Partecipanti e laboratori devono rispettare:

```text
tutto o niente
```

In caso di errore:

* rollback;
* nessuna scrittura parziale;
* timestamp import invariato.

Timestamp e modifiche appartengono alla stessa operazione riuscita.

---

# 26. Gruppi della domenica

Esistono esattamente **20 gruppi**.

La persistenza nel DB è numerica:

```text
1 ... 20
```

Mappa applicativa unica:

```text
1  Avventura
2  Bisogno
3  Cura
4  Dio
5  Esperienza
6  Fuori
7  Gradualità
8  Habitus
9  Incontro
10 Linguaggio
11 Mistero
12 Natura
13 Occasione
14 Progettualità
15 Quotidiano
16 Responsabilità
17 Sfida
18 Tempo
19 Unicità
20 Vivere
```

Usare la costante esistente:

```text
NOMI_GRUPPI_DOMENICA
```

Non duplicare questa mappa.

---

# 27. Ricalcolo domenica

Considerare solo:

```text
includi_domenica = true
```

Criteri, in ordine:

1. Regione;
2. ruolo;
3. FoCa;
4. Sesso.

Riutilizzare l’algoritmo esistente:

* categorie rare;
* greedy;
* scambi locali;
* bilanciamento numerico;
* comportamento deterministico.

Non progettare un algoritmo nuovo senza richiesta.

Il ricalcolo:

* salva `gruppo_domenica`;
* pulisce gli esclusi;
* è atomico;
* non modifica il sabato.

Con meno di 20 persone sono ammessi gruppi vuoti.

Con zero persone il risultato è valido.

---

# 28. Visualizzazione domenica

## Non richiesta

```text
includi_domenica = false
```

Mostrare:

```text
Partecipazione ai gruppi della domenica: non richiesta
```

Ignorare eventuali vecchie assegnazioni persistite.

## Richiesta ma non assegnata

```text
Non ancora assegnato
```

## Assegnata

Lato utente mostrare il nome:

```text
Gradualità
```

Lato admin può essere utile:

```text
7 – Gradualità
```

---

# 29. Gruppi A/B del sabato

A/B viene calcolato separatamente per:

* ogni laboratorio;
* ogni fascia.

La stessa persona può quindi essere:

```text
A mattino
B pomeriggio
```

Considerare solo persone realmente iscritte al laboratorio.

Escludere:

* scelta `NULL`;
* “non partecipa”.

Criteri:

1. Regione;
2. ruolo;
3. FoCa;
4. Sesso.

Riutilizzare lo stesso nucleo algoritmico della domenica.

Gruppo algoritmo:

```text
1 → A
2 → B
```

Persistire esclusivamente:

```text
A
B
NULL
```

---

# 30. Quando può essere calcolato A/B

Il ricalcolo A/B è consentito solo quando:

```text
stato_iscrizioni = chiuse
```

La protezione deve esistere:

* nella UI;
* nel backend.

Con iscrizioni aperte:

* non calcolare;
* non modificare A/B esistenti;
* mostrare un messaggio chiaro.

---

# 31. Ricalcolo A/B

Il ricalcolo globale:

* pulisce le vecchie A/B;
* ricalcola tutti i laboratori;
* è atomico;
* non modifica scelte;
* non modifica rinunce;
* non modifica timestamp;
* non modifica domenica.

Non ricalcolare automaticamente dopo ogni modifica manuale.

Procedura operativa prevista:

```text
chiusura iscrizioni
→ ricalcolo A/B
```

Se successivamente un admin modifica una scelta, può ricalcolare nuovamente.

---

# 32. Dashboard admin

I contatori del sabato considerano come popolazione rilevante solo:

```text
deve_iscriversi_sabato = true
```

Chi ha sabato non richiesto deve avere stato:

```text
Non richiesta
```

e non deve essere contato tra:

* incompleti;
* non iniziati.

Il totale generale partecipanti continua a includere tutti.

Non persistere statistiche aggregate.

---

# 33. Export iscrizioni

Esistono due export distinti.

## Generale

Nome:

```text
iscrizioni_generali_<data>.xlsx
```

## Per laboratorio

Nome:

```text
iscrizioni_per_laboratorio_<data>.xlsx
```

Verificare sempre `Content-Disposition`.

---

# 34. Foglio generale

Deve includere tutti i partecipanti.

Campi principali:

* codice;
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

---

# 35. Semantica export sabato

La colonna laboratorio e la colonna A/B non devono lasciare stati ambigui.

| Stato                            | Laboratorio              | A/B                      |
| -------------------------------- | ------------------------ | ------------------------ |
| sabato non richiesto             | Iscrizione non richiesta | Iscrizione non richiesta |
| scelta non fatta                 | Non iscritto             | Non iscritto             |
| rinuncia                         | Non partecipa            | Non partecipa            |
| laboratorio scelto, A/B assente  | laboratorio              | Non assegnato            |
| laboratorio scelto, A/B presente | laboratorio              | A oppure B               |

Nei fogli del singolo laboratorio:

* mostrare solo iscritti effettivi;
* A/B assente → `Non assegnato`.

---

# 36. File comunicazioni

Il file comunicazioni usa esclusivamente il database.

Non esiste più il merge operativo con Excel domenica.

Include tutti i partecipanti una volta sola.

Campi:

* codice;
* nome;
* cognome;
* email;
* sabato mattino;
* A/B mattino;
* sabato pomeriggio;
* A/B pomeriggio;
* domenica.

Email:

```text
Partecipante.email
```

Domenica:

* flag false → `Iscrizione non richiesta`;
* flag true + gruppo `NULL` → `Non assegnato`;
* gruppo presente → nome da `NOMI_GRUPPI_DOMENICA`.

La generazione è read-only.

Non ricalcolare domenica o A/B durante gli export.

---

# 37. Area amministrativa operativa

Devono essere raggiungibili in modo chiaro almeno:

* login/logout;
* cambio password;
* stato iscrizioni;
* messaggio informativo;
* import partecipanti;
* import laboratori;
* gestione partecipanti;
* gestione laboratori;
* reset sabato singolo;
* modifica manuale assegnazioni;
* suddivisione domenica;
* gruppi A/B;
* export;
* comunicazioni.

Non lasciare nel percorso operativo riferimenti a vecchi flussi sostituiti.

---

# 38. Test

## SQLite

Usare per:

* logica applicativa;
* route;
* validazioni;
* rendering;
* export;
* import;
* algoritmi.

## MariaDB

Usare quando pertinente per:

* migration;
* lock;
* concorrenza;
* `FOR UPDATE`;
* CHECK;
* ultimo posto;
* comportamento del driver.

Differenze SQLite/MariaDB documentate e accettate:

* alcuni CHECK MariaDB/PyMySQL possono produrre `OperationalError 4025`;
* valori troppo lunghi possono produrre `DataError 1406`;
* la collation MariaDB può essere case-insensitive per A/B.

Non modificare schema/collation solo per uniformare eccezioni dei test quando la semantica applicativa è corretta.

L’applicazione deve comunque scrivere solo `A` e `B` maiuscoli.

---

# 39. Test distruttivi

Le suite che cancellano o ricreano dati devono usare un database temporaneo dedicato.

**Mai eseguire suite distruttive su `app_db`.**

Prima di un test distruttivo verificare esplicitamente il target DB.

Al termine rimuovere container/database temporanei.

---

# 40. Migrazioni

Ogni modifica allo schema deve usare Alembic.

Non modificare manualmente il DB come soluzione definitiva.

Verificare, quando pertinente:

* upgrade da DB vuoto;
* compatibilità MariaDB;
* conservazione dati esistenti.

Il container esegue le migration all’avvio secondo la configurazione esistente.

Prima di concludere che una migrazione non esiste o non funziona, verificare che il container sia stato ricostruito con il codice corrente.

---

# 41. Sicurezza

Applicare misure proporzionate al progetto.

Prestare attenzione a:

* validazione server-side;
* route admin;
* sessioni;
* hashing password;
* minimizzazione dei dati;
* escaping;
* rollback;
* errori non sensibili.

Non introdurre infrastrutture di sicurezza sproporzionate senza richiesta.

Il backend non deve mai fidarsi del frontend.

---

# 42. Privacy

Persistire esclusivamente i dati necessari.

Il CSV originale dei partecipanti:

* rimane nel browser;
* non viene caricato integralmente sul server;
* non viene salvato;
* non viene memorizzato in localStorage/sessionStorage.

Campi non previsti dal mapping devono essere ignorati.

---

# 43. Frontend

L’applicazione deve essere soprattutto utilizzabile da smartphone.

Preferire:

* Bootstrap esistente;
* card;
* pulsanti chiari;
* testi brevi;
* feedback immediato;
* navigazione semplice;
* sezioni `<details>` per informazioni lunghe;
* form che preservano i valori in caso di errore.

Non introdurre React, Vue o altri framework.

---

# 44. Compatibilità

Prima di considerare conclusa una modifica significativa verificare, quando pertinente:

* homepage;
* login/logout;
* stato iscrizioni;
* verifica codice;
* conferma identità;
* sabato richiesto;
* sabato non richiesto;
* mattino;
* pomeriggio;
* rinunce;
* modifica scelte;
* laboratori pieni;
* iscrizioni chiuse;
* riepilogo domenica;
* import partecipanti;
* import laboratori;
* admin manuale;
* ricalcolo domenica;
* ricalcolo A/B;
* export;
* comunicazioni.

Non rompere un flusso esistente per completarne un altro.

---

# 45. Git

Remote:

```text
origin
```

fork di sviluppo:

```text
fracfe/perMeSeiAvventura_laboratori
```

Remote upstream:

```text
upstream
```

repository originale:

```text
calminaro/perMeSeiAvventura_laboratori
```

Prima di ogni task:

```bash
git status
git branch --show-current
```

Non cancellare modifiche già presenti.

Non fare commit o push salvo richiesta esplicita.

---

# 46. Criterio di completamento di una task

Una task è completata quando:

1. il requisito richiesto funziona;
2. le invarianti correlate sono preservate;
3. i test pertinenti passano;
4. MariaDB è stato verificato quando necessario;
5. il container è stato riallineato se usato;
6. `git diff --check` passa;
7. non sono presenti modifiche estranee;
8. il report finale descrive chiaramente il risultato.

Non continuare a “migliorare” il codice dopo che questi criteri sono soddisfatti.

---

# 47. Obiettivo finale

Questo progetto deve essere una piccola applicazione:

* affidabile;
* semplice;
* comprensibile;
* mobile-friendly;
* sufficientemente sicura;
* facile da amministrare;
* facile da correggere durante l’evento.

L’obiettivo non è costruire una piattaforma perfetta.

L’obiettivo è che **circa 400 partecipanti possano svolgere correttamente il proprio percorso e che gli organizzatori possano gestire iscrizioni, assegnazioni ed eccezioni senza intervenire direttamente sul database**.
