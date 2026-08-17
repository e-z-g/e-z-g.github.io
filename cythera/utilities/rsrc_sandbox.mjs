#!/usr/bin/env node
// Runs the JS out of resource_fork_browser.html inside a Node vm with just
// enough of a DOM for the decoders and the ZIP export to execute.
// Shared by rsrc_snapshot.mjs and zip_export_test.mjs.

import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import { collectPageScripts } from './page_scripts.mjs';

// ---- the smallest canvas the decoders actually use ------------------------
// Every path here is putImageData/fillRect/drawImage only, so a plain RGBA
// buffer is enough and the pixels stay hashable.
function makeCanvas(opts) {
  const cv = {
    width: 0, height: 0, style: {}, className: '', title: '', _px: null,
    getContext() {
      return {
        canvas: cv,
        imageSmoothingEnabled: true, fillStyle: '#000', globalAlpha: 1,
        createImageData: (w, h) => ({ width: w, height: h, data: new Uint8ClampedArray(w * h * 4) }),
        putImageData(im) { cv._px = im; cv.width = cv.width || im.width; cv.height = cv.height || im.height; },
        getImageData(x, y, w, h) {
          return cv._px || { width: w, height: h, data: new Uint8ClampedArray(w * h * 4) };
        },
        fillRect(x, y, w, h) {
          if (!cv._px) cv._px = { width: cv.width, height: cv.height, data: new Uint8ClampedArray(cv.width * cv.height * 4) };
          const m = /rgb\((\d+),(\d+),(\d+)\)/.exec(this.fillStyle) || [];
          const [r, g, b] = [+m[1] || 0, +m[2] || 0, +m[3] || 0];
          for (let yy = y; yy < y + h && yy < cv.height; yy++)
            for (let xx = x; xx < x + w && xx < cv.width; xx++) {
              const o = (yy * cv.width + xx) * 4;
              cv._px.data[o] = r; cv._px.data[o + 1] = g; cv._px.data[o + 2] = b; cv._px.data[o + 3] = 255;
            }
        },
        clearRect() {}, drawImage(src) { if (src && src._px) cv._px = src._px; },
      };
    },
    // Not a real PNG encoder: a deterministic stand-in so the ZIP writer gets
    // non-trivial bytes to checksum.
    toBlob(cb) {
      const px = cv._px ? cv._px.data : new Uint8ClampedArray(0);
      const bytes = new Uint8Array(16);
      for (let i = 0; i < px.length; i++) bytes[i % 16] = (bytes[i % 16] + px[i]) & 255;
      setTimeout(() => cb(new opts.Blob([bytes])), 0);
    },
    appendChild() {}, append() {},
  };
  return cv;
}

// Enough of an element for the render and preview code to run: children are
// tracked so a test can tell "drew something" from "silently drew nothing",
// and innerHTML='' really empties it the way the browser does.
function makeEl(tag, opts) {
  if (tag === 'canvas') return makeCanvas(opts);
  const el = {
    tagName: tag.toUpperCase(), style: {}, className: '', _text: '', children: [], _html: '',
    value: '', checked: false, files: [], colSpan: 0, tabIndex: 0, title: '', href: '', download: '',
    controls: false, src: '', options: [], onclick: null, onkeydown: null,
    set textContent(v) { this._text = String(v); this.children.length = 0; },
    get textContent() { return this._text; },
    set innerHTML(v) {
      this._html = String(v);
      this.children.length = 0;
      // The two call sites that build markup this way both create <td> cells,
      // and later index tr.children[n], so those have to exist.
      const cells = String(v).match(/<td\b/g);
      if (cells) for (let i = 0; i < cells.length; i++) this.children.push(makeEl('td', opts));
    },
    get innerHTML() { return this._html; },
    // Appending a fragment moves its children in and empties it, exactly as
    // the DOM does; treating it as one child made row counts read as 1.
    appendChild(c) {
      if (c && c.tagName === 'FRAGMENT') { this.children.push(...c.children); c.children.length = 0; }
      else this.children.push(c);
      return c;
    },
    append(...cs) { for (const c of cs) this.appendChild(c); },
    addEventListener() {}, setAttribute() {}, focus() {}, remove() {}, click() {},
    scrollIntoView() {}, blur() {},
    classList: { add() {}, remove() {}, contains: () => false, toggle() {} },
  };
  return el;
}

