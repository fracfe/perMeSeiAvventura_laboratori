# AGENTS.md

## Progetto

Questo repository contiene l'applicazione web per la gestione delle iscrizioni ai laboratori del convegno nazionale AGESCI **“Per Me Sei Avventura”**, previsto a settembre 2026.

L'applicazione verrà utilizzata da circa **400 partecipanti**, con un possibile picco iniziale di circa **50–100 utenti contemporanei**.

La vita operativa dell'applicazione sarà molto breve: terminato il convegno, non è previsto che diventi un prodotto, una piattaforma o un gestionale permanente.

Lo sviluppo deve quindi privilegiare:

1. affidabilità;
2. semplicità;
3. chiarezza del codice;
4. facilità di test;
5. rapidità nel completamento;
6. buona esperienza utente;
7. integrità dei dati.

**Non introdurre complessità non necessaria.**

Non progettare il software come una piattaforma enterprise, multi-tenant o destinata a crescere negli anni.

---

## Obiettivo dello sviluppo

Il progetto è già in gran parte realizzato ed è nella fase finale di completamento e rifinitura.

Il lavoro restante consiste principalmente in:

* correggere eventuali bug;
* rifinire UX e testi;
* completare piccole funzionalità mancanti;
* verificare affidabilità e sicurezza;
* effettuare test;
* preparare il deploy di produzione.

Non effettuare riscritture generali o grandi refactoring se non espressamente richiesti.

Quando una modifica può essere realizzata intervenendo sul codice esistente in modo semplice e leggibile, questa soluzione è preferibile all'introduzione di:

* nuove astrazioni;
* framework;
* servizi;
* layer;
* infrastrutture aggiuntive.

L'obiettivo non è produrre il codice più sofisticato possibile.

L'obiettivo è avere una piccola applicazione **semplice, comprensibile, affidabile e pronta per l'evento**.

---

## Stack attuale

### Backend

* Python 3.11
* Flask
* Flask-SQLAlchemy
* Flask-Migrate / Alembic
* Flask-Login
* Gunicorn

### Database

* MariaDB 11.4 come database di riferimento per test e produzione
* il codice supporta anche SQLite, utilizzato principalmente per alcuni test isolati

Le funzionalità che dipendono da:

* lock;
* concorrenza;
* `SELECT ... FOR UPDATE`;
* migration;
* vincoli MariaDB;

devono essere considerate valide solo dopo verifica su MariaDB.

### Frontend

* Jinja
* Bootstrap
* Alpine.js
* JavaScript semplice
* SheetJS/XLSX per la lettura locale dei file Excel

### Deployment

* Docker
* Docker Compose
* Gunicorn
* GitHub Container Registry
* GitHub Actions

Non introdurre framework frontend, API layer, code generator, task queue, Redis o altri servizi salvo richiesta esplicita.

---

## Struttura generale

L'applicazione è volutamente piccola e monolitica.

Backend principale:

`app.py`

Template:

`templates/`

File statici:

`static/`

Migration:

`migrations/`

Test:

`tests/`

Dockerfile e script di entrypoint sono nella root del repository.

Mantenere questa struttura salvo motivazioni concrete concordate prima.

Non suddividere il progetto in package, service layer, repository layer o altre architetture soltanto per principio.

---

# Modello funzionale

## Partecipante

Rappresenta una persona autorizzata a iscriversi ai laboratori.

Il suo `id` corrisponde al **codice censimento AGESCI**.

I codici censimento utilizzati nel progetto sono:

* numerici;
* interi positivi;
* sequenziali;
* senza zeri iniziali significativi.

Il partecipante conserva codice censimento, nome, cognome e i campi anagrafici
esplicitamente previsti dall'import CSV descritto sotto. Il gruppo domenicale
è persistito separatamente dai dati aggiornabili dal CSV.

---

## Laboratorio

Contiene almeno:

* identificativo interno;
* codice laboratorio;
* titolo;
* descrizione;
* numero massimo di posti;
* tipologia.

Le tipologie utilizzate sono:

* `mattino`
* `pomeriggio`

Un laboratorio del mattino non può essere utilizzato come scelta del pomeriggio e viceversa.

---

## Iscrizione

Ogni partecipante può avere **una sola riga `Iscrizione`**.

