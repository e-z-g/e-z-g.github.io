#!/usr/bin/env node
// Checks cythera_data_viewer.html against delvmod, the reference implementation
// this project's knowledge of the Cythera archive came from.
//
//   node utilities/delv_crosscheck.mjs cythera_data_viewer.html \
//        sources/github_delvmod/code "$TMPDIR/Cythera Data.data"
//
// The viewer carries copies of several tables that delvmod worked out first:
// which subindexes are encrypted, and the symbol names that make a disassembled
// script readable. A copy drifts silently -- nothing in a browser complains
// that a syscall is labelled with the wrong name, or that a resource is being
// shown as raw ciphertext. So this re-reads the tables out of delvmod's Python
// and compares.
//
// It found the encryption tables mattered: the viewer used to guess, with a
// printable-ratio-and-entropy heuristic, and disagreed with delvmod on 18 of
// 1,558 resources -- always by leaving an encrypted resource undecrypted.
// 0x1415 was the clearest, scoring 0.238 raw against 0.223 decrypted while its
// decrypted form plainly reads "Sewers".
//
// Nothing in the delvmod checkout is modified or executed; only read. (Its
// Python does not run on Python 3.11+ anyway -- inspect.getargspec is gone and
// rdasm imports parsley -- so parsing the source is also the robust option.)

import {readFileSync, existsSync} from 'node:fs';
import vm from 'node:vm';
import {pageSource} from './page_scripts.mjs';

const [htmlPath = 'cythera_data_viewer.html',
       delvPath = 'sources/github_delvmod/code',
       dataPath] = process.argv.slice(2);
for (const p of [htmlPath, delvPath]) {
  if (!existsSync(p)) { console.error('missing: ' + p); process.exit(2); }
}

let failures = 0;
const fail = (what, detail) => { failures++; console.log('  FAIL ' + what + (detail ? ' — ' + detail : '')); };
const ok = (what, detail) => console.log('  ok   ' + what + (detail ? ' — ' + detail : ''));

// ---- read the reference tables out of the Python ---------------------------
// Commented-out entries have to go before anything is parsed. delvmod keeps
// several `#   0x10: "Unknown_10",` lines inside its tables -- names that were
// tried and withdrawn -- and reading those as live entries made this harness's
// first run report two failures that were entirely its own.
function stripPyComments(src) {
  return src.split('\n').map(line => {
    let quote = null;
    for (let i = 0; i < line.length; i++) {
      const c = line[i];
      if (quote) { if (c === quote && line[i-1] !== '\\') quote = null; }
      else if (c === '"' || c === "'") quote = c;
      else if (c === '#') return line.slice(0, i);
    }
    return line;
  }).join('\n');
}

const archivePy = stripPyComments(readFileSync(`${delvPath}/delv/archive.py`, 'utf8'));
const symbolsPy = stripPyComments(readFileSync(`${delvPath}/delv/rdasm_symbolics.py`, 'utf8'));

