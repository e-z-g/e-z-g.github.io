#!/usr/bin/env python3
"""
A node's depth whose steps are those the network and the model's mesh agree
on: the network's shape, rebuilt from its gradients with each step checked
against the mesh.

    python agree_depth.py SITE OUT_DIR --names N1 ... N6 --mesh MESH_DIR
        --node-depth node_depth.json [--tau 0.1] [--keep-above 0.5]
        [--max-span 0.3] [--lam 0.01] [--masks MASKS --node 4084] [--band 48]

SITE holds the node's depth (<name>_measured-depth.png, node_depth.py's:
Depth Anything fitted to what was measured); MESH_DIR mesh_depth.py's output
for the node (<name>_mesh-z.npy and _mesh-span.npy, in the site depth's
units). Working in q = r_far / r on each face, between every pixel and its
right and lower neighbour:
  - a step is a change of more than --tau of the value over the two pixels
    either side;
  - where the network steps and the mesh, reliable there (its triangle
    spanning under --max-span radians, not under the sky and water masks),
    does not, the network's step was one it made up (MASS 84's rock wall: a
    slab per column): the gradient there is the mesh's;
  - where the mesh steps and the network does not, the mesh's (a seam between
    its flat patches) is ignored: the network's gradient stays;
  - with --cloud, a step the fused cloud bears out (something nearer by --tau
    within a few px of its near side, after cloud_depth.py's filters) stays:
    the lamp post beside MASS 84's walkway is in the cloud and not the mesh,
    and is as wide as the rock wall's made-up slabs, which the cloud has as
    a smooth wall;
  - a network step of more than --keep-above of the value stays whatever the
    mesh says, and with --thin so does any step beside a thin near thing (one
    nearer than round it by 10% and gone after an opening --thin px across):
    rails, posts and slats the mesh never had, whose steps off the wall behind
    are about a slab's.
The depth is then the one whose gradients are those, held to the mesh with
weight --lam where the mesh is reliable (so a face the network put at the
wrong distance overall, MASS 84's face 3, comes to the mesh's) and very
weakly to the network's own depth elsewhere: a sparse linear solve (scipy).
The six faces are blended at their seams (node_depth.feather, --band px) and
written in the site's encoding with r_far set from the new depth, beyond it
the farthest level, never the sky. Needs numpy, Pillow, opencv-python, scipy;
node_depth.py beside it.
"""
import argparse
import json
import os
import sys

import cv2
import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from node_depth import edge_pairs, feather  # noqa: E402

RATIO = 20.0


def steps_of(q, tau):
    """Pairs (i, i+1) along x and along y where q changes by more than tau of
    its value over the two pixels either side, and the relative size."""
    out = []
    for ax in (1, 0):
        prev = np.roll(q, 1, ax); nxt2 = np.roll(q, -2, ax)
        nxt = np.roll(q, -1, ax)
        lo = np.maximum(np.minimum(prev, nxt2), 1e-9)
        rel = np.abs(nxt2 - prev) / lo
        rel1 = np.abs(nxt - q) / np.maximum(np.minimum(q, nxt), 1e-9)
        size = np.maximum(rel, rel1)
        out.append((size > tau, size))
    return out


def cloud_q(xyz, R, t, N, norm, r_far, scale, q, mask, window=5, behind=0.6, gate=2.5):
    """The fused cloud projected into a face (nearest point a pixel), in q, with
    cloud_depth.py's filters: not behind a nearer point within window px, not
    more than gate times off q, not under mask."""
    Y = xyz @ R.T + t
    Y = Y[Y[:, 2] > 1e-3]
    x = Y[:, 0] / Y[:, 2]; y = Y[:, 1] / Y[:, 2]
    k = (np.abs(x) < 1) & (np.abs(y) < 1)
    Y, x, y = Y[k], x[k], y[k]
    px = np.clip(((x + 1) * N / 2).astype(int), 0, N - 1); py = np.clip(((y + 1) * N / 2).astype(int), 0, N - 1)
    z = np.full((N, N), np.inf); np.minimum.at(z, (py, px), Y[:, 2])
    qc = np.where(np.isfinite(z), r_far / (np.where(np.isfinite(z), z, 1) * norm / scale), 0.0)
    has = (qc > 0) & mask
    near = cv2.dilate(np.where(has, qc, 0).astype(np.float32), np.ones((window, window), np.uint8))
    has &= qc >= behind * near
    has &= np.abs(np.log(np.maximum(qc, 1e-9) / np.maximum(q, 1e-9))) < np.log(gate)
    return np.where(has, qc, 0.0)