Il database deve garantire l'unicità dell'iscrizione per partecipante.

L'iscrizione contiene:

* partecipante;
* scelta del sabato mattina;
* scelta del sabato pomeriggio;
* data/ora dell'ultimo aggiornamento.

Le due scelte possono essere temporaneamente `NULL`, perché l'iscrizione viene completata progressivamente.

### Iscrizione incompleta

Una iscrizione è incompleta quando manca almeno una delle due scelte.

Il caso normale previsto è:

* mattino salvato;
* pomeriggio ancora `NULL`.

### Iscrizione completa

Una iscrizione è completa quando:

* `scelta_mattino` non è `NULL`;
* `scelta_pomeriggio` non è `NULL`.

---

## User

Rappresenta l'utente amministrativo.

Gli utenti normali non possiedono account permanenti.

I partecipanti vengono identificati tramite codice censimento e sessione temporanea Flask-Login.

---

## SysOption

La tabella `SysOption` viene utilizzata per semplici impostazioni applicative.

Tra queste:

* stato delle iscrizioni;
* messaggio informativo;
* timestamp ultimo import partecipanti;
* timestamp ultimo import laboratori.

Non creare nuove tabelle quando una semplice opzione chiave/valore è sufficiente.

---

# Stato delle iscrizioni

Esistono soltanto due stati:

* `aperte`
* `chiuse`

Il valore viene conservato in `SysOption` con chiave:

`stato_iscrizioni`

Se il valore:

* manca;
* è invalido;
* non è riconosciuto;

il comportamento sicuro deve essere:

`chiuse`

---

## Messaggio informativo

Esiste inoltre:

`messaggio_iscrizioni`

È un semplice testo libero modificabile dall'amministratore.

Può essere usato, per esempio, per scrivere:

* quando apriranno le iscrizioni;
* quando chiuderanno;
* comunicazioni operative.

Non interpretare questo testo come data o orario.

Non introdurre scheduler o automazioni temporali salvo richiesta esplicita.

---

# Flusso utente definitivo

Il flusso ordinario è **strettamente sequenziale**.

## 1. Homepage

Il partecipante apre la homepage.

La pagina mostra:

* titolo;
* stato delle iscrizioni;
* messaggio informativo;
* breve spiegazione;
* campo codice censimento;
* accesso amministratori.

Il codice censimento deve poter essere verificato anche quando le iscrizioni sono chiuse.

---

## 2. Verifica codice censimento

Il partecipante inserisce il proprio codice.

Il sistema verifica che il codice sia presente nell'elenco dei partecipanti importati.

Se non esiste, mostra un messaggio chiaro.

Se esiste, mostra:

* nome;
* cognome.

---

## 3. Conferma esplicita dell'identità

Il partecipante NON deve essere portato immediatamente ai laboratori.

Deve prima confermare esplicitamente di essere la persona indicata.

Concettualmente:

`Sei Mario Rossi?`

Azioni:

* `Sì, sono io`
* `Cambia codice`

Deve inoltre essere mostrata l'indicazione che, se la persona visualizzata non è corretta, bisogna:

* verificare il codice inserito;
* eventualmente contattare gli Incaricati nazionali EG all'indirizzo `eg@agesci.it`.

La conferma dell'identità deve essere registrata nella sessione e non essere soltanto grafica.

Una verifica fallita deve eliminare eventuali sessioni temporanee precedenti riferite ad altri partecipanti.

---

# Instradamento dopo conferma identità

Dopo `Sì, sono io`, il sistema decide automaticamente il punto corretto del percorso.

## Nessuna scelta salvata

Se:

* mattino = `NULL`;
* pomeriggio = `NULL`;

allora:

### iscrizioni aperte

portare alla scelta del sabato mattina.

### iscrizioni chiuse

mostrare chiaramente:

`Non risulta ancora alcuna iscrizione ai laboratori.`

---

## Solo mattino salvato

Se:

* mattino valorizzato;
* pomeriggio = `NULL`;

allora:

### iscrizioni aperte

portare direttamente alla scelta del sabato pomeriggio.

### iscrizioni chiuse

mostrare la scelta già effettuata e indicare chiaramente che l'iscrizione è incompleta.

---

## Iscrizione completa

Se mattino e pomeriggio sono entrambi valorizzati:

