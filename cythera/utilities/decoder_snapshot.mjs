#!/usr/bin/env node
// Exercises the viewer's real decoders against the real archive and prints a
// deterministic snapshot. Diff two snapshots to see whether a change altered
// any decoded output.
//
//   python3 utilities/binhex_decode.py "sources/Cythera Data.hqx" /tmp
//   node utilities/decoder_snapshot.mjs cythera_data_viewer.html "/tmp/Cythera Data.data"
//
// The viewer is a browser single-file app, so the script body is evaluated in a
// vm with just enough DOM stubbed for the top-level to run. Only pure decode
// functions are then called -- nothing that needs layout.

import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import {pageSource} from './page_scripts.mjs';
import { createHash } from 'node:crypto';

const [htmlPath, dataPath] = process.argv.slice(2);
if (!htmlPath || !dataPath) {
  console.error('usage: decoder_snapshot.mjs <viewer.html> <Cythera Data.data>');
  process.exit(2);
}

const html = readFileSync(htmlPath, 'utf8');
const js = pageSource(htmlPath);
const archive = new Uint8Array(readFileSync(dataPath));

// ---- minimal DOM so the top-level script body can be evaluated -------------
const noop = () => {};
function stubEl() {
  const el = {
    style: {}, classList: { add: noop, remove: noop, toggle: noop, contains: () => false },
    children: [], options: [], dataset: {},
    innerHTML: '', textContent: '', value: '', width: 0, height: 0,
    appendChild: c => c, removeChild: noop, addEventListener: noop,
    removeEventListener: noop, setAttribute: noop, getAttribute: () => null,
    querySelector: () => null, querySelectorAll: () => [], focus: noop, click: noop,
    getContext: () => null, remove: noop, insertBefore: noop, cloneNode: () => stubEl(),
    getBoundingClientRect: () => ({ left: 0, top: 0, width: 100, height: 100 }),
  };
  return el;
}
const document = {
  getElementById: () => stubEl(), createElement: () => stubEl(),
  createElementNS: () => stubEl(), querySelector: () => null, querySelectorAll: () => [],
  addEventListener: noop, removeEventListener: noop,
  body: stubEl(), head: stubEl(), documentElement: stubEl(),
};

const sandbox = {
  document, console, TextDecoder, TextEncoder, Uint8Array, Int16Array, Uint32Array,
  Float32Array, Uint8ClampedArray, ArrayBuffer, DataView, Math, JSON, Map, Set,
  Object, Array, String, Number, Boolean, Error, RegExp, Promise, isNaN, parseInt,
  parseFloat, Infinity, NaN, undefined,
  setTimeout, clearTimeout, setInterval, clearInterval,
  requestAnimationFrame: noop, cancelAnimationFrame: noop,
  fetch: () => Promise.reject(new Error('offline')),
  Blob: globalThis.Blob, URL: globalThis.URL,
  CompressionStream: globalThis.CompressionStream, Response: globalThis.Response,
  matchMedia: () => ({ matches: false, addEventListener: noop }),
  localStorage: { getItem: () => null, setItem: noop, removeItem: noop },
  location: { hash: '', href: 'file:///x', search: '' },
  history: { replaceState: noop, pushState: noop },
  navigator: { userAgent: 'node' },
  performance: { now: () => 0 },
};
sandbox.window = sandbox;
sandbox.globalThis = sandbox;
sandbox.self = sandbox;

const ctx = vm.createContext(sandbox);
// Top-level const/let never become properties of the vm context, so the tables
// declared that way are re-exported onto window before the script ends.
const EXPORT_CONSTS = ['PALETTE', 'PAL_RGB', 'CYTHERA_CHARACTERS', 'CYTHERA_LANDSCAPES',
  'ZONES', 'PROP_TYPE_NAMES', 'CATEGORY_NAMES', 'CANONICAL_SIZE', 'NAV_GROUPS',
  'MACROMAN_HIGH', 'PALETTE_CYCLES', 'TILE_SHEET_HINTS'];
// Assigning g.fileBytes from out here creates a property on the vm global that
// the page's own functions never see: `fileBytes` is a top-level `let`, so it
// lives in the global *lexical* environment. This setter is defined inside that
// scope, which is the only way to reach it.
const epilogue = '\n;' + EXPORT_CONSTS
  .map(n => `try{window.__${n}=${n}}catch(e){}`).join('') +
  '\n;window.__bind = (a, m) => { fileBytes = a; masterIndexGlobal = m; };\n';
try {
  new vm.Script(js + epilogue, { filename: htmlPath }).runInContext(ctx);
} catch (e) {
  console.error('FATAL: script body threw while loading: ' + e.message);
  process.exit(1);
}
for (const n of EXPORT_CONSTS) if (ctx['__' + n] !== undefined) ctx[n] = ctx['__' + n];

const g = ctx;
const h = b => createHash('sha256').update(Buffer.from(b)).digest('hex').slice(0, 16);
const lines = [];
const say = s => { lines.push(s); console.log(s); };

