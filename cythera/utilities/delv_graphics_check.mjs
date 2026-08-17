#!/usr/bin/env node
// Compares cythera_data_viewer.html's graphics decoder against delvmod's, pixel
// for pixel, over every image in the archive.
//
//   python3 utilities/delv_graphics_ref.py sources/github_delvmod/code \
//           "$TMPDIR/Cythera Data.data" > "$TMPDIR/gfx_ref.json" 2>/dev/null
//   node utilities/delv_graphics_check.mjs cythera_data_viewer.html \
//        "$TMPDIR/Cythera Data.data" "$TMPDIR/gfx_ref.json"
//
// (It will run the Python itself if the reference file is not supplied.)
//
// decompressDCG is the most intricate code in the viewer, and until this existed
// nothing had ever checked that it was *right* -- decoder_snapshot.mjs only
// proves it is *unchanged*, which is a different thing and would happily
// preserve a bug forever. delvmod's DelvImage is an independent implementation
// of the same format by the people who worked the format out, so where the two
// agree the artwork is almost certainly being drawn correctly, and where they
// disagree one of them is wrong and it is worth knowing which.
//
// The two do differ deliberately in four places, all in opcodes delvmod treats
// as fatal or unknown; those are listed at the bottom of the output rather than
// hidden, because the whole point is to know where the readings part company.

import {readFileSync, existsSync} from 'node:fs';
import {execFileSync} from 'node:child_process';
import {createHash} from 'node:crypto';
import vm from 'node:vm';
import {pageSource} from './page_scripts.mjs';

const [htmlPath = 'cythera_data_viewer.html', dataPath, refPath] = process.argv.slice(2);
if (!dataPath) {
  console.error('usage: delv_graphics_check.mjs <viewer.html> <Cythera Data.data> [gfx_ref.json]');
  process.exit(2);
}

// ---- the reference ---------------------------------------------------------
let refJson = refPath && existsSync(refPath) ? readFileSync(refPath, 'utf8') : null;
if (!refJson) {
  const script = new URL('./delv_graphics_ref.py', import.meta.url).pathname;
  const delvDir = 'sources/github_delvmod/code';
  if (!existsSync(delvDir)) { console.error('missing: ' + delvDir); process.exit(2); }
  refJson = execFileSync('python3', [script, delvDir, dataPath],
                         {maxBuffer: 64 << 20, stdio: ['ignore', 'pipe', 'ignore']}).toString();
}
const REF = JSON.parse(refJson);

// ---- the viewer ------------------------------------------------------------
const noop = () => {};
function stubEl() {
  const el = {
    style: {}, classList: {add: noop, remove: noop, toggle: noop, contains: () => false},
    children: [], options: [], dataset: {}, innerHTML: '', textContent: '', value: '',
    width: 0, height: 0, appendChild: c => c, removeChild: noop, addEventListener: noop,
    removeEventListener: noop, setAttribute: noop, getAttribute: () => null,
    querySelector: () => null, querySelectorAll: () => [], focus: noop, click: noop,
    getContext: () => null, remove: noop, insertBefore: noop, cloneNode: () => stubEl(),
    getBoundingClientRect: () => ({left: 0, top: 0, width: 100, height: 100}),
  };
  return el;
}
const sandbox = {
  document: {
    getElementById: stubEl, createElement: stubEl, createElementNS: stubEl,
    querySelector: () => null, querySelectorAll: () => [], addEventListener: noop,
    removeEventListener: noop, body: stubEl(), head: stubEl(), documentElement: stubEl(),
  },
  console, TextDecoder, TextEncoder, Uint8Array, Int16Array, Uint32Array, Float32Array,
  Uint8ClampedArray, ArrayBuffer, DataView, Math, JSON, Map, Set, Date, Object, Array,
  String, Number, Boolean, Error, RegExp, Promise, isNaN, parseInt, parseFloat,
  Infinity, NaN, undefined, URLSearchParams, setTimeout, clearTimeout, setInterval,
  clearInterval, requestAnimationFrame: noop, cancelAnimationFrame: noop,
  fetch: () => Promise.reject(new Error('offline')),
  Blob: globalThis.Blob, URL: globalThis.URL,
  CompressionStream: globalThis.CompressionStream, Response: globalThis.Response,
  matchMedia: () => ({matches: false, addEventListener: noop}),
  localStorage: {getItem: () => null, setItem: noop, removeItem: noop},
  location: {hash: '', href: 'file:///x', search: ''},
  history: {replaceState: noop, pushState: noop},
  navigator: {userAgent: 'node'}, performance: {now: () => 0},
};
sandbox.window = sandbox; sandbox.globalThis = sandbox; sandbox.self = sandbox;
const ctx = vm.createContext(sandbox);
new vm.Script(pageSource(htmlPath) + '\n;window.__peek = n => eval(n);', {filename: htmlPath})
  .runInContext(ctx);