portare al riepilogo.

### iscrizioni aperte

consentire modifica mattino e pomeriggio.

### iscrizioni chiuse

mostrare soltanto la consultazione.

---

# Iscrizione progressiva

Il processo ordinario è obbligatoriamente:

1. scelta sabato mattina;
2. salvataggio reale del mattino;
3. scelta sabato pomeriggio;
4. salvataggio reale del pomeriggio;
5. riepilogo finale.

L'utente non può iniziare dal pomeriggio se il mattino non è stato salvato.

Non esiste una conferma globale finale che assegna entrambi i posti insieme.

Ogni fascia viene salvata realmente quando il partecipante conferma quella scelta.

---

# Scelta del sabato mattina

La pagina deve mostrare esclusivamente laboratori di tipo:

`mattino`

L'interfaccia deve essere mobile-first e utilizzare preferibilmente card.

Ogni laboratorio mostra almeno:

* codice;
* titolo;
* descrizione;
* posti disponibili;
* stato disponibile/completo;
* azione di selezione.

Il pulsante di conferma deve essere disabilitato finché non esiste una scelta valida.

Quando il partecipante conferma:

* il backend verifica nuovamente tutto;
* il laboratorio viene realmente assegnato;
* il posto viene occupato;
* la scelta viene salvata nel database.

Se non esiste ancora la riga `Iscrizione`, deve essere creata.

Dopo il salvataggio il partecipante passa automaticamente al pomeriggio.

---

# Scelta del sabato pomeriggio

La pagina mostra esclusivamente laboratori di tipo:

`pomeriggio`

La logica è analoga al mattino.

Alla conferma:

* viene aggiornata la stessa riga `Iscrizione`;
* viene assegnato realmente il posto;
* l'iscrizione diventa completa.

Dopo il salvataggio si passa al riepilogo.

---

# Riepilogo finale

Il riepilogo mostra chiaramente:

## Sabato mattina

* codice laboratorio;
* titolo.

## Sabato pomeriggio

* codice laboratorio;
* titolo.

Deve inoltre comunicare chiaramente che il partecipante ha completato quanto richiesto.

Quando le iscrizioni sono aperte mostra:

* `Modifica mattino`
* `Modifica pomeriggio`

Quando sono chiuse mostra soltanto i dati salvati.

Deve esistere una navigazione chiara verso la homepage.

---

# Modifica delle scelte

Mattino e pomeriggio possono essere modificati separatamente.

## Modifica mattino

Il partecipante vede i laboratori del mattino e la scelta corrente.

Se sceglie un nuovo laboratorio:

* verificare la disponibilità;
* non liberare la scelta precedente prima che la nuova sia stata validata;
* salvare il nuovo laboratorio;
* tornare al riepilogo.

Se il nuovo laboratorio non è più disponibile:

* la vecchia scelta deve rimanere invariata;
* mostrare un messaggio chiaro.

## Modifica pomeriggio

Stessa logica applicata alla fascia pomeridiana.

---

# Laboratori completi

Un laboratorio con zero posti disponibili:

* deve rimanere visibile;
* deve mostrare chiaramente `Completo`;
* non deve essere selezionabile da chi non lo possiede già.

Se il laboratorio è già assegnato al partecipante:

deve poter essere mantenuto anche se risulta completo.

Può essere mostrato un messaggio tipo:

`Completo — il tuo posto è già riservato`.

---

# Disponibilità dinamica

Durante la scelta dei laboratori la disponibilità viene aggiornata periodicamente.

La frequenza indicativa è circa:

8 secondi.

Non usare websocket.

Non introdurre caching, Redis o altri sistemi aggiuntivi.

Se un laboratorio selezionato ma non ancora confermato diventa pieno:

* invalidare la selezione;
* informare chiaramente l'utente;
* impedire il salvataggio;
* richiedere una nuova scelta.

Una scelta già salvata nel database è invece realmente assegnata e non viene invalidata dal polling.

---

# Concorrenza e assegnazione posti

La disponibilità mostrata dal browser è soltanto informativa.

Il server è sempre l'autorità finale.

L'assegnazione deve essere protetta tramite:

* transazioni MariaDB brevi;
* `SELECT ... FOR UPDATE`;
* lock sulle righe dei laboratori coinvolti;
* conteggio aggiornato degli occupanti dopo il lock.

