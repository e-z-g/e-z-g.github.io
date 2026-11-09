#!/usr/bin/env python3
"""
Depths for a walk between nodes that describe one scene: where two nodes see
the same surface, both are brought to the same place, and the water is one
flat plane for all of them.

    python walk_joint.py IMAGES SPARSE_TXT OUT_DIR --node 4084 DEPTH_DIR R_FAR_JSON
        --node 4089 DEPTH_DIR R_FAR_JSON [--masks MASKS] [--gate 0.25] [--rounds 3]
        [--water-percentile 20] [--blur 6]

Each node's depth (node_depth.py's encoding, DEPTH_DIR/MA-<node>-<k>
_measured-depth.png) is made from that node's picture alone, and two nodes'
depths disagree about the same surfaces: for MASS 84 and 89, by a median 4-6%
on the walls and 19% on the floor, and the water, which a depth network puts
at the depth of what it reflects, lands far behind where the other node has
it. Drawn as two meshes, the walk then shows two scenes a little apart, and
any change from one node's picture to the other's shows as a fade.

  - Water: pixels under the masks (MASKS/f<k>/MA-<node>.jpg.png, white where
    solid) that are not sky. Its level is a low percentile (--water-percentile)
    of the heights of the solid pixels just beside it below the horizon (where
    piers and shores meet it), over all the nodes, and each water pixel's ray
    is cut at that plane (at the node's r_far beyond).
  - Shared surfaces: each round, every node's points are drawn into every
    other node's faces (nearest wins); where a pixel's own distance and the
    other node's differ by less than --gate (more is taken to be a different
    surface, one in front of the other), the log of their ratio is a
    correction toward their mean. The corrections are spread with a Gaussian
    of --blur px over where they were found (so one surface moves as one) and
    applied. After a few rounds the nodes agree where they overlap.

Writes OUT_DIR/<node>/MA-<node>-<k>_measured-depth.png and walk_joint.json
(r_far, as before, and how well the nodes agree before and after), for
walk_scene.py. The site's panoramas are not changed. Needs numpy, Pillow,
opencv-python; view_check.py beside it.
"""
import argparse
import json
import os
import sys

import cv2
import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from view_check import read_model  # noqa: E402

RATIO = 20.0


def load(images, imgs, node, ddir, js, masks):
    r_far = json.load(open(js))['r_far']
    faces = {}
    C = None
    for k in range(1, 7):
        R, t = imgs[f'f{k}/MA-{node}.jpg'][:2]
        if C is None:
            C = -R.T @ t
        N = Image.open(os.path.join(images, f'f{k}', f'MA-{node}.jpg')).size[0]
        d8 = np.asarray(Image.open(os.path.join(ddir, f'MA-{node}-{k}_measured-depth.png')).convert('L')
                        .resize((N, N), Image.NEAREST)).astype(float)
        u = (np.arange(N) + .5) / N * 2 - 1
        xx, yy = np.meshgrid(u, u)
        dirs = np.stack([xx, yy, np.ones_like(xx)], -1) @ R
        dirs /= np.linalg.norm(dirs, axis=-1, keepdims=True)
        sky = d8 == 0
        water = np.zeros((N, N), bool)
        if masks:
            mp = os.path.join(masks, f'f{k}', f'MA-{node}.jpg.png')
            if os.path.exists(mp):
                water = (np.asarray(Image.open(mp).convert('L').resize((N, N), Image.NEAREST)) <= 127) & ~sky
        r = np.where(sky, np.nan, r_far / (1 + (RATIO - 1) * d8 / 255))
        faces[k] = dict(R=R, t=t, N=N, dirs=dirs, r=r, sky=sky, water=water)
    return dict(node=node, C=C, r_far=r_far, faces=faces)


def project(src, dst_face):
    """src's points (all faces, water included) drawn into one face of another
    node: the nearest distance from that face's node, per pixel (inf where none)."""
    N, R, t = dst_face['N'], dst_face['R'], dst_face['t']
    zb = np.full((N, N), np.inf)
    for f in src['faces'].values():
        ok = np.isfinite(f['r'])
        P = src['C'] + f['dirs'][ok] * f['r'][ok, None]
        Y = P @ R.T + t
        m = Y[:, 2] > 1e-3
        Y = Y[m]
        x = (Y[:, 0] / Y[:, 2] + 1) * N / 2; y = (Y[:, 1] / Y[:, 2] + 1) * N / 2
        m = (x >= 0) & (x < N) & (y >= 0) & (y < N)
        np.minimum.at(zb, (y[m].astype(int), x[m].astype(int)), np.linalg.norm(Y[m], axis=1))
    # close the pinholes the points leave where the face sees them larger than their own
    filled = -cv2.dilate(-np.where(np.isfinite(zb), zb, 1e9).astype(np.float32), np.ones((3, 3), np.uint8))
    return np.where(np.isfinite(zb), zb, np.where(filled < 1e8, filled, np.inf))


