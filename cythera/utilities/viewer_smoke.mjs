#!/usr/bin/env node
// Drives cythera_data_viewer.html's user interface in Node, because Chrome
// cannot start under this machine's sandbox (ProcessSingleton binds a unix
// socket and bind() returns EPERM -- see utilities/browser_smoke.mjs).
//
//   python3 utilities/binhex_decode.py "sources/Cythera Data.hqx" "$TMPDIR"
//   node utilities/viewer_smoke.mjs cythera_data_viewer.html "$TMPDIR/Cythera Data.data"
//
// decoder_snapshot.mjs proves the decoders still produce the same bytes. This
// proves the page around them still works: it feeds the archive through the
// real entry point (parseArchiveBytes), then opens every category, renders
// every gallery, and opens every resource in it -- so a missing element id, a
// renamed function or a branch that throws surfaces as a failure line instead
// of a blank pane someone finds later.
//
// The DOM below is a stand-in, not a browser. It is deliberately strict where
// that catches real mistakes (unknown getElementById targets are recorded,
// appendChild(undefined) throws) and lax where the browser's behaviour does
// not change the outcome (layout, painting, fonts).

import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import {pageSource, describeScripts} from './page_scripts.mjs';

const [htmlPath, dataPath, onlyCat] = process.argv.slice(2);
if (!htmlPath || !dataPath) {
  console.error('usage: viewer_smoke.mjs <viewer.html> <Cythera Data.data> [category]');
  process.exit(2);
}
const html = readFileSync(htmlPath, 'utf8');
const js = pageSource(htmlPath);
const archive = new Uint8Array(readFileSync(dataPath));
// The resource fork, if it was extracted beside the data fork. The viewer gets
// this from the container it opened; here it is passed in the same way
// adoptArchive would, so the resource-fork gallery is exercised too.
const rsrcPath = dataPath.replace(/\.data$/, '.rsrc');
let rsrcFork = null;
try { rsrcFork = new Uint8Array(readFileSync(rsrcPath)); } catch (e) { rsrcFork = null; }

// ---- a small DOM -----------------------------------------------------------
const missingIds = new Set();
let nodeCount = 0;

function makeCtx(cv) {
  const im = (w, h) => ({ width: w, height: h, data: new Uint8ClampedArray(Math.max(0, w * h * 4)) });
  return {
    canvas: cv, fillStyle: '#000', strokeStyle: '#000', lineWidth: 1, font: '', textAlign: 'left',
    globalAlpha: 1, globalCompositeOperation: 'source-over', imageSmoothingEnabled: true,
    createImageData: (w, h) => im(w, h),
    putImageData(d) { cv._px = d; },
    getImageData(x, y, w, h) { return cv._px || im(w, h); },
    drawImage() {}, fillRect() {}, clearRect() {}, strokeRect() {},
    beginPath() {}, closePath() {}, moveTo() {}, lineTo() {}, arc() {}, stroke() {}, fill() {},
    save() {}, restore() {}, translate() {}, scale() {}, setTransform() {}, setLineDash() {},
    fillText() {}, strokeText() {}, measureText: t => ({ width: String(t).length * 6 }),
    createRadialGradient: () => ({ addColorStop() {} }),
    createLinearGradient: () => ({ addColorStop() {} }),
    createPattern: () => null, clip() {}, rect() {}, quadraticCurveTo() {}, ellipse() {},
  };
}

