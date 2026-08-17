#!/usr/bin/env node
// Behavioural snapshot for resource_fork_browser.html.
//
// The browser file has no build step and no tests, so the only way to know a
// decoder edit did not change what the tool renders is to run the real
// decoders over a real resource fork and hash the result.
//
//   python3 utilities/binhex_decode.py "sources/Cythera.hqx" "$TMPDIR"
//   node utilities/rsrc_snapshot.mjs resource_fork_browser.html "$TMPDIR/Cythera.rsrc"
//
// Prints one line per resource type plus a total hash. Any change to a hash is
// a regression unless you intended it. DUMP=1 prints every resource line,
// PIXSTATS=1 adds colour counts to canvases.

import { readFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { loadBrowserFile } from './rsrc_sandbox.mjs';

const [htmlPath, ...forkPaths] = process.argv.slice(2);
if (!htmlPath || !forkPaths.length) {
  console.error('usage: rsrc_snapshot.mjs <browser.html> <fork.rsrc> [more.rsrc...]');
  process.exit(2);
}

const { sandbox: G, peek } = loadBrowserFile(htmlPath);
// Function declarations land on the sandbox global, but top-level const/let do
// not, so the tables the decoders need are copied across explicitly.
for (const n of ['MAC_4BIT_PAL', 'MAC_8BIT_PAL', 'MAC_8BIT_PAL_APPROX', 'COLOR_TABLE_TYPES',
                 'TYPE_BADGES', 'RES_ATTRS', 'FACE_BITS', 'FOND_STYLES', 'PLTT_USAGE',
                 'CRC_TABLE', 'TEXT_PREVIEW_LIMIT', 'CODE_TYPES', 'CFRG_ARCH']) {
  try { G[n] = peek(n); } catch { /* not present in this build */ }
}

const hash = s => createHash('sha256').update(s).digest('hex').slice(0, 12);
function canvasSig(c) {
  if (!c) return 'nocanvas';
  const px = c._px ? Buffer.from(c._px.data.buffer, c._px.data.byteOffset, c._px.data.length) : Buffer.alloc(0);
  let extra = '';
  // PIXSTATS answers "did it decode, or is it a wall of unmapped-index
  // magenta?" without opening a browser.
  if (process.env.PIXSTATS && px.length) {
    const seen = new Set(); let magenta = 0;
    for (let i = 0; i < px.length; i += 4) {
      seen.add((px[i] << 16) | (px[i + 1] << 8) | px[i + 2]);
      if (px[i] === 255 && px[i + 1] === 0 && px[i + 2] === 255) magenta++;
    }
    extra = ` colors:${seen.size} magenta:${Math.round(magenta * 400 / px.length)}%`;
  }
  return `${c.width}x${c.height}:${hash(px)}${extra}`;
}

function describe(type, entry, data) {
  const T = type;
  const text = fn => { const s = fn(); return `text:${s.length}:${hash(s)}`; };
  const cv = fn => `canvas:${canvasSig(fn())}`;
  switch (T) {
    case 'STR#': return text(() => G.decodeSTRList(data).join('\u0000'));
    case 'STR ': return text(() => G.decodeSTR(data));
    case 'TEXT': return text(() => G.decodeTEXT(data));
    case 'vers': return text(() => G.decodeVers(data));
    case 'DITL': return text(() => G.decodeDITL(data));
    case 'MENU': return text(() => G.decodeMENU(data));
    case 'WIND': return text(() => G.decodeWIND(data));
    case 'ALRT': return text(() => G.decodeALRT(data));
    case 'DLOG': return text(() => G.decodeDLOG(data));
    case 'MBAR': return text(() => G.decodeMBAR(data));
    case 'FREF': return text(() => G.decodeFREF(data));
    case 'BNDL': return text(() => G.decodeBNDL(data));
    case 'SIZE': return text(() => G.decodeSIZE(data));
    case 'TMPL': return text(() => G.decodeTMPL(data));
    case 'PAT ': return cv(() => G.decodePAT(data));
    case 'PAT#': return G.decodePATList ? `list:${G.decodePATList(data).map(canvasSig).join(',')}` : 'n/a';
    case 'ppat': return cv(() => G.decodePpat(data));
    case 'clut': return cv(() => G.decodeClut(data).canvas);
    case 'cicn': return cv(() => G.decodeCicn(data));
    case 'CURS': { const c = G.decodeCURS(data); return `canvas:${canvasSig(c.canvas)} hot(${c.hotX},${c.hotY})`; }
    case 'crsr': { const c = G.decodeCrsr(data); return `canvas:${canvasSig(c.canvas)} hot(${c.hotX},${c.hotY}) ${c.pixelSize}bit`; }
    case 'acur': { const a = G.decodeAcur(data); return `acur:${a.count}:${a.ids.join('/')}`; }
    case 'ICN#': return cv(() => G.decode1bitIcon(data, 32));
    case 'ics#': return cv(() => G.decode1bitIcon(data, 16));
    case 'ICON': return G.decodeICON ? cv(() => G.decodeICON(data)) : 'n/a';
    case 'SICN': return G.decodeSICN ? `list:${G.decodeSICN(data).map(canvasSig).join(',')}` : 'n/a';
    case 'icl4': return cv(() => G.drawIndexedIcon(data, 32, 4, G.MAC_4BIT_PAL));
    case 'icl8': return cv(() => G.drawIndexedIcon(data, 32, 8, G.MAC_8BIT_PAL));
    case 'ics4': return cv(() => G.drawIndexedIcon(data, 16, 4, G.MAC_4BIT_PAL));
    case 'ics8': return cv(() => G.drawIndexedIcon(data, 16, 8, G.MAC_8BIT_PAL));
    case 'PICT': { const r = G.decodePict(data); return r.kind === 'canvas' ? `pict:${canvasSig(r.canvas)} ${r.colorSpace} op${r.opcode.toString(16)}` : `pict:embedded:${r.ext}`; }
    case 'snd ': { const r = G.decodeSndToWav(data); const b = r.blob || r;
      const n = b.parts ? b.parts.reduce((a, p) => a + (p.byteLength || p.length || 0), 0) : 0;
      return `wav:${n}${r.description ? ' ' + r.description : ''}`; }
    case 'sfnt': { const i = G.decodeSfntInfo(data); return `sfnt:${i.numTables}:${i.tables.join(',')}`; }
    case 'CNTL': return text(() => G.decodeCNTL(data));
    case 'nrct': return text(() => G.decodeNrct(data));
    case 'styl': return text(() => G.decodeStyl(data));
    case 'FOND': return text(() => G.decodeFOND(data).text);
    case 'pltt': { const r = G.decodePltt(data); return `pltt:${r.count}:${r.usage}:${canvasSig(r.canvas)}`; }
    case 'NFNT': case 'FONT': { const f = G.decodeNFNT(data);
      return `font:${f.info}:${canvasSig(f.canvas)}:glyphs${f.glyphs.length}:${hash(f.glyphs.map(g => g.code + 'x' + g.width).join(','))}`; }
    case 'cfrg': return G.decodeCfrg ? text(() => G.decodeCfrg(data)) : 'n/a';
    default:
      if (G.COLOR_TABLE_TYPES && G.COLOR_TABLE_TYPES[T]) { const r = G.decodeClut(data); return `ctab:${r.count}:${canvasSig(r.canvas)}`; }
      // 68K code: CODE and the definition procedures, which are the same thing
      // under other names. The id matters -- CODE 0 is the jump table.
      if (G.CODE_TYPES && G.CODE_TYPES[T]) return text(() => G.decodeCodeResource(T, entry.id, data));
      return null;
  }
}

let grandTotal = [];
for (const forkPath of forkPaths) {
  const bytes = new Uint8Array(readFileSync(forkPath));
  G.parseResourceFork(bytes);
  const byType = peek('resourcesByType');
  const types = Object.keys(byType).sort();
  console.log(`\n=== ${forkPath.split('/').pop()} — ${types.length} types ===`);
  const lines = [];
  let ok = 0, fail = 0, skip = 0;
  for (const type of types) {
    const list = byType[type];
    const per = [];
    let tOk = 0, tFail = 0, tSkip = 0;
    for (const entry of list) {
      let data;
      try { data = G.getResourceData(type, entry); }
      catch (e) { per.push(`${type}#${entry.id} READERR ${e.message}`); tFail++; continue; }
      let sig;
      try { sig = describe(type, entry, data); }
      catch (e) { sig = `ERR ${e.message}`; }
      if (sig === null) { tSkip++; per.push(`${type}#${entry.id} raw:${data.length}`); continue; }
      if (String(sig).startsWith('ERR')) tFail++; else tOk++;
      per.push(`${type}#${entry.id} ${data.length}B ${sig}`);
    }
    ok += tOk; fail += tFail; skip += tSkip;
    const label = tSkip === list.length ? 'no decoder' : `${tOk} ok, ${tFail} fail`;
    console.log(`  '${type}' ${String(list.length).padStart(4)} res  ${label.padEnd(16)} ${hash(per.join('\n'))}`);
    lines.push(...per);
  }
  // The cursor gallery collapses acur sets into animations; it is the one
  // view built from several resources at once, so it gets its own line.
  try {
    const items = G.cursorGalleryItems();
    const desc = items.map(i => i.anim ? `anim#${i.id}[${i.ids.join('/')}]=${i.frames.length}frames`
                                       : `${i.cur.type}#${i.id}`).join(' ');
    console.log(`  cursor gallery: ${items.filter(i => i.anim).length} animated, ${items.filter(i => !i.anim).length} single`);
    lines.push('GALLERY ' + desc);
    if (process.env.DUMP) console.log('  ' + desc);
  } catch (e) { console.log(`  cursor gallery: ERROR ${e.message}`); lines.push('GALLERY ERR'); }
  console.log(`  TOTAL ${ok} decoded, ${fail} failed, ${skip} without a decoder — ${hash(lines.join('\n'))}`);
  grandTotal.push(lines.join('\n'));
  if (process.env.DUMP) console.log(lines.join('\n'));
}
console.log(`\nSNAPSHOT ${hash(grandTotal.join('\n'))}`);
