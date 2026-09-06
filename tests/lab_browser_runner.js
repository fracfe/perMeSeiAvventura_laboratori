const fs = require('node:fs');
const vm = require('node:vm');
const XLSX = require(process.env.SHEETJS_TEST_PATH);
const html = JSON.parse(fs.readFileSync(0, 'utf8'));
const calls = [];
const context = { XLSX, console, fetch: async url => {
    calls.push(url);
    return {ok: true, json: async () => ({
        ok: true, inseriti: 1, aggiornati: 1, invariati: 0, totale: 2,
        dettaglio: ['mattino / M01 – Bosco: nuovo', 'pomeriggio / P01 – Bosco: modificati Posti'],
        ultimo_import: '06/09/2026 18:00'
    })};
}};
vm.createContext(context);
vm.runInContext(html.match(/<script>\s*(function excelUploader[\s\S]*?)<\/script>/)[1], context);
(async () => {
    const workbook = XLSX.utils.book_new();
    for (const [fascia, id] of [['mattino', 'M01'], ['pomeriggio', 'P01']]) {
        XLSX.utils.book_append_sheet(workbook,
            XLSX.utils.json_to_sheet([{id, titolo:'Bosco', descrizione:'Bosco', posti:5}]), fascia);
    }
    const bytes = XLSX.write(workbook, {bookType:'xlsx', type:'buffer'});
    const u = context.excelUploader();
    const event = {target: {files: [{arrayBuffer: async () => bytes}]}};
    await u.loadFile(event);
    const preview = {calls: [...calls], riepilogo:u.riepilogo, dettaglio:u.dettaglio,
        pronta:u.anteprima, ultimoImport:u.ultimoImport};
    // Cambiare file ripete soltanto il confronto, senza importare.
    await u.loadFile(event);
    const cambio = [...calls];
    await u.upload();
    const finale = {calls, riepilogo:u.riepilogo, pronta:u.anteprima, ultimoImport:u.ultimoImport};
    await u.upload();
    process.stdout.write(JSON.stringify({preview, cambio, finale}));
})().catch(error => { console.error(error); process.exitCode = 1; });
