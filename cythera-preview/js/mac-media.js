/* mac-media.js — turning decoded pixels and samples back into files a modern
 * machine understands.
 *
 * Needs mac-bytes.js (crc32). Load it first.
 *
 * WAV
 *   Two entry points, because the two callers hold their audio differently:
 *   the Delver sound decoder produces an Int16Array of frames, while the
 *   classic `snd ` decoder hands back the raw sample bytes still in whatever
 *   width and channel count the resource declared. Both were separately
 *   implemented as "samplesToWav", with the same name and incompatible
 *   arguments, in two files.
 *
 * PNG
 *   canvas.toBlob() writes a truecolour PNG and, depending on the engine,
 *   decorates it with an iCCP colour profile and sometimes an eXIf block. Both
 *   are actively harmful here: the profile makes a downstream tool colour-manage
 *   pixels that are already exactly the values wanted, and neither chunk carries
 *   the one thing that matters, which is the palette. So indexed art is written
 *   by hand as colour-type-3 with PLTE and, where there is a transparent slot,
 *   tRNS -- and nothing else, so a decoder reproduces the CLUT byte for byte.
 */

/* ---- WAV --------------------------------------------------------------- */
function wavHeader(dataSize, rate, bits, channels) {
  const buffer = new ArrayBuffer(44 + dataSize);
  const view = new DataView(buffer);
  const bytesPerFrame = channels * bits / 8;
  const ws = (off, str) => { for (let i = 0; i < str.length; i++) view.setUint8(off + i, str.charCodeAt(i)); };
  ws(0, 'RIFF'); view.setUint32(4, 36 + dataSize, true); ws(8, 'WAVE');
  ws(12, 'fmt '); view.setUint32(16, 16, true); view.setUint16(20, 1, true);
  view.setUint16(22, channels, true); view.setUint32(24, rate, true);
  view.setUint32(28, rate * bytesPerFrame, true);
  view.setUint16(32, bytesPerFrame, true);
  view.setUint16(34, bits, true);
  ws(36, 'data'); view.setUint32(40, dataSize, true);
  return { buffer, view };
}

/* Signed 16-bit frames, one channel. Returns bytes so a caller can put them
 * straight into a zip entry without unwrapping a Blob again. */
function wavFromInt16(samples, rate) {
  const { buffer, view } = wavHeader(samples.length * 2, rate, 16, 1);
  let off = 44;
  for (let i = 0; i < samples.length; i++) { view.setInt16(off, samples[i], true); off += 2; }
  return new Uint8Array(buffer);
}

/* Raw big-endian PCM bytes, as they came out of a `snd ` resource. */
function wavFromPcmBytes(bytes, rate, bits, channels) {
  const bytesPerFrame = channels * bits / 8;
  const dataSize = bytes.length - (bytes.length % bytesPerFrame || 0);
  const { buffer, view } = wavHeader(dataSize, rate, bits, channels);
  if (bits === 8) {
    for (let i = 0; i < dataSize; i++) view.setUint8(44 + i, bytes[i]);
  } else {
    // Big-endian in the resource, little-endian in the file.
    for (let i = 0; i + 1 < dataSize; i += 2) view.setInt16(44 + i, (bytes[i] << 24 >> 16) | bytes[i + 1], true);
  }
  return new Uint8Array(buffer);
}

/* ---- PNG --------------------------------------------------------------- */
function pngAdler32(bytes) {
  let a = 1, b = 0;
  for (let i = 0; i < bytes.length; i++) {
    a = (a + bytes[i]) % 65521;
    b = (b + a) % 65521;
  }
  return ((b << 16) | a) >>> 0;
}

function pngChunk(type, data) {
  const out = new Uint8Array(12 + data.length);
  const dv = new DataView(out.buffer);
  dv.setUint32(0, data.length);
  for (let i = 0; i < 4; i++) out[4 + i] = type.charCodeAt(i);
  out.set(data, 8);
  dv.setUint32(8 + data.length, crc32(out.subarray(4, 8 + data.length)));
  return out;
}

/* A zlib stream of stored (uncompressed) deflate blocks. Correct everywhere,
 * and the fallback when CompressionStream is missing. */
