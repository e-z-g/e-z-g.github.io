/* mac-resfork.js — reading a classic Mac resource fork.
 *
 * Needs mac-bytes.js. Load it first.
 *
 * A resource fork is a data area, a map, and a type list that indexes into
 * both. Every structural offset here is validated before it is followed, for
 * two reasons that both turned out to matter: a fork whose map is truncated or
 * garbage should say so rather than list invented resources, and callers use
 * "does this parse?" as a format sniff, so a parser that accepts anything makes
 * the sniff useless.
 *
 * openResourceFork(bytes) returns a fork object rather than setting globals, so
 * two forks can be open at once -- which is the point of putting it here.
 * cythera_data_viewer.html holds the Cythera Data *data* fork open as the game
 * archive and its *resource* fork at the same time; resource_fork_browser.html
 * keeps one at a time and wraps this in its own globals.
 */

const RESOURCE_ATTRS = [
  [0x40, 'system heap'], [0x20, 'purgeable'], [0x10, 'locked'],
  [0x08, 'protected'], [0x04, 'preload'], [0x02, 'changed']
];

function resourceAttrNames(a) {
  return RESOURCE_ATTRS.filter(([bit]) => a & bit).map(([, name]) => name);
}

function openResourceFork(bytes) {
  const inRange = (off, len, what) => {
    if (!(off >= 0) || off + len > bytes.length)
      throw new Error(`${what} runs past the end of the fork (offset ${off}, ${len} bytes, file is ${bytes.length})`);
  };
  if (bytes.length < 286) throw new Error('too small to be a resource fork (header + map need 286 bytes)');

  const dataOff = u32be(bytes, 0);
  const mapOff = u32be(bytes, 4);
  const dataLen = u32be(bytes, 8);
  const mapLen = u32be(bytes, 12);
  inRange(mapOff, 30, 'resource map');
  inRange(dataOff, 0, 'resource data area');

  const typeListOffRel = u16be(bytes, mapOff + 24);
  const nameListOffRel = u16be(bytes, mapOff + 26);
  const typeListAbs = mapOff + typeListOffRel;
  inRange(typeListAbs, 2, 'type list');
  const numTypes = u16be(bytes, typeListAbs) + 1;
  inRange(typeListAbs + 2, numTypes * 8, `type list (${numTypes} types)`);

  const typeList = [];
  let pos = typeListAbs + 2;
  for (let i = 0; i < numTypes; i++) {
    const rtype = String.fromCharCode(bytes[pos], bytes[pos+1], bytes[pos+2], bytes[pos+3]);
    typeList.push({ type: rtype, count: u16be(bytes, pos + 4) + 1, refListOff: u16be(bytes, pos + 6) });
    pos += 8;
  }

  const nameListAbs = mapOff + nameListOffRel;
  const resourcesByType = {};
  for (const t of typeList) {
    const refListAbs = typeListAbs + t.refListOff;
    inRange(refListAbs, t.count * 12, `reference list for '${t.type}'`);
    const list = [];
    let rp = refListAbs;
    for (let i = 0; i < t.count; i++) {
      // Resource IDs are signed; system resources use negative ones, and
      // reading them unsigned listed SIZE #-1 as #65535.
      const id = i16be(bytes, rp);
      const nameOffSigned = i16be(bytes, rp + 2);   // -1 when unnamed
      const attrsAndDataOff = u32be(bytes, rp + 4);
      const attrs = (attrsAndDataOff >>> 24) & 0xFF;
      const dataOffRel = attrsAndDataOff & 0xFFFFFF;
      let name = null;
      if (nameOffSigned !== -1) {
        const nAbs = nameListAbs + nameOffSigned;
        // A bad name offset should cost one name, not the whole fork.
        if (nAbs >= 0 && nAbs < bytes.length) {
          const nLen = Math.min(bytes[nAbs], bytes.length - nAbs - 1);
          name = decodeMacRoman(bytes.subarray(nAbs + 1, nAbs + 1 + nLen));
        }
      }
      list.push({ id, name, attrs, dataOffRel });
      rp += 12;
    }
    resourcesByType[t.type] = list;
  }

  // Slicing every resource of a type on every keystroke was the single biggest
  // cost in the browser's list render; a fork never changes while it is open,
  // so each payload is sliced once and kept.
  const cache = new Map();

  const fork = {
    bytes, dataOff, mapOff, dataLen, mapLen, typeList, resourcesByType,

    // Reading a length costs nothing; copying the bytes does. A list only needs
    // sizes, so it asks for this and never touches the payload.
    sizeOf(type, entry) {
      const abs = dataOff + entry.dataOffRel;
      if (abs + 4 > bytes.length)
        throw new Error(`data offset ${abs} is past the end of the fork (${bytes.length} bytes)`);
      const len = u32be(bytes, abs);
      // slice() clamps, so without this an overlong length silently yields a
      // short buffer and the decoders report a corrupt resource instead of a
      // corrupt map.
      if (abs + 4 + len > bytes.length)
        throw new Error(`declares ${len.toLocaleString()} bytes but only ${(bytes.length - abs - 4).toLocaleString()} remain in the fork`);
      return len;
    },

    dataOf(type, entry) {
      const key = type + '\u0000' + entry.id;   // NUL: type names can contain spaces
      const hit = cache.get(key);
      if (hit) return hit;
      const abs = dataOff + entry.dataOffRel;
      const d = bytes.slice(abs + 4, abs + 4 + fork.sizeOf(type, entry));
      cache.set(key, d);
      return d;
    },

    // Every resource, in type order, for a caller that wants to sweep the fork.
    all() {
      const out = [];
      for (const t of typeList) for (const e of resourcesByType[t.type]) out.push({ type: t.type, entry: e });
      return out;
    },

    total() {
      let n = 0;
      for (const k in resourcesByType) n += resourcesByType[k].length;
      return n;
    }
  };
  return fork;
}