Non utilizzare la riga globale `SysOption` per serializzare tutte le iscrizioni.

Non introdurre:

* code di accesso;
* prenotazioni temporanee;
* hold del posto;
* countdown;
* Redis;
* websocket.

In caso di contesa sull'ultimo posto:

* la prima transazione che conclude correttamente ottiene il posto;
* le successive devono ricevere un errore chiaro, normalmente HTTP `409`.

---

# Validazione server-side

Il backend non deve mai fidarsi del frontend.

Ogni salvataggio deve verificare almeno:

* sessione valida;
* identità confermata;
* partecipante esistente;
* stato iscrizioni;
* laboratorio esistente;
* tipologia corretta;
* capienza;
* ordine previsto del flusso.

Payload non validi devono produrre risposte coerenti e comprensibili, non errori 500 generici quando evitabili.

---

# Area amministrativa

L'area amministrativa comprende:

* login;
* logout;
* cambio password;
* stato iscrizioni;
* messaggio informativo;
* import partecipanti;
* import laboratori;
* ultimo import partecipanti;
* ultimo import laboratori;
* gestione iscrizioni;
* riepilogo statistico.

Non creare funzionalità amministrative ulteriori salvo richiesta esplicita.

---

# Gestione manuale essenziale

L'admin può creare e modificare partecipanti dalla gestione iscrizioni, usando
form dedicati e le stesse validazioni dell'import CSV. Il codice censimento
è immutabile in modifica, anche per richieste POST manipolate. I due flag
richiedono una scelta esplicita; le creazioni non producono iscrizioni o gruppi.

Gestione dati mostra i laboratori e i link ai form di aggiunta/modifica.
Codice e fascia non sono modificabili; per una nuova coppia già presente la
creazione viene rifiutata. Titolo, descrizione e posti sono validati come
nell'import. Il numero di iscritti viene verificato sotto lock del laboratorio
prima di salvare la capienza. Nessun nuovo vincolo UNIQUE.

Il reset singolo è POST e protetto da admin_required, con conferma JavaScript
nella gestione iscrizioni. Elimina esclusivamente la riga Iscrizione: comprende
scelte, rinunce e A/B, preservando tutti i dati del Partecipante e la domenica.
Bloccare prima il partecipante, poi i laboratori in ordine di ID, coerentemente
con il salvataggio delle scelte. Gli errori DB richiedono rollback completo.
Non introdurre eliminazioni individuali di partecipanti/laboratori né modificare
i timestamp degli import con questi form.

---

# Dashboard iscrizioni

La pagina di gestione iscrizioni mostra almeno:

* totale partecipanti importati;
* iscrizioni complete;
* iscrizioni incomplete;
* partecipanti che non hanno iniziato;
* percentuale di completamento;
* semplice rappresentazione grafica;
* elenco delle iscrizioni.

## Completati

Partecipanti con:

* mattino valorizzato;
* pomeriggio valorizzato.

## Incompleti

Partecipanti con almeno una riga `Iscrizione`, ma una delle due scelte mancante.

## Non iniziati

Partecipanti importati senza alcuna riga `Iscrizione`.

I contatori vengono calcolati dai dati correnti.

Non persistere statistiche aggregate nel database.

---

# Data dell'iscrizione

Il campo `Iscrizione.data` viene aggiornato a ogni salvataggio o modifica.

Nell'interfaccia amministrativa va quindi interpretato come:

`Ultimo aggiornamento`

e non necessariamente come data della prima iscrizione.

Non aggiungere una seconda data salvo richiesta esplicita.

---

# Cambio password amministratore

La pagina di cambio password deve richiedere:

* password attuale;
* nuova password;
* conferma nuova password.

Il backend deve:

* verificare la password attuale;
* verificare coincidenza delle nuove password;
* salvare tramite hashing Werkzeug.

Il frontend deve inoltre verificare immediatamente la coincidenza dei due nuovi campi e impedire l'invio se non coincidono.

La validazione client-side non sostituisce quella server-side.

---

# Import partecipanti CSV

