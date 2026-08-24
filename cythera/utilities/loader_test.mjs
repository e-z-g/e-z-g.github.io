#!/usr/bin/env node
// Exercises the viewer's archive-opening path: the BinHex 4.0 decoder, the
// MacBinary / AppleSingle / AppleDouble unwrappers, the "is this actually a
// Delver archive" test, and the messages produced when it is not.
//
//   python3 utilities/binhex_decode.py "sources/Cythera Data.hqx" "$TMPDIR"
//   node utilities/loader_test.mjs cythera_data_viewer.html \
//        "sources/Cythera Data.hqx" "$TMPDIR/Cythera Data.data" \
//        "$TMPDIR/Cythera Data.rsrc" "sources/Cythera.hqx"
//
// The forks written by binhex_decode.py are the reference: the JS decoder has
// to reproduce them byte for byte, which is the whole point of porting it.

import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import {pageSource} from './page_scripts.mjs';
import {makeSandbox} from './dom_stub.mjs';
import { createHash } from 'node:crypto';

const [htmlPath, hqxPath, dataPath, rsrcPath, appHqxPath] = process.argv.slice(2);
if (!htmlPath || !hqxPath || !dataPath) {
  console.error('usage: loader_test.mjs <viewer.html> <Cythera Data.hqx> <Cythera Data.data> [<.rsrc>] [<Cythera.hqx>]');
  process.exit(2);
}

const html = readFileSync(htmlPath, 'utf8');
const js = pageSource(htmlPath);

// ---- minimal DOM so the top-level script body can be evaluated -------------
// The stub lives in dom_stub.mjs; see the header there for why it has a canvas.
// Ids are memoised here: this check sets a value on an element and expects the
// page to read the same element back.
const {sandbox} = makeSandbox();
const ctx = vm.createContext(sandbox);
// Top-level const/let are not properties of the vm global; reach them through
// an eval defined inside that scope.
const epilogue = '\n;window.__peek = function(n){ return eval(n); };\n';
try {
  new vm.Script(js + epilogue, { filename: htmlPath }).runInContext(ctx);
} catch (e) {
  console.error('FATAL: script body threw while loading: ' + e.message);
  process.exit(1);
}
const peek = n => ctx.__peek(n);

let failures = 0;
const h = b => createHash('sha256').update(Buffer.from(b)).digest('hex').slice(0, 16);
function check(name, cond, detail) {
  console.log((cond ? '  ok   ' : '  FAIL ') + name + (detail ? '  — ' + detail : ''));
  if (!cond) failures++;
}

// ---- 1. BinHex, against the Python reference forks -------------------------
const hqx = new Uint8Array(readFileSync(hqxPath));
const refData = new Uint8Array(readFileSync(dataPath));
const refRsrc = rsrcPath ? new Uint8Array(readFileSync(rsrcPath)) : null;

check('looksLikeBinHex accepts the .hqx', peek('looksLikeBinHex')(hqx));
check('looksLikeBinHex rejects a decoded fork', !peek('looksLikeBinHex')(refData));

const t0 = Date.now();
const forks = peek('binhexSplitForks')(peek('binhexDecode')(hqx));
const ms = Date.now() - t0;
check('name/type/creator', forks.name === 'Cythera Data' && forks.type === 'DelS' && forks.creator === 'Delv',
      `${forks.name} / ${forks.type} / ${forks.creator}`);
check('data fork length', forks.data.length === refData.length, `${forks.data.length} vs ${refData.length}`);
check('data fork bytes', h(forks.data) === h(refData), h(forks.data));
if (refRsrc) {
  check('rsrc fork length', forks.rsrc.length === refRsrc.length, `${forks.rsrc.length} vs ${refRsrc.length}`);
  check('rsrc fork bytes', h(forks.rsrc) === h(refRsrc), h(forks.rsrc));
}
console.log(`  (decoded ${(hqx.length/1048576).toFixed(1)} MB of BinHex in ${ms} ms)`);

// ---- 2. The 0x90 run-length cases, which real archives exercise rarely -----
// Hand-built vectors: a literal 0x90, a run, and a run at the very end.
function rleOnly(bytes) {
  // Re-encode as BinHex so the decoder's own front end is used end to end.
  const ALPHA = peek('HQX_ALPHA');
  let bits = '', out = ':';
  for (const b of bytes) bits += b.toString(2).padStart(8, '0');
  while (bits.length % 6) bits += '0';
  for (let i = 0; i < bits.length; i += 6) out += ALPHA[parseInt(bits.slice(i, i + 6), 2)];
  return new TextEncoder().encode(out + ':');
}
const dec = peek('binhexDecode');
const cases = [
  [[0x41, 0x90, 0x00, 0x42], [0x41, 0x90, 0x42], 'literal 0x90'],
  [[0x41, 0x90, 0x04], [0x41, 0x41, 0x41, 0x41], 'run of 4'],
  [[0x01, 0x02, 0x90, 0x03, 0x04], [0x01, 0x02, 0x02, 0x02, 0x04], 'run mid-stream'],
];
for (const [enc, want, label] of cases) {
  const got = Array.from(dec(rleOnly(enc))).slice(0, want.length);
  check('RLE ' + label, JSON.stringify(got) === JSON.stringify(want), JSON.stringify(got));
}