// `name = [ 1, 2, 3 ]`, possibly across several lines.
function pyIntList(src, name) {
  const m = new RegExp(`${name}\\s*=\\s*\\[([^\\]]*)\\]`).exec(src);
  if (!m) throw new Error(`${name} not found`);
  return new Set(m[1].split(',').map(s => s.trim()).filter(Boolean).map(Number));
}
// `name = { 0x0210: False }`
function pySingleKnown(src, name) {
  const m = new RegExp(`${name}\\s*=\\s*\\{([^}]*)\\}`).exec(src);
  if (!m) throw new Error(`${name} not found`);
  const out = new Map();
  for (const pair of m[1].split(',')) {
    const kv = /(0x[0-9a-f]+|\d+)\s*:\s*(True|False)/i.exec(pair);
    if (kv) out.set(Number(kv[1]), kv[2] === 'True');
  }
  return out;
}
// `NAME = {  'Label': 0x12,  ... }` or `{ 0x12: 'Label', ... }`
function pyNameMap(src, name, {valueIsName = false} = {}) {
  const start = src.indexOf(name + ' = {');
  if (start < 0) throw new Error(`${name} not found`);
  const end = src.indexOf('\n}', start);
  const body = src.slice(start, end);
  const out = new Map();
  const re = valueIsName
    ? /(0x[0-9a-fA-F]+|\d+)\s*:\s*["']([^"']+)["']/g
    : /["']([^"']+)["']\s*:\s*\(?\s*(0x[0-9a-fA-F]+|\d+)/g;
  for (const m of body.matchAll(re)) {
    const code = Number(valueIsName ? m[1] : m[2]);
    const label = valueIsName ? m[2] : m[1];
    if (label.startsWith('_')) continue;          // _size / _name metadata
    // The first spelling wins: these tables occasionally list an alias after
    // the canonical name, and delvmod's own dict comprehension keeps the last,
    // but only the code->name direction is used here.
    if (!out.has(code)) out.set(code, label);
  }
  return out;
}

// The Scenario subclass is the one that describes Cythera Data; the base
// Archive class has empty lists.
const scenario = archivePy.slice(archivePy.indexOf('class Scenario'));
const REF_ENCRYPTED = pyIntList(scenario, 'known_encrypted');
const REF_CLEAR = pyIntList(scenario, 'known_clear');
const REF_SINGLE = pySingleKnown(scenario, 'single_known');

const REF_SYSCALL = pyNameMap(symbolsPy, 'ASM_SYSCALL_NAMES');
const REF_FIELD = pyNameMap(symbolsPy, 'ASM_STRUCT_HINTS');
const REF_METHOD = pyNameMap(symbolsPy, 'ASM_OBJECT_HINTS');
const REF_GUI = pyNameMap(symbolsPy, 'ASM_GUI_NAME_HINTS', {valueIsName: true});
const REF_GLOBAL = pyNameMap(symbolsPy, 'DASM_GLOBAL_NAME_HINTS', {valueIsName: true});
const REF_OBJTYPE = pyNameMap(symbolsPy, 'DASM_OBJ_NAME_HINTS', {valueIsName: true});
const REF_RESOURCE = pyNameMap(symbolsPy, 'DASM_RESOURCE_NAME_HINTS', {valueIsName: true});
const REF_CHARACTER = pyNameMap(symbolsPy, 'DASM_CYTHERA_CHARACTERS', {valueIsName: true});

console.log(`  delvmod: ${REF_ENCRYPTED.size} encrypted + ${REF_CLEAR.size} clear subindexes, ` +
            `${REF_SYSCALL.size} syscalls, ${REF_METHOD.size} methods, ${REF_FIELD.size} fields, ` +
            `${REF_CHARACTER.size} characters`);

// ---- load the viewer -------------------------------------------------------
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
try {
  new vm.Script(pageSource(htmlPath) + '\n;window.__peek = n => eval(n);', {filename: htmlPath})
    .runInContext(ctx);
} catch (e) {
  console.error('FATAL: the viewer threw while loading: ' + e.message);
  process.exit(1);
}
const peek = n => { try { return ctx.__peek(n); } catch (e) { return undefined; } };

// ---- 1. the encryption tables ---------------------------------------------
const setsEqual = (a, b) => a && b && a.size === b.size && [...a].every(v => b.has(v));
{
  const vEnc = peek('DELV_ENCRYPTED_SUBN'), vClear = peek('DELV_CLEAR_SUBN'), vSingle = peek('DELV_CLEAR_RESID');
  if (!vEnc || !vClear) {
    fail('encryption tables', 'the viewer has no DELV_ENCRYPTED_SUBN/DELV_CLEAR_SUBN — it is guessing');
  } else {
    if (setsEqual(vEnc, REF_ENCRYPTED)) ok('encrypted subindexes', `${vEnc.size} match delvmod`);
    else fail('encrypted subindexes', `viewer ${[...vEnc].sort((a,b)=>a-b)} vs delvmod ${[...REF_ENCRYPTED].sort((a,b)=>a-b)}`);

    if (setsEqual(vClear, REF_CLEAR)) ok('clear subindexes', `${vClear.size} match delvmod`);
    else fail('clear subindexes', `viewer ${[...vClear].sort((a,b)=>a-b)} vs delvmod ${[...REF_CLEAR].sort((a,b)=>a-b)}`);

    const wantClear = new Set([...REF_SINGLE].filter(([, enc]) => !enc).map(([rid]) => rid));
    if (setsEqual(vSingle, wantClear)) ok('per-resource exceptions', [...wantClear].map(r => '0x' + r.toString(16).toUpperCase()).join(', ') || 'none');
    else fail('per-resource exceptions', `viewer ${[...(vSingle || [])]} vs delvmod ${[...wantClear]}`);

    const overlap = [...REF_ENCRYPTED].filter(s => REF_CLEAR.has(s));
    if (overlap.length) fail('delvmod tables', 'a subindex is in both lists: ' + overlap.join(', '));
  }
}

// ---- 2. the disassembler's symbol tables -----------------------------------
{
  const sym = peek('DVM_SYM');
  if (!sym) fail('DVM_SYM', 'not found in the viewer');
  else {
    const compare = (label, viewerTable, refMap) => {
      const v = new Map(Object.entries(viewerTable || {}).map(([k, n]) => [Number(k), n]));
      const missing = [], wrong = [];
      for (const [code, name] of refMap) {
        if (!v.has(code)) missing.push(`0x${code.toString(16).toUpperCase()} ${name}`);
        else if (v.get(code) !== name) wrong.push(`0x${code.toString(16).toUpperCase()} viewer "${v.get(code)}" delvmod "${name}"`);
      }
      const extra = [...v.keys()].filter(c => !refMap.has(c));
      if (wrong.length) fail(`${label} names`, wrong.slice(0, 6).join('; ') + (wrong.length > 6 ? ` (+${wrong.length - 6})` : ''));
      else if (missing.length) fail(`${label} names`, `${missing.length} missing: ` + missing.slice(0, 5).join('; '));
      else ok(`${label} names`, `${refMap.size} match` + (extra.length ? `, ${extra.length} extra in the viewer` : ''));
    };
    compare('syscall', sym.syscall, REF_SYSCALL);
    compare('method', sym.method, REF_METHOD);
    compare('field', sym.field, REF_FIELD);
    compare('global', sym.global, REF_GLOBAL);
    compare('gui', sym.gui, REF_GUI);
    compare('objtype', sym.objtype, REF_OBJTYPE);
    compare('resource', sym.resource, REF_RESOURCE);
    compare('character', sym.character, REF_CHARACTER);
  }
}

// ---- 3. the opcode table ---------------------------------------------------
// delvmod's OpTable maps a byte to an Opcode class. Most entries are built by
// the Opcoder(mnemonic, expect, fixed) factory and can be read straight out of
// the table; the rest name a class whose mnemonic is a line in its body.
{
  const ddasm = stripPyComments(readFileSync(`${delvPath}/delv/ddasm.py`, 'utf8'));

  // Inheritance has to be followed, not assumed away. `class OpIfNot(OpIf)`
  // declares only its mnemonic and inherits expect=1 from OpIf; reading its
  // body alone gives 0 and reports the viewer as wrong about how many operand
  // expressions an `if_not` consumes. That was this check's first finding, and
  // it was this check's own bug.
  const raw = new Map();
  for (const m of ddasm.matchAll(/class\s+(Op\w+)\((\w+)[^)]*\):([\s\S]*?)(?=\nclass |\ndef |\nOpTable)/g)) {
    const mn = /mnemonic\s*=\s*['"]([^'"]*)['"]/.exec(m[3]);
    const ex = /\bexpect\s*=\s*(\d+)/.exec(m[3]);
    raw.set(m[1], {base: m[2], mnemonic: mn ? mn[1] : null, expect: ex ? Number(ex[1]) : null});
  }
  const classMnemonic = new Map();
  const resolve = (name, seen = new Set()) => {
    const e = raw.get(name);
    if (!e || seen.has(name)) return {mnemonic: null, expect: 0};
    seen.add(name);
    const up = raw.has(e.base) ? resolve(e.base, seen) : {mnemonic: null, expect: 0};
    return {
      mnemonic: e.mnemonic !== null ? e.mnemonic : up.mnemonic,
      expect: e.expect !== null ? e.expect : up.expect,
    };
  };
  for (const name of raw.keys()) {
    const r = resolve(name);
    if (r.mnemonic) classMnemonic.set(name, r);
  }

  const tableSrc = ddasm.slice(ddasm.indexOf('OpTable = {'), ddasm.indexOf('\n}', ddasm.indexOf('OpTable = {')));
  const REF_OPS = new Map();
  for (const m of tableSrc.matchAll(/(0x[0-9A-Fa-f]{2})\s*:\s*(?:Opcoder\(\s*'([^']+)'\s*(?:,\s*(\d+))?|(\w+))/g)) {
    const code = Number(m[1]);
    if (m[2]) REF_OPS.set(code, {mnemonic: m[2], expect: m[3] ? Number(m[3]) : 0});
    else if (classMnemonic.has(m[4])) REF_OPS.set(code, classMnemonic.get(m[4]));
  }

  // Divergences this project has made on purpose, with the reason. Anything
  // not listed here is a drift and fails.
  const DELIBERATE = new Map([
    // delvmod abbreviates; the long form is what the viewer shows a reader.
    // (Applies to the 0x00-0x2F local range, which is not in OpTable anyway.)
  ]);

  const vOps = peek('DVM_OPS');
  if (!vOps) fail('DVM_OPS', 'not found in the viewer');
  else if (!REF_OPS.size) fail('delvmod OpTable', 'could not be parsed');
  else {
    const wrongName = [], wrongExpect = [], missing = [];
    for (const [code, ref] of REF_OPS) {
      const v = vOps[code];
      if (!v) { missing.push(`0x${code.toString(16).toUpperCase()} ${ref.mnemonic}`); continue; }
      const allowed = DELIBERATE.get(code);
      if (v[0] !== ref.mnemonic && allowed !== v[0])
        wrongName.push(`0x${code.toString(16).toUpperCase()} viewer "${v[0]}" delvmod "${ref.mnemonic}"`);
      if (v[2] !== ref.expect)
        wrongExpect.push(`0x${code.toString(16).toUpperCase()} ${ref.mnemonic} takes ${ref.expect} in delvmod, ${v[2]} here`);
    }
    const extra = Object.keys(vOps).map(Number).filter(c => !REF_OPS.has(c));
    if (wrongName.length) fail('opcode mnemonics', wrongName.join('; '));
    else if (missing.length) fail('opcode coverage', `${missing.length} not decoded here: ` + missing.join('; '));
    else ok('opcode mnemonics', `${REF_OPS.size} match delvmod` + (extra.length ? `, ${extra.length} extra here` : ''));
    // `expect` is what nests a disassembly: get it wrong and the operands of
    // one instruction are attributed to another.
    if (wrongExpect.length) fail('opcode operand counts', wrongExpect.join('; '));
    else ok('opcode operand counts', 'every expect matches');
  }
}

// ---- 4. every resource in a real archive -----------------------------------
if (!dataPath) {
  console.log('  (no archive given — skipping the per-resource check)');
} else if (!existsSync(dataPath)) {
  fail('archive', 'not found: ' + dataPath);
} else {
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

  let agree = 0, noOpinion = 0;
  const disagree = [];
  for (let subn = 0; subn < 256; subn++) {
    if (!mi[subn][0]) continue;
    for (let ri = 0, n = Math.min(256, mi[subn][1] / 8); ri < n; ri++) {
      const resid = (subn + 1) * 0x100 + ri;
      const raw = ctx.getResourceBytes(resid);
      if (!raw || !raw.length) continue;
      let v;
      try { v = ctx.smartDecrypt(raw, resid); } catch (e) { continue; }
      const truth = REF_SINGLE.has(resid) ? REF_SINGLE.get(resid)
                  : REF_ENCRYPTED.has(subn) ? true
                  : REF_CLEAR.has(subn) ? false : null;
      if (truth === null) { noOpinion++; continue; }
      if (!!v.wasDecrypted === truth) agree++;
      else disagree.push(`0x${resid.toString(16).toUpperCase()} (sub ${subn}) read as ` +
                         `${v.wasDecrypted ? 'encrypted' : 'clear'}, delvmod says ${truth ? 'encrypted' : 'clear'}`);
    }
  }
  if (disagree.length) fail(`decryption of ${agree + disagree.length} resources`,
    `${disagree.length} wrong: ` + disagree.slice(0, 8).join('; ') + (disagree.length > 8 ? ` (+${disagree.length - 8})` : ''));
  else ok('decryption', `all ${agree} resources agree with delvmod` +
    (noOpinion ? `, ${noOpinion} in subindexes delvmod does not describe` : ''));
}

// ---- 5. the one reading delvmod does not have ------------------------------
// 0x1xxxxxxx word constants. delvmod classes the whole 0x10000000-0x2FFFFFFF
// range as unidentified; the wiki reads the 0x1 nibble as a reference to a
// local variable, and that is what dvmWord renders. It is the only part of the
// word decoder without a reference implementation behind it, so it gets its
// own evidence instead: every such reference should name a local that its own
// function declares, and usually one that same function also reads directly.
if (dataPath && existsSync(dataPath) && typeof ctx.dvmExtents === 'function') {
  let refs = 0, inRange = 0, alsoReadDirectly = 0, rawZero = 0;
  const SCRIPT_SUBN = [0, 3, 7, 8, 9, 11, 12, 13, 14, 15, 16, 19, 20, 23, 24, 25, 26, 27, 29, 47];
  for (const subn of SCRIPT_SUBN) {
    for (let ri = 0; ri < 256; ri++) {
      const resid = (subn + 1) * 0x100 + ri;
      let raw;
      try { raw = ctx.getResourceBytes(resid); } catch (e) { continue; }
      if (!raw || !raw.length) continue;
      let data, objs;
      try { data = ctx.smartDecrypt(raw, resid).data; objs = ctx.dvmExtents(data, resid); }
      catch (e) { continue; }
      for (const [st, en, kind] of objs) {
        if (kind !== 'function') continue;
        const seg = data.subarray(st, Math.min(en, data.length));
        if (seg.length < 4) continue;
        const nlocals = seg[2];
        let dis;
        try { dis = ctx.dvmDisassemble(seg, 3); } catch (e) { continue; }
        const readDirectly = new Set();
        for (const op of dis.ops) {
          if (op[2] !== 'local') continue;
          const m = /^Var([0-9A-Fa-f]+)/.exec(String(op[3]));
          if (m) readDirectly.add(parseInt(m[1], 16));
        }
        for (const op of dis.ops) {
          if (op[2] !== 'word') continue;
          const m = /^&Var(-?\d+)/.exec(String(op[3]));
          if (!m) continue;
          const idx = parseInt(m[1], 10);
          refs++;
          if (idx >= 0 && idx < nlocals) inRange++;
          if (idx + 1 === 0) rawZero++;
          if (readDirectly.has(idx)) alsoReadDirectly++;
        }
      }
    }
  }
  if (!refs) ok('&Var references', 'none in this archive');
  else if (inRange !== refs)
    fail('&Var references', `${refs - inRange} of ${refs} name a local their function does not declare — ` +
                            'the 0x1xxxxxxx reading may be wrong');
  else if (rawZero)
    fail('&Var references', 'an encoded value of 0 appeared, so the encoding is not 1-based and the -1 in dvmWord is wrong');
  else
    ok('&Var references', `all ${refs} name a declared local; ` +
       `${Math.round(100 * alsoReadDirectly / refs)}% are also read directly in the same function`);
}

// ---- 6. the prop-visibility rule -------------------------------------------
// renderMapVisual departs from delvmod's show_in_map() on purpose: delvmod
// hides anything with flags & 0x58, and the viewer exempts characters from
// that. delvmod's own comment on the function is "This is probably wrong --
// many details yet to be determined. FIXME", so the divergence is measured
// rather than argued. What must hold is the *direction*: this rule may only
// ever add people to a map, never remove one delvmod would have drawn.
if (dataPath && existsSync(dataPath) && typeof ctx.parseDelverPropList === 'function') {
  const chars = typeof ctx.characterProptypes === 'function' ? ctx.characterProptypes() : new Set();
  let records = 0, agree = 0, viewerOnly = 0, delvmodOnly = 0;
  for (let n = 0; n < 256; n++) {
    const propResid = 0x8100 + n;
    let raw;
    try { raw = ctx.getResourceBytes(propResid); } catch (e) { continue; }
    if (!raw || !raw.length) continue;
    let recs;
    try { recs = ctx.parseDelverPropList(ctx.smartDecrypt(raw, propResid).data); } catch (e) { continue; }
    for (const r of recs) {
      records++;
      const deleted = r.flags === 0xFF, contained = !!(r.flags & 0x58);
      // 0x42 EGG and 0x44 ROOF are markers, not props to draw: delvmod names
      // them rather than reading their proptype, and the viewer now skips them
      // on the terrain layer too (roofs have their own layer and toggle).
      const marker = r.flags === 0x42 || r.flags === 0x44;
      const delvShows = !deleted && !contained;
      const viewerShows = !deleted && !marker && (!contained || chars.has(r.proptype));
      if (delvShows === viewerShows) agree++;
      else if (viewerShows) viewerOnly++;
      else delvmodOnly++;
    }
  }
  if (!records) ok('prop visibility', 'no prop lists in this archive');
  else if (delvmodOnly)
    fail('prop visibility', `${delvmodOnly} props delvmod draws are hidden here — the rule is ` +
                            'supposed to be a strict superset of show_in_map()');
  else
    ok('prop visibility', `${records} records, ${agree} agree, ${viewerOnly} drawn here that ` +
       'delvmod hides (characters; EGG/ROOF markers excluded), none the other way');
}

// ---- 7. the prop location word ---------------------------------------------
// A prop's three location bytes are only coordinates when it is on the floor.
// delvmod's textual_location() in delv/level.py is the reference:
//
//   flags == 0xFF -> deleted
//   flags & 0x10  -> carried by character (raw & 0xFFFF)
//   flags & 0x08  -> inside prop index (raw & 0xFFFF) - 0x100
//   otherwise     -> (raw >> 12, raw & 0xFFF)
//
// Reading them as coordinates unconditionally put 985 props at meaningless
// positions. This re-derives the rules from the Python and checks every record.
if (dataPath && existsSync(dataPath) && typeof ctx.parseDelverPropList === 'function') {
  const levelPy = stripPyComments(readFileSync(`${delvPath}/delv/level.py`, 'utf8'));
  const fn = levelPy.slice(levelPy.indexOf('def textual_location'), levelPy.indexOf('def proptypename_with_flags'));
  const expectCarried = /flags\s*&\s*0x10/.test(fn);
  const expectInside = /flags\s*&\s*0x08/.test(fn);
  const expectOffset = /-\s*0x100/.test(fn);
  if (!expectCarried || !expectInside || !expectOffset) {
    fail('prop location', 'delvmod\'s textual_location no longer reads the way this viewer does');
  } else {
    let records = 0, floor = 0, carried = 0, contained = 0, deleted = 0, bad = 0;
    for (let n = 0; n < 256; n++) {
      const resid = 0x8100 + n;
      let raw;
      try { raw = ctx.getResourceBytes(resid); } catch (e) { continue; }
      if (!raw || !raw.length) continue;
      let recs;
      try { recs = ctx.parseDelverPropList(ctx.smartDecrypt(raw, resid).data); } catch (e) { continue; }
      for (const r of recs) {
        records++;
        if (r.flags === 0xFF) { deleted++; continue; }
        if (r.carriedBy !== null) carried++;
        else if (r.container !== null) contained++;
        else floor++;
        // A containment link has to point at something that exists.
        if (r.container !== null && (r.container < 0 || r.container >= recs.length)) bad++;
      }
    }
    if (!records) ok('prop location', 'no prop lists in this archive');
    else if (bad)
      fail('prop location', `${bad} containment links point outside their own prop list`);
    else
      ok('prop location', `${records} records: ${floor} on the floor, ${contained} inside ` +
         `another prop, ${carried} carried, ${deleted} deleted`);
  }
}

// ---- 8. roofs --------------------------------------------------------------
// A roofed map's header declares how many 8x8 roof blocks it carries, and the
// flags-0x44 prop records say where each one goes. The relationship that makes
// that reading safe is countable: every declared block placed, none invented,
// and all of them landing on the map.
if (dataPath && existsSync(dataPath) && typeof ctx.mapRoofSections === 'function') {
  let maps = 0, sections = 0, badIndex = 0, offMap = 0, unplaced = 0;
  for (let n = 0; n < 256; n++) {
    const mapResid = 0x8000 + n;
    let raw;
    try { raw = ctx.getResourceBytes(mapResid); } catch (e) { continue; }
    if (!raw) continue;
    let data = ctx.smartDecrypt(raw, mapResid).data;
    let m = ctx.parseDelverMap(data);
    if (!m) {
      const alt = ctx.decryptResource(raw, mapResid);
      const m2 = ctx.parseDelverMap(alt);
      if (m2) { data = alt; m = m2; }
    }
    if (!m || !m.roofLayerSize) continue;
    maps++;
    const secs = ctx.mapRoofSections(mapResid);
    sections += secs.length;
    const seen = new Set();
    for (const sec of secs) {
      if (sec.block >= m.roofLayerSize) badIndex++; else seen.add(sec.block);
      if (sec.x - 7 < 0 || sec.y - 7 < 0 || sec.x >= m.width || sec.y >= m.height) offMap++;
    }
    if (seen.size !== m.roofLayerSize) unplaced += m.roofLayerSize - seen.size;
  }
  // A block nobody places is a property of the archive, not a misreading: the
  // Temple (0x801A) declares three full blocks and carries no 0x44 record at
  // all, which is a roof that was taken off the map with its tiles left behind.
  // (Its 19 flags-0x42 records are not the placement -- those carry real prop
  // types, 352-361, and delvmod names them EGG.) So unplaced blocks are
  // reported; an index the map never declared is the actual error.
  if (!maps) ok('roofs', 'no roofed maps in this archive');
  else if (badIndex) fail('roofs', `${badIndex} sections name a block the map does not declare`);
  else if (offMap > 2) fail('roofs', `${offMap} sections run past the map edge — more than the two known`);
  else ok('roofs', `${maps} roofed maps, ${sections} sections placed, ${unplaced} declared blocks ` +
                   `never placed, ${offMap} clipped at the map edge`);
}

console.log(failures ? `\nFAIL — ${failures} problem(s)` : '\ndelvmod cross-check: clean');
process.exit(failures ? 1 : 0);
