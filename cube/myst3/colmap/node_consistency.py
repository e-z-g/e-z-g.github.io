#!/usr/bin/env python3
"""
Which nodes of a model disagree with their neighbours: a misplaced node's
depth maps put a second copy of what it sees beside the first in a fused
cloud (a ghost of a tower's top beside the tower in the 131-node Amateria
model, absent from COLMAP's own 62-node model).

    python node_consistency.py DENSE SPARSE_TXT [--neighbours 5] [--samples 3000] [--tol 0.1]

For every node, points from its faces' geometric depth maps (DENSE as
run_dense.ps1 leaves it) are projected into the faces of its --neighbours
nearest nodes, and wherever a neighbour has a depth there the two distances
along the neighbour's ray are compared. A point counts as agreeing when the
neighbour's depth is within --tol of the projected one, and as contradicted
when the neighbour sees something more than --tol farther (it sees past where
the point should be, which a correct point cannot allow; nearer is an
occluder and says nothing). Prints the nodes most contradicted first. Needs
numpy, Pillow; depth_fill.py and model_backdrop.py beside it.
"""
import argparse
import os
import re

import numpy as np

from depth_fill import read_colmap_array
from model_backdrop import read_poses


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('dense'); ap.add_argument('sparse_txt')
    ap.add_argument('--neighbours', type=int, default=5)
    ap.add_argument('--samples', type=int, default=3000)
    ap.add_argument('--tol', type=float, default=0.1)
    ap.add_argument('--names', help="prepare_age.py's nodes.json, for ROOM:node labels")
    a = ap.parse_args()
    poses = read_poses(a.sparse_txt)
    node_of = {}
    for name in poses:
        m = re.fullmatch(r'f(\d)/(.*)\.jpg', name)
        if m:
            node_of.setdefault(m.group(2), {})[int(m.group(1))] = name
    centres = {n: -poses[f[1]][0].T @ poses[f[1]][1] for n, f in node_of.items() if 1 in f}
    labels = {}
    if a.names:
        import json
        rooms = json.load(open(a.names)).get('rooms', {})
        labels = {n: rooms.get(n.split('-')[-1], n) for n in centres}
    depth = {}

    def dmap(name):
        if name not in depth:
            p = os.path.join(a.dense, 'stereo', 'depth_maps', name + '.geometric.bin')
            depth[name] = read_colmap_array(p) if os.path.exists(p) else None
        return depth[name]

    rng = np.random.default_rng(0)
    rows = []
    for n, faces in node_of.items():
        if n not in centres:
            continue
        near = sorted((m for m in centres if m != n), key=lambda m: np.linalg.norm(centres[m] - centres[n]))[:a.neighbours]
        pts = []
        for k, name in faces.items():
            z = dmap(name)
            if z is None:
                continue
            H, W = z.shape
            v, u = np.nonzero(z > 0)
            if not len(v):
                continue
            i = rng.choice(len(v), min(a.samples, len(v)), replace=False)
            v, u, zz = v[i], u[i], z[v[i], u[i]]
            Xc = np.stack([(u + 0.5 - W / 2) / (W / 2) * zz, (v + 0.5 - H / 2) / (H / 2) * zz, zz], 1)
            R, t = poses[name]
            pts.append((Xc - t) @ R)
        if not pts:
            continue
        X = np.concatenate(pts)
        agree = contra = 0
        for m in near:
            for k, name in node_of[m].items():
                z = dmap(name)
                if z is None:
                    continue
                H, W = z.shape
                R, t = poses[name]
                Y = X @ R.T + t
                ok = Y[:, 2] > 1e-6
                x = Y[:, 0] / np.where(ok, Y[:, 2], 1); y = Y[:, 1] / np.where(ok, Y[:, 2], 1)
                ok &= (np.abs(x) < 1) & (np.abs(y) < 1)
                px = np.clip(((x + 1) * W / 2).astype(int), 0, W - 1); py = np.clip(((y + 1) * H / 2).astype(int), 0, H - 1)
                zn = np.where(ok, z[py, px], 0)
                has = ok & (zn > 0)
                rel = (zn[has] - Y[has, 2]) / Y[has, 2]
                agree += int((np.abs(rel) <= a.tol).sum()); contra += int((rel > a.tol).sum())
        tot = agree + contra
        if tot:
            rows.append((contra / tot, agree, contra, n, np.linalg.norm(centres[near[0]] - centres[n])))
    rows.sort(reverse=True)
    print('node  contradicted  agreeing  (checked against its %d nearest)' % a.neighbours)
    for share, ag, co, n, dn in rows[:25]:
        print(f'{labels.get(n, n):>10} {n:>10}  {share * 100:5.1f}%  {ag:7d} agree  {co:7d} seen past  nearest node {dn:.2f}')
    med = np.median([r[0] for r in rows])
    print(f'median contradicted share over {len(rows)} nodes: {med * 100:.1f}%')


if __name__ == '__main__':
    main()
