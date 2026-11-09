#!/usr/bin/env python3
"""
How well a site node's depth predicts what other cameras of the model saw:
the node's six faces moved, by their depth, to another camera's position and
compared with that camera's picture.

    python view_check.py DENSE SPARSE_TXT --node 4084 --names N1 ... N6
        --variant NAME DEPTH_DIR SUFFIX R_FAR_JSON [--variant ...]
        [--scale 1.089189] [--radius 3] [--frames 40] [--out OUT_DIR]

DENSE is the model's dense workspace (images/<name>, the pictures COLMAP was
given, the node's faces and the other cameras alike, so their brightness
matches); SPARSE_TXT its text model (images.txt, cameras.txt). Each --variant
is a depth for the node: DEPTH_DIR/<name>SUFFIX in node_depth.py's encoding
(d = (r_far / r - 1) / 19, 0 the sky), r_far from R_FAR_JSON's "r_far", in
units of which the model's are --scale times. A variant named "infinity"
(DEPTH_DIR ignored) puts everything at infinity, so only the turn is applied:
the floor any depth should beat. The pixels judged are those every other
version covers; it is judged on what it covers of them.

The test views: every face of the other nodes, and every movie frame, within
--radius of the node (in the model's units; at most --frames movie frames,
evenly spread). Each pixel of the node's faces becomes a point at its depth,
projected into the test view; the nearest point wins each pixel, and each
point covers the pixels its footprint would there (a 1/320 rad pixel at the
point's distance), so a near surface stays closed. Over the pixels covered by
every variant, so all are judged on the same pixels, the mean absolute
difference from the test view's picture (0-255, the three channels averaged)
is the score; lower is better. Prints a table per view and the mean, and
with --out writes for each view the picture beside each variant's render.

Why: the site's depth was judged against node_depth.py's own measured depth,
which is itself Depth Anything's shape, so a better depth could score worse;
the other cameras' pictures are what the age looks like from elsewhere.
Needs numpy, Pillow.
"""
import argparse
import json
import os
import sys

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from node_depth import qvec2rot  # noqa: E402

RATIO = 20.0
FACE_F = 320.0      # a 640 px face's focal length; faces read at other sizes are scaled


def read_model(txt):
    cams = {}
    with open(os.path.join(txt, 'cameras.txt')) as fh:
        for line in fh:
            if line.startswith('#') or not line.strip():
                continue
            p = line.split()
            model, w, h = p[1], int(p[2]), int(p[3]); pr = [float(x) for x in p[4:]]
            if model in ('SIMPLE_PINHOLE', 'SIMPLE_RADIAL', 'RADIAL'):
                fx = fy = pr[0]; cx, cy = pr[1], pr[2]
            else:
                fx, fy, cx, cy = pr[:4]
            cams[int(p[0])] = (w, h, fx, fy, cx, cy)
    imgs = {}
    with open(os.path.join(txt, 'images.txt')) as fh:
        head = True
        for line in fh:
            if line.startswith('#'):
                continue
            if head:
                p = line.split()
                R = qvec2rot(np.array(p[1:5], float)); t = np.array(p[5:8], float)
                imgs[p[9]] = (R, t, int(p[8]))
            head = not head
    return cams, imgs


def splat(P, cols, R, t, cam, src_f, grow=1.0):
    """Points P (n x 3, model frame) with colours, drawn into camera (R, t, cam):
    image and coverage. Each point covers its footprint (src pixel at its
    distance) times grow, nearest first."""
    w, h, fx, fy, cx, cy = cam
    Y = P @ R.T + t
    z = Y[:, 2]
    ok = z > 1e-3
    Y, z, c = Y[ok], z[ok], cols[ok]
    r = np.linalg.norm(P[ok] - (-R.T @ t), axis=1)
    x = fx * Y[:, 0] / z + cx; y = fy * Y[:, 1] / z + cy
    inside = (x > -4) & (x < w + 4) & (y > -4) & (y < h + 4)
    x, y, z, c, r = x[inside], y[inside], z[inside], c[inside], r[inside]
    rad = np.clip(np.ceil(0.5 * grow * fx * (r / src_f) / z), 1, 4).astype(int)
    order = np.argsort(-z)                         # far first, near written over
    x, y, z, c, rad = x[order], y[order], z[order], c[order], rad[order]
    img = np.zeros((h, w, 3), np.float32); zb = np.full((h, w), np.inf, np.float32)
    xi = np.rint(x).astype(int); yi = np.rint(y).astype(int)
    for s in range(1, 5):
        m = rad == s
        if not m.any():
            continue
        for dy in range(-s + 1, s):
            for dx in range(-s + 1, s):
                xx = xi[m] + dx; yy = yi[m] + dy
                okk = (xx >= 0) & (xx < w) & (yy >= 0) & (yy < h)
                xx, yy, zz, cc = xx[okk], yy[okk], z[m][okk], c[m][okk]
                # nearest wins: write in far-to-near order, then keep where nearer
                o = np.argsort(-zz)
                xx, yy, zz, cc = xx[o], yy[o], zz[o], cc[o]
                nearer = zz < zb[yy, xx]
                xx, yy, zz, cc = xx[nearer], yy[nearer], zz[nearer], cc[nearer]
                zb[yy, xx] = zz; img[yy, xx] = cc
    return img, np.isfinite(zb)


