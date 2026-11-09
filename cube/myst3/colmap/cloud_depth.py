#!/usr/bin/env python3
"""
A site node's depth held to the model's fused point cloud: the cloud's points
where it has them, the existing depth's shape between them.

    python cloud_depth.py SITE OUT_DIR --names N1 ... N6 --node 4084
        --sparse SPARSE_TXT --cloud fused.ply --node-depth node_depth.json
        [--scale 1.089189] [--masks MASKS] [--window 15] [--behind 0.6]
        [--gate 3] [--lam 0.01] [--min-share 0.05] [--band 48]

SITE holds the node's six faces' depth (<name>_measured-depth.png,
node_depth.py's: d = (r_far / r - 1) / 19, r_far from --node-depth's report).
SPARSE_TXT is the text model the cloud is in (images.txt with the node's faces
as f<k>/MA-<node>.jpg); distances in it are --scale times the site depth's
(MASS 84's run was moved back into the model scaled by 1.089189).

For each face the cloud is projected (the nearest point in each pixel) and
filtered: a point goes if it lies well behind the nearer points round it
(r_far / r under --behind times the most within --window px: a point seen
through a gap in a near surface with few points of its own), if it is more
than --gate times nearer or farther than the existing depth (points from
behind the house where the house wall has none), and where --masks (sky_masks.py's,
black on sky, sea and water) blacks it out. The existing depth is then held
to the points left (node_depth.follow_stereo, weight --lam): a correction
smooth within each surface the depth drew and free across its steps; weak
(0.01), so a surface takes the mean of the many points on it and no single
point makes a bump (held at 1, every point's noise showed as blotches). A face
whose points left cover under --min-share of it is left as it was (the floor
and the sky). The six faces are blended at their seams over --band px
(node_depth.feather) and written in the same encoding with r_far set again
from the new depth (RATIO times its 0.5th percentile of distance), to
OUT_DIR, with a preview and a report (cloud_depth.json, whose r_far the
backdrop step reads).

Why: Depth Anything V2 draws MASS 84's rock wall as a slab per column (2.4 to
3.6 in r_far / r along one row of face 4); the fused cloud, the points that
several views agree on, has a wall receding smoothly (1.6 to 2.4). COLMAP's
single-view depth map, tried before, was wrong on the rails; the fused cloud
keeps only what views agree on.
Needs numpy, Pillow, opencv-python, scipy; node_depth.py beside it.
"""
import argparse
import json
import os
import sys

import cv2
import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from node_depth import feather, follow_stereo, qvec2rot, read_ply_xyz, seam_pairs  # noqa: E402