function zlibStored(data) {
  const blocks = Math.max(1, Math.ceil(data.length / 65535));
  const out = new Uint8Array(2 + blocks * 5 + data.length + 4);
  let p = 0;
  out[p++] = 0x78; out[p++] = 0x01;
  for (let i = 0; i < blocks; i++) {
    const off = i * 65535;
    const len = Math.min(65535, data.length - off);
    out[p++] = (i === blocks - 1) ? 1 : 0;
    out[p++] = len & 0xFF; out[p++] = (len >> 8) & 0xFF;
    out[p++] = (~len) & 0xFF; out[p++] = ((~len) >> 8) & 0xFF;
    out.set(data.subarray(off, off + len), p); p += len;
  }
  new DataView(out.buffer).setUint32(p, pngAdler32(data));
  return out;
}

async function zlibDeflate(data) {
  if (typeof CompressionStream === 'undefined') return zlibStored(data);
  try {
    const cs = new CompressionStream('deflate');
    const w = cs.writable.getWriter();
    w.write(data); w.close();
    return new Uint8Array(await new Response(cs.readable).arrayBuffer());
  } catch (e) {
    return zlibStored(data);
  }
}

/* image: one palette index per pixel, row-major, W*H entries.
 * palette: array of [r,g,b].
 * transparentIndex: the slot to make fully transparent, or null. */
async function encodeIndexedPNG(W, H, image, palette, transparentIndex) {
  const pal = palette || [];
  const n = Math.max(1, Math.min(256, pal.length));
  // One filter byte (0 = None) per scanline, then the raw indices. None is the
  // right filter for indexed art: the byte values are palette slots, so the
  // differencing filters would only add noise for deflate to chew through.
  const raw = new Uint8Array(H * (W + 1));
  let p = 0;
  for (let y = 0; y < H; y++) {
    raw[p++] = 0;
    for (let x = 0; x < W; x++) {
      const v = image[y * W + x];
      raw[p++] = (v >= 0 && v < n) ? v : 0;
    }
  }
  const ihdr = new Uint8Array(13);
  const dv = new DataView(ihdr.buffer);
  dv.setUint32(0, W); dv.setUint32(4, H);
  ihdr[8] = 8;    // bit depth
  ihdr[9] = 3;    // colour type 3 = indexed
  ihdr[10] = 0; ihdr[11] = 0; ihdr[12] = 0;   // deflate / adaptive filter / no interlace
  const plte = new Uint8Array(n * 3);
  for (let i = 0; i < n; i++) {
    const c = pal[i] || [0, 0, 0];
    plte[i * 3] = c[0] & 0xFF; plte[i * 3 + 1] = c[1] & 0xFF; plte[i * 3 + 2] = c[2] & 0xFF;
  }
  const parts = [
    new Uint8Array([0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A]),
    pngChunk('IHDR', ihdr),
    pngChunk('PLTE', plte)
  ];
  // tRNS for colour type 3 is a run of alpha values starting at index 0, and it
  // may stop early -- everything past its end is opaque. The usual case here is
  // a single zero byte.
  if (transparentIndex !== null && transparentIndex !== undefined && transparentIndex >= 0) {
    const trns = new Uint8Array(transparentIndex + 1).fill(255);
    trns[transparentIndex] = 0;
    parts.push(pngChunk('tRNS', trns));
  }
  parts.push(pngChunk('IDAT', await zlibDeflate(raw)));
  parts.push(pngChunk('IEND', new Uint8Array(0)));
  let total = 0; for (const q of parts) total += q.length;
  const out = new Uint8Array(total);
  let o = 0; for (const q of parts) { out.set(q, o); o += q.length; }
  return out;
}

/* For the truecolour path, where the pixels only exist on a canvas: keep the
 * critical chunks and throw away everything the browser decorated them with. */
const _PNG_KEEP = new Set(['IHDR', 'PLTE', 'tRNS', 'IDAT', 'IEND']);
function stripPngMetadata(bytes) {
  const sig = [0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A];
  for (let i = 0; i < 8; i++) if (bytes[i] !== sig[i]) return bytes;
  const parts = [bytes.subarray(0, 8)];
  let p = 8;
  while (p + 8 <= bytes.length) {
    const len = u32be(bytes, p);
    const type = String.fromCharCode(bytes[p + 4], bytes[p + 5], bytes[p + 6], bytes[p + 7]);
    const end = p + 12 + len;
    if (end > bytes.length) break;
    if (_PNG_KEEP.has(type)) parts.push(bytes.subarray(p, end));
    p = end;
    if (type === 'IEND') break;
  }
  let total = 0; for (const q of parts) total += q.length;
  const out = new Uint8Array(total);
  let o = 0; for (const q of parts) { out.set(q, o); o += q.length; }
  return out;
}
