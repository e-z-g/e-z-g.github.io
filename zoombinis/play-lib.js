/*
  play-lib.js - what play.html needs to turn archive.org's copy of the game
  into a js-dos bundle in the browser. A classic script (it defines
  window.ZoombiniPlay) that also loads under Node, where the zoombinis
  extraction project checks it against its own tools.

  - unpack: the Zomb's Lair installer on archive.org is a 7-Zip archive
    behind a Windows stub, with every path base64-encoded UTF-16; 7-Zip
    compiled to WebAssembly (7z-wasm, from jsDelivr) pulls out just its Game
    folder in a worker, reading the download in place rather than copying it.
  - readIso: the files on the game's CD image (ISO 9660), so the mod can
    change two of them and js-dos mount the folder as drive D.
  - patchArchive / patchExe: the mod, as tools/make_web_patch.py writes it,
    applied the way tools/mohawk_write.py does - the resource rebuilt with a
    literal-only LZ stream, appended, and its file-table entry repointed - so
    the result is byte for byte the archive the Python tools make.
  - zipBundle: a stored (uncompressed) zip for js-dos, with an entry for
    every folder: js-dos's unzip makes only a file's own folder, and a folder
    holding nothing but folders otherwise stops the bundle loading.
*/
(function (root) {
  'use strict';

  // ---- Mohawk archives ----------------------------------------------------

  const be16 = (b, o) => (b[o] << 8) | b[o + 1];
  const be32 = (b, o) => ((b[o] << 24) >>> 0) + (b[o + 1] << 16) + (b[o + 2] << 8) + b[o + 3];

  function mhk(b) {
    const tag = s => String.fromCharCode(...b.subarray(s, s + 4));
    if (tag(0) !== 'MHWK' || tag(8) !== 'RSRC') throw new Error('not a Mohawk archive');
    const absOff = be32(b, 20), ftOff = be16(b, 24);
    const typeCount = be16(b, absOff + 2);
    const table = absOff + ftOff + 4;               // file table entries, 10 bytes each
    const res = {};
    for (let t = 0; t < typeCount; t++) {
      const o = absOff + 4 + 8 * t;
      const rt = absOff + be16(b, o + 4);
      const n = be16(b, rt);
      const list = res[tag(o)] = [];
      for (let k = 0; k < n; k++) list.push({ id: be16(b, rt + 2 + 4 * k), index: be16(b, rt + 4 + 4 * k) });
    }
    const entry = index => table + 10 * (index - 1);
    const find = (t, id) => {
      const r = (res[t] || []).find(r => r.id === id);
      if (!r) throw new Error(`no ${t} ${id}`);
      return r;
    };
    return {
      entry, find,
      get(t, id) {
        const e = entry(find(t, id).index);
        const off = be32(b, e), size = be16(b, e + 4) + (b[e + 6] << 16);
        return b.subarray(off, off + size);
      },
    };
  }

  // MohawkBitmap::decompressLZ (ScummVM), as tools/mohawk_bmp.py ports it.
  function decompressLz(src, size) {
    const LEN_BITS = 6, MIN_STRING = 3, POS_BITS = 16 - LEN_BITS;
    const MAX_STRING = (1 << LEN_BITS) + MIN_STRING - 1, BUF = 1 << POS_BITS, MASK = BUF - 1;
    const out = new Uint8Array(Math.max(size, BUF) + MAX_STRING + BUF);
    let dst = 0, buf = 0, flags = 0, bytesOut = 0, insert = 0, p = 0;
    const n = src.length;
    while (p < n) {
      flags >>>= 1;
      if (!(flags & 0x100)) { if (p >= n) break; flags = src[p++] | 0xff00; }
      if (flags & 1) {
        if (++bytesOut > size) break;
        out[dst++] = src[p++];
        if (++insert > MASK) { insert = 0; buf += BUF; }
      } else {
        if (p + 2 > n) break;
        const offLen = (src[p] << 8) | src[p + 1]; p += 2;
        let len = (offLen >> POS_BITS) + MIN_STRING;
        let pos = (offLen + MAX_STRING) & MASK;
        bytesOut += len;
        if (bytesOut > size) len -= bytesOut - size;
        let from = buf + pos;
        if (pos > insert) {
          if (bytesOut >= BUF) from -= BUF;
          else if (pos + len > MASK) {
            for (let k = 0; k < len; k++) {
              out[dst++] = out[from++];
              if (++pos > MASK) { pos = 0; from = 0; }
            }
            insert = (insert + len) & MASK;
            if (bytesOut >= size) break;
            continue;
          }
        }
        insert += len;
        if (insert > MASK) { insert &= MASK; buf += BUF; }
        for (let k = 0; k < len; k++) out[dst++] = out[from++];
        if (bytesOut >= size) break;
      }
    }
    return out.subarray(0, size);
  }

  // A compound tBMP's sub-images (each with its own 8-byte header).
  function subimages(tbmp) {
    const count = be16(tbmp, 0) & 0x3fff, fmt = be16(tbmp, 6);
    if ((fmt & 0x0f00) !== 0x0100 || (fmt & 0x0008)) throw new Error('expected an LZ-packed compound tBMP');
    const usize = be32(tbmp, 8), csize = be32(tbmp, 12);
    const payload = decompressLz(tbmp.subarray(18, 18 + csize), usize);
    const offs = [];
    for (let k = 0; k < count; k++) offs.push(be32(payload, 4 * k));
    return offs.map((o, k) => payload.subarray(o - 8, (k + 1 < count ? offs[k + 1] : payload.length + 8) - 8));
  }

  // tools/mohawk_write.py compound(): the template's outer header, and the
  // frames behind a literal-only LZ stream (a 0xff flags byte per 8 bytes).
  function compound(template, frames) {
    const count = frames.length;
    let size = 4 * count;
    for (const f of frames) size += f.length;
    const payload = new Uint8Array(size);
    const dv = new DataView(payload.buffer);
    let o = 4 * count;
    frames.forEach((f, k) => { dv.setUint32(4 * k, o + 8); payload.set(f, o); o += f.length; });
    const body = new Uint8Array(size + Math.ceil(size / 8));
    let q = 0;
    for (let i = 0; i < size; i += 8) { body[q++] = 0xff; const c = payload.subarray(i, i + 8); body.set(c, q); q += c.length; }
    const out = new Uint8Array(18 + q);
    const ov = new DataView(out.buffer);
    ov.setUint16(0, count); out.set(template.subarray(2, 8), 2);
    ov.setUint32(8, size); ov.setUint32(12, q); ov.setUint16(16, 1024);
    out.set(body.subarray(0, q), 18);
    return out;
  }

  const b64 = s => typeof atob === 'function'
    ? Uint8Array.from(atob(s), c => c.charCodeAt(0))
    : new Uint8Array(Buffer.from(s, 'base64'));

  // The archive with each patched resource rebuilt and appended, in order.
  function patchArchive(bytes, resources) {
    const a = mhk(bytes);
    const built = resources.map(r => {
      const old = a.get(r.tag, r.id);
      if (r.tag === 'tBMP') {
        const frames = subimages(old);
        for (const [k, v] of Object.entries(r.frames)) frames[+k] = b64(v);
        return compound(old, frames);
      }
      if (r.tag === 'REGS') {
        const out = old.slice();
        const dv = new DataView(out.buffer);
        for (const [k, v] of Object.entries(r.values)) dv.setInt16(2 + 2 * +k, v);
        return out;
      }
      throw new Error('cannot patch ' + r.tag);
    });
    const total = bytes.length + built.reduce((n, x) => n + x.length, 0);
    const out = new Uint8Array(total);
    out.set(bytes);
    const dv = new DataView(out.buffer);
    let end = bytes.length;
    resources.forEach((r, k) => {
      const e = a.entry(a.find(r.tag, r.id).index), data = built[k];
      dv.setUint32(e, end); dv.setUint16(e + 4, data.length & 0xffff); out[e + 6] = data.length >>> 16;
      out.set(data, end); end += data.length;
    });
    dv.setUint32(4, total - 8);                      // MHWK chunk size
    dv.setUint32(16, total);                         // RSRC file size
    return out;
  }

  function patchExe(bytes, changes) {
    const out = bytes.slice();
    for (const [k, v] of Object.entries(changes)) out[+k] = v;
    return out;
  }

  // ---- the CD image ---------------------------------------------------------

  // Every file and folder on an ISO 9660 image: [{path, data}] (data null for
  // a folder), paths as DOS sees them - version suffix and trailing dot gone.
  function readIso(iso) {
    const S = 2048, le32 = o => iso[o] | (iso[o + 1] << 8) | (iso[o + 2] << 16) | ((iso[o + 3] << 24) >>> 0);
    const pvd = 16 * S;
    if (iso[pvd] !== 1 || String.fromCharCode(...iso.subarray(pvd + 1, pvd + 6)) !== 'CD001') throw new Error('not an ISO 9660 image');
    const out = [];
    const walk = (lba, len, prefix) => {
      for (let p = lba * S, end = lba * S + len; p < end;) {
        const n = iso[p];
        if (!n) { p = (Math.floor(p / S) + 1) * S; continue; }
        const at = le32(p + 2), size = le32(p + 10), dir = iso[p + 25] & 2, nl = iso[p + 32];
        const raw = iso.subarray(p + 33, p + 33 + nl);
        p += n;
        if (nl === 1 && raw[0] < 2) continue;         // "." and ".."
        const name = String.fromCharCode(...raw).replace(/;\d+$/, '').replace(/\.$/, '');
        const path = prefix + name;
        if (dir) { out.push({ path, data: null }); walk(at, size, path + '/'); }
        else out.push({ path, data: iso.subarray(at * S, at * S + size) });
      }
    };
    walk(le32(pvd + 156 + 2), le32(pvd + 156 + 10), '');
    return out;
  }

  // ---- the js-dos bundle ----------------------------------------------------

  const CRC = (() => {
    const t = new Uint32Array(256);
    for (let n = 0; n < 256; n++) { let c = n; for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1; t[n] = c >>> 0; }
    return t;
  })();
  function crc32(b) {
    let c = 0xffffffff;
    for (let i = 0; i < b.length; i++) c = CRC[(c ^ b[i]) & 0xff] ^ (c >>> 8);
    return (c ^ 0xffffffff) >>> 0;
  }

  // A stored zip of [{path, data}] (data null: a folder), as an array of
  // parts for a Blob. Every folder gets an entry, parents first.
  function zipBundle(files) {
    const enc = new TextEncoder();
    const folders = new Set();
    for (const f of files) {
      const parts = f.path.split('/');
      for (let k = 1; k < parts.length + (f.data === null ? 1 : 0); k++) folders.add(parts.slice(0, k).join('/'));
    }
    const entries = [...[...folders].sort().map(p => ({ path: p + '/', data: null })),
                     ...files.filter(f => f.data !== null)];
    const parts = [], central = [];
    let offset = 0;
    for (const e of entries) {
      const name = enc.encode(e.path), data = e.data || new Uint8Array(0), crc = e.data ? crc32(data) : 0;
      const h = new Uint8Array(30 + name.length), dv = new DataView(h.buffer);
      dv.setUint32(0, 0x04034b50, true); dv.setUint16(4, 20, true);
      dv.setUint32(14, crc, true); dv.setUint32(18, data.length, true); dv.setUint32(22, data.length, true);
      dv.setUint16(26, name.length, true); h.set(name, 30);
      const c = new Uint8Array(46 + name.length), cv = new DataView(c.buffer);
      cv.setUint32(0, 0x02014b50, true); cv.setUint16(4, 20, true); cv.setUint16(6, 20, true);
      cv.setUint32(16, crc, true); cv.setUint32(20, data.length, true); cv.setUint32(24, data.length, true);
      cv.setUint16(28, name.length, true); cv.setUint32(38, e.data ? 0 : 0x10, true); cv.setUint32(42, offset, true);
      c.set(name, 46);
      parts.push(h, data); central.push(c);
      offset += h.length + data.length;
    }
    const cdSize = central.reduce((n, c) => n + c.length, 0);
    const end = new Uint8Array(22), ev = new DataView(end.buffer);
    ev.setUint32(0, 0x06054b50, true); ev.setUint16(8, entries.length, true); ev.setUint16(10, entries.length, true);
    ev.setUint32(12, cdSize, true); ev.setUint32(16, offset, true);
    return [...parts, ...central, end];
  }

  // ---- the installer --------------------------------------------------------

  const SEVENZIP = 'https://cdn.jsdelivr.net/npm/7z-wasm@1.2.0/';
  // "Game" in the installer's base64 UTF-16 path components.
  const GAME = 'RwBhAG0AZQA=';

  // Each path component is base64 UTF-16, except the installer's marker for
  // an empty folder, a last component of plain "empty.empty".
  const decodeName = n => n.split('\\').map(p => {
    if (p === 'empty.empty') return p;
    const bin = typeof atob === 'function' ? atob(p) : Buffer.from(p, 'base64').toString('binary');
    let s = '';
    for (let i = 0; i + 1 < bin.length; i += 2) s += String.fromCharCode(bin.charCodeAt(i) | (bin.charCodeAt(i + 1) << 8));
    return s;
  }).join('/');

  // In a worker: 7-Zip reads the installer (a Blob) in place through WORKERFS
  // and writes the Game folder's files, which come back transferred.
  const WORKER = `
    importScripts('${SEVENZIP}7zz.umd.js');
    onmessage = async e => {
      try {
        const log = [];
        const sz = await SevenZip({ locateFile: f => '${SEVENZIP}' + f, print: s => log.push(s), printErr: s => log.push(s) });
        sz.FS.mkdir('/in'); sz.FS.mount(sz.WORKERFS, { blobs: [{ name: 'setup.exe', data: e.data }] }, '/in');
        sz.FS.mkdir('/out');
        sz.callMain(['x', '/in/setup.exe', '-o/out', '-y', '-bso0', '-bsp0', '${GAME}*']);
        const files = [];
        for (const name of sz.FS.readdir('/out')) {
          if (name === '.' || name === '..') continue;
          const data = sz.FS.readFile('/out/' + name);
          files.push({ name, data });
          sz.FS.unlink('/out/' + name);
        }
        postMessage({ files, log }, files.map(f => f.data.buffer));
      } catch (err) { postMessage({ error: String(err && err.message || err) }); }
    };`;

  // {path: data} for the installer's Game folder (paths like HDD/WINDOWS/..;
  // data null for an empty folder).
  function unpack(installer) {
    return new Promise((resolve, reject) => {
      const url = URL.createObjectURL(new Blob([WORKER], { type: 'text/javascript' }));
      const w = new Worker(url);
      w.onmessage = e => {
        w.terminate(); URL.revokeObjectURL(url);
        if (e.data.error) return reject(new Error(e.data.error));
        const out = {};
        for (const f of e.data.files) {
          const path = decodeName(f.name);
          if (!path.startsWith('Game/')) continue;
          if (path.endsWith('/empty.empty')) out[path.slice(5, -12)] = null;   // an empty folder
          else out[path.slice(5)] = f.data;
        }
        if (!out['Disc/Zoombini.iso']) return reject(new Error('the installer had no Game/Disc/Zoombini.iso: ' + e.data.log.slice(-3).join(' ')));
        resolve(out);
      };
      w.onerror = e => { w.terminate(); reject(new Error(e.message || 'the unpacking worker failed')); };
      w.postMessage(installer);
    });
  }

  const CONF = mountD => `[sdl]
autolock=false
fullscreen=false
[dosbox]
machine=svga_s3
memsize=16
[cpu]
core=auto
cputype=pentium_slow
cycles=max
[mixer]
rate=44100
[midi]
mpu401=intelligent
[sblaster]
sbtype=sb16
sbbase=220
irq=7
dma=1
hdma=5
[dos]
xms=true
ems=false
umb=true
[autoexec]
${mountD}
mount c hdd
c:
call windows.bat
exit
`;

  // The js-dos bundle (zip parts) from the installer's Game folder: stock,
  // with the CD image mounted as it is, or with `patch` applied - the CD's
  // files then go in as a folder, two archives and the EXE rebuilt.
  function bundle(game, patch) {
    const enc = new TextEncoder();
    const files = [];
    for (const [path, data] of Object.entries(game)) {
      if (!path.startsWith('HDD/')) continue;
      let d = data;
      if (patch && path.slice(4).toUpperCase() === patch.exe.path.toUpperCase()) d = patchExe(data, patch.exe.bytes);
      files.push({ path: 'hdd/' + path.slice(4), data: d });
    }
    let mount;
    if (!patch) {
      files.push({ path: 'zoombini.iso', data: game['Disc/Zoombini.iso'] });
      mount = 'imgmount d zoombini.iso -t iso';
    } else {
      for (const f of readIso(game['Disc/Zoombini.iso'])) {
        const name = f.path.split('/').pop().toUpperCase();
        const resources = f.path.toUpperCase().startsWith('DATA/') && patch.archives[name];
        files.push({ path: 'cd/' + f.path, data: resources ? patchArchive(f.data, resources) : f.data });
      }
      mount = 'mount d cd -t cdrom -label ZOOMBINI';
    }
    files.push({ path: '.jsdos/dosbox.conf', data: enc.encode(CONF(mount)) });
    return zipBundle(files);
  }

  const api = { mhk, decompressLz, subimages, compound, patchArchive, patchExe, readIso, crc32, zipBundle, decodeName, unpack, bundle };
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.ZoombiniPlay = api;
})(typeof window !== 'undefined' ? window : globalThis);