RATIO = 20.0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('site'); ap.add_argument('out')
    ap.add_argument('--names', nargs=6, required=True); ap.add_argument('--node', required=True)
    ap.add_argument('--sparse'); ap.add_argument('--cloud')
    ap.add_argument('--mesh', help="mesh_depth.py's folder (<name>_mesh-z.npy, _mesh-span.npy, in the site depth's units): "
                    'held to the mesh instead of the cloud')
    ap.add_argument('--max-span', type=float, default=0.3,
                    help="with --mesh: not where the hit triangle's longest edge spans more than this (radians): "
                         'a surface the mesher made up')
    ap.add_argument('--thin', type=int, default=0,
                    help='not on thin near things the depth draws (nearer than round them by 10%%, gone after an '
                         'opening this many px across; 0: off): the mesh and the cloud lose rails and posts')
    ap.add_argument('--node-depth', required=True)
    ap.add_argument('--scale', type=float, default=1.0)
    ap.add_argument('--masks')
    ap.add_argument('--window', type=int, default=15); ap.add_argument('--behind', type=float, default=0.6)
    ap.add_argument('--gate', type=float, default=3.0); ap.add_argument('--lam', type=float, default=0.01)
    ap.add_argument('--floor', type=float, default=1e-4,
                    help="weight between pixels across the depth's own steps (follow_stereo's floor): at 0.01, as "
                         "much as --lam, a slab's long edge outweighed the points on it and the slabs stayed")
    ap.add_argument('--min-share', type=float, default=0.05,
                    help='a face is held to the cloud only if the points left cover this share of what is not sky')
    ap.add_argument('--band', type=int, default=48)
    ap.add_argument('--depth-suffix', default='_measured-depth.png')
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    r_far = json.load(open(a.node_depth))['r_far']
    poses = {}
    want = {f'f{k}/MA-{a.node}.jpg': k for k in range(1, 7)}
    with open(os.path.join(a.sparse, 'images.txt')) if a.sparse else open(os.devnull) as fh:
        for line in fh:
            p = line.split()
            if len(p) >= 10 and p[9] in want:
                poses[want[p[9]]] = (qvec2rot(np.array(p[1:5], float)), np.array(p[5:8], float))
    if a.mesh:
        xyz = np.zeros((0, 3))
    else:
        xyz = read_ply_xyz(a.cloud)
        print(f'{len(xyz)} points; poses for faces {sorted(poses)}', flush=True)
    faces, report, tiles = {}, {}, []
    for k, name in enumerate(a.names, 1):
        d8 = np.asarray(Image.open(os.path.join(a.site, name + a.depth_suffix)).convert('L')).astype(np.float64)
        N = d8.shape[0]
        u = (np.arange(N) + .5) / N * 2 - 1
        xx, yy = np.meshgrid(u, u)
        norm = np.sqrt(1 + xx ** 2 + yy ** 2)
        q = np.where(d8 > 0, 1 + (RATIO - 1) * d8 / 255, 0.0)
        ok = q > 0
        qc = np.zeros((N, N))
        if k in poses:
            R, t = poses[k]
            Y = xyz @ R.T + t
            Y = Y[Y[:, 2] > 1e-3]
            x = Y[:, 0] / Y[:, 2]; y = Y[:, 1] / Y[:, 2]
            inside = (np.abs(x) < 1) & (np.abs(y) < 1)
            Y, x, y = Y[inside], x[inside], y[inside]
            px = np.clip(((x + 1) * N / 2).astype(int), 0, N - 1); py = np.clip(((y + 1) * N / 2).astype(int), 0, N - 1)
            z = np.full((N, N), np.inf)
            np.minimum.at(z, (py, px), Y[:, 2])
            hit = np.isfinite(z)
            qc[hit] = r_far / (z[hit] * norm[hit] / a.scale)
        if a.mesh:
            zm = np.load(os.path.join(a.mesh, f'{name}_mesh-z.npy')).astype(np.float64)
            span = np.load(os.path.join(a.mesh, f'{name}_mesh-span.npy'))
            if zm.shape[0] != N:
                zm = cv2.resize(zm, (N, N), interpolation=cv2.INTER_NEAREST); span = cv2.resize(span, (N, N), interpolation=cv2.INTER_NEAREST)
            qc = np.where((zm > 0) & (span < a.max_span), r_far / np.maximum(zm * norm, 1e-9), 0.0)
        has = (qc > 0) & ok
        if a.thin > 0:
            qf = q.astype(np.float32)
            loc = cv2.medianBlur(np.clip(qf * 10, 0, 255).astype(np.uint8), 31).astype(np.float32) / 10
            nearer = (ok & (qf > 1.1 * np.maximum(loc, 1e-3))).astype(np.uint8)
            kk = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (a.thin, a.thin))
            thin = (nearer > 0) & ~(cv2.morphologyEx(nearer, cv2.MORPH_OPEN, kk) > 0)
            has &= ~(cv2.dilate(thin.astype(np.uint8), np.ones((5, 5), np.uint8)) > 0)
        n0 = int(has.sum())
        if a.masks:
            mp = os.path.join(a.masks, f'f{k}', f'MA-{a.node}.jpg.png')
            if os.path.exists(mp):
                has &= np.asarray(Image.open(mp).convert('L').resize((N, N), Image.NEAREST)) > 127
        n1 = int(has.sum())
        if not a.mesh:                     # a mesh's rays stop at the first surface already
            nearest = cv2.dilate(np.where(has, qc, 0).astype(np.float32), np.ones((a.window, a.window), np.uint8))
            has &= qc >= a.behind * nearest
        n2 = int(has.sum())
        has &= np.abs(np.log(np.maximum(qc, 1e-9) / np.maximum(q, 1e-9))) < np.log(a.gate)
        n3 = int(has.sum())
        rec = {'cloud_pixels': n0, 'after_masks': n1, 'after_behind': n2, 'used': n3}
        if n3 >= a.min_share * max(int(ok.sum()), 1):
            before = np.abs(q[has] - qc[has]) / qc[has]
            qn, _ = follow_stereo(q, np.where(has, qc, 0.0), ok, has, lam=a.lam, floor=a.floor)
            after = np.abs(qn[has] - qc[has]) / qc[has]
            rec.update(before_median=float(np.median(before)), before_p90=float(np.percentile(before, 90)),
                       after_median=float(np.median(after)), after_p90=float(np.percentile(after, 90)))
            print(f'{name}: {n3} cloud points used of {n0} ({n1} past the masks, {n2} not behind a nearer one); '
                  f'off by median {np.median(before) * 100:.1f}%, 90% {np.percentile(before, 90) * 100:.1f}% before, '
                  f'{np.median(after) * 100:.1f}%, {np.percentile(after, 90) * 100:.1f}% after', flush=True)
        else:
            qn = q.copy()
            print(f'{name}: {n3} cloud points left, under {a.min_share:.0%} of the face; left as it was', flush=True)
        report[name] = rec
        faces[k] = {'r': np.where(qn > 0, r_far / np.maximum(qn, 1e-12), np.inf), 'has': has, 'name': name,
                    'followed': n3 >= a.min_share * max(int(ok.sum()), 1)}
    # A face left as it was (the floor, which no other node sees, so the old
    # depth only guessed it from its seams) no longer met its neighbours once
    # they were held to the cloud: MASS 84's track on face 3 came out far
    # nearer than the floor under it. It is held at its edges to them.
    pairs = seam_pairs(N, N)
    for k, f in faces.items():
        if f['followed']:
            continue
        okk = np.isfinite(f['r'])
        sv = np.zeros((N, N)); hk = np.zeros((N, N), bool)
        for (v, u, j, v2, u2) in pairs[k]:
            rj = faces[j]['r'][v2, u2]
            if faces[j]['followed'] and np.isfinite(rj) and okk[v, u]:
                sv[v, u] = r_far / rj; hk[v, u] = True
        if hk.sum() < 20:
            continue
        q0 = np.where(okk, r_far / np.where(okk, f['r'], 1.0), 0.0)
        q2, _ = follow_stereo(q0, sv, okk, hk, lam=1.0)
        f['r'] = np.where(okk & (q2 > 0), r_far / np.maximum(q2, 1e-12), np.inf)
        report[f['name']]['held_at_edges'] = int(hk.sum())
        print(f"{f['name']}: held at {int(hk.sum())} edge pixels to its neighbours", flush=True)
    feather(faces, N, N, a.band)
    # The cloud puts some things nearer than the old depth's nearest (MASS
    # 84's floor and track): written with the old r_far they clipped to one
    # flat white. r_far is set again as node_depth.py sets it, RATIO times
    # the 0.5th percentile of distance.
    allr = np.concatenate([f['r'][::4, ::4].ravel() for f in faces.values()])
    allr = allr[np.isfinite(allr)]
    r_far_new = float(RATIO * np.percentile(allr, 0.5))
    print(f'r_far {r_far:.4f} before, {r_far_new:.4f} now (in the site depth\'s units)', flush=True)
    for k, f in faces.items():
        qn = np.where(np.isfinite(f['r']), r_far_new / f['r'], 0.0)
        d = np.clip((qn - 1) / (RATIO - 1), 0, 1)
        # 0 is the sky: what lies beyond r_far is written as the farthest
        # level, 1, not as sky (with r_far set again nearer, the far pier
        # and sea MASS 84 looks out at had turned to sky)
        out8 = np.where(qn > 0, np.maximum(np.rint(d * 255), 1), 0).astype(np.uint8)
        Image.fromarray(out8).save(os.path.join(a.out, f['name'] + a.depth_suffix))
        old = np.asarray(Image.open(os.path.join(a.site, f['name'] + a.depth_suffix)).convert('L'))
        tiles.append(np.concatenate([old, np.where(f['has'], 255, 0).astype(np.uint8), out8], 1))
    Image.fromarray(np.concatenate(tiles, 0)).resize((3 * 320, 6 * 320)).save(os.path.join(a.out, 'preview.png'))
    with open(os.path.join(a.out, 'cloud_depth.json'), 'w') as fh:
        json.dump({'r_far': r_far_new, 'r_far_before': r_far, 'ratio': RATIO, 'scale': a.scale, 'cloud': a.cloud, 'mesh': a.mesh,
                   'faces': report}, fh, indent=1)


if __name__ == '__main__':
    main()
