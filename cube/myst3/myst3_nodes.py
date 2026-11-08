#!/usr/bin/env python3
"""
Myst III: Exile — extract every node's cube faces, named by node, and map
how the nodes connect.

    python myst3_nodes.py "C:\\GOG Games\\Myst 3" out

Needs only Python 3.8+ (no extra packages). Writes, under the output folder:

    faces/<ROOM>/<ROOM>-<node>-f<face>.jpg   every cube face, byte for byte
                                             as shipped (the game stores
                                             JPEG, so nothing is re-encoded)
    faces_index.csv                          room, node, face, archive,
                                             running number (over every
                                             resource; not Riveal's), size
    maps/<ROOM>.json                         the room's nodes and links
    maps/<ROOM>.svg                          a rough top-down sketch of them
    maps/index.html                          all the sketches on one page

The faces come straight out of the game's <ROOM>nodes.m3a archives. Their
index is decoded the way ScummVM's Myst III engine does it
(engines/myst3/archive.cpp): an XOR-obfuscated table of entries, one per
node, each listing its resources by face number and type. Faces 1-6 of
type "cube face" are a node's six views. In the files we already have
they run front, bottom, back, right, left, top.

The links come from ScummVM's myst3.dat — its copy of the game's node
scripts (engines/myst3/database.cpp). It is downloaded from ScummVM's
GitHub the first time, or pass --dat to use a local copy. Every movement
hotspot records the heading it sits at in its node. All nodes share one
world orientation (checked on Voltaic: a walk A->B and its walk back
B->A differ by 180 deg +/- 4 deg, median over 186 pairs), so a heading is
the compass bearing from one node to the next.

The sketch map places nodes by those bearings, taking every walking step
as the same length. Real steps vary, so treat it as a diagram of what is
next to what and roughly which way, not a survey. "Zip" links (jumps to a
distant point you can see) are drawn dashed and left out of the layout.
"""

import argparse, csv, json, math, os, re, struct, sys, urllib.request
from collections import defaultdict

DAT_URL = 'https://raw.githubusercontent.com/scummvm/scummvm/master/dists/engine-data/myst3.dat'
CUBE_FACE = 0
FACE_NAMES = {1: 'front', 2: 'bottom', 3: 'back', 4: 'right', 5: 'left', 6: 'top'}  # as observed, not from the engine


# ── .m3a archives ─────────────────────────────────────────────────────────

def decrypt_header(data):
    """The directory, decrypted (archive.cpp, Archive::decryptHeader)."""
    add_key, mult_key = 0x3C6EF35F, 0x0019660D
    size = struct.unpack_from('<I', data, 0)[0]
    words = size ^ add_key if size > 1000000 else size
    out = bytearray()
    key = 0
    for i in range(words):
        w = struct.unpack_from('<I', data, i * 4)[0]
        if size > 1000000:
            key = (key + add_key) & 0xFFFFFFFF
            w ^= key
            key = (key * mult_key) & 0xFFFFFFFF
        out += struct.pack('<I', w)
    return bytes(out)


def read_directory(path, room=None):
    """[(room, node, [(face, type, offset, size), ...]), ...] in archive order.
    A <ROOM>nodes.m3a holds one room and its entries carry no room name."""
    with open(path, 'rb') as f:
        head = f.read(4)
        size = struct.unpack('<I', head)[0]
        words = size ^ 0x3C6EF35F if size > 1000000 else size
        f.seek(0)
        hdr = decrypt_header(f.read(words * 4))
    p = 4  # first word: the directory size
    entries = []
    while p + 4 < len(hdr):
        if room is None:
            r = hdr[p:p + 4].decode('ascii', 'replace'); p += 4
        else:
            r = room
        index = hdr[p] | hdr[p + 1] << 8 | hdr[p + 2] << 16; p += 3
        count = hdr[p]; p += 1
        subs = []
        for _ in range(count):
            offset, length, meta = struct.unpack_from('<IIH', hdr, p); p += 10
            face, typ = hdr[p], hdr[p + 1]; p += 2
            p += 4 * meta
            subs.append((face, typ, offset, length))
        entries.append((r, index, subs))
    return entries


