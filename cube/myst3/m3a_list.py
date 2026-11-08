#!/usr/bin/env python3
"""
List, and optionally extract, every resource in Myst III <ROOM>nodes.m3a archives,
not only the cube faces myst3_nodes.py takes.

    python m3a_list.py ARCHIVE.m3a [...]                 summary per type, and every
                                                          resource over --min-mb
    python m3a_list.py ARCHIVE.m3a --extract OUT_DIR [--types 8,72] [--min-mb 0]

Each archive entry is one node (or other numbered item) with resources by
"face" (sub-index) and type, read with myst3_nodes.read_directory. ScummVM's
Myst III engine (engines/myst3/archive.h) names the types: 0 cube face,
1-4 effect masks, 5 spot item, 6 frame, 7 raw data, 8 movie, 10 still movie,
11 text, 12 text metadata, 13 number metadata, 69 localized spot item,
70 localized frame, 72 multitrack movie, 74 dialog movie. The magic bytes are
shown so a movie can be told by its container ('BIK' is Bink).

Extracted files are named <ROOM>-<entry>-<sub>-t<type>.<ext>, ext from the magic.
Standard library only.
"""
import argparse
import os
import re
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from myst3_nodes import read_directory  # noqa: E402

NAMES = {0: 'cube face', 1: 'water mask', 2: 'lava mask', 3: 'magnetic mask', 4: 'shield mask',
         5: 'spot item', 6: 'frame', 7: 'raw data', 8: 'movie', 10: 'still movie', 11: 'text',
         12: 'text metadata', 13: 'number metadata', 69: 'localized spot item', 70: 'localized frame',
         72: 'multitrack movie', 74: 'dialog movie'}


def ext_for(magic):
    if magic[:3] == b'BIK' or magic[:3] == b'KB2':
        return 'bik'
    if magic[:3] == b'\xff\xd8\xff':
        return 'jpg'
    return 'bin'


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('archives', nargs='+')
    ap.add_argument('--extract'); ap.add_argument('--types')
    ap.add_argument('--min-mb', type=float, default=1.0)
    a = ap.parse_args()
    types = {int(t) for t in a.types.split(',')} if a.types else None
    for path in a.archives:
        room = re.match(r'([A-Za-z0-9]{4})nodes', os.path.basename(path), re.I).group(1).upper()
        entries = read_directory(path, room)
        per = defaultdict(lambda: [0, 0])
        big = []
        with open(path, 'rb') as f:
            for r, node, subs in entries:
                for sub, typ, off, size in subs:
                    per[typ][0] += 1; per[typ][1] += size
                    f.seek(off); magic = f.read(4)
                    if size >= a.min_mb * 1e6:
                        big.append((node, sub, typ, size, magic))
                    if a.extract and (types is None or typ in types) and size >= a.min_mb * 1e6:
                        os.makedirs(a.extract, exist_ok=True)
                        f.seek(off)
                        name = f'{room}-{node}-{sub}-t{typ}.{ext_for(magic)}'
                        with open(os.path.join(a.extract, name), 'wb') as o:
                            o.write(f.read(size))
        print(f'{os.path.basename(path)}: {len(entries)} entries')
        for typ, (n, s) in sorted(per.items()):
            print(f'  type {typ:3d} {NAMES.get(typ, "?"):20s} {n:5d} resources {s / 1e6:8.1f} MB')
        for node, sub, typ, size, magic in sorted(big, key=lambda b: -b[3]):
            print(f'    entry {node:6d} sub {sub:3d} type {typ:3d} {size / 1e6:7.2f} MB  magic {magic!r}')


if __name__ == '__main__':
    main()