export function loadBrowserFile(htmlPath, opts = {}) {
  const html = readFileSync(htmlPath, 'utf8');
  // Every <script src> the page loads, then its inline block, in document
  // order -- the shared js/*.js modules are where the container decoders, the
  // ZIP writer and the WAV writer now live.
  const scripts = collectPageScripts(htmlPath).sources.map(s => s.code);
  if (!scripts.length) throw new Error('no <script> block found in ' + htmlPath);

  class StubBlob {
    constructor(parts = [], o = {}) {
      this.parts = parts; this.type = o.type || '';
      this._bytes = flatten(parts);
      this.size = this._bytes.length;
    }
    arrayBuffer() { return Promise.resolve(this._bytes.buffer.slice(this._bytes.byteOffset, this._bytes.byteOffset + this._bytes.length)); }
  }
  // Buffers built inside the vm come from the vm's own ArrayBuffer
  // constructor, so `instanceof ArrayBuffer` is false here. Duck-type instead:
  // getting this wrong silently produced zero-byte WAVs in the export test.
  function flatten(parts) {
    const chunks = [];
    for (const p of parts) {
      if (typeof p === 'string') chunks.push(new TextEncoder().encode(p));
      else if (p instanceof StubBlob) chunks.push(p._bytes);
      else if (p && p.buffer && typeof p.byteLength === 'number') chunks.push(new Uint8Array(p.buffer, p.byteOffset, p.byteLength));
      else if (p && typeof p.byteLength === 'number') chunks.push(new Uint8Array(p));
    }
    const total = chunks.reduce((a, c) => a + c.length, 0);
    const out = new Uint8Array(total);
    let o = 0;
    for (const c of chunks) { out.set(c, o); o += c.length; }
    return out;
  }

  const els = new Map();
  const downloads = [];
  const sandbox = {
    console,
    document: {
      createElement: t => makeEl(t, { Blob: StubBlob }),
      getElementById(id) {
        if (!els.has(id)) els.set(id, makeEl('div', { Blob: StubBlob }));
        return els.get(id);
      },
      createDocumentFragment: () => makeEl('fragment', { Blob: StubBlob }),
      querySelector: () => null,
      querySelectorAll: () => [],
      addEventListener() {},
      body: makeEl('body', { Blob: StubBlob }),
      fonts: { add() {} },
    },
    matchMedia: () => ({ matches: false, addEventListener() {}, addListener() {} }),
    addEventListener() {},
    location: { hash: '' },
    history: { replaceState() {} },
    Blob: StubBlob,
    URL: { createObjectURL: () => 'blob:stub', revokeObjectURL() {} },
    FontFace: class { load() { return Promise.reject(new Error('stub')); } },
    FileReader: class { readAsArrayBuffer() {} },
    TextDecoder, TextEncoder, setTimeout, clearTimeout, setInterval: () => 0, clearInterval() {},
    requestAnimationFrame: () => 0, cancelAnimationFrame() {},
    IntersectionObserver: class { observe() {} unobserve() {} disconnect() {} },
    Promise, Date, Math, JSON, performance,
  };
  // `window` must be the sandbox object itself: the file assigns window.foo and
  // reads bare `foo`, so two distinct objects would silently diverge.
  sandbox.window = sandbox;
  sandbox.globalThis = sandbox;
  vm.createContext(sandbox);
  for (const src of scripts) vm.runInContext(src, sandbox, { filename: htmlPath });

  // Top-level const/let live in the context's lexical scope, not on the global
  // object, so they can only be reached through an eval defined in that scope.
  vm.runInContext('window.__peek = n => eval(n);', sandbox);
  const peek = n => sandbox.__peek(n);

  // Intercept saves so a test can inspect what would have been downloaded, and
  // keep the file list the ZIP writer was handed -- a test wants to look at the
  // individual payloads, not just the archive they ended up in.
  vm.runInContext(`window.dlBlob = (blob, name) => { window.__downloads.push({blob, name}); };`, sandbox);
  vm.runInContext(`(function(){ const inner = buildZip; buildZip = files => { window.__lastZipFiles = files; return inner(files); }; })();`, sandbox);
  sandbox.__downloads = downloads;

  return { sandbox, peek, downloads, StubBlob, els };
}