def agreement(nodes, gate):
    out = []
    for X in nodes:
        for Y in nodes:
            if X is Y:
                continue
            e = []
            for f in X['faces'].values():
                rY = project(Y, f)
                has = np.isfinite(rY) & np.isfinite(f['r'])
                q = np.abs(rY[has] / f['r'][has] - 1)
                e.append(q[q < 1.0])
            e = np.concatenate(e)
            out.append({'from': Y['node'], 'into': X['node'], 'median': float(np.median(e)),
                        'within_3': float(np.mean(e < .03)), 'within_10': float(np.mean(e < .1))})
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('images'); ap.add_argument('sparse'); ap.add_argument('out')
    ap.add_argument('--node', nargs=3, action='append', required=True, metavar=('NODE', 'DEPTH_DIR', 'R_FAR_JSON'))
    ap.add_argument('--masks'); ap.add_argument('--gate', type=float, default=0.25)
    ap.add_argument('--rounds', type=int, default=3); ap.add_argument('--blur', type=float, default=6.0)
    ap.add_argument('--water-percentile', type=float, default=20.0)
    a = ap.parse_args()
    _, imgs = read_model(a.sparse)
    nodes = [load(a.images, imgs, n, d, j, a.masks) for n, d, j in a.node]
    up = -imgs[f'f1/MA-{nodes[0]["node"]}.jpg'][0][1]
    before = agreement(nodes, a.gate)
    for b in before:
        print(f"before: {b['from']} into {b['into']}: median {b['median'] * 100:.1f}%, within 3% {b['within_3'] * 100:.0f}%, within 10% {b['within_10'] * 100:.0f}%")
    # the water's level, from the solid pixels beside it below the horizon
    hs = []
    for X in nodes:
        for f in X['faces'].values():
            if not f['water'].any():
                continue
            ring = cv2.dilate(f['water'].astype(np.uint8), np.ones((7, 7), np.uint8)).astype(bool) & ~f['water'] & ~f['sky']
            ring &= (f['dirs'] @ up) < -0.05
            P = X['C'] + f['dirs'][ring] * f['r'][ring, None]
            hs.append(P @ up)
    level = None
    if hs:
        hs = np.concatenate(hs)
        level = float(np.percentile(hs, a.water_percentile))
        print(f'water level {level:.3f} (heights beside it: 10% {np.percentile(hs, 10):.3f}, 50% {np.percentile(hs, 50):.3f}, '
              f'90% {np.percentile(hs, 90):.3f}; the first node stands at {nodes[0]["C"] @ up:.3f})')
        for X in nodes:
            for f in X['faces'].values():
                if not f['water'].any():
                    continue
                du = f['dirs'] @ up
                with np.errstate(all='ignore'):
                    rw = (level - X['C'] @ up) / du
                rw = np.where((du < -1e-3) & (rw > 0), np.minimum(rw, X['r_far']), X['r_far'])
                f['r'] = np.where(f['water'], rw, f['r'])
    for rnd in range(a.rounds):
        corr = []
        for X in nodes:
            cx = {}
            for k, f in X['faces'].items():
                acc = np.zeros((f['N'], f['N'])); n = np.zeros((f['N'], f['N']))
                for Y in nodes:
                    if Y is X:
                        continue
                    rY = project(Y, f)
                    has = np.isfinite(rY) & np.isfinite(f['r']) & ~f['water']
                    lq = np.zeros_like(acc)
                    lq[has] = np.log(rY[has] / f['r'][has])
                    has &= np.abs(lq) < np.log(1 + a.gate)
                    acc += np.where(has, lq / 2, 0); n += has
                w = cv2.GaussianBlur(n.astype(np.float32), (0, 0), a.blur)
                c = cv2.GaussianBlur(acc.astype(np.float32), (0, 0), a.blur) / np.maximum(w, 1e-6)
                cx[k] = np.where(w > 0.05, c * np.clip(w / 0.3, 0, 1), 0.0)
            corr.append(cx)
        for X, cx in zip(nodes, corr):
            for k, f in X['faces'].items():
                f['r'] = np.where(f['water'] | f['sky'], f['r'], f['r'] * np.exp(cx[k]))
        print(f'round {rnd + 1}: mean correction {np.mean([np.abs(c).mean() for cx in corr for c in cx.values()]) * 100:.2f}%', flush=True)
    after = agreement(nodes, a.gate)
    for b in after:
        print(f"after:  {b['from']} into {b['into']}: median {b['median'] * 100:.1f}%, within 3% {b['within_3'] * 100:.0f}%, within 10% {b['within_10'] * 100:.0f}%")
    for X in nodes:
        od = os.path.join(a.out, X['node'])
        os.makedirs(od, exist_ok=True)
        for k, f in X['faces'].items():
            q = np.where(f['sky'], 0.0, X['r_far'] / np.maximum(f['r'], 1e-9))
            d = np.clip((q - 1) / (RATIO - 1), 0, 1)
            d8 = np.where(f['sky'], 0, np.maximum(np.rint(d * 255), 1)).astype(np.uint8)
            Image.fromarray(d8).save(os.path.join(od, f'MA-{X["node"]}-{k}_measured-depth.png'))
        with open(os.path.join(od, 'walk_joint.json'), 'w') as fh:
            json.dump({'r_far': X['r_far'], 'water_level': level, 'gate': a.gate, 'rounds': a.rounds,
                       'before': before, 'after': after}, fh, indent=1)


if __name__ == '__main__':
    main()