def seam_fit(faces, report, names, N, below, min_pairs=40):
    """A face the mesh barely covers keeps its depth's shape but takes its level
    from its neighbours: one factor on its distances, the median ratio of the
    neighbour's distance to its own across every seam where both have depth (so
    the sky, on both sides of most of a top face's seams, does not vote). Faces
    are fitted most covered first, and each fitted face then counts as a
    neighbour. MASS 89's top face, 5% covered: the network put the roof corner
    and its insignia far off, so the insignia stood still as the eye moved,
    while on the walls beside it the roof is near."""
    pairs = edge_pairs(N, N)
    order = sorted(range(1, 7), key=lambda k: -report[names[k - 1]]['mesh_good'])
    done = [k for k in order if report[names[k - 1]]['mesh_good'] >= below]
    for k in [k for k in order if k not in done]:
        ratios = []
        for (kk, edge), e in pairs.items():
            if kk != k:
                continue
            v, u, j, v2, u2 = e.T
            r1 = faces[k]['r'][v, u]
            r2 = np.array([faces[jj]['r'][vv, uu] if jj in done else np.inf for jj, vv, uu in zip(j, v2, u2)])
            ok = np.isfinite(r1) & np.isfinite(r2)
            ratios.append(r2[ok] / r1[ok])
        ratios = np.concatenate(ratios) if ratios else np.zeros(0)
        name = names[k - 1]
        if len(ratios) >= min_pairs:
            f = float(np.median(ratios))
            faces[k]['r'] = faces[k]['r'] * f
            report[name]['seam_factor'] = f
            print(f'{name}: mesh reliable on {report[name]["mesh_good"] * 100:.1f}%: distances times {f:.2f} '
                  f'to meet its neighbours at {len(ratios)} seam pixels', flush=True)
        else:
            print(f'{name}: too few seam pixels with depth on both sides ({len(ratios)}); left as it is', flush=True)
        done.append(k)