// ---- wire the real archive in ---------------------------------------------
function readU32(off) {
  return ((archive[off] * 0x1000000) + (archive[off + 1] << 16) +
          (archive[off + 2] << 8) + archive[off + 3]) >>> 0;
}
const masterIndex = [];
for (let i = 0; i < 256; i++) masterIndex.push([readU32(0x88 + i * 8), readU32(0x88 + i * 8 + 4)]);
g.fileBytes = archive;
g.masterIndexGlobal = masterIndex;
if (typeof ctx.__bind === 'function') ctx.__bind(archive, masterIndex);

say(`archive ${archive.length} bytes, title "${new TextDecoder('latin1').decode(archive.slice(1, 1 + archive[0]))}"`);

// resource table for a subindex: cnt entries of [offset,len] u32 pairs
function entries(subn) {
  const [off, cnt] = masterIndex[subn];
  const n = cnt / 8 | 0;
  const out = [];
  if (!off || off + cnt > archive.length) return out;
  for (let i = 0; i < n; i++) {
    const o = readU32(off + i * 8), l = readU32(off + i * 8 + 4);
    if (o && l && o + l <= archive.length) out.push([i, o, l]);
  }
  return out;
}

const populated = [];
for (let s = 0; s < 256; s++) {
  const e = entries(s);
  if (e.length) populated.push([s, e.length]);
}
say(`populated subindexes: ${populated.length} -> ${populated.map(([s, n]) => `${s}:${n}`).join(' ')}`);

// ---- exercise the decoders ------------------------------------------------
function tryCall(name, fn) {
  try { return { ok: true, v: fn() }; }
  catch (e) { return { ok: false, e: e.message }; }
}

// graphics: decodeResource over every image subindex
const IMG_SUBN = [135, 137, 141, 131, 142];
for (const subn of IMG_SUBN) {
  const es = entries(subn);
  if (!es.length) { say(`sub ${subn}: no entries`); continue; }
  let ok = 0, fail = 0, blank = 0;
  const digest = createHash('sha256');
  for (const [idx, off, len] of es) {
    const bytes = archive.slice(off, off + len);
    // The resid matters: one 0x8Exx resource is a sized picture rather than a
    // tile strip, and decodeResource can only tell which from its id.
    const resid = ((subn + 1) << 8) | idx;
    const r = tryCall('decodeResource', () => g.decodeResource(bytes, subn, resid));
    if (!r.ok) { fail++; continue; }
    const img = r.v && (r.v.image || r.v);
    if (!img || !img.length) { blank++; continue; }
    ok++;
    digest.update(Buffer.from(img.buffer ? img : Uint8Array.from(img)));
  }
  say(`sub ${subn}: ${es.length} entries -> ${ok} decoded, ${fail} failed, ${blank} blank  pixels=${digest.digest('hex').slice(0, 16)}`);
}

// sounds
{
  const es = entries(144);
  let ok = 0, fail = 0; const d = createHash('sha256');
  for (const [i, off, len] of es) {
    const r = tryCall('decodeSound', () => g.decodeSound(archive.slice(off, off + len)));
    if (r.ok && r.v) { ok++; d.update(Buffer.from(new Int16Array(r.v.samples || r.v).buffer)); }
    else fail++;
  }
  say(`sub 144 sounds: ${es.length} -> ${ok} ok, ${fail} failed  samples=${d.digest('hex').slice(0, 16)}`);
}

// music -> midi
{
  const es = entries(143);
  let ok = 0, fail = 0, notes = 0; const d = createHash('sha256');
  const why = new Map();
  for (const [i, off, len] of es) {
    // qtmaToMidi returns {midi, noteCount, ...}, not a byte array.
    const r = tryCall('qtmaToMidi', () => g.qtmaToMidi(archive.slice(off, off + len)));
    if (r.ok && r.v && r.v.midi && r.v.midi.length) {
      ok++;
      d.update(Buffer.from(r.v.midi));
      notes += r.v.noteCount | 0;
    } else {
      fail++;
      const k = r.ok ? 'returned no midi bytes' : r.e;
      why.set(k, (why.get(k) || 0) + 1);
    }
  }
  say(`sub 143 music: ${es.length} -> ${ok} midi (${notes} notes), ${fail} failed  midi=${d.digest('hex').slice(0, 16)}`);
  for (const [k, n] of why) say(`    ${n}x ${k}`);
}