def stretch_points(Pg, Cg, R, t, cam, longest=96):
    """The node's faces drawn as the viewer draws them, a surface through every
    pixel and its right and lower neighbours: where two neighbours land 2 px
    or more apart in the view, points along the line between them (in 3D,
    so the stretch is where the surface is), their colours blended, at most
    `longest` a line. Pg, Cg: (6, N, N, 3) positions (NaN where none) and
    colours. Returns the extra points and colours."""
    w, h, fx, fy, cx, cy = cam
    Y = Pg @ R.T + t
    z = Y[..., 2]
    with np.errstate(all='ignore'):
        x = fx * Y[..., 0] / z + cx; y = fy * Y[..., 1] / z + cy
    good = np.isfinite(z) & (z > 1e-3)
    inside = good & (x > -50) & (x < w + 50) & (y > -50) & (y < h + 50)
    outP, outC = [], []
    for a_, b_ in ((np.s_[:, :, :-1], np.s_[:, :, 1:]), (np.s_[:, :-1, :], np.s_[:, 1:, :])):
        L = np.hypot(x[b_] - x[a_], y[b_] - y[a_])
        ok = good[a_] & good[b_] & (inside[a_] | inside[b_]) & (L >= 2)
        if not ok.any():
            continue
        m = np.minimum(np.ceil(L[ok]), longest).astype(int) - 1          # points inside each line
        P1, P2 = Pg[a_][ok], Pg[b_][ok]; C1, C2 = Cg[a_][ok], Cg[b_][ok]
        e = np.repeat(np.arange(len(m)), m)
        start = np.repeat(np.cumsum(m) - m, m)
        f = ((np.arange(len(e)) - start + 1) / np.repeat(m + 1, m))[:, None]
        outP.append(P1[e] + f * (P2[e] - P1[e])); outC.append(C1[e] + f * (C2[e] - C1[e]))
    if not outP:
        return np.zeros((0, 3)), np.zeros((0, 3), np.float32)
    return np.concatenate(outP), np.concatenate(outC).astype(np.float32)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('dense'); ap.add_argument('sparse')
    ap.add_argument('--node', required=True); ap.add_argument('--names', nargs=6, required=True)
    ap.add_argument('--variant', nargs=4, action='append', required=True, metavar=('NAME', 'DIR', 'SUFFIX', 'R_FAR_JSON'))
    ap.add_argument('--scale', type=float, default=1.0)
    ap.add_argument('--radius', type=float, default=3.0); ap.add_argument('--frames', type=int, default=40)
    ap.add_argument('--out')
    ap.add_argument('--connected', action='store_true',
                    help="draw the faces as the viewer does, a surface joining neighbouring pixels (stretched across "
                         "steps), the sky at r_far as the viewer puts it, not as separate points: a false step then smears")
    a = ap.parse_args()
    cams, imgs = read_model(a.sparse)
    own = {k: f'f{k}/MA-{a.node}.jpg' for k in range(1, 7)}
    C = -imgs[own[1]][0].T @ imgs[own[1]][1]
    centre = lambda n: -imgs[n][0].T @ imgs[n][1]
    nodes, frames = [], []
    for n in imgs:
        if n in own.values():
            continue
        d = float(np.linalg.norm(centre(n) - C))
        if d > a.radius:
            continue
        (nodes if n.startswith('f') else frames).append((d, n))
    nodes.sort(); frames.sort(key=lambda x: x[1])
    if len(frames) > a.frames:
        frames = [frames[i] for i in np.linspace(0, len(frames) - 1, a.frames).astype(int)]
    views = nodes + frames
    print(f'node {a.node} at {np.round(C, 3)}: {len(nodes)} node faces and {len(frames)} movie frames within {a.radius}', flush=True)
    # the node's faces: colours and directions
    face_cols, face_dirs = {}, {}
    for k in range(1, 7):
        img = np.asarray(Image.open(os.path.join(a.dense, 'images', own[k])).convert('RGB'), np.float32)
        N = img.shape[0]
        u = (np.arange(N) + .5) / N * 2 - 1
        xx, yy = np.meshgrid(u, u)
        R = imgs[own[k]][0]
        d = np.stack([xx, yy, np.ones_like(xx)], -1).reshape(-1, 3) @ R
        face_dirs[k] = d / np.linalg.norm(d, axis=1, keepdims=True)
        face_cols[k] = img.reshape(-1, 3)
    src_f = FACE_F * N / 640
    points, grids = {}, {}
    for name, ddir, suffix, rjson in a.variant:
        P, cols, gP, gC = [], [], [], []
        r_far = json.load(open(rjson))['r_far'] if name != 'infinity' else 1.0
        for k, nm in enumerate(a.names, 1):
            if name == 'infinity':
                r = np.full(N * N, 1e4)
            else:
                d8 = np.asarray(Image.open(os.path.join(ddir, nm + suffix)).convert('L').resize((N, N), Image.NEAREST)).astype(float).ravel()
                q = 1 + (RATIO - 1) * d8 / 255
                # the viewer puts the sky (0) at r_far, the farthest it draws
                r = np.where(d8 > 0, r_far / q * a.scale, r_far * a.scale if a.connected else np.nan)
            keep = np.isfinite(r)
            P.append(C + face_dirs[k][keep] * r[keep, None]); cols.append(face_cols[k][keep])
            if a.connected:
                gP.append((C + face_dirs[k] * r[:, None]).reshape(N, N, 3)); gC.append(face_cols[k].reshape(N, N, 3))
        points[name] = (np.concatenate(P), np.concatenate(cols))
        if a.connected:
            grids[name] = (np.stack(gP), np.stack(gC))
    names = [v[0] for v in a.variant]
    print('view'.ljust(28) + 'dist ' + ''.join(n[:14].rjust(15) for n in names) + '   covered', flush=True)
    sums = {n: [] for n in names}
    if a.out:
        os.makedirs(a.out, exist_ok=True)
    for d, view in views:
        R, t, cid = imgs[view]
        cam = cams[cid]
        path = os.path.join(a.dense, 'images', view)
        if not os.path.exists(path):
            print(f'{view}: no picture at {path}', flush=True)
            continue
        target = np.asarray(Image.open(path).convert('RGB'), np.float32)
        if target.shape[:2] != (cam[1], cam[0]):
            print(f'{view}: picture {target.shape[1]}x{target.shape[0]}, camera {cam[0]}x{cam[1]}', flush=True)
            continue
        if a.connected:
            renders = {}
            for n in names:
                eP, eC = stretch_points(*grids[n], R, t, cam)
                renders[n] = splat(np.concatenate([points[n][0], eP]), np.concatenate([points[n][1], eC]), R, t, cam, src_f)
        else:
            renders = {n: splat(*points[n], R, t, cam, src_f) for n in names}
        # the pixels every real depth covers; the turn alone puts everything
        # far off and lands elsewhere in a view from the side, so it is judged
        # on what it covers of those
        real = [n for n in names if n != 'infinity'] or names
        cov = np.logical_and.reduce([renders[n][1] for n in real])
        if cov.mean() < 0.05:
            print(f'{view}: {cov.mean() * 100:.1f}% covered by every version, left out', flush=True)
            continue
        row = view.ljust(28)[:28] + f'{d:4.2f} '
        for n in names:
            cn = cov & renders[n][1]
            e = float(np.abs(renders[n][0][cn] - target[cn]).mean()) if cn.any() else float('nan')
            sums[n].append(e); row += f'{e:15.2f}'
        print(row + f'   {cov.mean() * 100:5.1f}%', flush=True)
        if a.out:
            tiles = [target] + [np.where(cov[..., None], renders[n][0], 0) for n in names]
            Image.fromarray(np.concatenate(tiles, 1).astype(np.uint8)).save(
                os.path.join(a.out, view.replace('/', '_').replace('.jpg', '') + '.jpg'), quality=85)
    print('mean'.ljust(33) + ''.join(f'{np.nanmean(sums[n]):15.2f}' for n in names) + f'   over {len(sums[names[0]])} views')
    if a.out:
        with open(os.path.join(a.out, 'view_check.json'), 'w') as fh:
            json.dump({n: {'mean': float(np.nanmean(sums[n])), 'per_view': sums[n]} for n in names}, fh, indent=1)


if __name__ == '__main__':
    main()