def extract_faces(game_dir, out_dir):
    rows = []
    archives = []
    for root, _, files in os.walk(game_dir):
        for name in files:
            m = re.fullmatch(r'([A-Za-z0-9]{4})nodes\.m3a', name, re.I)
            if m:
                archives.append((m.group(1).upper(), os.path.join(root, name)))
    if not archives:
        sys.exit(f'No <ROOM>nodes.m3a archives under {game_dir!r}. Point this at the installed game folder.')
    for room, path in sorted(archives):
        entries = read_directory(path, room)
        seq = 0
        with open(path, 'rb') as f:
            for r, node, subs in entries:
                for face, typ, offset, length in subs:
                    seq += 1   # running number over every resource, in archive order
                    if typ != CUBE_FACE or not 1 <= face <= 6:
                        continue
                    f.seek(offset)
                    data = f.read(length)
                    rel = os.path.join('faces', room, f'{room}-{node:04d}-f{face}.jpg')
                    os.makedirs(os.path.join(out_dir, 'faces', room), exist_ok=True)
                    with open(os.path.join(out_dir, rel), 'wb') as o:
                        o.write(data)
                    rows.append({'room': room, 'node': node, 'face': face, 'direction': FACE_NAMES[face],
                                 'archive': os.path.basename(path), 'running_number': seq,
                                 'bytes': length, 'jpeg': data[:3] == b'\xff\xd8\xff', 'file': rel})
        print(f'{room}: {len({(r["node"]) for r in rows if r["room"] == room})} nodes from {os.path.basename(path)}')
    with open(os.path.join(out_dir, 'faces_index.csv'), 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader(); w.writerows(rows)
    bad = [r for r in rows if not r['jpeg']]
    if bad:
        print(f'Warning: {len(bad)} faces do not start like a JPEG — see faces_index.csv')
    return sorted({r['room'] for r in rows})


# ── myst3.dat node scripts ─────────────────────────────────────────────────

NAV = {136: 'walk', 137: 'walk', 138: 'walk', 164: 'walk',
       139: 'walk-room', 165: 'walk-room', 140: 'zip', 141: 'zip-room',
       151: 'movie', 152: 'movie', 166: 'age'}


class Reader:
    def __init__(self, b): self.b, self.p = b, 0
    def u16(self): v = struct.unpack_from('<H', self.b, self.p)[0]; self.p += 2; return v
    def s16(self): v = struct.unpack_from('<h', self.b, self.p)[0]; self.p += 2; return v
    def u32(self): v = struct.unpack_from('<I', self.b, self.p)[0]; self.p += 4; return v
    def eos(self): return self.p >= len(self.b)


def opcodes(r):
    out = []
    while not r.eos():
        code = r.u16()
        op, n = code & 0xFF, code >> 8
        if op == 0 and n == 0:
            break
        out.append((op, [r.s16() for _ in range(n)]))
    return out


def cond_scripts(r):
    while not r.eos():
        if r.u16() == 0:
            break
        opcodes(r)


def hotspots(r):
    out = []
    while not r.eos():
        cond = r.s16()
        if cond == 0:
            break
        rects = []
        if cond != -1:
            while True:
                pitch, heading, w, h = r.u16(), r.u16(), r.s16(), r.s16()
                rects.append((pitch if pitch < 32768 else pitch - 65536, heading))
                if w >= 0 or r.eos():
                    break
            r.u16()  # cursor
        out.append((rects, opcodes(r)))
    return out


def room_hotspots(blob):
    r = Reader(blob)
    nodes = defaultdict(list)
    while not r.eos():
        nid = r.s16()
        if nid == 0:
            break
        if nid > 0:
            ids = [nid]
        elif nid == -10:
            ids = []
            while True:
                x = r.s16()
                if x == 0:
                    break
                ids += list(range(-x, r.u16() + 1)) if x < 0 else [x]
        else:
            ids = [r.u16() for _ in range(-nid)]
        cond_scripts(r)
        hs = hotspots(r)
        for i in ids:
            nodes[i] += hs
    return nodes


def load_dat(path):
    b = open(path, 'rb').read()
    if b[:4] != b'TSYM':
        sys.exit(f'{path!r} is not ScummVM\'s myst3.dat')
    r = Reader(b); r.p = 8
    indexes = []
    for _ in range(7):
        entries = []
        for _ in range(r.u32()):
            name = b[r.p:r.p + 4].decode('ascii', 'replace'); r.p += 5
            entries.append((name, r.u32(), r.u32(), r.u32()))
        indexes.append(entries)
    for _ in range(2):            # sound-name tables: a count, then 36 bytes each
        n = r.u32()               # (read first: 'r.p += r.u32() * 36' would add to the old r.p)
        r.p += n * 36
    start = r.p
    return {name: b[start + off:start + off + size]
            for name, typ, off, size in indexes[0] if typ == 0}   # the PC/Mac node scripts


def bearing(h):
    a = math.radians(h)
    return math.sin(a), math.cos(a)   # x east-ish, y north-ish; heading clockwise


def sketch(nodes, walks):
    """Positions from bearings, every walking step one unit long."""
    adj = defaultdict(list)
    for (a, b), h in walks.items():
        ux, uy = bearing(h)
        adj[a].append((b, ux, uy))
        adj[b].append((a, -ux, -uy))
    pos, comps = {}, []
    for start in sorted(nodes):
        if start in pos or start not in adj:
            continue
        comp = [start]; pos[start] = (0.0, 0.0); queue = [start]
        while queue:
            a = queue.pop(0)
            for b, ux, uy in adj[a]:
                if b not in pos:
                    pos[b] = (pos[a][0] + ux, pos[a][1] + uy); comp.append(b); queue.append(b)
        for _ in range(500):          # settle loops: each node to the mean its links imply
            for a in comp[1:]:
                xs = [(pos[b][0] - ux, pos[b][1] - uy) for b, ux, uy in adj[a] if b in pos]
                pos[a] = (sum(x for x, _ in xs) / len(xs), sum(y for _, y in xs) / len(xs))
        comps.append(comp)
    return pos, comps


def svg(room, nodes, walks, zips, pos, comps):
    # Lay components side by side.
    placed, x0 = {}, 0.0
    for comp in sorted(comps, key=len, reverse=True):
        xs = [pos[n][0] for n in comp]; ys = [pos[n][1] for n in comp]
        for n in comp:
            placed[n] = (pos[n][0] - min(xs) + x0, max(ys) - pos[n][1])
        x0 += max(xs) - min(xs) + 3
    singles = [n for n in sorted(nodes) if n not in placed]
    k, pad = 60, 40
    if placed:
        W = max(x for x, _ in placed.values()) * k + 2 * pad
        H = max(y for _, y in placed.values()) * k + 2 * pad
    else:
        W, H = 400, 60
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W:.0f}" height="{H + 40:.0f}" '
           f'font-family="sans-serif" font-size="11"><rect width="100%" height="100%" fill="#fff"/>',
           f'<text x="8" y="16" font-size="14" font-weight="bold">{room}</text>']
    P = lambda n: (placed[n][0] * k + pad, placed[n][1] * k + pad + 10)
    for a, b in zips:
        if a in placed and b in placed:
            (x1, y1), (x2, y2) = P(a), P(b)
            out.append(f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="#c77" stroke-dasharray="4 3"/>')
    for a, b in walks:
        if a in placed and b in placed:
            (x1, y1), (x2, y2) = P(a), P(b)
            out.append(f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="#333"/>')
    for n in placed:
        x, y = P(n)
        out.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="9" fill="#fff" stroke="#333"/>'
                   f'<text x="{x:.1f}" y="{y + 4:.1f}" text-anchor="middle">{n}</text>')
    if singles:
        out.append(f'<text x="8" y="{H + 30:.0f}" fill="#666">Not reached by walking (close-ups and the like): '
                   f'{", ".join(map(str, singles))}</text>')
    out.append('</svg>')
    return '\n'.join(out)


def map_rooms(dat_path, rooms, out_dir):
    scripts = load_dat(dat_path)
    os.makedirs(os.path.join(out_dir, 'maps'), exist_ok=True)
    pages = []
    for room in rooms:
        if room not in scripts:
            print(f'{room}: no node scripts in myst3.dat, skipped')
            continue
        hs = room_hotspots(scripts[room])
        nodes = sorted(n for n in hs if n < 32000)
        links, heads = [], defaultdict(list)
        zips = set()
        for n in nodes:
            for rects, ops in hs[n]:
                for op, args in ops:
                    if op not in NAV or not args:
                        continue
                    for pitch, heading in rects or [(None, None)]:
                        links.append({'from': n, 'kind': NAV[op], 'opcode': op, 'args': args,
                                      'heading': heading, 'pitch': pitch})
                        if NAV[op] == 'walk' and heading is not None and args[0] in hs:
                            heads[(n, args[0])].append(heading)
                        if NAV[op] == 'zip' and args[0] in hs:
                            zips.add((n, args[0]))
        # One bearing per walked pair: both directions folded together.
        walks = {}
        for (a, b), hh in heads.items():
            if (a, b) in walks or (b, a) in walks:
                continue
            h = sorted(hh)[len(hh) // 2]
            if (b, a) in heads:
                back = sorted(heads[(b, a)])[len(heads[(b, a)]) // 2]
                d = (back - 180 - h + 540) % 360 - 180
                if abs(d) > 45:      # not opposite: a ladder or a turn-around, not a straight walk
                    continue
                h = (h + d / 2) % 360
            walks[(a, b)] = h
        pos, comps = sketch(nodes, walks)
        json.dump({'room': room, 'nodes': nodes, 'links': links,
                   'walk_bearings': [{'from': a, 'to': b, 'heading': h} for (a, b), h in walks.items()],
                   'sketch_positions': {n: pos[n] for n in pos},
                   'walk_connected_groups': sorted(comps, key=len, reverse=True)},
                  open(os.path.join(out_dir, 'maps', f'{room}.json'), 'w'), indent=1)
        with open(os.path.join(out_dir, 'maps', f'{room}.svg'), 'w') as f:
            f.write(svg(room, nodes, list(walks), zips, pos, comps))
        pages.append(room)
        print(f'{room}: {len(nodes)} nodes, {len(walks)} walking links, groups {[len(c) for c in sorted(comps, key=len, reverse=True)]}')
    with open(os.path.join(out_dir, 'maps', 'index.html'), 'w') as f:
        f.write('<!doctype html><meta charset="utf-8"><title>Myst III node maps</title>'
                '<body style="font-family:sans-serif">' +
                ''.join(f'<p><img src="{r}.svg" style="max-width:100%"></p>' for r in pages))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('game_dir', nargs='?', help='installed Myst III folder (holds the *nodes.m3a files)')
    ap.add_argument('out_dir', help='where to write faces/ and maps/')
    ap.add_argument('--dat', help="path to ScummVM's myst3.dat (downloaded if not given)")
    ap.add_argument('--maps-only', metavar='ROOMS', help='skip extraction; map these rooms, e.g. ENSI,ENCH')
    a = ap.parse_args()
    os.makedirs(a.out_dir, exist_ok=True)
    if a.maps_only:
        rooms = [r.strip().upper() for r in a.maps_only.split(',')]
    else:
        if not a.game_dir:
            ap.error('give the game folder, or --maps-only')
        rooms = extract_faces(a.game_dir, a.out_dir)
    dat = a.dat or os.path.join(a.out_dir, 'myst3.dat')
    if not os.path.exists(dat):
        print('Downloading myst3.dat from ScummVM ...')
        urllib.request.urlretrieve(DAT_URL, dat)
    map_rooms(dat, rooms, a.out_dir)
    print(f'Done. Open {os.path.join(a.out_dir, "maps", "index.html")} to see the maps.')


if __name__ == '__main__':
    main()
