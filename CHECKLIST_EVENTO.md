# Checklist evento

Riferimento per comandi e recupero: [OPERATIONS.md](OPERATIONS.md).
Panoramica: [README.md](README.md). Regole tecniche: [AGENTS.md](AGENTS.md).
Spuntare dopo la verifica; non eseguire suite distruttive su `app_db`.

## A. Prima dell’apertura

- [ ] Confermare ambiente, branch/commit e deploy corretti; working tree pulito.
- [ ] Verificare db healthy, web avviato e homepage raggiungibile.
- [ ] Verificare migrazione DB alla head.
- [ ] Usare credenziali produzione reali e `SECRET_KEY` reale; cambiare password admin.
- [ ] Eseguire e verificare backup DB iniziale.
- [ ] Importare il CSV partecipanti definitivo: controllare preview, conteggi e dettaglio prima di **Conferma import**.
- [ ] Importare Excel laboratori definitivo: controllare preview, fasce, codici e capienze; confermare.
- [ ] Verificare riepiloghi finali degli import e timestamp; importare uno alla volta.
- [ ] Verificare i flussi di 2–3 partecipanti: sabato richiesto e non richiesto, domenica richiesta e non richiesta.
- [ ] Provare i salvataggi su ambiente temporaneo; sul DB operativo effettuare soltanto scelte reali concordate.
- [ ] Generare e aprire export generale, export per laboratorio e file comunicazioni.
- [ ] Lasciare iscrizioni inizialmente **chiuse** e verificare il messaggio pubblico.

## B. Apertura iscrizioni

- [ ] Aprire da **Iscrizioni → Stato iscrizioni** e salvare.
- [ ] Verificare homepage e stato aperto.
- [ ] Provare un codice reale con la persona interessata e confermare l’identità.
- [ ] Controllare scelta/salvataggio mattino e poi pomeriggio.
- [ ] Verificare riepilogo e conteggi admin.
- [ ] Controllare log web e DB dopo i primi minuti.

## C. Durante il periodo di iscrizione

- [ ] Controllare dashboard, incomplete e non iniziati.
- [ ] Gestire eccezioni tramite UI admin; ricontrollare capienza dopo assegnazioni forzate.
- [ ] Fare backup periodico dopo molte iscrizioni o modifiche.
- [ ] Non ricalcolare A/B a iscrizioni aperte.
- [ ] Verificare preview e dettaglio di ogni import aggiuntivo; eseguire import seriali.
- [ ] Non cancellare partecipanti/laboratori per riprovare.

## D. Chiusura iscrizioni

- [ ] Chiudere da **Stato iscrizioni** e verificare homepage.
- [ ] Verificare che gli utenti possano consultare ma non modificare le scelte.
- [ ] Fare e verificare backup DB.
- [ ] Controllare incomplete e non iscritti, distinguendoli dai non richiesti.
- [ ] Effettuare le eventuali correzioni manuali.
- [ ] Ricalcolare A/B dal pulsante **Ricalcola gruppi A/B sabato**.
- [ ] Controllare distribuzione per laboratorio e fascia.
- [ ] Applicare eventuali eccezioni A/B dopo il ricalcolo; un nuovo ricalcolo le sovrascrive.
- [ ] Generare export aggiornati.

## E. Domenica

- [ ] Verificare `includi_domenica` e dati necessari alla distribuzione.
- [ ] Eseguire **Ricalcola gruppi domenica** sui 20 gruppi.
- [ ] Controllare distribuzione, esclusi e nomi.
- [ ] Gestire eccezioni manuali dopo il ricalcolo; non ricalcolare senza valutarne la sovrascrittura.
- [ ] Rigenerare comunicazioni.

## F. Prima dell’evento / consegna finale

- [ ] Fare e verificare backup DB.
- [ ] Generare export generale.
- [ ] Generare export per laboratorio.
- [ ] Generare file comunicazioni.
- [ ] Aprire gli XLSX e verificare stati sabato, A/B, email e gruppi domenica.
- [ ] Conservare una copia riservata di dump ed export fuori dalla VM.
- [ ] Verificare accesso admin e disponibilità delle credenziali agli operatori autorizzati.
- [ ] Verificare sito in sola consultazione per i partecipanti, se richiesto, con iscrizioni chiuse.

## G. Dopo l’evento

- [ ] Chiudere definitivamente le iscrizioni.
- [ ] Fare e verificare backup finale.
- [ ] Generare e aprire export finali.
- [ ] Conservare dump, checksum, file finali e riferimento del commit.
- [ ] Documentare interventi manuali significativi.
- [ ] Valutare spegnimento/disattivazione dopo la fine della consultazione, preservando i dati.