def solve(q, gx, gy, wx, wy, anchor, wa):
    """The field whose differences are gx, gy (weights wx, wy) and which is held
    to anchor with weights wa."""
    import scipy.sparse as sp
    import scipy.sparse.linalg as spl
    H, W = q.shape
    n = H * W
    idx = np.arange(n).reshape(H, W)
    rows, cols, vals, b = [], [], [], np.zeros(n)
    for (a0, b0, g, w) in ((idx[:, :-1], idx[:, 1:], gx[:, :-1], wx[:, :-1]), (idx[:-1, :], idx[1:, :], gy[:-1, :], wy[:-1, :])):
        i, j, g, w = a0.ravel(), b0.ravel(), g.ravel(), w.ravel()
        m = w > 0
        i, j, g, w = i[m], j[m], g[m], w[m]
        rows += [i, j, i, j]; cols += [i, j, j, i]; vals += [w, w, -w, -w]
        np.add.at(b, j, w * g); np.add.at(b, i, -w * g)        # q_j - q_i = g
    A = sp.csr_matrix((np.concatenate(vals), (np.concatenate(rows), np.concatenate(cols))), shape=(n, n))
    A = A + sp.diags(wa.ravel() + 1e-9)
    x = spl.spsolve(A.tocsc(), b + wa.ravel() * anchor.ravel())
    return x.reshape(H, W)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('site'); ap.add_argument('out')
    ap.add_argument('--names', nargs=6, required=True); ap.add_argument('--mesh', required=True)
    ap.add_argument('--node-depth', required=True)
    ap.add_argument('--tau', type=float, default=0.1); ap.add_argument('--keep-above', type=float, default=0.5)
    ap.add_argument('--max-span', type=float, default=0.3); ap.add_argument('--lam', type=float, default=0.01)
    ap.add_argument('--thin', type=int, default=0, help='protect the steps of thin near things this many px across (0: off)')
    ap.add_argument('--cloud', help='a fused cloud (fused.ply): a network step the cloud bears out is kept')
    ap.add_argument('--sparse', help="with --cloud: the cloud's text model, with the node's faces (f<k>/MA-<node>.jpg)")
    ap.add_argument('--scale', type=float, default=1.0, help="with --cloud: the model's units in the site depth's")
    ap.add_argument('--seam-fit-below', type=float, default=0.0,
                    help='a face the mesh is reliable on less of than this share takes its level from its neighbours at the seams (seam_fit)')
    ap.add_argument('--masks'); ap.add_argument('--node')
    ap.add_argument('--prefix', default='MA-', help="the node's pictures in the model are f<k>/<prefix><node>.jpg (ENSI-, LEIS-)")
    ap.add_argument('--band', type=int, default=48)
    ap.add_argument('--depth-suffix', default='_measured-depth.png')
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    r_far = json.load(open(a.node_depth))['r_far']
    faces, report = {}, {}
    poses, xyz = {}, None
    if a.cloud:
        from node_depth import qvec2rot, read_ply_xyz
        want = {f'f{k}/{a.prefix}{a.node}.jpg': k for k in range(1, 7)}
        with open(os.path.join(a.sparse, 'images.txt')) as fh:
            for line in fh:
                p = line.split()
                if len(p) >= 10 and p[9] in want:
                    poses[want[p[9]]] = (qvec2rot(np.array(p[1:5], float)), np.array(p[5:8], float))
        xyz = read_ply_xyz(a.cloud)
    for k, name in enumerate(a.names, 1):
        d8 = np.asarray(Image.open(os.path.join(a.site, name + a.depth_suffix)).convert('L')).astype(np.float64)
        N = d8.shape[0]
        u = (np.arange(N) + .5) / N * 2 - 1
        xx, yy = np.meshgrid(u, u)
        norm = np.sqrt(1 + xx ** 2 + yy ** 2)
        sky = d8 == 0
        q = np.where(sky, 1.0, 1 + (RATIO - 1) * d8 / 255)       # the sky held at the farthest level
        zm = np.load(os.path.join(a.mesh, f'{name}_mesh-z.npy')).astype(np.float64)
        span = np.load(os.path.join(a.mesh, f'{name}_mesh-span.npy'))
        if zm.shape[0] != N:
            zm = cv2.resize(zm, (N, N), interpolation=cv2.INTER_NEAREST); span = cv2.resize(span, (N, N), interpolation=cv2.INTER_NEAREST)
        good = (zm > 0) & (span < a.max_span) & ~sky
        mmask = np.ones((N, N), bool)
        if a.masks and a.node:
            mp = os.path.join(a.masks, f'f{k}', f'{a.prefix}{a.node}.jpg.png')
            if os.path.exists(mp):
                mmask = np.asarray(Image.open(mp).convert('L').resize((N, N), Image.NEAREST)) > 127
                good &= mmask
        qm = np.where(good, r_far / np.maximum(zm * norm, 1e-9), 0.0)
        (sn_x, sz_x), (sn_y, sz_y) = steps_of(q, a.tau)
        (sm_x, _), (sm_y, _) = steps_of(np.where(good, qm, q), a.tau)
        gx = np.roll(q, -1, 1) - q; gy = np.roll(q, -1, 0) - q
        gmx = np.roll(qm, -1, 1) - qm; gmy = np.roll(qm, -1, 0) - qm
        okx = good & np.roll(good, -1, 1); oky = good & np.roll(good, -1, 0)
        # the network's steps the mesh does not have, and are not big: the mesh's gradient there
        fx = sn_x & ~sm_x & okx & (sz_x < a.keep_above)
        fy = sn_y & ~sm_y & oky & (sz_y < a.keep_above)
        if a.cloud:
            # a step the cloud bears out stays: something near, by tau, within a few px
            # of the step's near side (a lamp post the mesh lost is in the cloud; a
            # slab Depth Anything made up is not: there the cloud has a smooth wall)
            if k in poses:
                qc = cloud_q(xyz, *poses[k], N, norm, r_far, a.scale, q, ~sky & mmask)
                near_c = cv2.dilate(qc.astype(np.float32), np.ones((7, 7), np.uint8))
                for f_, ax in ((fx, 1), (fy, 0)):
                    nb = np.roll(q, -1, ax)
                    far_q = np.minimum(q, nb)
                    near_px = np.where(q >= nb, near_c, np.roll(near_c, -1, ax))
                    f_ &= ~(near_px >= far_q * (1 + a.tau))
                kept_c = int(fx.sum() + fy.sum())
        if a.thin > 0:
            # not beside thin near things (nearer than round them by 10%, gone after an
            # opening --thin px across): an overhead rail or a lamp post steps off the wall
            # behind it by about what a slab does, and the mesh never had it
            qf = q.astype(np.float32)
            loc = cv2.medianBlur(np.clip(qf * 10, 0, 255).astype(np.uint8), 31).astype(np.float32) / 10
            nearer = ((qf > 1.1 * np.maximum(loc, 1e-3)) & ~sky).astype(np.uint8)
            kk = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (a.thin, a.thin))
            thin = (nearer > 0) & ~(cv2.morphologyEx(nearer, cv2.MORPH_OPEN, kk) > 0)
            thin = cv2.dilate(thin.astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
            fx &= ~(thin | np.roll(thin, -1, 1)); fy &= ~(thin | np.roll(thin, -1, 0))
        gx = np.where(fx, gmx, gx); gy = np.where(fy, gmy, gy)
        wx = np.ones_like(q); wy = np.ones_like(q)
        wx[:, -1] = 0; wy[-1, :] = 0
        wx[sky | np.roll(sky, -1, 1)] = 0.01; wy[sky | np.roll(sky, -1, 0)] = 0.01     # loose against the sky
        anchor = np.where(good, qm, q)
        wa = np.where(good, a.lam, 1e-4)
        wa[sky] = 1.0
        qn = solve(q, gx, gy, wx, wy, anchor, wa)
        qn = np.where(sky, 0.0, np.maximum(qn, 1e-3))
        flat = int(fx.sum() + fy.sum())
        report[name] = {'flattened_pairs': flat, 'mesh_good': float(good.mean())}
        print(f'{name}: mesh reliable on {good.mean() * 100:.1f}%; {flat} network steps the mesh does not have flattened', flush=True)
        faces[k] = {'r': np.where(qn > 0, r_far / np.maximum(qn, 1e-12), np.inf), 'name': name}
    if a.seam_fit_below > 0:
        seam_fit(faces, report, a.names, N, a.seam_fit_below)
    feather(faces, N, N, a.band)
    allr = np.concatenate([f['r'][::4, ::4].ravel() for f in faces.values()])
    allr = allr[np.isfinite(allr)]
    r_far_new = float(RATIO * np.percentile(allr, 0.5))
    for k, f in faces.items():
        qn = np.where(np.isfinite(f['r']), r_far_new / f['r'], 0.0)
        d = np.clip((qn - 1) / (RATIO - 1), 0, 1)
        out8 = np.where(qn > 0, np.maximum(np.rint(d * 255), 1), 0).astype(np.uint8)
        Image.fromarray(out8).save(os.path.join(a.out, f['name'] + a.depth_suffix))
    with open(os.path.join(a.out, 'agree_depth.json'), 'w') as fh:
        json.dump({'r_far': r_far_new, 'r_far_before': r_far, 'tau': a.tau, 'keep_above': a.keep_above,
                   'max_span': a.max_span, 'lam': a.lam, 'faces': report}, fh, indent=1)
    print(f'r_far {r_far:.4f} before, {r_far_new:.4f} now')


if __name__ == '__main__':
    main()
