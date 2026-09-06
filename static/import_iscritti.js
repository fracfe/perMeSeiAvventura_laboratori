/* SheetJS è già caricato dall'area admin. Il CSV originale resta nel browser. */
function leggiCsvPartecipanti(testo, colonne) {
    testo = testo.replace(/^\uFEFF/, '');
    if (!testo.trim()) throw new Error('Il file CSV è vuoto.');
    const workbook = XLSX.read(testo, { type: 'string', raw: true, FS: ';' });
    const foglio = workbook.Sheets[workbook.SheetNames[0]];
    const righe = XLSX.utils.sheet_to_json(foglio, {
        header: 1, defval: '', blankrows: true
    });
    const intestazioni = (righe[0] || []).map(valore => String(valore).trim());
    const colonneRichieste = Object.keys(colonne);
    const mancanti = colonneRichieste.filter(nome => !intestazioni.includes(nome));
    if (mancanti.length) throw new Error(`Mancano le colonne: ${mancanti.join(', ')}.`);
    const duplicate = colonneRichieste.filter(nome =>
        intestazioni.indexOf(nome) !== intestazioni.lastIndexOf(nome));
    if (duplicate.length) throw new Error(`Intestazioni duplicate: ${duplicate.join(', ')}.`);
    const indici = colonneRichieste.map(nome => [intestazioni.indexOf(nome), colonne[nome]]);
    const codiciVisti = new Set();
    const partecipanti = [];
    for (let indice = 1; indice < righe.length; indice += 1) {
        const riga = righe[indice];
        if (riga.every(valore => String(valore ?? '').trim() === '')) continue;
        const partecipante = {};
        for (const [posizione, campo] of indici) {
            partecipante[campo] = String(riga[posizione] ?? '').trim();
        }
        if (!/^[0-9]+$/.test(partecipante.id)
            || Number(partecipante.id) <= 0 || Number(partecipante.id) > 2147483647) {
            throw new Error(`Riga CSV ${indice + 1}: codice censimento non valido.`);
        }
        partecipante.id = Number(partecipante.id);
        if (codiciVisti.has(partecipante.id)) {
            throw new Error(`Riga CSV ${indice + 1}: codice censimento duplicato ${partecipante.id}.`);
        }
        codiciVisti.add(partecipante.id);
        partecipanti.push(partecipante);
    }
    if (!partecipanti.length) throw new Error('Il file deve contenere almeno un partecipante.');
    return partecipanti;
}

function csvUploader(colonne) {
    return {
        rows: [],
        errore: '',
        riepilogo: '',
        ultimoImport: '',
        analisi: false,
        caricamento: false,
        get puoCaricare() {
            return this.rows.length > 0 && !this.errore && !this.analisi && !this.caricamento;
        },
        async invia(url, payload) {
            const response = await fetch(url, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            if (response.redirected) throw new Error('Sessione scaduta. Accedi nuovamente all’area amministrativa.');
            let data = {};
            try { data = await response.json(); } catch (_) { /* Risposta non JSON. */ }
            if (!response.ok || data.ok !== true) {
                throw new Error(data.errore || 'Operazione non riuscita. Verifica la sessione e riprova.');
            }
            return data;
        },
        async loadFile(event) {
            if (this.analisi || this.caricamento) return;
            this.rows = [];
            this.errore = '';
            this.riepilogo = '';
            const file = event.target.files[0];
            if (!file) return;
            this.analisi = true;
            try {
                if (!file.name.toLowerCase().endsWith('.csv')) throw new Error('Seleziona un file .csv.');
                if (file.size > 10 * 1024 * 1024) throw new Error('Il file supera 10 MB.');
                const contenuto = await file.arrayBuffer();
                let testo;
                try {
                    testo = new TextDecoder('utf-8', { fatal: true }).decode(contenuto);
                } catch (_) {
                    throw new Error('Il CSV deve essere codificato in UTF-8.');
                }
                const payload = leggiCsvPartecipanti(testo, colonne);
                const data = await this.invia('/import_iscritti/valida', payload);
                this.rows = data.partecipanti;
            } catch (err) {
                this.rows = [];
                this.errore = err.message || 'Il file CSV non può essere letto.';
            } finally {
                this.analisi = false;
                event.target.value = '';
            }
        },
        async upload() {
            if (!this.puoCaricare) return;
            this.caricamento = true;
            this.errore = '';
            try {
                const data = await this.invia('/import_iscritti', this.rows);
                this.riepilogo = `Import completato: ${data.inseriti} nuovi inseriti, ${data.aggiornati} esistenti aggiornati, ${data.totale} righe elaborate.`;
                this.ultimoImport = data.ultimo_import;
                this.rows = [];
            } catch (err) {
                this.errore = err.message || 'Import non riuscito.';
            } finally {
                this.caricamento = false;
            }
        }
    };
}
