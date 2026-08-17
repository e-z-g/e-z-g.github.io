#!/usr/bin/env node
// Runs the viewer's "Save this gallery as .zip" path for real, on the real
// archive, and writes each archive out so `unzip -t` can judge the CRC-32s,
// local headers and central directory it writes by hand.
//
//   python3 utilities/binhex_decode.py "sources/Cythera Data.hqx" "$TMPDIR"
//   node utilities/export_test.mjs cythera_data_viewer.html "$TMPDIR/Cythera Data.data" "$TMPDIR/exports"
//
// The payloads are the genuine ones -- indexed PNGs from encodeIndexedPNG,
// WAVs from the sound decoder, MIDI from qtmaToMidi, disassembly from
// dvmRender -- so a decoder regression shows up here as a failed export
// rather than as a silently smaller zip.

import { readFileSync, writeFileSync, mkdirSync } from 'node:fs';
import vm from 'node:vm';
import {pageSource} from './page_scripts.mjs';

const [htmlPath, dataPath, outDir] = process.argv.slice(2);
if (!htmlPath || !dataPath || !outDir) {
  console.error('usage: export_test.mjs <viewer.html> <Cythera Data.data> <outdir>');
  process.exit(2);
}
mkdirSync(outDir, { recursive: true });

const html = readFileSync(htmlPath, 'utf8');
const js = pageSource(htmlPath);
const archive = new Uint8Array(readFileSync(dataPath));

const noop = () => {};
function stubEl() {
  const el = {
    style: {}, classList: { add: noop, remove: noop, toggle: noop, contains: () => false },
    children: [], options: [], dataset: {}, disabled: false,
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
  Float32Array, Uint8ClampedArray, ArrayBuffer, DataView, Math, JSON, Map, Set, Date,
  Object, Array, String, Number, Boolean, Error, RegExp, Promise, isNaN, parseInt,
  parseFloat, Infinity, NaN, undefined, URLSearchParams,
  setTimeout, clearTimeout, setInterval, clearInterval,
  requestAnimationFrame: noop, cancelAnimationFrame: noop,
  fetch: () => Promise.reject(new Error('offline')),
  Blob: globalThis.Blob, URL: { createObjectURL: () => 'blob:stub', revokeObjectURL: noop },
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
try {
  new vm.Script(js + '\n;window.__peek = function(n){ return eval(n); };\n', { filename: htmlPath })
    .runInContext(ctx);
} catch (e) {
  console.error('FATAL: script body threw while loading: ' + e.message);
  process.exit(1);
}
const peek = n => ctx.__peek(n);

// Catch the save instead of performing it.
const downloads = [];
ctx.__downloads = downloads;
peek('dlBlob = (blob, name) => { window.__downloads.push({ blob, name }); }');

// ---- wire the archive into the module-scope bindings -----------------------
const u32 = off => ((archive[off] * 0x1000000) + (archive[off+1] << 16) +
                    (archive[off+2] << 8) + archive[off+3]) >>> 0;
const masterIndex = [];
for (let i = 0; i < 256; i++) {
  const off = u32(0x88 + i*8), len = u32(0x88 + i*8 + 4);
  masterIndex.push((off >= 0x888 && len > 0 && len % 8 === 0 && off + len <= archive.length) ? [off, len] : [0, 0]);
}
ctx.__archive = archive;
ctx.__mi = masterIndex;
peek('fileBytes = window.__archive');
peek('masterIndexGlobal = window.__mi');

function residsFor(subn) {
  const [off, len] = masterIndex[subn];
  const out = [];
  if (!off) return out;
  for (let n = 0; n < len / 8; n++) {
    const o = u32(off + n*8), l = u32(off + n*8 + 4);
    if (o) out.push([(subn + 1) * 0x100 + n, o, l]);
  }
  return out;
}

// One gallery of each shape the exporter branches on.
const GALLERIES = [
  [135, 'portraits (indexed PNG)'],
  [141, 'tile sheets (reshaped PNG)'],
  [144, 'sounds (WAV)'],
  [143, 'music (MIDI)'],
  [1,   'text (disassembly + raw)'],
  [127, 'maps (raw)'],
];

let failures = 0;
const written = [];
for (const [subn, what] of GALLERIES) {
  const resids = residsFor(subn);
  if (!resids.length) { console.log(`  sub ${subn}: no entries — skipped`); continue; }
  ctx.CUR_SUBN = subn;
  ctx.CUR_RESIDS = resids;
  downloads.length = 0;
  const t0 = Date.now();
  try {
    await ctx.exportGallery();
  } catch (e) {
    console.log(`  FAIL sub ${subn} (${what}): ${e.message}`);
    failures++;
    continue;
  }
  if (!downloads.length) { console.log(`  FAIL sub ${subn}: nothing was saved`); failures++; continue; }
  const { blob, name } = downloads[downloads.length - 1];
  const bytes = new Uint8Array(await blob.arrayBuffer());
  const path = `${outDir}/sub${subn}.zip`;
  writeFileSync(path, bytes);
  written.push([path, name]);
  console.log(`  sub ${subn} ${what}: ${resids.length} resources -> ${name} ` +
              `(${(bytes.length/1048576).toFixed(2)} MB, ${Date.now() - t0} ms)`);
}

console.log('\nNow validate them:');
for (const [path] of written) console.log(`  unzip -t "${path}" | tail -1`);
process.exit(failures ? 1 : 0);