L'import partecipanti accetta esclusivamente CSV UTF-8 separati da `;`, con
intestazioni nella prima riga. Il vecchio Excel BC non è più supportato.
La lettura avviene nel browser con SheetJS 0.18.5 già caricato dall'admin:
non usare un parser basato su `split(';')`.

Le intestazioni dei 13 campi da importare sono tutte obbligatorie, anche quando
il valore è facoltativo. Le colonne possono essere riordinate. Sono supportati
BOM UTF-8, accenti, campi quotati, delimitatori e newline nei campi quotati,
terminazioni Windows/Linux. Le righe completamente vuote sono ignorate.

| Intestazione CSV | Campo Partecipante |
|---|---|
| Codice | id |
| Nome | nome |
| Cognome | cognome |
| Gruppo | gruppo |
| Zona | zona |
| Regione | regione |
| EmailContatto | email |
| Sesso | sesso |
| FoCa | foca |
| Partecipo in qualità di: | ruolo |
| Se hai indicato "altro" specifica incarico: | incarico_altro |
| Partecipa ai laboratori di sabato come partecipante | deve_iscriversi_sabato |
| Partecipa ai laboratori di domenica come partecipante | includi_domenica |

## Privacy e minimizzazione dei dati

Il CSV originale resta nel browser. Solo i campi della tabella vengono inviati
come JSON al backend. `BC`, `PIC`, `DataNascita`, `CAP`, `Città`, `PR`,
`EmailReferente` e qualsiasi altra colonna sono ignorati: non devono essere
persistiti, mostrati in anteprima, loggati o inviati al server.
L'email persistente proviene esclusivamente da `EmailContatto`.
Non conservare il file originale o i suoi dati in localStorage/sessionStorage.

## Validazione e anteprima

La pagina legge il file e invia il payload minimo a
`POST /import_iscritti/valida`, protetta per l'admin e senza scritture.
Solo dopo la validazione mostra l'anteprima. `POST /import_iscritti` ripete
la stessa validazione prima di importare.

Controllare codice intero positivo fino a 2147483647, codici duplicati,
nome/cognome obbligatori, tipi e lunghezze compatibili col DB e presenza dei
campi previsti. I testi facoltativi vuoti diventano NULL, anche in aggiornamento.

I flag sono obbligatori. Dopo trim e confronto senza distinzione tra maiuscole
e minuscole: `Sì`, `Si`, `S`, `Yes`, `True`, `1` sono true;
`No`, `N`, `False`, `0` sono false. Vuoti o sconosciuti bloccano l'import.
Il payload normalizzato dell'anteprima usa boolean JSON, accettati dal backend.

## Import incrementale

Codice nuovo: inserimento. Codice già presente: aggiornamento di tutti e soli
i campi CSV. Persona assente dal file: nessuna modifica e nessuna cancellazione.
Non modificare iscrizioni sabato, rinunce, timestamp delle iscrizioni,
sottogruppi A/B o gruppo domenicale. Anche il passaggio del flag domenica a
false deve conservare un gruppo già assegnato fino al futuro ricalcolo.

Validare l'intero payload prima di scrivere. Scritture e timestamp ultimo import
appartengono alla stessa transazione; qualsiasi errore DB richiede rollback.
Mostrare inseriti, aggiornati e totale elaborato dopo il commit.
Gli aggiornati contano i codici già presenti, anche se i valori sono identici.

---

# Import laboratori

Il file laboratori contiene due fogli obbligatori:

* `mattino`
* `pomeriggio`

Le colonne richieste sono:

* `id`
* `titolo`
* `descrizione`
* `posti`

Entrambe le fasce devono contenere almeno un laboratorio valido.

La capienza deve essere un intero positivo.

Il backend deve validare completamente entrambi i fogli prima di inserire o aggiornare laboratori.
I codici duplicati nello stesso foglio, dopo trim, bloccano l’import; lo stesso
codice è consentito una volta in ciascuna fascia.

Un payload invalido non deve modificare il database.

---

# Reimport laboratori

Il reimport è incrementale e consentito anche in presenza di iscrizioni.
La chiave di riconciliazione è `(tipologia, id_lab)`: zero corrispondenze nel DB
inseriscono un nuovo laboratorio; una aggiorna titolo, descrizione e posti,
preservando la primary key; più corrispondenze bloccano l’intero import.
Non aggiungere per ora un UNIQUE: alcune fixture contengono duplicati intenzionali.
I laboratori assenti dal file restano invariati, compresi eventuali duplicati.

