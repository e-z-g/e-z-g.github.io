#!/usr/bin/env node
// Drives the UI layer of resource_fork_browser.html, not just its decoders.
//
//   node utilities/preview_smoke.mjs resource_fork_browser.html "$TMPDIR/Cythera.rsrc"
//
// Feeds a real fork through the same entry point the file picker uses, then
// renders the list and the gallery for every type and opens a preview for
// every single resource. A preview branch that throws, or that quietly draws
// nothing, is reported here instead of being found by a user clicking around.
//
// (Real Chrome would be better and utilities/browser_smoke.mjs does exactly
// this in a browser, but Chrome cannot start under this machine's sandbox.)

import { readFileSync } from 'node:fs';
import { loadBrowserFile } from './rsrc_sandbox.mjs';

const [htmlPath, ...forkPaths] = process.argv.slice(2);
if (!htmlPath || !forkPaths.length) {
  console.error('usage: preview_smoke.mjs <browser.html> <fork.rsrc> [more.rsrc...]');
  process.exit(2);
}

let problems = 0;
const fail = m => { problems++; console.log('  ' + m); };

for (const forkPath of forkPaths) {
  const { sandbox: G, peek, els } = loadBrowserFile(htmlPath);
  console.log(`\n=== ${forkPath.split('/').pop()} ===`);

  const bytes = new Uint8Array(readFileSync(forkPath));
  try { G.handleBytes({ name: forkPath.split('/').pop(), size: bytes.length }, bytes); }
  catch (e) { fail('FAIL handleBytes: ' + e.message); continue; }

  const err = els.get('error');
  if (err && err.textContent) fail('FAIL load reported: ' + err.textContent);
  console.log('  status: ' + els.get('status').textContent);
  console.log('  cursor gallery button: ' + (els.get('cursorGalleryBtn').style.display || 'default'));

  const byType = peek('resourcesByType');
  const types = peek('typeList').map(t => t.type);
  const preview = els.get('preview');
  const select = els.get('typeSelect');

  let previewed = 0, blank = 0;
  for (const t of types) {
    select.value = t;
    try { G.onTypeChange(); } catch (e) { fail(`FAIL onTypeChange '${t}': ${e.message}`); continue; }
    const rows = els.get('resTableBody').children.length;
    if (rows !== byType[t].length) fail(`FAIL row count '${t}': ${rows} rows for ${byType[t].length} resources`);
    for (const entry of byType[t]) {
      try {
        const data = G.getResourceData(t, entry);
        G.previewResource(t, entry, data);
        previewed++;
        if (!preview.children.length) { blank++; fail(`BLANK preview '${t}' #${entry.id}`); }
      } catch (e) { fail(`FAIL preview '${t}' #${entry.id}: ${e.message}`); }
    }
    // Thumbnails are lazy in the browser; call the factory directly so a
    // thumbnail that throws still gets caught here.
    for (const entry of byType[t].slice(0, 5)) {
      try { G.makeThumbnail(t, G.getResourceData(t, entry)); }
      catch (e) { fail(`FAIL thumbnail '${t}' #${entry.id}: ${e.message}`); }
    }
  }
  console.log(`  previewed ${previewed} resources, ${blank} drew nothing`);

  try { G.toggleView(); } catch (e) { fail('FAIL toggleView: ' + e.message); }
  for (const t of types) {
    select.value = t;
    try { G.onTypeChange(); } catch (e) { fail(`FAIL gallery '${t}': ${e.message}`); }
  }
  try { G.toggleView(); } catch (e) { fail('FAIL toggleView back: ' + e.message); }
  console.log('  gallery rendered for all types');

  try {
    G.showCursorGallery();
    const items = G.cursorGalleryItems();
    console.log(`  cursor gallery: ${items.length} tiles`);
    for (const it of items) {
      try { G.showCursorDetail(it); }
      catch (e) { fail(`FAIL cursor detail ${it.anim ? 'acur#' + it.id : it.cur.type + '#' + it.id}: ${e.message}`); }
    }
  } catch (e) { fail('FAIL cursor gallery: ' + e.message); }

  // Filtering, all-type search and every sort order.
  const sb = els.get('searchBox');
  sb.value = '1';
  try { G.onTypeChange(); } catch (e) { fail('FAIL filter: ' + e.message); }
  console.log('  filtered rows: ' + els.get('resTableBody').children.length);
  els.get('searchAll').checked = true;
  try { G.onTypeChange(); } catch (e) { fail('FAIL all-type search: ' + e.message); }
  console.log('  all-type rows: ' + els.get('resTableBody').children.length);
  els.get('searchAll').checked = false;
  sb.value = '';
  for (const m of ['id', 'name', 'size', 'fork']) {
    try { G.setSort(m); } catch (e) { fail(`FAIL sort ${m}: ${e.message}`); }
  }
  console.log('  filter and all four sort orders ran');

  // Text exports must survive a fork with unreadable entries.
  try { G.exportAllText(); G.exportSummary(); } catch (e) { fail('FAIL text export: ' + e.message); }

  // Wrap this fork in each container the page claims to read, and check it
  // comes back out. The header sniff is the only thing standing between a real
  // container and a binary file that merely starts with a zero byte, so it is
  // worth exercising deliberately rather than hoping the input covers it.
  //
  // The *decoded* fork is what gets wrapped, not the bytes that were fed in:
  // wrapping a .hqx produces a container whose payload is still BinHex text,
  // and the (correct) BinHex-first sniff wins, which used to make this check
  // skip itself for half the inputs.
  const fork = peek('extractedResourceFork') || bytes;
  const expectCount = /(\d[\d,]*) resources/.exec(els.get('status').textContent);

  const roundTrip = (label, wrapped, wantLabel) => {
    try {
      G.handleBytes({ name: 'wrapped.bin', size: wrapped.length }, wrapped);
      const st = els.get('status').textContent;
      if (!wantLabel.test(st)) fail(`FAIL ${label} not recognised: ` + st);
      else if (expectCount && !st.includes(expectCount[1] + ' resources'))
        fail(`FAIL ${label} resource count: ` + st);
      else console.log(`  ${label} round-trip: ` + st);
    } catch (e) { fail(`FAIL ${label}: ` + e.message); }
  };

  {
    const name = 'TestFile';
    const mb = new Uint8Array(128 + Math.ceil(fork.length / 128) * 128);
    mb[1] = name.length;
    for (let i = 0; i < name.length; i++) mb[2 + i] = name.charCodeAt(i);
    const dv = new DataView(mb.buffer);
    dv.setUint32(83, 0);              // data fork length
    dv.setUint32(87, fork.length);    // rsrc fork length
    mb.set(fork, 128);
    roundTrip('MacBinary', mb, /MacBinary — TestFile/);
  }

  {
    // AppleSingle: magic, version, 16 filler bytes, then a table of entries.
    // Entry 2 is the resource fork, entry 3 is the name.
    const name = new TextEncoder().encode('AppleSingleFile');
    const head = 26 + 2 * 12;
    const as = new Uint8Array(head + name.length + fork.length);
    const dv = new DataView(as.buffer);
    dv.setUint32(0, 0x00051600); dv.setUint32(4, 0x00020000);
    dv.setUint16(24, 2);
    dv.setUint32(26, 3); dv.setUint32(30, head); dv.setUint32(34, name.length);
    dv.setUint32(38, 2); dv.setUint32(42, head + name.length); dv.setUint32(46, fork.length);
    as.set(name, head); as.set(fork, head + name.length);
    roundTrip('AppleSingle', as, /AppleSingle — AppleSingleFile/);
  }

  // Garbage must be rejected, not accepted with an invented resource list.
  try {
    G.handleBytes({ name: 'junk.bin', size: 5000 }, new Uint8Array(5000).fill(0x41));
    if (!els.get('error').textContent) fail('FAIL garbage input was accepted silently');
    else console.log('  garbage input rejected: ' + els.get('error').textContent.slice(0, 60) + '…');
  } catch (e) { fail('FAIL garbage handling threw: ' + e.message); }
}

console.log(problems ? `\n=> ${problems} problem(s)` : '\n=> clean');
process.exit(problems ? 1 : 0);
