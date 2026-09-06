// Esegue il codice browser con la stessa versione SheetJS caricata dall'admin.
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const XLSX = require(process.env.SHEETJS_TEST_PATH);
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const chiamate = [];
const context = {
    XLSX, TextDecoder,
    fetch: async (url, options) => {
        chiamate.push({ url, payload: JSON.parse(options.body) });
        const anteprima = url.endsWith('/valida');
        const data = anteprima
            ? input.anteprima
            : { ok: true, inseriti: 1, aggiornati: 0, invariati: 0, dettaglio: ['101 – Rossi Anna: nuovo'], totale: 1, ultimo_import: '06/09/2026 16:00' };
        return { ok: data.ok, redirected: false, json: async () => data };
    }
};
vm.createContext(context);
vm.runInContext(fs.readFileSync(path.join(__dirname, '../static/import_iscritti.js'), 'utf8'), context);
(async () => {
    try {
        if (input.mode === 'flow') {
            const uploader = context.csvUploader(input.mapping);
            const event = { target: { value: 'file.csv', files: [{
                name: 'file.csv', size: Buffer.byteLength(input.csv),
                arrayBuffer: async () => Buffer.from(input.csv)
            }] } };
            await uploader.loadFile(event);
            const prima = { chiamate: chiamate.length, puoCaricare: uploader.puoCaricare,
                rows: uploader.rows, riepilogo: uploader.riepilogo, dettaglio: uploader.dettaglio, fileInput: event.target.value };
            await uploader.upload();
            process.stdout.write(JSON.stringify({ ok: true, prima, chiamate,
                riepilogo: uploader.riepilogo, errore: uploader.errore,
                ultimoImport: uploader.ultimoImport, puoCaricare: uploader.puoCaricare }));
        } else {
            const rows = context.leggiCsvPartecipanti(input.csv, input.mapping);
            process.stdout.write(JSON.stringify({ ok: true, rows }));
        }
    } catch (error) {
        process.stdout.write(JSON.stringify({ ok: false, errore: error.message }));
    }
})();
