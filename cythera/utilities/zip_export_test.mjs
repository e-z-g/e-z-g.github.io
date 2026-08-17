#!/usr/bin/env node
// Exercises resource_fork_browser.html's "Export everything as .zip" path in
// Node and writes the archive out, so `unzip -t` can judge whether the CRCs,
// local headers and central directory this file writes by hand are correct.
//
//   node utilities/zip_export_test.mjs resource_fork_browser.html "$TMPDIR/Cythera.rsrc" out.zip
//
// PNG payloads are stand-in bytes (there is no canvas encoder here); every
// other payload -- raw forks, text, WAV -- is the real thing.

import { readFileSync, writeFileSync } from 'node:fs';
import { loadBrowserFile } from './rsrc_sandbox.mjs';

const [htmlPath, forkPath, outPath] = process.argv.slice(2);
if (!htmlPath || !forkPath || !outPath) {
  console.error('usage: zip_export_test.mjs <browser.html> <fork.rsrc> <out.zip>');
  process.exit(2);
}

const { sandbox: G, peek, downloads } = loadBrowserFile(htmlPath);

// --- unit check on the CRC-32 before trusting a 3,000-file archive ---------
const crc32 = G.crc32;
const CHECKS = [
  ['', 0x00000000],
  ['a', 0xE8B7BE43],
  ['123456789', 0xCBF43926],
  ['The quick brown fox jumps over the lazy dog', 0x414FA339],
];
let bad = 0;
for (const [s, want] of CHECKS) {
  const got = crc32(new TextEncoder().encode(s));
  const ok = got === want;
  if (!ok) bad++;
  console.log(`  crc32(${JSON.stringify(s).slice(0, 24)}) = 0x${got.toString(16).padStart(8, '0')} ${ok ? 'ok' : 'EXPECTED 0x' + want.toString(16)}`);
}
if (bad) { console.error('CRC-32 is wrong; not writing an archive.'); process.exit(1); }

G.parseResourceFork(new Uint8Array(readFileSync(forkPath)));
const byType = peek('resourcesByType');
const total = Object.values(byType).reduce((a, l) => a + l.length, 0);
console.log(`\n  fork: ${Object.keys(byType).length} types, ${total} resources`);

await G.exportEverything();

if (!downloads.length) { console.error('export produced no download'); process.exit(1); }
const { blob, name } = downloads[downloads.length - 1];
const bytes = new Uint8Array(await blob.arrayBuffer());
writeFileSync(outPath, bytes);
console.log(`  wrote ${name} -> ${outPath} (${bytes.length.toLocaleString()} bytes)`);
console.log(`  status: ${G.document.getElementById('status').textContent}`);

// How many of the PNG payloads are real? Art that was drawn from a palette is
// encoded by js/mac-media.js and is a genuine indexed PNG even here. The rest
// come from canvas.toBlob, which this sandbox can only stand in for -- those
// bytes are a deterministic placeholder, and only a real browser makes them a
// PNG. Printing the split keeps that limitation visible instead of letting a
// zip full of placeholders look like a passing test.
{
  const SIG = [0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A];
  let png = 0, real = 0;
  for (const f of G.__lastZipFiles || []) {
    if (!f.name.endsWith('.png')) continue;
    png++;
    if (SIG.every((v, i) => f.bytes[i] === v)) real++;
  }
  if (png) console.log(`  PNG payloads: ${png}, genuinely encoded here: ${real} (the rest need a browser's canvas)`);
}
