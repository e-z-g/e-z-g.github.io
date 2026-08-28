/* mac-export.js — handing files to the browser.
 *
 * Needs mac-bytes.js (crc32, safeFileName). Load it first.
 *
 * Both pages grew a bulk "save everything as .zip", and each wrote its own
 * store-only ZIP writer with the same field layout, its own download helper,
 * and its own version of the Firefox workaround below.
 */

/* Store-only, method 0. Deflate would need a compressor, the point is getting
 * a whole fork or gallery out in one click, and PNG/WAV payloads barely
 * compress anyway. The CRC-32 is the one in mac-bytes.js, checked against the
 * standard vectors by utilities/zip_export_test.mjs and then against `unzip -t`
 * on a real archive -- a hand-written central directory is exactly the sort of
 * thing that looks fine and unpacks to nothing. */
function zipDosStamp(d) {
  return {
    time: ((d.getHours() << 11) | (d.getMinutes() << 5) | (d.getSeconds() >> 1)) & 0xFFFF,
    // Before 1980 is unrepresentable in a DOS timestamp, and a clock that is
    // badly wrong should not produce an archive that fails to open.
    date: (((Math.max(1980, d.getFullYear()) - 1980) << 9) | ((d.getMonth() + 1) << 5) | d.getDate()) & 0xFFFF
  };
}

/* files: [{ name, bytes }] -> Blob */
function buildZip(files) {
  const enc = new TextEncoder();
  const stamp = zipDosStamp(new Date());
  const parts = [], centrals = [];
  let offset = 0, centralSize = 0;
  for (const f of files) {
    const name = enc.encode(f.name);
    const crc = crc32(f.bytes);
    const size = f.bytes.length;

    const lh = new Uint8Array(30 + name.length);
    const lv = new DataView(lh.buffer);
    lv.setUint32(0, 0x04034b50, true);
    lv.setUint16(4, 20, true);
    lv.setUint16(6, 0x0800, true);          // names are UTF-8
    lv.setUint16(8, 0, true);               // method 0 = stored
    lv.setUint16(10, stamp.time, true); lv.setUint16(12, stamp.date, true);
    lv.setUint32(14, crc, true);
    lv.setUint32(18, size, true);
    lv.setUint32(22, size, true);
    lv.setUint16(26, name.length, true);
    lh.set(name, 30);
    parts.push(lh, f.bytes);

    const cd = new Uint8Array(46 + name.length);
    const cv = new DataView(cd.buffer);
    cv.setUint32(0, 0x02014b50, true);
    cv.setUint16(4, 20, true); cv.setUint16(6, 20, true);
    cv.setUint16(8, 0x0800, true); cv.setUint16(10, 0, true);
    cv.setUint16(12, stamp.time, true); cv.setUint16(14, stamp.date, true);
    cv.setUint32(16, crc, true);
    cv.setUint32(20, size, true);
    cv.setUint32(24, size, true);
    cv.setUint16(28, name.length, true);
    cv.setUint32(42, offset, true);
    cd.set(name, 46);
    centrals.push(cd);

    offset += lh.length + size;
    centralSize += cd.length;
  }
  const eocd = new Uint8Array(22);
  const ev = new DataView(eocd.buffer);
  ev.setUint32(0, 0x06054b50, true);
  ev.setUint16(8, files.length, true);
  ev.setUint16(10, files.length, true);
  ev.setUint32(12, centralSize, true);
  ev.setUint32(16, offset, true);
  return new Blob(parts.concat(centrals, [eocd]), { type: 'application/zip' });
}

/* Every save in both pages goes through here. Revoking the object URL in the
 * same tick as .click() cancels the download in Firefox, which is the kind of
 * bug that only shows up on someone else's machine. */
function dlBlob(blob, filename) {
  const href = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = href;
  a.download = filename;
  a.rel = 'noopener';
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(href), 8000);
}

function downloadBlob(bytes, filename) {
  dlBlob(new Blob([bytes], { type: 'application/octet-stream' }), filename);
}
