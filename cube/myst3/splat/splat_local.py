#!/usr/bin/env python3
"""
A COLMAP dataset for a Gaussian splat of a small area: the pictures taken near
a walk between nodes, for a splat that is to look like the nodes' own pictures
at the nodes and carry the walk between them.

    python splat_local.py SPARSE_TXT IMAGES TRUSTED MOVES.json FUSED.ply GHOSTS.ply OUT
        --nodes 4084 4089 [--radius 5] [--repeat 4] [--movies lemt mass11090]
        [--masks MASKS] [--voxel 0.02] [--far-voxel 0.2]

As splat_dataset.py (images/, masks/ black on the sky, sparse/0/*.txt, names
made flat), but keeping only the node faces (of trusted and moved nodes) and
movie frames taken within --radius of the middle of the --nodes, and each
face of the --nodes themselves --repeat more times under other names, so
training sees them that much more often and holds them tightest. Starting
points: FUSED without GHOSTS, one per --voxel cell within twice --radius and
one per --far-voxel cell beyond (the far scenery the walk looks out at).
With --sky-only the masks are kept only above the horizon: Amateria's
also take in the water, which a walk beside it needs trained. Needs numpy
(and Pillow with --sky-only); ghost_points.py in ../colmap. Run pad_small.py on images/ after it.
"""
import argparse
import json
import os
import re
import shutil
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'colmap'))
from ghost_points import read_ply  # noqa: E402