class El {
  constructor(tag) {
    nodeCount++;
    this.tagName = String(tag).toUpperCase();
    this.style = new Proxy({ cssText: '' }, { set(t, k, v) { t[k] = v; return true; } });
    this.children = [];
    this.childNodes = this.children;
    this.parentNode = null;
    this.attributes = {};
    this.dataset = {};
    this._text = '';
    this._html = '';
    this._id = '';
    this.className = '';
    this.value = '';
    this.checked = false;
    this.disabled = false;
    this.tabIndex = -1;
    this.title = '';
    this.href = ''; this.download = ''; this.rel = ''; this.src = '';
    this.width = 0; this.height = 0; this._px = null;
    this.paused = true;
    this.files = [];
    this.options = [];
    this.selectedIndex = -1;
    this.classList = {
      _set: new Set(),
      add: (...c) => c.forEach(x => this.classList._set.add(x)),
      remove: (...c) => c.forEach(x => this.classList._set.delete(x)),
      contains: c => this.classList._set.has(c),
      toggle: (c, on) => { if (on === undefined) on = !this.classList._set.has(c);
                           if (on) this.classList._set.add(c); else this.classList._set.delete(c); },
    };
  }
  get id() { return this._id; }
  set id(v) { this._id = v; if (v) REGISTRY.set(v, this); }
  set textContent(v) { this._text = v === null || v === undefined ? '' : String(v); this.children.length = 0; }
  get textContent() {
    if (this.children.length) return this._text + this.children.map(c => c.textContent).join(' ');
    return this._text;
  }
  set innerHTML(v) {
    this._html = String(v === null || v === undefined ? '' : v);
    this.children.length = 0;
    if (this.tagName === 'SELECT') this.options.length = 0;
  }
  get innerHTML() { return this._html; }
  appendChild(c) {
    if (!c || !(c instanceof El)) throw new TypeError('appendChild called with ' + c);
    c.parentNode = this;
    this.children.push(c);
    if (this.tagName === 'SELECT' && c.tagName === 'OPTION') this.options.push(c);
    return c;
  }
  append(...cs) { for (const c of cs) if (c instanceof El) this.appendChild(c); }
  insertBefore(c, ref) {
    const i = ref ? this.children.indexOf(ref) : -1;
    if (i < 0) return this.appendChild(c);
    c.parentNode = this; this.children.splice(i, 0, c); return c;
  }
  removeChild(c) { const i = this.children.indexOf(c); if (i >= 0) this.children.splice(i, 1); return c; }
  remove() { if (this.parentNode) this.parentNode.removeChild(this); }
  replaceChildren(...cs) { this.children.length = 0; this.append(...cs); }
  setAttribute(k, v) {
    this.attributes[k] = String(v);
    if (k === 'id') this.id = String(v);
    if (k === 'class') this.className = String(v);
  }
  getAttribute(k) { return k === 'class' ? this.className : (k in this.attributes ? this.attributes[k] : null); }
  hasAttribute(k) { return k === 'class' ? !!this.className : k in this.attributes; }
  removeAttribute(k) { delete this.attributes[k]; }
  addEventListener() {} removeEventListener() {}
  focus() {} blur() {} scrollIntoView() {}
  click() { if (typeof this.onclick === 'function') this.onclick({ shiftKey: false, preventDefault() {} }); }
  closest() { return null; }
  getContext(kind) { return kind === '2d' ? (this._ctx || (this._ctx = makeCtx(this))) : null; }
  toDataURL() { return 'data:image/png;base64,'; }
  toBlob(cb) { setTimeout(() => cb(new Blob([new Uint8Array(8)])), 0); }
  getBoundingClientRect() { return { left: 0, top: 0, right: 300, bottom: 300, width: 300, height: 300 }; }
  play() { this.paused = false; } pause() { this.paused = true; }
  _walk(out) { for (const c of this.children) { out.push(c); c._walk(out); } return out; }
  _matches(sel) {
    sel = sel.trim();
    if (sel.startsWith('.')) return this.className.split(/\s+/).includes(sel.slice(1)) || this.classList.contains(sel.slice(1));
    if (sel.startsWith('#')) return this._id === sel.slice(1);
    if (sel.startsWith('[')) { const k = sel.slice(1, -1).split('=')[0]; return this.hasAttribute(k); }
    return this.tagName === sel.toUpperCase();
  }
  querySelectorAll(sel) {
    // Only the shapes this file uses: "tag", ".class", "#id .class".
    const parts = String(sel).split(/\s+/).filter(Boolean);
    const last = parts[parts.length - 1];
    let scope = [this];
    if (parts.length > 1 && parts[0].startsWith('#')) {
      const root = REGISTRY.get(parts[0].slice(1));
      scope = root ? [root] : [];
    }
    const out = [];
    for (const s of scope) for (const n of s._walk([])) if (n._matches(last)) out.push(n);
    return out;
  }
  querySelector(sel) { return this.querySelectorAll(sel)[0] || null; }
}

