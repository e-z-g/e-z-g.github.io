#!/usr/bin/env python3
r"""
place_nodes.py's nodes written into a copy of the model, so scene_mesh.py and scene_attrs.py take them as any other.

    python place_model.py SPARSE_TXT MESH_DIR PLACED.json OUT_SPARSE_TXT [--nodes 1001 2011 ...]

SPARSE_TXT is the model as text (cameras.txt, images.txt, points3D.txt); MESH_DIR the scene place_nodes.py placed
the nodes in (its nodes.json, whose first node is the viewer's origin, and scales.json's unit); PLACED.json
place_nodes.py's OUT (each node's position and turn in the viewer's frame). Writes OUT_SPARSE_TXT: the same
model with each placed node (all of PLACED.json's, or --nodes) as six images, MA-<node>.jpg in f1 to f6, posed
from its place (face k turned from face 1 as moge_depth.py's faces are) and with no points of their own, so
scene_mesh.py scales its MoGe distances by the dense cloud alone. A node the model already has (misplaced) has its
six images replaced, ids kept; their points' tracks in points3D.txt are left as they were (scene_mesh.py and
scene_attrs.py read only the points' positions). Needs numpy.
"""
import argparse
import json
import os
import shutil
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from esrgan_dense_test import centre, read_model  # noqa: E402
from scene_mesh import face_rot, F  # noqa: E402


def quat(R):
    """Rotation matrix to COLMAP's (qw, qx, qy, qz)."""
    t = np.trace(R)
    if t > 0:
        s = np.sqrt(t + 1) * 2; w = s / 4; x = (R[2, 1] - R[1, 2]) / s; y = (R[0, 2] - R[2, 0]) / s; z = (R[1, 0] - R[0, 1]) / s
    else:
        i = int(np.argmax(np.diag(R)))
        if i == 0:
            s = np.sqrt(1 + R[0, 0] - R[1, 1] - R[2, 2]) * 2; w = (R[2, 1] - R[1, 2]) / s; x = s / 4; y = (R[0, 1] + R[1, 0]) / s; z = (R[0, 2] + R[2, 0]) / s
        elif i == 1:
            s = np.sqrt(1 + R[1, 1] - R[0, 0] - R[2, 2]) * 2; w = (R[0, 2] - R[2, 0]) / s; x = (R[0, 1] + R[1, 0]) / s; y = s / 4; z = (R[1, 2] + R[2, 1]) / s
        else:
            s = np.sqrt(1 + R[2, 2] - R[0, 0] - R[1, 1]) * 2; w = (R[1, 0] - R[0, 1]) / s; x = (R[0, 2] + R[2, 0]) / s; y = (R[1, 2] + R[2, 1]) / s; z = s / 4
    q = np.array([w, x, y, z]); return q / np.linalg.norm(q) * (1 if w >= 0 else -1)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('sparse'); ap.add_argument('mesh'); ap.add_argument('placed'); ap.add_argument('out')
    ap.add_argument('--nodes', nargs='*')
    a = ap.parse_args()
    cams, imgs = read_model(a.sparse)
    placed = json.load(open(a.placed))
    todo = a.nodes or list(placed)
    unit = json.load(open(os.path.join(a.mesh, 'scales.json')))['unit']
    n0 = next(iter(json.load(open(os.path.join(a.mesh, 'nodes.json')))))
    face1 = {h[9].split('/')[1][3:-4]: centre(h) for h, _ in imgs.values() if h[9].startswith('f1/MA-')}
    C0, R10 = face1[n0]
    cam = next(h[8] for h, _ in imgs.values() if h[9].startswith('f1/'))
    by_name = {h[9]: i for i, (h, _) in imgs.items()}
    next_id = max(imgs) + 1
    for n in todo:
        p = placed[n]
        rot, pos = np.array(p['rot']), np.array(p['pos'])
        R1 = F @ rot @ F @ R10                                 # views.json's rot is F R1[n] R1[n0]^T F
        C = C0 + R10.T @ F @ pos * unit                        # and pos F R1[n0] (C[n] - C[n0]) / unit
        for k in range(1, 7):
            Rk = face_rot(k) @ F @ R1                          # as the model's own faces are (face_rot(1) F is 1)
            q = quat(Rk); t = -Rk @ C
            name = f'f{k}/MA-{n}.jpg'
            i = by_name.get(name)
            if i is None:
                i = next_id; next_id += 1
            head = [str(i)] + [f'{x:.12g}' for x in q] + [f'{x:.12g}' for x in t] + [imgs[i][0][8] if i in imgs else cam, name]
            imgs[i] = (head, [])
        print(f'node {n}: placed from {p.get("from")}, '
              f'{"replacing the model's pose" if f"f1/MA-{n}.jpg" in by_name else "new"}', flush=True)
    os.makedirs(a.out, exist_ok=True)
    for f in ('cameras.txt', 'points3D.txt'):
        shutil.copyfile(os.path.join(a.sparse, f), os.path.join(a.out, f))
    with open(os.path.join(a.out, 'images.txt'), 'w', newline='\n') as fh:
        fh.write('# images: place_model.py\n')
        for i in sorted(imgs):
            h, pts = imgs[i]
            fh.write(' '.join(h) + '\n' + ' '.join(pts) + '\n')
    # check: every placed node's face 1 back as the views.json it came from
    _, back = read_model(a.out)
    f1 = {h[9].split('/')[1][3:-4]: centre(h) for h, _ in back.values() if h[9].startswith('f1/MA-')}
    for n in todo:
        C, R1 = f1[n]
        e = np.linalg.norm(F @ R10 @ (C - C0) / unit - np.array(placed[n]['pos'])) + np.abs(F @ R1 @ R10.T @ F - np.array(placed[n]['rot'])).max()
        assert e < 1e-6, (n, e)
    print(f'{len(todo)} nodes written to {a.out}')


if __name__ == '__main__':
    main()