Prima di scrivere, verificare anche tutte le riduzioni di capienza:
il nuovo valore deve essere almeno pari alle scelte effettive nella fascia
corrispondente. Le rinunce non occupano posti. Gli aumenti sono consentiti.
Acquisire i lock dei laboratori in ordine di ID prima di contare, mantenendoli
fino al commit/rollback. Non modificare iscrizioni, rinunce, timestamp o gruppi.
Mostrare nuovi inseriti, aggiornati e totale soltanto dopo il commit.

Senza UNIQUE, i lock sulle righe esistenti non garantiscono l’unicità di nuove
coppie create da import amministrativi simultanei: eseguire gli import uno alla volta.

---

# Atomicità degli import

Gli import devono essere "tutto o niente".

In caso di errore:

* rollback;
* nessuna scrittura parziale;
* nessuna cancellazione parziale;
* timestamp ultimo import invariato.

Il timestamp viene aggiornato soltanto dopo import completato con successo.

---

# Ultimo import

Memorizzare tramite `SysOption`:

* ultimo import partecipanti;
* ultimo import laboratori.

Mostrare una data/ora leggibile per l'amministratore.

Se l'import non è mai avvenuto:

`Ultimo import: mai`

---

# Sicurezza

Applicare misure proporzionate a una piccola applicazione pubblica.

Prestare attenzione a:

* validazione lato server;
* gestione corretta delle sessioni;
* protezione delle route amministrative;
* hashing password;
* minimizzazione dei dati;
* query sicure;
* escaping frontend;
* messaggi di errore non sensibili;
* rollback delle transazioni.

Segnalare vulnerabilità concrete.

Non introdurre infrastrutture di sicurezza sproporzionate senza richiesta.

---

# Credenziali e produzione

Le credenziali di esempio utilizzate nello sviluppo NON devono essere riutilizzate in produzione.

Prima del deploy devono essere impostati valori reali per almeno:

* `SECRET_KEY`;
* password MariaDB applicativa;
* password root MariaDB;
* password amministratore.

La password amministratore iniziale `password` deve essere cambiata prima dell'apertura pubblica.

HTTPS, cookie e protezioni CSRF vengono gestiti nella fase di hardening pre-produzione e non devono essere modificati unilateralmente senza richiesta.

---

# Dipendenze

Non aggiungere nuove dipendenze Python o JavaScript se la stessa funzionalità può essere realizzata chiaramente con quelle esistenti.

Se sembra necessaria una nuova dipendenza, spiegare prima:

* perché serve;
* quale problema risolve;
* perché lo stack attuale non è sufficiente.

Non aggiornare dipendenze casualmente durante una task non correlata.

---

# Database e migration

Quando una modifica richiede un cambiamento dello schema:

* usare Flask-Migrate/Alembic;
* non modificare manualmente il database come soluzione definitiva;
* mantenere compatibilità MariaDB.

Il deploy finale partirà da un database nuovo.

Il percorso di migration su database vuoto deve quindi essere sempre verificabile.

Non spendere tempo a rendere perfetti percorsi di downgrade o upgrade storici non utilizzati, salvo problemi concreti.

---

# Test

I test automatici possono utilizzare SQLite per la logica applicativa che non dipende dal database specifico.

Le funzionalità MariaDB-specifiche devono essere testate su MariaDB.

In particolare:

* migration;
* unique constraint;
* nullable;
* `SELECT ... FOR UPDATE`;
* concorrenza;
* ultimo posto.

I test MariaDB che cancellano dati devono avere protezioni rigide contro l'esecuzione accidentale su database persistenti.

Non eseguire test distruttivi contro database di sviluppo o produzione.

---

# Ambiente di sviluppo

L'ambiente di test è separato dalla produzione.

Repository:

`/opt/pmsea-test/app`

Infrastruttura Docker:

`/opt/pmsea-test/infra`

Applicazione di test:

`http://192.168.10.51:5000`

Lo stack contiene essenzialmente:

* applicazione Flask;
* MariaDB.

Non aggiungere servizi senza necessità concreta.

Per gestire lo stack:

```bash
cd /opt/pmsea-test/infra
docker compose ...
```