// Decryption across the whole archive. This is one number that moves if any
// resource starts being read as ciphertext when it was plaintext, or the other
// way round -- the thing the sampled lines below do not cover, and the thing
// that was silently wrong for 18 resources until delvmod's tables replaced the
// guessing heuristic. utilities/delv_crosscheck.mjs says *which* ones.
{
  let clear = 0, decrypted = 0, bytes = 0;
  const d = createHash('sha256');
  for (let subn = 0; subn < 256; subn++) {
    const [off, cnt] = masterIndex[subn];
    if (!off || off + cnt > archive.length) continue;
    for (let ri = 0, n = Math.min(256, cnt / 8); ri < n; ri++) {
      const resid = (subn + 1) * 0x100 + ri;
      let raw;
      try { raw = g.getResourceBytes(resid); } catch (e) { continue; }
      if (!raw || !raw.length) continue;
      let v;
      try { v = g.smartDecrypt(raw, resid); } catch (e) { continue; }
      if (v.wasDecrypted) decrypted++; else clear++;
      bytes += v.data.length;
      d.update(Buffer.from(v.data));
    }
  }
  say(`decryption: ${clear} clear, ${decrypted} decrypted, ${bytes} bytes  plaintext=${d.digest('hex').slice(0, 16)}`);
}

// The disassembly itself. Neither the decryption line above nor anything below
// covers dvmRender, so the opcode table, the symbol lookups and the 32-bit word
// decoder could all change without moving this snapshot -- which is what
// happened when the mnemonics were realigned with delvmod and the word decoder
// learned about negative numbers. utilities/delv_crosscheck.mjs checks those
// tables against delvmod; this checks that the rendered output stays put.
{
  let rendered = 0, chars = 0;
  const d = createHash('sha256');
  const SCRIPT_SUBN = [0, 3, 7, 8, 9, 11, 12, 13, 14, 15, 16, 19, 20, 23, 24, 25, 26, 27, 29, 47];
  for (const subn of SCRIPT_SUBN) {
    const [off, cnt] = masterIndex[subn] || [0, 0];
    if (!off || off + cnt > archive.length) continue;
    for (let ri = 0, n = Math.min(256, cnt / 8); ri < n; ri++) {
      const resid = (subn + 1) * 0x100 + ri;
      let raw;
      try { raw = g.getResourceBytes(resid); } catch (e) { continue; }
      if (!raw || !raw.length) continue;
      let text = '';
      try { text = g.dvmRender(g.smartDecrypt(raw, resid).data, resid) || ''; } catch (e) { text = 'ERR'; }
      if (!text) continue;
      rendered++; chars += text.length;
      d.update(text);
    }
  }
  say(`disassembly: ${rendered} scripts, ${chars} chars  text=${d.digest('hex').slice(0, 16)}`);
}

// text / strings
{
  const es = entries(1);
  const d = createHash('sha256');
  let n = 0;
  for (const [i, off, len] of es.slice(0, 400)) {
    const r = tryCall('decodeMacRoman', () => g.decodeMacRoman(archive.slice(off, off + len)));
    if (r.ok && typeof r.v === 'string') { n++; d.update(r.v); }
  }
  say(`sub 1 text: sampled ${n} -> text=${d.digest('hex').slice(0, 16)}`);
}

// maps: structured decode is renderer-bound, so just checksum raw + sizes
{
  const es = entries(127);
  const d = createHash('sha256');
  for (const [i, off, len] of es) d.update(Buffer.from(archive.slice(off, off + len)));
  say(`sub 127 maps: ${es.length} entries  raw=${d.digest('hex').slice(0, 16)}`);
}

// pure helpers, spot-checked so a refactor of them shows up here
{
  const checks = [
    ['scale6to8(255)', () => g.scale6to8(255)],
    ['scale6to8(0)', () => g.scale6to8(0)],
    ['PALETTE.length', () => g.PALETTE.length],
    ['PAL_RGB[0]', () => JSON.stringify(g.PAL_RGB[0])],
    ['PAL_RGB[255]', () => JSON.stringify(g.PAL_RGB[255])],
    ['prettyLabel("FooBarBaz")', () => g.prettyLabel('FooBarBaz')],
    ['propTypeName(141)', () => g.propTypeName(141)],
    ['decodeMacRoman([0xC4,0x41])', () => g.decodeMacRoman(new Uint8Array([0xC4, 0x41]))],
    ['qVlq(0)', () => JSON.stringify(g.qVlq(0))],
    ['qVlq(128)', () => JSON.stringify(g.qVlq(128))],
    ['qVlq(0x3FFF)', () => JSON.stringify(g.qVlq(0x3FFF))],
    // Was pngCrc32 when the PNG writer lived inside the viewer; the same
    // function is now crc32 in js/mac-bytes.js, shared with the ZIP writer.
    // That rename is the only difference between SNAPSHOT c0d9c78aa3e7f834
    // (before the js/ split) and the value printed today -- every decoded byte
    // in every other line was identical across the change.
    ['crc32(abc)', () => g.crc32(new Uint8Array([97, 98, 99])) >>> 0],
    ['pngAdler32(abc)', () => g.pngAdler32(new Uint8Array([97, 98, 99])) >>> 0],
    ['hashIndices([1,2,3])', () => g.hashIndices(new Uint8Array([1, 2, 3]))],
  ];
  for (const [label, fn] of checks) {
    const r = tryCall(label, fn);
    say(`  ${label} = ${r.ok ? r.v : 'THREW ' + r.e}`);
  }
}

say(`SNAPSHOT ${h(lines.join('\n'))}`);