const REGISTRY = new Map();
// Seed every id that exists in the static markup, so an id the JS looks up but
// the markup never declares is reported rather than silently invented.
for (const m of html.matchAll(/\bid="([^"]+)"/g)) REGISTRY.set(m[1], new El('div'));
// The categories live in static markup as <option>s; the nav bar is built from
// them, so they have to be present for anything to be navigable.
const catSel = REGISTRY.get('categorySelect');
catSel.tagName = 'SELECT';
const optionSource = html.slice(html.indexOf('<select id="categorySelect"'), html.indexOf('</select>'));
const CATEGORY_VALUES = [];
for (const m of optionSource.matchAll(/<option value="([^"]+)"[^>]*>([\s\S]*?)<\/option>/g)) {
  const o = new El('option');
  o.value = m[1];
  o.textContent = m[2].replace(/&amp;/g, '&').replace(/&nbsp;/g, ' ').trim();
  catSel.appendChild(o);
  CATEGORY_VALUES.push(m[1]);
}
catSel.value = CATEGORY_VALUES[0];
for (const tag of ['canvas', 'audio', 'input', 'select']) void tag;
REGISTRY.get('canvas').tagName = 'CANVAS';
REGISTRY.get('waveform').tagName = 'CANVAS';
REGISTRY.get('audioPlayer').tagName = 'AUDIO';
REGISTRY.get('residSelect').tagName = 'SELECT';
REGISTRY.get('categorySelect').tagName = 'SELECT';

const body = new El('body');
const documentStub = {
  getElementById(id) {
    if (!REGISTRY.has(id)) { missingIds.add(id); REGISTRY.set(id, new El('div')); }
    return REGISTRY.get(id);
  },
  createElement: t => new El(t),
  createElementNS: (ns, t) => new El(t),
  createDocumentFragment: () => new El('fragment'),
  createTextNode: t => { const e = new El('#text'); e.textContent = t; return e; },
  querySelector: s => body.querySelector(s),
  querySelectorAll: s => body.querySelectorAll(s),
  addEventListener() {}, removeEventListener() {},
  body, head: new El('head'), documentElement: new El('html'),
  fonts: { add() {} },
};

