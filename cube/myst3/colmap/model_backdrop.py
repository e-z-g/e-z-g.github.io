#!/usr/bin/env python3
"""
What is really behind a site node's near objects, from the other nodes of the
model that saw it: colour and depth for build_layers.py's backdrop.

    python model_backdrop.py DENSE SPARSE_TXT NODE SHARP_DIR NODE_DEPTH_JSON OUT
        [--names N1 ... N6] [--depth-suffix _sharp-depth.png] [--neighbours 12]
        [--behind 1.1] [--splat 2] [--masks MASKS]

DENSE is a run_dense.ps1 (or node_stereo.py) workspace: images/f<k>/<name>.jpg
and stereo/depth_maps/f<k>/<name>.jpg.geometric.bin. SPARSE_TXT is the text
model it was made from (images.txt: every face's pose). NODE is the node as in
the file names (4084, 0016). SHARP_DIR holds the site node's six depth maps
(sharpen_depth.py's, names --names, d = (r_far/r - 1)/19) and NODE_DEPTH_JSON
is node_depth.py's report, whose r_far puts them in the model's units.

Why. build_layers.py's backdrop is what is behind the foreground's near
objects. Painted by LaMa from the node's own picture it is invented, and two
layers had to be chosen by rules (which far side counts as behind) that suit
one scene and not the next. The nodes around saw behind those objects. Every
pixel with a geometric depth in the faces of the --neighbours nearest nodes
becomes a point of that colour in the model; projected into the site node's
faces, each pixel keeps the nearest point lying behind the foreground (farther
than --behind times the foreground's distance, and than the model's own depth
for this node where it has one), splatted over --splat pixels. A point counts
only if its node saw it within --max-angle (30) degrees of our own line of
sight, and not when it has the foreground pixel's colour within --same (1.6)
times its distance: then it is the foreground itself.
Where no node saw anything behind, LaMa still paints.

With --masks (sky_masks.py's: MASKS/f<k>/<name>.png, black on the sky, sea
and water), no pixel a neighbour's mask blacks out is used. Stereo gives the
clouds and the sea depths of their own: lit clouds came out a little behind
MASS 84's lamp post and track and were kept there as a dark and orange
speckle in the sky, and the post's reflection in the water, which stereo puts
below the water as far again, landed just behind the post as a second post.
LaMa paints sky and sea well from the node's own picture.

Writes, per face, OUT/<name>_model-bg.png (RGBA: alpha 255 where a point
landed) and OUT/<name>_model-bg-q.npy (float32 r_far / r, 0 where none), at the
size of the depth maps in SHARP_DIR. Needs numpy, Pillow; depth_fill.py beside it.
"""
import argparse
import json
import os

import numpy as np
from PIL import Image

from depth_fill import read_colmap_array


def qvec2rot(q):
    w, x, y, z = q
    return np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)],
                     [2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)],
                     [2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)]])