def qrot(q):
    w, x, y, z = q
    return np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)],
                     [2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)],
                     [2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)]])


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    for k in ('sparse_txt', 'images', 'trusted', 'moves', 'fused', 'ghosts', 'out'):
        ap.add_argument(k)
    ap.add_argument('--nodes', nargs='+', required=True)
    ap.add_argument('--radius', type=float, default=5.0); ap.add_argument('--repeat', type=int, default=4)
    ap.add_argument('--movies', nargs='*', default=['lemt', 'mass11090'])
    ap.add_argument('--masks'); ap.add_argument('--voxel', type=float, default=0.02)
    ap.add_argument('--far-voxel', type=float, default=0.2)
    ap.add_argument('--invert-masks', action='store_true',
                    help='with --masks: also write masks_brush/ with the masks inverted (white on what to ignore), '
                         'the way Brush reads them: trained with masks/ (black on the sky), the solid scene was left '
                         'untrained (a splat of two nodes reached 16.6 dB at its own training view, 29.1 without masks)')
    ap.add_argument('--sky-only', action='store_true',
                    help='with --masks: mask only above the horizon (the masks also take in water, which a walk over it needs)')
    a = ap.parse_args()
    good = set(re.findall(r'MA-\d+', open(a.trusted).read())) | set(json.load(open(a.moves)))
    lines = [l for l in open(os.path.join(a.sparse_txt, 'images.txt')) if not l.startswith('#')]
    heads = [l.split() for l in lines[0::2] if len(l.split()) >= 10]
    centre = lambda p: -qrot(np.array(p[1:5], float)).T @ np.array(p[5:8], float)
    poses = {p[9]: p for p in heads}
    mids = [centre(poses[f'f1/MA-{n}.jpg']) for n in a.nodes]
    mid = np.mean(mids, 0)
    kept = []
    for p in heads:
        name = p[9]
        m = re.fullmatch(r'f\d/(MA-\d+)\.jpg', name)
        if not ((m and m.group(1) in good) or name.split('/')[0] in a.movies):
            continue
        if np.linalg.norm(centre(p) - mid) <= a.radius:
            kept.append(p[:10])
    own = [p for p in kept if re.fullmatch(r'f\d/MA-(%s)\.jpg' % '|'.join(a.nodes), p[9])]
    flat = lambda name: name.replace('/', '_')
    out_lines, copies = [], []
    next_id = max(int(p[0]) for p in heads) + 1
    for p in kept:
        q = list(p); q[9] = flat(p[9]); out_lines.append(q); copies.append((p[9], q[9]))
    for r in range(a.repeat):
        for p in own:
            q = list(p); q[0] = str(next_id); next_id += 1
            q[9] = f'again{r + 1}_' + flat(p[9]); out_lines.append(q); copies.append((p[9], q[9]))
    os.makedirs(os.path.join(a.out, 'sparse', '0'), exist_ok=True)
    os.makedirs(os.path.join(a.out, 'images'), exist_ok=True)
    if a.masks:
        os.makedirs(os.path.join(a.out, 'masks'), exist_ok=True)
        if a.invert_masks:
            os.makedirs(os.path.join(a.out, 'masks_brush'), exist_ok=True)
    shutil.copy(os.path.join(a.sparse_txt, 'cameras.txt'), os.path.join(a.out, 'sparse', '0', 'cameras.txt'))
    with open(os.path.join(a.out, 'sparse', '0', 'images.txt'), 'w') as f:
        for q in out_lines:
            f.write(' '.join(q) + '\n0 0 -1\n')
    up = None
    if a.sky_only:
        # the model's up: minus the y axis of the first node's face 1 camera (y points down in a COLMAP image)
        up = -qrot(np.array(poses[f'f1/MA-{a.nodes[0]}.jpg'][1:5], float))[1]
        cams = {}
        for l in open(os.path.join(a.sparse_txt, 'cameras.txt')):
            if not l.startswith('#') and l.strip():
                c = l.split(); v = [float(x) for x in c[4:]]
                # (f, cx, cy) whichever model: SIMPLE_* give f cx cy, PINHOLE and OPENCV fx fy cx cy
                cams[c[0]] = (v[0], v[1], v[2]) if c[1].startswith('SIMPLE') else (v[0], v[2], v[3])
    for src, dst in copies:
        shutil.copy(os.path.join(a.images, src), os.path.join(a.out, 'images', dst))
        if a.masks:
            mp = os.path.join(a.masks, src + '.png')
            if not os.path.exists(mp):
                continue
            if up is None:
                shutil.copy(mp, os.path.join(a.out, 'masks', os.path.splitext(dst)[0] + '.png'))
                continue
            from PIL import Image
            m = np.asarray(Image.open(mp).convert('L')).copy()
            p = poses[src]
            Rm = qrot(np.array(p[1:5], float))
            prm = cams[p[8]]
            H, W = m.shape
            f, cx, cy = prm
            v, u = np.mgrid[0:H, 0:W]
            d = np.stack([(u + .5 - cx) / f, (v + .5 - cy) / f, np.ones_like(u, float)], -1) @ Rm
            m[(d @ up) <= 0] = 255                 # below the horizon: water and its reflections are trained on
            Image.fromarray(m).save(os.path.join(a.out, 'masks', os.path.splitext(dst)[0] + '.png'))
    A = read_ply(a.fused); G = read_ply(a.ghosts)
    key = lambda P: np.stack([P['x'], P['y'], P['z']], 1).astype(np.float32).view(np.uint32).reshape(-1, 3).astype(np.uint64)
    h = lambda k: k[:, 0] * np.uint64(1000003) ^ (k[:, 1] << np.uint64(21)) ^ (k[:, 2] << np.uint64(42))
    A = A[~np.isin(h(key(A)), h(key(G)))]
    xyz = np.stack([A['x'], A['y'], A['z']], 1).astype(np.float64)
    rgb = np.stack([A['red'], A['green'], A['blue']], 1)
    near = np.linalg.norm(xyz - mid, axis=1) <= 2 * a.radius
    pts = []
    for sel, vox in ((near, a.voxel), (~near, a.far_voxel)):
        v = np.floor(xyz[sel] / vox).astype(np.int64)
        _, first = np.unique(v, axis=0, return_index=True)
        pts.append((xyz[sel][first], rgb[sel][first]))
    P = np.concatenate([p for p, _ in pts]); Cc = np.concatenate([c for _, c in pts])
    with open(os.path.join(a.out, 'sparse', '0', 'points3D.txt'), 'w') as f:
        for i, (p, c) in enumerate(zip(P, Cc), 1):
            f.write(f'{i} {p[0]:.5f} {p[1]:.5f} {p[2]:.5f} {int(c[0])} {int(c[1])} {int(c[2])} 0\n')
    if a.masks and a.invert_masks:
        from PIL import Image, ImageOps
        md = os.path.join(a.out, 'masks')
        for f in os.listdir(md):
            ImageOps.invert(Image.open(os.path.join(md, f)).convert('L')).save(os.path.join(a.out, 'masks_brush', f))
    # Brush 0.3.0 needs every image to be at least 16387 bytes: run pad_small.py on images/ after this
    movies = sum(1 for p in kept if not p[9].startswith('f'))
    print(f'middle {np.round(mid, 3)}: {len(kept)} pictures within {a.radius} ({movies} movie frames), '
          f'{len(own)} of the nodes\' faces repeated {a.repeat} more times; {len(P)} starting points')
    with open(os.path.join(a.out, 'local.json'), 'w') as f:
        json.dump({'nodes': a.nodes, 'middle': mid.tolist(), 'radius': a.radius,
                   'centres': {n: c.tolist() for n, c in zip(a.nodes, mids)}}, f, indent=1)


if __name__ == '__main__':
    main()