const peek = n => { try { return ctx.__peek(n); } catch (e) { return undefined; } };

const archive = new Uint8Array(readFileSync(dataPath));
const u32 = o => ((archive[o] * 0x1000000) + (archive[o+1] << 16) + (archive[o+2] << 8) + archive[o+3]) >>> 0;
const mi = [];
for (let i = 0; i < 256; i++) {
  const off = u32(0x88 + i*8), len = u32(0x88 + i*8 + 4);
  mi.push((off >= 0x888 && len > 0 && len % 8 === 0 && off + len <= archive.length) ? [off, len] : [0, 0]);
}
ctx.__archive = archive; ctx.__mi = mi;
peek('fileBytes = window.__archive');
peek('masterIndexGlobal = window.__mi');

const sha = b => createHash('sha256').update(Buffer.from(b.buffer ? b : Uint8Array.from(b))).digest('hex').slice(0, 16);

// ---- compare ---------------------------------------------------------------
let same = 0, sized = 0, differed = 0, viewerFailed = 0, refFailed = 0, notFound = 0;
const problems = [];
const warned = new Map();

for (const ref of REF) {
  const {resid, subindex} = ref;
  const raw = ctx.getResourceBytes(resid);
  if (!raw || !raw.length) { notFound++; continue; }
  if (!ref.ok) { refFailed++; continue; }

  let got;
  try { got = ctx.decodeResource(raw, subindex); }
  catch (e) {
    viewerFailed++;
    problems.push(`0x${resid.toString(16).toUpperCase()} (sub ${subindex}) the viewer threw: ${e.message}`);
    continue;
  }
  const warning = peek('decompressDCG') && ctx.decompressDCG.lastWarning;
  if (warning) warned.set(resid, warning);

  // Compare what each one hands to a caller for display: delvmod's
  // get_image(), the viewer's decodeResource(). Both crop the decompression
  // buffer from logical_width down to the width the engine draws, which for
  // the 8Fxx "sized" resources differs by up to three pixels.
  if (got.W !== ref.width || got.H !== ref.height) {
    sized++;
    problems.push(`0x${resid.toString(16).toUpperCase()} (sub ${subindex}) size: viewer ` +
                  `${got.W}x${got.H}, delvmod ${ref.width}x${ref.height} ` +
                  `(buffer ${ref.logical_width}x${ref.logical_height})`);
    continue;
  }
  const mine = sha(got.image);
  if (mine === ref.sha256) same++;
  else {
    differed++;
    problems.push(`0x${resid.toString(16).toUpperCase()} (sub ${subindex}) pixels differ: ` +
                  `viewer ${mine}, delvmod ${ref.sha256} (${got.image.length} bytes). ` +
                  `Dump both with delv_graphics_ref.py and diff them to find where.`);
  }
}

const total = same + sized + differed + viewerFailed;
console.log(`  ${REF.length} images in the reference, ${total} compared`);
console.log(`  identical pixels : ${same}`);
if (sized) console.log(`  different size   : ${sized}`);
if (differed) console.log(`  different pixels : ${differed}`);
if (viewerFailed) console.log(`  viewer failed    : ${viewerFailed}`);
if (refFailed) console.log(`  delvmod failed   : ${refFailed}`);
if (notFound) console.log(`  not in this archive: ${notFound}`);

for (const p of problems.slice(0, 25)) console.log('  ! ' + p);
if (problems.length > 25) console.log(`  ! (+${problems.length - 25} more)`);

if (warned.size) {
  console.log(`\n  the viewer's decoder warned on ${warned.size} image(s):`);
  const kinds = new Map();
  for (const [resid, w] of warned) {
    const k = w.replace(/0x[0-9a-f]+/gi, '0x…');
    if (!kinds.has(k)) kinds.set(k, []);
    kinds.get(k).push('0x' + resid.toString(16).toUpperCase());
  }
  for (const [k, ids] of kinds) console.log(`    ${ids.length}x ${k}  e.g. ${ids.slice(0, 4).join(', ')}`);
}

