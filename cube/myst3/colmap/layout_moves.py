#!/usr/bin/env python3
r"""
A layout of nodes (warp_model.py's LAYOUT.json) as apply_moves.py's moves: each node's new centre and a depth scale,
so that a dense workspace can be fused again with the nodes moved and their depth maps stretched with them.

    python layout_moves.py SPARSE_TXT MESH_DIR LAYOUT.json PAIRS.json OUT.json [--new 2010 2011] [--height-from 2010=2009 ...]

SPARSE_TXT is the dense workspace's sparse model as text; MESH_DIR a scene_mesh.py output (views.json, nodes.json,
scales.json) for the viewer frame LAYOUT.json is given in ([x, z], the height kept, or [x, y, z]). PAIRS.json lists
the walks between nodes ([["2008", "2009"], ...]). A node's depth scale is how much the layout stretches its walks:
the sum of their lengths in the layout over the sum in the model (a node not in the layout keeps its place). --new
nodes are ones the model has in the wrong place: their walks are not measured, their scale is the mean of their
neighbours', and their height (when the layout gives none) is --height-from's node's. Writes {"nodes": {"MA-2012":
{"new": [...], "depth_scale": k, "shift": s, ...}}} for apply_moves.py --nodes. Needs numpy.
"""
import argparse
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from esrgan_dense_test import centre, read_model  # noqa: E402
from scene_mesh import F  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('sparse'); ap.add_argument('mesh'); ap.add_argument('layout'); ap.add_argument('pairs'); ap.add_argument('out')
    ap.add_argument('--new', nargs='*', default=[])
    ap.add_argument('--height-from', nargs='*', default=[])
    a = ap.parse_args()
    _, imgs = read_model(a.sparse)
    unit = json.load(open(os.path.join(a.mesh, 'scales.json')))['unit']
    views = json.load(open(os.path.join(a.mesh, 'views.json')))
    n0 = next(iter(json.load(open(os.path.join(a.mesh, 'nodes.json')))))
    face1 = {h[9].split('/')[1][3:-4]: centre(h) for h, _ in imgs.values() if h[9].startswith('f1/MA-')}
    C0, R10 = face1[n0]
    hf = dict(x.split('=') for x in a.height_from)
    old = {n: c for n, (c, _) in face1.items()}
    new = dict(old)
    for n, p in json.load(open(a.layout)).items():
        if len(p) == 2:
            y = views[n]['pos'][1] if n in views and n not in a.new else views[hf[n]]['pos'][1]
            p = [p[0], y, p[1]]
        new[n] = C0 + R10.T @ F @ np.asarray(p, float) * unit
    layout = [n for n in json.load(open(a.layout))]
    pairs = [tuple(p) for p in json.load(open(a.pairs))]
    scale = {}
    for n in layout:
        if n in a.new:
            continue
        ps = [p for p in pairs if n in p and not set(p) & set(a.new) and all(m in old for m in p)]
        if ps:
            scale[n] = sum(np.linalg.norm(new[p[0]] - new[p[1]]) for p in ps) / sum(np.linalg.norm(old[p[0]] - old[p[1]]) for p in ps)
    for n in a.new:
        nb = [m for p in pairs if n in p for m in p if m != n and m in scale]
        scale[n] = float(np.mean([scale[m] for m in nb])) if nb else 1.0
    out = {}
    for n in layout:
        if n not in old:
            print(f'node {n}: not in the model, left out'); continue
        s = scale.get(n, 1.0)
        out['MA-' + n] = {'new': new[n].tolist(), 'depth_scale': s, 'shift': float(np.linalg.norm(new[n] - old[n]) / unit),
                          'agree_old': 0, 'agree_new': 0, 'spread': 0}
        print(f'node {n}: moved {out["MA-" + n]["shift"]:.2f} spacings, depth x{s:.3f}' + (' (new)' if n in a.new else ''))
    json.dump({'nodes': out}, open(a.out, 'w'), indent=1)


if __name__ == '__main__':
    main()