// ---- 3. Recognising the archive -------------------------------------------
const describe = peek('describeDelverArchive');
const d = describe(refData);
check('data fork is a Delver archive', d.ok && d.populated === 34, `${d.populated} subindexes, title "${d.title}"`);
check('title', d.title === 'Cythera: Fate of Alaric', d.title);
check('rsrc fork is rejected', refRsrc ? !describe(refRsrc).ok : true,
      refRsrc ? describe(refRsrc).reason : 'skipped');
check('raw BinHex ASCII is rejected', !describe(hqx).ok, describe(hqx).reason);
check('a short buffer is rejected', !describe(new Uint8Array(64)).ok);

// ---- 4. extractDelverArchive: unwrapping and legible refusals --------------
const extract = peek('extractDelverArchive');
const viaRaw = extract(refData);
check('raw fork passes through', viaRaw.via === 'data fork' && viaRaw.bytes.length === refData.length);
const viaHqx = extract(hqx);
check('.hqx is unwrapped', viaHqx.via === 'BinHex 4.0 data fork' && h(viaHqx.bytes) === h(refData), viaHqx.via);

// MacBinary wrapper around the real fork.
function macbinary(name, type, creator, data) {
  const pad = n => (n + 127) & ~127;
  const out = new Uint8Array(128 + pad(data.length));
  out[1] = name.length;
  for (let i = 0; i < name.length; i++) out[2 + i] = name.charCodeAt(i);
  for (let i = 0; i < 4; i++) { out[65 + i] = type.charCodeAt(i); out[69 + i] = creator.charCodeAt(i); }
  const dv = new DataView(out.buffer);
  dv.setUint32(83, data.length);
  out.set(data, 128);
  return out;
}
const mb = extract(macbinary('Cythera Data', 'DelS', 'Delv', refData));
check('MacBinary is unwrapped', mb.via === 'MacBinary data fork' && h(mb.bytes) === h(refData), mb.via);

// AppleSingle wrapper.
function applesingle(data) {
  const out = new Uint8Array(26 + 12 + data.length);
  const dv = new DataView(out.buffer);
  dv.setUint32(0, 0x00051600); dv.setUint32(4, 0x00020000);
  dv.setUint16(24, 1);
  dv.setUint32(26, 1); dv.setUint32(30, 38); dv.setUint32(34, data.length);
  out.set(data, 38);
  return out;
}
const as = extract(applesingle(refData));
check('AppleSingle is unwrapped', as.via === 'AppleSingle data fork' && h(as.bytes) === h(refData), as.via);

function refusal(bytes, label) {
  try { extract(bytes); return { threw: false, msg: '(accepted!)' }; }
  catch (e) { return { threw: true, msg: e.message }; }
}
const r1 = refusal(new TextEncoder().encode('<html>not an archive at all</html>'));
check('plain junk is refused', r1.threw && /Not a Delver archive/.test(r1.msg), r1.msg.slice(0, 90));
if (refRsrc) {
  const r2 = refusal(refRsrc);
  check('a bare resource fork is refused', r2.threw, r2.msg.slice(0, 90));
}
if (appHqxPath) {
  const appHqx = new Uint8Array(readFileSync(appHqxPath));
  const r3 = refusal(appHqx);
  check('the application .hqx is refused by name', r3.threw && /APPL|application/.test(r3.msg), r3.msg.slice(0, 140));
}

// ---- 5. Deep links ---------------------------------------------------------
const parseDeepLink = peek('parseDeepLink');
const trials = [
  ['#c=141&r=8D02', { c: '141', r: '8D02' }],
  ['#c=CHARACTERS', { c: 'CHARACTERS' }],
  ['#8D02', { r: '8D02' }],
  ['#0x8D02', { r: '8D02' }],
  ['', null],
];
for (const [hash, want] of trials) {
  ctx.location.hash = hash;
  const got = parseDeepLink();
  check('deep link ' + (hash || '(empty)'), JSON.stringify(got) === JSON.stringify(want), JSON.stringify(got));
}
ctx.location.hash = '';

// ---- 6. the load path itself -----------------------------------------------
// Every check above calls extractDelverArchive or parseArchiveBytes directly.
// Nothing ran loadDefaultArchive, and that is how setStatus() -- which only the
// loading and failure paths call -- could be deleted outright and leave every
// check passing while the page threw before it could load anything at all.
{
  // fetch rejects in this sandbox, so every candidate URL fails and the run has
  // to end in archiveLoadFailed. What matters is that it gets there without
  // throwing, and says what it tried.
  let threw = null;
  try { await peek('loadDefaultArchive')(); }
  catch (e) { threw = e; }
  check('loadDefaultArchive survives a total failure', !threw, threw ? threw.message : 'reported cleanly');

  const out = ctx.document.getElementById('output').textContent || '';
  check('it says what it tried', /Tried, in order/.test(out) && /Cythera Data/.test(out),
        out.split('\n')[0] || '(nothing)');
  const status = ctx.document.getElementById('sourceStatus').textContent || '';
  check('the status line was written', /No archive loaded/.test(status), status.slice(0, 60) || '(empty)');

  // And the same for a file the user picks that turns out not to be an archive.
  let threw2 = null;
  try { await peek('ingestArchiveFile')({ name: 'junk.bin', size: 9, arrayBuffer: async () => new Uint8Array(9).buffer }); }
  catch (e) { threw2 = e; }
  check('a rejected file reports rather than throwing', !threw2, threw2 ? threw2.message : 'reported cleanly');
}

console.log(failures ? `\nFAIL — ${failures} check(s) failed` : '\nAll loader checks passed');
process.exit(failures ? 1 : 0);