// The four places the two readings deliberately part company are all in
// opcodes delvmod treats as fatal or undefined. Whether that matters is not a
// matter of opinion -- it depends on whether any image in the archive reaches
// them -- so walk every opcode stream and count. Pixel agreement above plus an
// empty count here is what makes the divergence safe to keep, and both halves
// are needed: agreement alone would also be explained by a divergent opcode
// that simply never fires, which is exactly what this turns out to be.
{
  const census = new Map();
  const bump = op => census.set(op, (census.get(op) || 0) + 1);
  let walked = 0, ranOff = 0;
  for (const ref of REF) {
    const raw = ctx.getResourceBytes(ref.resid);
    if (!raw || !raw.length) continue;
    // Skip the uncompressed skill icons and step over the 4-byte header where
    // there is one, so the walk starts on a real opcode.
    if (ref.subindex === 137) continue;
    const d = ref.subindex === 142 ? raw.subarray(4) : raw;
    // Step exactly as decompressDCG does, using its own bit helpers. A walker
    // that computes the operand widths independently desyncs and starts
    // counting pixel data as instructions -- the first version of this
    // reported all 256 byte values as opcodes, which is the giveaway.
    const bits = ctx.bitsOfSingle;
    for (let p = 0; p < d.length;) {
      const op = d[p];
      bump(op);
      if (op < 0x80) { p += 2 + bits(d.subarray(p, p + 2), 2, 11); }
      else if (op < 0xC0) { p += 3 + bits(d.subarray(p, p + 3), 2, 22); }
      else if (op < 0xD0) { p += 1 + (bits(d.subarray(p, p + 1), 4, 4) + 1) * 4; }
      else if (op < 0xE0) { p += 1 + (op & 0x03); }
      else if (op < 0xF0) { p += 2; }
      else if (op < 0xF8) { p += 3; }
      else break;                       // terminator, or an opcode nobody knows
      if (p > d.length) { ranOff++; break; }
    }
    walked++;
  }
  const range = (lo, hi) => {
    let n = 0;
    for (const [op, c] of census) if (op >= lo && op <= hi) n += c;
    return n;
  };
  const divergences = [
    ['0xD4-0xDF', range(0xD4, 0xDF), 'literal count: the viewer reads the low 2 bits (the wiki\'s "1101 BB CC" split), delvmod reads the whole low nibble'],
    ['0xF1-0xF7', range(0xF1, 0xF7), 'the viewer decodes these as Long Run; delvmod raises'],
    ['0xFE     ', range(0xFE, 0xFE), 'the viewer treats it as a terminator alongside 0xFF'],
    ['0xF8-0xFD', range(0xF8, 0xFD), 'the viewer returns a partial image; delvmod raises'],
  ];
  console.log('\n  Where the two readings deliberately differ, and how often this archive');
  console.log('  reaches them:');
  for (const [label, count, why] of divergences) {
    console.log(`    ${label}  ${String(count).padStart(5)} seen  ${count ? '<-- REACHED' : ''}`);
    console.log(`               ${why}`);
  }
  const opsSeen = [...census.keys()].sort((a, b) => a - b);
  // Self-checks on the walk, because a census is only worth as much as the
  // walk behind it. 0x00-0xBF are all valid opcodes (they pack the copy
  // parameters into the opcode byte itself), so 225 distinct values is the
  // most a well-formed stream can show; near 256 would mean desync.
  console.log(`\n  Census self-check: ${opsSeen.length} distinct opcode bytes (225 is the maximum a`);
  console.log(`  well-formed stream can use); ${walked} images walked, ${ranOff} ran past the end.`);
  console.log(`  Short Data 0xD0-0xD3, which the corpus does use: ${range(0xD0, 0xD3)} seen.`);
  console.log(`  Terminator 0xFF: ${range(0xFF, 0xFF)} seen.`);
}

const failed = sized + differed + viewerFailed;
console.log(failed ? `\nFAIL — ${failed} image(s) disagree` : '\ngraphics cross-check: clean');
process.exit(failed ? 1 : 0);
