#!/usr/bin/env python3
"""
What a COLMAP run on a Myst III room did: which nodes each model holds, and how
well each linked node pair matched.

    python inspect_run.py WORK [TAG]      (WORK and -Tag as given to run_colmap.ps1)

Reads WORK/runs/TAG/database.db (verified matches per image pair, from
two_view_geometries) and the models in WORK/runs/TAG/sparse/<n>/, converted to text
with COLMAP's model_converter (COLMAP_BAT, or C:\\colmap\\4.2.1\\COLMAP.bat). Without
TAG it reads the first run's layout, WORK/database.db and WORK/sparse. Standard
library only.
"""
import collections
import json
import os
import re
import sqlite3
import subprocess
import sys


def pair_id_to_ids(pid):
    return pid // 2147483647, pid % 2147483647


def node_of(name):
    m = re.search(r'-(\d+)\.jpg$', name)
    return int(m.group(1))


def main():
    work = sys.argv[1]
    run = os.path.join(work, 'runs', sys.argv[2]) if len(sys.argv) > 2 else work
    db = sqlite3.connect(os.path.join(run, 'database.db'))
    names = dict(db.execute('select image_id, name from images'))
    inl = collections.Counter()
    for pid, rows in db.execute('select pair_id, rows from two_view_geometries'):
        a, b = pair_id_to_ids(pid)
        na, nb = node_of(names[a]), node_of(names[b])
        if na != nb:
            inl[(min(na, nb), max(na, nb))] += rows
    feats = dict(db.execute('select image_id, rows from keypoints'))
    per_node = collections.Counter()
    for i, n in feats.items():
        per_node[node_of(names[i])] += n

    nodes = json.load(open(os.path.join(work, 'nodes.json')))
    bat = os.environ.get('COLMAP_BAT', r'C:\colmap\4.2.1\COLMAP.bat')
    models = {}
    sparse = os.path.join(run, 'sparse')
    for m in sorted(os.listdir(sparse)):
        path = os.path.join(sparse, m)
        if not os.path.isdir(path):
            continue
        txt = os.path.join(run, 'sparse_txt', m)
        os.makedirs(txt, exist_ok=True)
        if not os.path.exists(os.path.join(txt, 'images.txt')) and os.path.exists(bat):
            subprocess.run([bat, 'model_converter', '--input_path', path, '--output_path', txt,
                            '--output_type', 'TXT'], capture_output=True)
        regs = set()
        with open(os.path.join(txt, 'images.txt')) as fh:
            lines = [l for l in fh if not l.startswith('#')]
        for l in lines[::2]:
            parts = l.split()
            if len(parts) >= 10:
                regs.add(node_of(parts[-1]))
        models[m] = sorted(regs)
    placed = {n for v in models.values() for n in v}
    for m, v in models.items():
        print(f'model {m}: {len(v)} nodes: {v}')
    print(f'not placed: {[n for n in nodes["nodes"] if n not in placed]}')
    print('\nfeatures per node (six faces):')
    print('  ' + '  '.join(f'{n}:{per_node[n]}' for n in nodes['nodes']))
    print('\nlinked pairs, verified matches summed over their 36 face pairs:')
    where = {n: m for m, v in models.items() for n in v}
    for a, b in nodes['links']:
        print(f'  {a:3d} - {b:3d}  {inl[(a, b)]:6d}   {where.get(a, "-")}/{where.get(b, "-")}')


if __name__ == '__main__':
    main()