def read_poses(txt):
    """name -> (R, t) for every image of a COLMAP text model."""
    poses = {}
    with open(os.path.join(txt, 'images.txt')) as f:
        head = True
        for line in f:
            if line.startswith('#'):
                continue
            if head:
                p = line.split()
                poses[p[9]] = (qvec2rot(np.array(p[1:5], float)), np.array(p[5:8], float))
            head = not head
    return poses


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('dense'); ap.add_argument('sparse_txt'); ap.add_argument('node')
    ap.add_argument('sharp'); ap.add_argument('node_json'); ap.add_argument('out')
    ap.add_argument('--names', nargs=6, required=True)
    ap.add_argument('--depth-suffix', default='_sharp-depth.png')
    ap.add_argument('--neighbours', type=int, default=12)
    ap.add_argument('--behind', type=float, default=1.15)
    ap.add_argument('--splat', type=int, default=2)
    ap.add_argument('--same', type=float, default=1.6)
    ap.add_argument('--max-angle', type=float, default=30.0)
    ap.add_argument('--masks', help="sky_masks.py's folder: the neighbours' pixels it blacks out (sky, sea, water) are not used")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    r_far = json.load(open(a.node_json))['r_far']
    poses = read_poses(a.sparse_txt)
    own = {k: next(m for m in poses if m.startswith(f'f{k}/') and m.endswith(f'-{a.node}.jpg')) for k in range(1, 7)}
    C = -poses[own[1]][0].T @ poses[own[1]][1]
    # the nearest other nodes, by the centre of their face 1
    centres = {}
    for name, (R, t) in poses.items():
        if name.startswith('f1/') and name != own[1]:
            centres[name[3:]] = -R.T @ t
    near = sorted(centres, key=lambda n: np.linalg.norm(centres[n] - C))[:a.neighbours]
    print(f'node {a.node} at {np.round(C, 2)}; neighbours: ' +
          ', '.join(f'{n} ({np.linalg.norm(centres[n] - C):.2f})' for n in near))
    # the site node's foreground, in r_far / r
    fg, N = {}, None
    for k, name in enumerate(a.names, 1):
        d = np.asarray(Image.open(os.path.join(a.sharp, name + a.depth_suffix)).convert('L')).astype(np.float32) / 255
        fg[k] = 1 + 19 * d
        N = d.shape[0]
    f = N / 2.0
    # What counts as the foreground: the nearer of the site depth and the
    # model's own depth for this node (its geometric depth maps, nearest within
    # 5 px), so where the two disagree (the site depth is a fit, 10-15% off
    # the model on some faces) the same surface is not taken for what is behind.
    import cv2
    ref, fgc = {}, {}
    for k in range(1, 7):
        r = fg[k].copy()
        dm = os.path.join(a.dense, 'stereo', 'depth_maps', own[k] + '.geometric.bin')
        if os.path.exists(dm):
            z = read_colmap_array(dm)
            h = z.shape[0]
            u = (np.arange(h) + 0.5) / h * 2 - 1
            xx, yy = np.meshgrid(u, u)
            qo = np.where(z > 0, r_far / np.maximum(z * np.sqrt(1 + xx ** 2 + yy ** 2), 1e-9), 0).astype(np.float32)
            qo = cv2.resize(cv2.dilate(qo, np.ones((5, 5), np.uint8)), (N, N), interpolation=cv2.INTER_NEAREST)
            r = np.maximum(r, qo)
        ref[k] = r
        img = Image.open(os.path.join(a.dense, 'images', own[k])).convert('RGB').resize((N, N), Image.BILINEAR)
        fgc[k] = np.asarray(img).astype(np.int16)
    best_q = {k: np.zeros((N, N), np.float32) for k in fg}
    best_c = {k: np.zeros((N, N, 3), np.uint8) for k in fg}
    used = masked = 0
    for n in near:
        for k2 in range(1, 7):
            name = f'f{k2}/{n}'
            dm = os.path.join(a.dense, 'stereo', 'depth_maps', f'f{k2}', n + '.geometric.bin')
            if name not in poses or not os.path.exists(dm):
                continue
            z = read_colmap_array(dm)
            img = np.asarray(Image.open(os.path.join(a.dense, 'images', f'f{k2}', n)).convert('RGB'))
            H, W = z.shape
            valid = z > 0
            if a.masks:
                mp = os.path.join(a.masks, f'f{k2}', n + '.png')
                if os.path.exists(mp):
                    mk = np.asarray(Image.open(mp).convert('L').resize((W, H), Image.NEAREST))
                    valid &= mk > 127
                    masked += 1
            v, u = np.nonzero(valid)
            if not len(v):
                continue
            used += 1
            zz = z[v, u]
            fx = W / 2.0                                   # the faces are 90-degree pinholes
            Xc = np.stack([(u + 0.5 - W / 2) / fx * zz, (v + 0.5 - H / 2) / fx * zz, zz], 1)
            R, t = poses[name]
            X = (Xc - t) @ R                               # R^T (Xc - t)
            col = img[v, u]
            # Only what that node saw from about our direction: moving the eye
            # a little uncovers what lies past an object's edge, never its
            # back, which the nodes beyond it see from the other side (the
            # stone tower's far side came back inside its outline).
            Cn = -R.T @ t
            d1 = X - C; d2 = X - Cn
            cosang = (d1 * d2).sum(1) / (np.linalg.norm(d1, axis=1) * np.linalg.norm(d2, axis=1) + 1e-12)
            keep = cosang > np.cos(np.radians(a.max_angle))
            X, col = X[keep], col[keep]
            if not len(X):
                continue
            for k in range(1, 7):
                Rk, tk = poses[own[k]]
                Y = X @ Rk.T + tk
                ok = Y[:, 2] > 1e-6
                x = Y[:, 0] / np.where(ok, Y[:, 2], 1); y = Y[:, 1] / np.where(ok, Y[:, 2], 1)
                ok &= (np.abs(x) < 1) & (np.abs(y) < 1)
                if not ok.any():
                    continue
                px = np.clip(((x[ok] + 1) * f).astype(int), 0, N - 1)
                py = np.clip(((y[ok] + 1) * f).astype(int), 0, N - 1)
                q = (r_far / np.linalg.norm(Y[ok], axis=1)).astype(np.float32)
                c = col[ok]
                behind = q * a.behind < ref[k][py, px]     # farther than --behind times the foreground
                # and not the foreground itself, seen a little farther: the same
                # colour (the renders' lighting does not change with the node)
                # within --same times the foreground's distance
                same = (np.abs(c.astype(np.int16) - fgc[k][py, px]).sum(1) < 36) & (q * a.same > ref[k][py, px])
                behind &= ~same
                px, py, q, c = px[behind], py[behind], q[behind], c[behind]
                # nearest first wins: write farthest first, then nearer over it
                order = np.argsort(q)
                px, py, q, c = px[order], py[order], q[order], c[order]
                for dy in range(a.splat):
                    for dx in range(a.splat):
                        yy = np.clip(py + dy, 0, N - 1); xx = np.clip(px + dx, 0, N - 1)
                        keep = q > best_q[k][yy, xx]
                        best_q[k][yy[keep], xx[keep]] = q[keep]
                        best_c[k][yy[keep], xx[keep]] = c[keep]
    print(f'{used} neighbouring faces with depth projected' + (f', {masked} with a sky and water mask' if a.masks else ''))
    for k, name in enumerate(a.names, 1):
        has = best_q[k] > 0
        rgba = np.dstack([best_c[k], np.where(has, 255, 0).astype(np.uint8)])
        Image.fromarray(rgba).save(os.path.join(a.out, name + '_model-bg.png'))
        np.save(os.path.join(a.out, name + '_model-bg-q.npy'), best_q[k])
        print(f'{name}: {has.mean() * 100:.1f}% of the face has something behind the foreground from the model')


if __name__ == '__main__':
    main()
