#!/usr/bin/env python3
r"""
Nodes of the model moved to a new layout, and the model's sparse points and dense cloud moved with them.

    python warp_model.py SPARSE_TXT DENSE_PLY MESH_DIR LAYOUT.json OUT_SPARSE_TXT OUT_PLY [--sigma 1.0] [--rot-from 2010=2009 ...]

For a model that has a stretch of nodes squeezed or bent (MAIS 8-29, 12 November 2026: the game's moves and the
player's account of the path put MAIS 12 1.6 node spacings farther from MAIS 8 than the model has it).
LAYOUT.json gives, per node, its new place in the viewer's frame of MESH_DIR (scene_mesh.py's: nodes.json's first
node at the origin, y up, one unit the node spacing) as [x, z] (its height kept) or [x, y, z]. Each listed node's six
images move by its offset, their turn kept; a listed node the model does not have, or whose pose is to be taken
from another node's turn (--rot-from NODE=OTHER), gets six images posed at its new place with OTHER's turn and no
points of its own. The sparse points (points3D.txt) and the dense cloud move by a smooth blend of the nodes'
offsets: each point by the Gaussian-weighted (--sigma spacings) mean of the offsets of every node of the model
(the unlisted ones with none), so a point near moved nodes moves with them and a point near nodes left alone stays.
Needs numpy, open3d.
"""
import argparse
import json
import os
import shutil
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from esrgan_dense_test import centre, read_model  # noqa: E402
from place_model import quat  # noqa: E402
from scene_mesh import face_rot, F  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('sparse'); ap.add_argument('dense'); ap.add_argument('mesh'); ap.add_argument('layout')
    ap.add_argument('out_sparse'); ap.add_argument('out_ply')
    ap.add_argument('--sigma', type=float, default=1.0, help='node spacings over which a node carries the points round it')
    ap.add_argument('--rot-from', nargs='*', default=[], help='NODE=OTHER: NODE posed new with OTHER\'s turn')
    a = ap.parse_args()
    import open3d as o3d
    cams, imgs = read_model(a.sparse)
    unit = json.load(open(os.path.join(a.mesh, 'scales.json')))['unit']
    views = json.load(open(os.path.join(a.mesh, 'views.json')))
    n0 = next(iter(json.load(open(os.path.join(a.mesh, 'nodes.json')))))
    face1 = {h[9].split('/')[1][3:-4]: centre(h) for h, _ in imgs.values() if h[9].startswith('f1/MA-')}
    C0, R10 = face1[n0]
    to_model = lambda v: C0 + R10.T @ F @ np.asarray(v, float) * unit
    layout = json.load(open(a.layout))
    rot_from = dict(x.split('=') for x in a.rot_from)
    new_c, offset = {}, {}
    for n, p in layout.items():
        if len(p) == 2:
            y = views[n]['pos'][1] if n in views else views[rot_from[n]]['pos'][1]
            p = [p[0], y, p[1]]
        new_c[n] = to_model(p)
        if n in face1 and n not in rot_from and n in views:
            offset[n] = new_c[n] - face1[n][0]
    # every node of the model that is in the mesh: its offset (none for those not listed), for the blend
    anchors = [(face1[n][0], offset.get(n, np.zeros(3))) for n in views if n in face1]
    A = np.array([c for c, _ in anchors]); D = np.array([d for _, d in anchors])
    sig = a.sigma * unit

    def warp(X):
        out = np.empty_like(X)
        for i in range(0, len(X), 50000):
            x = X[i:i + 50000]
            d2 = ((x[:, None, :] - A[None]) ** 2).sum(-1)
            w = np.exp(-(d2 - d2.min(1, keepdims=True)) / (2 * sig * sig))        # relative to the nearest node
            near = np.exp(-d2.min(1) / (2 * (3 * sig) ** 2))                     # far from every node: no move
            out[i:i + 50000] = x + (w @ D) / w.sum(1, keepdims=True) * near[:, None]
        return out

    by_name = {h[9]: i for i, (h, _) in imgs.items()}
    cam = next(h[8] for h, _ in imgs.values() if h[9].startswith('f1/'))
    next_id = max(imgs) + 1
    for n, C in new_c.items():
        R1 = face1[rot_from[n]][1] if n in rot_from else face1[n][1]
        posed_new = n in rot_from or n not in views
        for k in range(1, 7):
            name = f'f{k}/MA-{n}.jpg'; i = by_name.get(name)
            Rk = face_rot(k) @ F @ R1
            if i is None:
                i = next_id; next_id += 1
            pts = [] if posed_new or i not in imgs else imgs[i][1]
            head = [str(i)] + [f'{x:.12g}' for x in quat(Rk)] + [f'{x:.12g}' for x in -Rk @ C] + [imgs[i][0][8] if i in imgs else cam, name]
            imgs[i] = (head, pts)
        print(f'node {n}: ' + ('posed new' if posed_new else f'moved {np.linalg.norm(offset[n]) / unit:.2f} spacings'), flush=True)
    os.makedirs(a.out_sparse, exist_ok=True)
    shutil.copyfile(os.path.join(a.sparse, 'cameras.txt'), os.path.join(a.out_sparse, 'cameras.txt'))
    with open(os.path.join(a.out_sparse, 'images.txt'), 'w', newline='\n') as fh:
        fh.write('# images: warp_model.py\n')
        for i in sorted(imgs):
            h, pts = imgs[i]
            fh.write(' '.join(h) + '\n' + ' '.join(pts) + '\n')
    # the sparse points
    lines, P, rows = [], [], []
    for line in open(os.path.join(a.sparse, 'points3D.txt')):
        if line.startswith('#') or not line.strip():
            lines.append(line); rows.append(None); continue
        p = line.split(); rows.append(p); P.append([float(x) for x in p[1:4]]); lines.append(None)
    W = warp(np.array(P)); j = 0
    with open(os.path.join(a.out_sparse, 'points3D.txt'), 'w', newline='\n') as fh:
        for line, p in zip(lines, rows):
            if p is None:
                fh.write(line); continue
            p[1:4] = [f'{x:.9g}' for x in W[j]]; j += 1
            fh.write(' '.join(p) + '\n')
    moved = np.linalg.norm(W - np.array(P), axis=1) / unit
    print(f'{len(P)} sparse points; {np.mean(moved > 0.05) * 100:.1f}% moved over 0.05 spacings, the most {moved.max():.2f}', flush=True)
    pc = o3d.io.read_point_cloud(a.dense)
    X = np.asarray(pc.points).astype(np.float64)
    Y = warp(X)
    moved = np.linalg.norm(Y - X, axis=1) / unit
    pc.points = o3d.utility.Vector3dVector(Y)
    o3d.io.write_point_cloud(a.out_ply, pc)
    print(f'{len(X)} dense points; {np.mean(moved > 0.05) * 100:.1f}% moved over 0.05 spacings, the most {moved.max():.2f}')


if __name__ == '__main__':
    main()
