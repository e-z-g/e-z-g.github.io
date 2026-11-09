#!/usr/bin/env python3
"""
Depths for a walk between two nodes measured from the two nodes' own pictures,
so that each node's picture, moved by its depth, lands where the other node
sees the same things.

    python walk_flow.py IMAGES SPARSE_TXT OUT_DIR --node 4084 DEPTH_DIR R_FAR_JSON
        --node 4089 DEPTH_DIR R_FAR_JSON [--wide 1024] [--check 1.5] [--min-angle 1.0]
        [--blur 3] [--save-flow]

Each node's depth (node_depth.py's encoding, DEPTH_DIR/MA-<node>-<k>
_measured-depth.png) is a depth network's guess fitted to the model's sparse
points, and two nodes' guesses are 10-60% apart on things like MASS 84's ride
car: the walk then shows the car twice. Here, for each face of each node, both
nodes' panoramas are drawn as one wide picture (--wide px, the face in the
middle at its own scale, its neighbours round it) looking the same way from
each node's centre; the cameras then differ by the step between the nodes
only, and RAFT (torchvision's raft_large) finds where each pixel went, both
ways. A pixel whose flow there and back returns within --check px, and whose
two rays meet at more than --min-angle degrees, gets the distance where the
two rays pass closest: the depth that puts it where the other node sees it.
A reflection matched this way gets the depth of its mirror image, which a
flat water surface keeps in one place from either node, so it lines up too.
The rest keep their depth, with the measured correction spread to them from
measured pixels nearby (a Gaussian of --blur px). Sky stays sky.

Writes OUT_DIR/<node>/MA-<node>-<k>_measured-depth.png and walk_flow.json
(r_far as before, and per face how much was measured), for walk_scene.py; the
site's panoramas are not changed. Needs numpy, Pillow, opencv-python, torch,
torchvision; view_check.py beside it.
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


def load(images, imgs, node, ddir, js):
    r_far = json.load(open(js))['r_far']
    faces = {}
    for k in range(1, 7):
        R, t = imgs[f'f{k}/MA-{node}.jpg'][:2]
        img = np.asarray(Image.open(os.path.join(images, f'f{k}', f'MA-{node}.jpg')).convert('RGB'))
        N = img.shape[0]
        d8 = np.asarray(Image.open(os.path.join(ddir, f'MA-{node}-{k}_measured-depth.png')).convert('L')
                        .resize((N, N), Image.NEAREST)).astype(float)
        r = np.where(d8 == 0, np.nan, r_far / (1 + (RATIO - 1) * d8 / 255))
        faces[k] = dict(R=R, t=t, img=img, N=N, r=r, sky=d8 == 0)
    C = -faces[1]['R'].T @ faces[1]['t']
    return dict(node=node, C=C, r_far=r_far, faces=faces)


def wide_view(X, R, W, f):
    """X's panorama seen through a W x W pinhole camera with rotation R (world to
    camera rows) and focal f px, from X's centre."""
    v, u = np.mgrid[0:W, 0:W].astype(np.float64)
    cam = np.stack([(u + .5 - W / 2) / f, (v + .5 - W / 2) / f, np.ones_like(u)], -1)
    dirs = cam @ R                                          # world directions
    out = np.zeros((W, W, 3), np.float32); best = np.full((W, W), -np.inf)
    for fc in X['faces'].values():
        c = dirs @ fc['R'].T
        with np.errstate(all='ignore'):
            x = c[..., 0] / c[..., 2]; y = c[..., 1] / c[..., 2]
        ok = (c[..., 2] > 0) & (np.abs(x) <= 1.001) & (np.abs(y) <= 1.001)
        score = np.where(ok, c[..., 2] / np.linalg.norm(c, axis=-1), -np.inf)
        take = score > best
        if not take.any():
            continue
        N = fc['N']
        mx = ((x + 1) * N / 2 - .5).astype(np.float32); my = ((y + 1) * N / 2 - .5).astype(np.float32)
        s = cv2.remap(fc['img'], np.where(ok, mx, 0), np.where(ok, my, 0), cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
        out[take] = s[take]; best[take] = score[take]
    return out, dirs


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('images'); ap.add_argument('sparse'); ap.add_argument('out')
    ap.add_argument('--node', nargs=3, action='append', required=True, metavar=('NODE', 'DEPTH_DIR', 'R_FAR_JSON'))
    ap.add_argument('--wide', type=int, default=1024); ap.add_argument('--check', type=float, default=1.5)
    ap.add_argument('--min-angle', type=float, default=1.0); ap.add_argument('--blur', type=float, default=3.0)
    ap.add_argument('--save-flow', action='store_true')
    a = ap.parse_args()
    assert len(a.node) == 2, 'two nodes'
    import torch
    from torchvision.models.optical_flow import raft_large, Raft_Large_Weights
    dev = 'cuda' if torch.cuda.is_available() else 'cpu'
    net = raft_large(weights=Raft_Large_Weights.DEFAULT).to(dev).eval()

    def flow(p, q):
        tp = torch.from_numpy(p).permute(2, 0, 1)[None].float().to(dev) / 127.5 - 1
        tq = torch.from_numpy(q).permute(2, 0, 1)[None].float().to(dev) / 127.5 - 1
        with torch.no_grad():
            return net(tp, tq, num_flow_updates=24)[-1][0].permute(1, 2, 0).cpu().numpy().astype(np.float64)

    _, imgs = read_model(a.sparse)
    nodes = [load(a.images, imgs, n, d, j) for n, d, j in a.node]
    os.makedirs(a.out, exist_ok=True)
    report = {}
    for X, Y in ((nodes[0], nodes[1]), (nodes[1], nodes[0])):
        od = os.path.join(a.out, X['node']); os.makedirs(od, exist_ok=True)
        report[X['node']] = {}
        for k, fc in X['faces'].items():
            N, W = fc['N'], a.wide
            f = N / 2                                       # the face's own scale
            R = fc['R']
            px, dirs = wide_view(X, R, W, f)
            py, _ = wide_view(Y, R, W, f)
            fxy = flow(px, py); fyx = flow(py, px)
            v, u = np.mgrid[0:W, 0:W].astype(np.float64)
            u2, v2 = u + fxy[..., 0], v + fxy[..., 1]
            back = np.stack([cv2.remap(fyx[..., i].astype(np.float32), u2.astype(np.float32), v2.astype(np.float32),
                                       cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=1e4) for i in range(2)], -1)
            err = np.hypot(fxy[..., 0] + back[..., 0], fxy[..., 1] + back[..., 1])
            cam2 = np.stack([(u2 + .5 - W / 2) / f, (v2 + .5 - W / 2) / f, np.ones_like(u2)], -1) @ R
            d1 = dirs / np.linalg.norm(dirs, axis=-1, keepdims=True); d2 = cam2 / np.linalg.norm(cam2, axis=-1, keepdims=True)
            b = Y['C'] - X['C']
            # closest approach of X['C'] + s d1 and Y['C'] + w d2
            c12 = (d1 * d2).sum(-1); bd1 = d1 @ b; bd2 = d2 @ b
            den = 1 - c12 ** 2
            with np.errstate(all='ignore'):
                s = (bd1 - c12 * bd2) / den; w = (c12 * bd1 - bd2) / den
            ang = np.degrees(np.arccos(np.clip(c12, -1, 1)))
            # the face's own pixels sit in the middle of the wide picture
            o = (W - N) // 2
            sl = (slice(o, o + N), slice(o, o + N))
            s, w, err, ang = s[sl], w[sl], err[sl], ang[sl]
            r0 = fc['r']
            good = (err < a.check) & (ang > a.min_angle) & (s > 0) & (w > 0) & np.isfinite(r0) & ~fc['sky']
            good &= (s > r0 / 4) & (s < r0 * 4)
            lc = np.where(good, np.log(np.where(good, s, 1) / np.where(good, r0, 1)), 0.0)
            wt = cv2.GaussianBlur(good.astype(np.float32), (0, 0), a.blur)
            cs = cv2.GaussianBlur(lc.astype(np.float32), (0, 0), a.blur) / np.maximum(wt, 1e-6)
            # measured pixels keep their own value; the rest take the spread correction, fading out away from them
            corr = np.where(good, lc, np.where(wt > 0.02, cs * np.clip(wt / 0.2, 0, 1), 0.0))
            r = np.where(fc['sky'], np.nan, r0 * np.exp(corr))
            q = np.where(fc['sky'], 0.0, X['r_far'] / np.maximum(np.where(np.isfinite(r), r, X['r_far']), 1e-9))
            d = np.clip((q - 1) / (RATIO - 1), 0, 1)
            d8 = np.where(fc['sky'], 0, np.maximum(np.rint(d * 255), 1)).astype(np.uint8)
            Image.fromarray(d8).save(os.path.join(od, f'MA-{X["node"]}-{k}_measured-depth.png'))
            med = float(np.median(np.exp(lc[good]))) if good.any() else float('nan')
            report[X['node']][k] = {'measured': float(good.mean()), 'median_ratio_to_before': med}
            print(f'{X["node"]} face {k}: measured {good.mean() * 100:.0f}% (flow returns within {a.check} px on '
                  f'{np.mean(err < a.check) * 100:.0f}%, rays apart over {a.min_angle} deg on {np.mean(ang > a.min_angle) * 100:.0f}%); '
                  f'new / before median {med:.2f}', flush=True)
            if a.save_flow:
                Image.fromarray(np.concatenate([px, py], 1).astype(np.uint8)).resize((W, W // 2)).save(os.path.join(od, f'wide_f{k}.jpg'), quality=85)
        with open(os.path.join(od, 'walk_flow.json'), 'w') as fh:
            json.dump({'r_far': X['r_far'], 'other': Y['node'], 'faces': report[X['node']], 'check': a.check,
                       'min_angle': a.min_angle, 'wide': a.wide}, fh, indent=1)


if __name__ == '__main__':
    main()