const rafQueue = [];
const sandbox = {
  document: documentStub, console,
  TextDecoder, TextEncoder, Uint8Array, Int8Array, Int16Array, Uint16Array, Uint32Array,
  Int32Array, Float32Array, Float64Array, Uint8ClampedArray, ArrayBuffer, DataView,
  Math, JSON, Map, Set, WeakMap, Date, Object, Array, String, Number, Boolean, Symbol,
  Error, TypeError, RangeError, RegExp, Promise, isNaN, isFinite, parseInt, parseFloat,
  Infinity, NaN, undefined, URLSearchParams, Intl,
  setTimeout, clearTimeout, setInterval: () => 0, clearInterval() {},
  requestAnimationFrame: cb => { rafQueue.push(cb); return rafQueue.length; },
  cancelAnimationFrame() {},
  fetch: () => Promise.reject(new Error('offline')),
  Blob: globalThis.Blob,
  URL: { createObjectURL: () => 'blob:stub', revokeObjectURL() {} },
  CompressionStream: globalThis.CompressionStream, Response: globalThis.Response,
  matchMedia: () => ({ matches: false, addEventListener() {}, addListener() {} }),
  localStorage: { getItem: () => null, setItem() {}, removeItem() {} },
  indexedDB: undefined,
  location: { hash: '', href: 'file:///viewer.html', search: '', reload() {} },
  // replaceState with a '#…' url really does rewrite location.hash in a
  // browser. Stubbing it as a no-op hid a bug where the page overwrote the
  // link it was opened on before reading it.
  history: {
    replaceState(s, t, url) { if (typeof url === 'string' && url.startsWith('#')) sandbox.location.hash = url; },
    pushState(s, t, url) { this.replaceState(s, t, url); },
  },
  navigator: { userAgent: 'node' },
  performance: { now: () => 0 },
  addEventListener() {}, removeEventListener() {},
  scrollTo() {}, scrollY: 0, innerWidth: 1200, innerHeight: 900,
  alert(msg) { sandbox.__alerts.push(String(msg)); },
  MutationObserver: class { observe() {} disconnect() {} },
  // Fires immediately, as though everything were on screen. The galleries
  // decode their tiles lazily now, so a no-op observer would leave this test
  // counting cells that were created but never decoded -- it would still say
  // "clean" while exercising none of the decoders.
  IntersectionObserver: class {
    constructor(cb) { this.cb = cb; }
    observe(el) { this.cb([{isIntersecting: true, target: el}], this); }
    unobserve() {} disconnect() {}
  },
  getComputedStyle: () => ({ gridTemplateColumns: '96px 96px 96px 96px' }),
  __alerts: [],
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

// ---- drive it --------------------------------------------------------------
let failures = 0;
const fail = (what, e) => { failures++; console.log('  FAIL ' + what + ' — ' + (e && e.message ? e.message : e)); };

console.log(`  markup ids seeded: ${REGISTRY.size}, categories: ${CATEGORY_VALUES.length}`);

const t0 = Date.now();
try {
  ctx.parseArchiveBytes(archive, 'Cythera Data (smoke test)', { via: 'data fork', rsrc: rsrcFork });
} catch (e) { fail('parseArchiveBytes', e); process.exit(1); }
const status = REGISTRY.get('sourceStatus').textContent;
console.log(`  parseArchiveBytes: ${Date.now() - t0} ms — status "${status.slice(0, 80)}"`);
if (!/Loaded:/.test(status)) fail('status line', 'did not report a load: ' + status);
if (!ctx.__peek('masterIndexGlobal').filter(m => m[0]).length) fail('master index', 'no subindexes');

const wanted = onlyCat ? [onlyCat] : CATEGORY_VALUES;
let galleries = 0, opened = 0, cellsSeen = 0;
for (const v of wanted) {
  const grid = REGISTRY.get('sheetGrid');
  try {
    if (!ctx.showCategory(v)) { fail('showCategory ' + v, 'refused'); continue; }
  } catch (e) { fail('showCategory ' + v, e); continue; }
  galleries++;
  const cells = grid.querySelectorAll('.cell').length + grid.children.length;
  cellsSeen += cells;
  const resids = ctx.CUR_RESIDS || [];
  const out = REGISTRY.get('output').textContent;
  if (!out) fail('gallery ' + v, 'no status text');
  if (!cells) console.log(`  note: category ${v} drew no tiles (${out.slice(0, 60)})`);

  // Open every resource this category lists.
  let localFail = 0;
  for (const entry of resids) {
    try {
      if (!ctx.openResource(entry[0])) { localFail++; continue; }
      opened++;
    } catch (e) {
      localFail++;
      if (localFail <= 2) fail(`open 0x${entry[0].toString(16).toUpperCase()} in ${v}`, e);
    }
  }
  if (localFail > 2) fail(`category ${v}`, `${localFail} resources failed to open`);
  // Back to the gallery, which is also what Esc does.
  try { ctx.returnToSheet(); } catch (e) { fail('returnToSheet from ' + v, e); }
  console.log(`  ${String(v).padEnd(11)} ${String(resids.length).padStart(4)} resources  ${String(cells).padStart(4)} tiles  ${localFail ? localFail + ' FAILED' : 'ok'}`);
}

// The detail views that are not resource-backed.
for (const [name, call] of [
  ['character detail', () => ctx.showCharacterDetail(1)],
  ['prop detail',      () => { const t = ctx.getPropTileList(); ctx.showPropTypeDetail(Object.keys(t).map(Number).find(k => t[k])); }],
  ['monster detail',   () => ctx.showMonsterDetail(22)],
  ['composite detail', () => ctx.showCompositeDetail(0x1000, ctx.loadCompositionTable()[0])],
  ['search',           () => { REGISTRY.get('searchBox').value = 'locked'; ctx.runSearch(); }],
  ['xref report',      () => ctx.xrefReport(0x8801)],
]) {
  try { call(); } catch (e) { fail(name, e); }
}

// The item browser reads a class script per prop type and joins it to the prop
// lists; "the gallery rendered" says nothing about whether it found anything.
try {
  ctx.showCategory('ITEMS');
  const list = ctx.inventoryItemList ? ctx.inventoryItemList() : null;
  if (!list || !list.length) fail('items', 'no inventory items found');
  else {
    const weighed = list.filter(i => i.weight !== null).length;
    const placed = list.filter(i => i.instances > 0).length;
    if (!weighed) fail('items', 'not one item carries a weight — is parseItemClass finding the table?');
    else if (!placed) fail('items', 'no item is placed anywhere — is buildItemIndex reading the prop lists?');
    else console.log(`  items: ${list.length} classes, ${weighed} with a weight, ${placed} placed in the world`);
    // The containment reading is what makes "placed" mean anything.
    const held = list.reduce((a, i) => a + ((ctx.buildItemIndex()[i.pt] || {}).carried || 0), 0);
    if (!held) fail('items', 'nothing is carried by anyone — the prop location word is being read as coordinates again');
    else console.log(`  items: ${held} carried by characters`);
  }
} catch (e) { fail('items', e); }

// Galleries decode lazily now, so "the cells exist" is no longer evidence that
// anything was decoded. Check the tally the gallery itself reports.
try {
  ctx.showCategory('141');
  const line = REGISTRY.get('output').textContent;
  const m = /Gallery: (\d+) decoded, (\d+) errors/.exec(line);
  if (!m) fail('lazy gallery', 'no decode tally in: ' + line.slice(0, 90));
  else if (Number(m[1]) === 0) fail('lazy gallery', 'no tile was decoded — is the observer firing? ' + line.slice(0, 90));
  else if (/still off screen/.test(line)) fail('lazy gallery', 'tiles left undecoded: ' + line.slice(0, 90));
  else console.log(`  lazy gallery: ${m[1]} tiles decoded, ${m[2]} errors, none left pending`);
} catch (e) { fail('lazy gallery', e); }

// The resource fork: the other half of the Cythera Data file. Its Delver-only
// types need this viewer's tile system to mean anything, which is why they are
// here rather than in resource_fork_browser.html.
if (!rsrcFork) {
  console.log('  resource fork: not extracted beside the data fork — skipped');
} else try {
  const fork = ctx.CYTHERA_RSRC;
  if (!fork) fail('resource fork', 'was passed in but never opened');
  else {
    const inv = ctx.rsrcInventory();
    const list = ctx.rsrcPatternList();
    if (!list.length) fail('resource fork', 'no stamps or brushes found');
    else {
      // Every tile of every stamp should resolve to real artwork and have a
      // name in F004 -- that is the check that the format is read right, and it
      // is what distinguishes a decoded stamp from 64 plausible numbers.
      let tiles = 0, drawn = 0, named = 0;
      for (const it of list) {
        for (const t of it.pat.tiles) {
          tiles++;
          const img = ctx.resolveTileImage(t);
          if (img && img.length) drawn++;
          if (ctx.terrainNameFor(t)) named++;
        }
      }
      if (drawn !== tiles) fail('resource fork', `${tiles - drawn} of ${tiles} stamp/brush tiles resolve to no artwork`);
      else if (named !== tiles) fail('resource fork', `${tiles - named} of ${tiles} tiles have no terrain name`);
      else console.log(`  resource fork: ${fork.total()} resources, ${list.length} stamps and brushes, ` +
                       `all ${tiles} tiles resolve and are named`);
      // The gallery, and a detail view reachable by URL.
      ctx.showCategory('RSRC');
      const galleryText = REGISTRY.get('output').textContent || '';
      if (!/Resource fork: /.test(galleryText)) fail('resource fork', 'gallery said: ' + galleryText.slice(0, 80));
      const stamp = list.find(i => i.type === 'eSTM');
      ctx.location.hash = `#c=RSRC&d=rsrc:eSTM:${stamp.entry.id}`;
      if (!ctx.applyDeepLink()) fail('resource fork', 'the deep link to a stamp was not applied');
      else if (!ctx.DETAIL_VIEW || ctx.DETAIL_VIEW.id !== 'eSTM:' + stamp.entry.id)
        fail('resource fork', 'deep link landed on ' + JSON.stringify(ctx.DETAIL_VIEW));
      else console.log(`  resource fork: #c=RSRC&d=rsrc:eSTM:${stamp.entry.id} reopens that stamp`);
      ctx.location.hash = '';
    }
  }
} catch (e) { fail('resource fork', e); }

// Roofs: a toggle that draws nothing is indistinguishable from a toggle that
// works, so check the tile count the layer reports rather than that it ran.
try {
  ctx.showCategory('127');
  let roofed = 0, tiles = 0;
  for (const [resid] of (ctx.CUR_RESIDS || [])) {
    ctx.openResource(resid);
    const cm = ctx.CUR_MAP;
    if (!cm || !cm.roofSections || !cm.roofSections.length) continue;
    roofed++;
    ctx.toggleRoofs(true);
    tiles += cm.roofTilesDrawn || 0;
    if (!cm.roofTilesDrawn) fail('roofs', `0x${resid.toString(16).toUpperCase()} has ` +
      `${cm.roofSections.length} roof sections but drew no tiles`);
    ctx.toggleRoofs(false);
    if (cm.roofTilesDrawn) fail('roofs',
      `0x${resid.toString(16).toUpperCase()} still drew ${cm.roofTilesDrawn} roof tiles with the toggle off`);
  }
  if (!roofed) fail('roofs', 'no map reported any roof sections');
  else console.log(`  roofs: ${roofed} roofed maps, ${tiles} tiles drawn with the toggle on`);
} catch (e) { fail('roofs', e); }

// The map inspector: every square a prop was drawn on must name that prop.
try {
  ctx.showCategory('127');
  const maps = (ctx.CUR_RESIDS || []).slice(0, 8);
  let mapsWithProps = 0, probes = 0, named = 0, withPeople = 0;
  for (const [resid] of maps) {
    ctx.openResource(resid);
    const cm = ctx.CUR_MAP;
    if (!cm || !cm.props || !cm.props.length) continue;
    mapsWithProps++;
    for (const p of cm.props.slice(0, 20)) {
      const [tx, ty] = p.cells[0];
      ctx.inspectMapSquare(tx, ty);
      const html = REGISTRY.get('mapInspect').innerHTML;
      probes++;
      if (html.includes('record #' + p.rec.index)) named++;
      if (html.includes('Dossier')) withPeople++;
    }
  }
  if (!mapsWithProps) fail('map inspector', 'no map reported any props');
  else if (named !== probes) fail('map inspector', `${probes - named} of ${probes} squares did not name their prop`);
  else console.log(`  map inspector: ${probes} prop squares on ${mapsWithProps} maps, all named`);

  // Characters stand where their schedule puts them, which is not where the
  // prop list puts anything, so they need their own probe.
  let peopleProbes = 0, peopleNamed = 0;
  for (const [resid] of maps) {
    ctx.openResource(resid);
    const cm = ctx.CUR_MAP;
    if (!cm) continue;
    const people = ctx.charactersOnLevel(cm.level, 12);
    for (const c of people.slice(0, 8)) {
      ctx.inspectMapSquare(Math.round(c.x), Math.round(c.y));
      const html = REGISTRY.get('mapInspect').innerHTML;
      peopleProbes++;
      if (html.includes('Dossier') && html.includes('showCharacterDetail(' + c.index + ')')) peopleNamed++;
    }
  }
  if (!peopleProbes) fail('map inspector', 'no scheduled characters found on any of the first maps');
  else if (peopleNamed !== peopleProbes) fail('map inspector', `${peopleProbes - peopleNamed} of ${peopleProbes} inhabited squares did not link the character`);
  else console.log(`  map inspector: ${peopleProbes} inhabited squares, all linked to their dossier`);
  // A square outside everything must say so rather than throw.
  ctx.inspectMapSquare(0, 0);
  ctx.clearMapInspector();
} catch (e) { fail('map inspector', e); }

// Deep links round-trip: a URL must reopen exactly what it named.
try {
  ctx.showCategory('135');
  ctx.openResource(0x8801);
  const link = ctx.currentSelectedResid();
  if (link !== 0x8801) fail('deep link', 'selected resid came back as ' + link);

  ctx.showCategory('144');                       // somewhere else entirely
  ctx.location.hash = '#c=135&r=8801';
  if (!ctx.applyDeepLink()) fail('deep link', '#c=135&r=8801 was not applied');
  else if (ctx.currentSelectedResid() !== 0x8801) fail('deep link', 'landed on 0x' + (ctx.currentSelectedResid() || 0).toString(16));

  ctx.location.hash = '#9101';                   // bare id, category unstated
  if (!ctx.applyDeepLink()) fail('deep link', 'bare #9101 was not applied');
  else if (ctx.currentSelectedResid() !== 0x9101) fail('deep link', 'bare id landed on 0x' + (ctx.currentSelectedResid() || 0).toString(16));

  ctx.location.hash = '#c=CHARACTERS&d=char:3';  // a dossier
  if (!ctx.applyDeepLink()) fail('deep link', 'dossier link was not applied');
  else {
    const d = ctx.DETAIL_VIEW;
    if (!d || d.kind !== 'char' || d.id !== 3) fail('deep link', 'dossier state is ' + JSON.stringify(d));
  }
  // Arriving on a link: the archive load itself must honour the hash the page
  // was opened with, not the default category it renders on the way in.
  ctx.location.hash = '#c=144&r=9103';
  ctx.parseArchiveBytes(archive, 'Cythera Data (arrived on a link)', { via: 'data fork' });
  if (ctx.currentSelectedResid() !== 0x9103)
    fail('deep link', 'opening with #c=144&r=9103 landed on 0x' + (ctx.currentSelectedResid() || 0).toString(16));
  ctx.location.hash = '';
} catch (e) { fail('deep link', e); }

// "Where is this art used?" — the reverse index has to agree with the forward
// one: every sheet it claims a map uses must really appear in that map.
try {
  const t = Date.now();
  const idx = ctx.buildTileSheetUsage();
  const sheets = Object.keys(idx).map(Number).sort((a, b) => a - b);
  const withMaps = sheets.filter(s => idx[s].maps.length);
  const withProps = sheets.filter(s => idx[s].props.length);
  console.log(`  art usage: ${sheets.length} sheets referenced (${withMaps.length} by maps, ` +
              `${withProps.length} by prop types) in ${Date.now() - t} ms`);
  const mapsCovered = new Set();
  for (const s2 of withMaps) for (const r of idx[s2].maps) mapsCovered.add(r);
  // subindex 127 declares 256 slots; only some are populated, and the gallery
  // knows which -- that is the number every map should be accounted for in.
  ctx.showCategory('127');
  const realMaps = (ctx.CUR_RESIDS || []).length;
  console.log(`  art usage: ${mapsCovered.size} of ${realMaps} maps contributed tiles`);
  if (!withMaps.length || !withProps.length) fail('art usage', 'index is empty');
  if (mapsCovered.size < realMaps)
    fail('art usage', `${realMaps - mapsCovered.size} maps contributed nothing — the decrypt fallback is probably failing`);

  // Cross-check one claim the hard way: re-read the map and look for the sheet.
  const sheet = withMaps[0], mapResid = idx[sheet].maps[0];
  const raw = ctx.getResourceBytes(mapResid);
  let data = ctx.smartDecrypt(raw, mapResid).data;
  let m = ctx.parseDelverMap(data);
  if (!m) { const alt = ctx.decryptResource(raw, mapResid); const m2 = ctx.parseDelverMap(alt); if (m2) { data = alt; m = m2; } }
  let found = false;
  for (let i = 0; m && i < m.width * m.height && !found; i++) {
    const o = m.mapDataOffset + i * 2;
    const tile = (data[o] << 8) | data[o + 1];
    if (tile && tile < 0x1000 && peek('sheetResidForTile')(tile) === sheet) found = true;
  }
  if (!found) fail('art usage', `claims map 0x${mapResid.toString(16)} draws sheet 0x${sheet.toString(16)}, but no tile in it does`);

  // And the rendered panel names something.
  ctx.showCategory('141');
  ctx.openResource(sheet);
  const panel = REGISTRY.get('artUsage').innerHTML;
  if (!/Maps|Prop types|Composite/.test(panel)) fail('art usage', 'panel said: ' + panel.slice(0, 80));
} catch (e) { fail('art usage', e); }

// Opening a second archive must not leave the first one's derived tables
// behind. Sentinels survive only if something is not being reset.
try {
  const marked = ['SCHEDULES', 'CHAR_TABLE', 'LIVING_PROPTYPES', '_CHAR_PROPTYPES',
                  'TERRAIN_NAMES', 'ZONE_NAMES', 'ZONEPORTS', 'STORE_SYMBOLS',
                  'XREF_INDEX', 'SCRIPT_TEXT', 'MONSTER_STATS', 'RESOURCE_SYMBOLS'];
  for (const k of marked) ctx[k] = '__stale__';
  peek('tileCanvasCache').set(-1, '__stale__');
  peek('spriteCountCache').set(-1, '__stale__');
  peek('pathCache').set('__stale__', 1);
  peek('_tileImageCache')['-1'] = '__stale__';
  ctx.parseArchiveBytes(archive, 'Cythera Data (reloaded)', { via: 'data fork' });
  const survivors = marked.filter(k => ctx[k] === '__stale__');
  for (const [name, present] of [
    ['tileCanvasCache', peek('tileCanvasCache').has(-1)],
    ['spriteCountCache', peek('spriteCountCache').has(-1)],
    ['pathCache', peek('pathCache').has('__stale__')],
    ['_tileImageCache', '-1' in peek('_tileImageCache')],
  ]) if (present) survivors.push(name);
  if (survivors.length) fail('archive swap', 'stale after reload: ' + survivors.join(', '));
  else console.log(`  archive swap: all ${marked.length + 4} derived caches were dropped`);
} catch (e) { fail('archive swap', e); }

while (rafQueue.length) { const cb = rafQueue.shift(); try { cb(0); } catch (e) { fail('rAF callback', e); } }

console.log(`\n  ${galleries} galleries, ${cellsSeen} tiles, ${opened} resources opened in ${Date.now() - t0} ms`);
if (missingIds.size) console.log('  ids looked up but not in the markup: ' + [...missingIds].join(', '));
if (ctx.__alerts.length) console.log('  alert() calls: ' + ctx.__alerts.length);
console.log(failures ? `\nFAIL — ${failures} problem(s)` : '\nviewer smoke: clean');
process.exit(failures ? 1 : 0);