---

# Git

Branch di sviluppo:

`dev`

Branch stabile/produzione:

`main`

## Remote

`origin`

→ fork di sviluppo:

`fracfe/perMeSeiAvventura_laboratori`

`upstream`

→ repository originale:

`calminaro/perMeSeiAvventura_laboratori`

Il lavoro ordinario avviene su:

`dev`

del fork.

Le modifiche destinate al repository originale verranno successivamente proposte tramite pull request.

Prima di modificare:

1. controllare branch;
2. controllare `git status`;
3. verificare modifiche già presenti.

Non cancellare o sovrascrivere modifiche non proprie.

Non eseguire:

* commit;
* push;
* merge;
* reset;
* rebase;
* operazioni distruttive;

senza richiesta esplicita.

Non lavorare direttamente su `main` salvo richiesta esplicita.

---

# Metodo di lavoro

Il progetto viene sviluppato in modo iterativo.

Per ogni attività:

1. leggere il codice coinvolto;
2. comprendere il comportamento esistente;
3. verificare `AGENTS.md`;
4. identificare la soluzione più semplice;
5. implementare esclusivamente quanto richiesto;
6. effettuare test pertinenti;
7. riportare chiaramente:

   * file modificati;
   * comportamento cambiato;
   * migration eventuali;
   * test eseguiti;
   * problemi rimasti;
   * `git status`.

Quando la richiesta è esclusivamente di analisi:

**non modificare alcun file.**

---

# Principio fondamentale: evitare overengineering

Questa applicazione deve servire circa 400 persone per uno specifico evento e poi verrà dismessa.

Non sono obiettivi del progetto:

* scalabilità a milioni di utenti;
* alta disponibilità distribuita;
* microservizi;
* architetture event-driven;
* repository pattern;
* service layer generalizzati;
* sistemi di caching complessi;
* code asincrone;
* Redis;
* websocket;
* prenotazioni temporanee;
* sistemi di configurazione sofisticati;
* astrazioni create “per il futuro”;
* generalizzazioni per casi d'uso inesistenti.

Un controllo semplice e corretto nel punto appropriato è spesso preferibile a un nuovo livello architetturale.

---

# Frontend

Mantenere:

* Bootstrap;
* Alpine.js;
* JavaScript semplice;
* rendering Jinja.

L'applicazione deve funzionare bene soprattutto da smartphone.

Privilegiare:

* testi comprensibili;
* pulsanti grandi e chiari;
* card;
* flussi guidati;
* feedback immediato;
* gerarchia visiva semplice;
* navigazione verso homepage;
* leggibilità delle descrizioni.

Non sostituire il frontend con React, Vue, Angular o altri framework.

---

# Compatibilità

Non rompere funzionalità già operative per implementarne una nuova.

Quando pertinente verificare sempre:

* homepage;
* login admin;
* logout;
* cambio password;
* stato iscrizioni;
* import partecipanti;
* import laboratori;
* verifica codice censimento;
* conferma identità;
* scelta mattino;
* salvataggio mattino;
* scelta pomeriggio;
* salvataggio pomeriggio;
* riepilogo;
* modifica mattino;
* modifica pomeriggio;
* laboratori completi;
* dashboard admin;
* consultazione a iscrizioni chiuse.

---

# Comunicazione durante il lavoro

Essere sintetici ma precisi.

Quando viene individuato un problema non richiesto:

* segnalarlo;
* indicarne la gravità;
* non modificarlo automaticamente salvo che sia indispensabile per completare correttamente la task.

Se esistono più soluzioni, privilegiare quella:

* più semplice;
* più leggibile;
* meno invasiva;
* più facile da testare;
* più coerente con il codice esistente.

Non ampliare automaticamente lo scope.

---

# Obiettivo finale

Il progetto deve arrivare al convegno come una piccola applicazione:

* semplice;
* affidabile;
* comprensibile;
* mobile-friendly;
* sufficientemente sicura;
* rispettosa della minimizzazione dei dati;
* facile da verificare;
* facile da mettere in produzione.

L'obiettivo non è costruire una piattaforma perfetta.

L'obiettivo è che **circa 400 partecipanti possano scegliere correttamente i propri laboratori e che gli organizzatori possano gestire il processo senza sorprese**.
