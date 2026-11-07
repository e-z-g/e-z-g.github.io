#!/usr/bin/env python3
"""
Look at a fused point cloud of a Myst III room: a plan from above, and the view
from a node's own centre set beside the node's real face, so the two can be
compared picture for picture.

    python render_cloud.py FUSED.ply SPARSE_TXT_DIR OUT_DIR [NODE ...]

SPARSE_TXT_DIR is the sparse model the cloud was made from, as text (its
images.txt gives each face's pose); IMAGES next to it is not needed: the real
faces are read from the path in --images. Writes OUT_DIR/plan.png and, per node,
OUT_DIR/node-<n>.png: for each of the six faces, the real face above and the
cloud seen from the same camera below (points splatted 2x2 with a depth test,
black where nothing landed). The share of a face's pixels the cloud covers and
their mean colour difference from the real face are printed.

Needs numpy and Pillow.
"""
import argparse
import os
import re
import sys

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from evaluate_model import qvec2rot  # noqa: E402


def read_ply(path):
    with open(path, 'rb') as fh:
        props, n = [], 0
        while True:
            line = fh.readline().decode().strip()
            if line.startswith('element vertex'):
                n = int(line.split()[-1])
            elif line.startswith('property'):
                _, t, name = line.split()
                props.append((name, {'float': '<f4', 'double': '<f8', 'uchar': 'u1', 'int': '<i4'}[t]))
            elif line == 'end_header':
                break
        data = np.frombuffer(fh.read(n * np.dtype(props).itemsize), dtype=props, count=n)
    xyz = np.stack([data['x'], data['y'], data['z']], 1).astype(np.float64)
    rgb = np.stack([data['red'], data['green'], data['blue']], 1)
    return xyz, rgb


def read_images(txt_dir):
    out = {}
    lines = [l for l in open(os.path.join(txt_dir, 'images.txt')) if not l.startswith('#')]
    for l in lines[::2]:
        p = l.split()
        if len(p) >= 10:
            out[p[-1]] = (qvec2rot([float(v) for v in p[1:5]]), np.array([float(v) for v in p[5:8]]))
    return out


def render(xyz, rgb, R, t, size=640, f=320.0):
    cam = xyz @ R.T + t
    z = cam[:, 2]
    keep = z > 1e-3
    u = f * cam[keep, 0] / z[keep] + size / 2
    v = f * cam[keep, 1] / z[keep] + size / 2
    zc, col = z[keep], rgb[keep]
    img = np.zeros((size, size, 3), np.uint8)
    depth = np.full((size, size), np.inf)
    order = np.argsort(-zc)                          # far first, near overwrite
    for du in (0, 1):
        for dv in (0, 1):
            x = (u[order] + du - 0.5).astype(int); y = (v[order] + dv - 0.5).astype(int)
            ok = (x >= 0) & (x < size) & (y >= 0) & (y < size)
            img[y[ok], x[ok]] = col[order][ok]
            depth[y[ok], x[ok]] = np.minimum(depth[y[ok], x[ok]], zc[order][ok])
    return img, np.isfinite(depth)


def plan(xyz, rgb, size=1400):
    # the up axis: the sparse model's own frame is arbitrary, so take the direction of
    # least spread of the points as up (the room is wider than it is tall)
    c = xyz - np.median(xyz, 0)
    lo, hi = np.percentile(c, 1, 0), np.percentile(c, 99, 0)
    keep = np.all((c > lo) & (c < hi), 1)
    c, col = c[keep], rgb[keep]
    _, _, vt = np.linalg.svd(c[::max(1, len(c) // 20000)], full_matrices=False)
    a, b, up = vt[0], vt[1], vt[2]
    P = np.stack([c @ a, c @ b], 1); h = c @ up
    span = (P.max(0) - P.min(0)).max()
    px = ((P - P.min(0)) / span * (size - 1)).astype(int)
    img = np.full((size, size, 3), 255, np.uint8)
    order = np.argsort(h * np.sign(np.median(h) - h.mean() + 1e-9))   # draw higher points last
    img[px[order, 1], px[order, 0]] = col[order]
    return img


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('ply'); ap.add_argument('sparse_txt'); ap.add_argument('out')
    ap.add_argument('nodes', nargs='*', type=int)
    ap.add_argument('--images', required=True, help='folder of the real faces (f<face>/<ROOM>-<node>.jpg)')
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    xyz, rgb = read_ply(a.ply)
    print(f'{len(xyz)} points')
    Image.fromarray(plan(xyz, rgb)).save(os.path.join(a.out, 'plan.png'))
    imgs = read_images(a.sparse_txt)
    for n in a.nodes:
        row_real, row_cloud = [], []
        for f in range(1, 7):
            name = next((k for k in imgs if re.fullmatch(rf'f{f}/.+-{n:04d}\.jpg', k)), None)
            if name is None:
                continue
            R, t = imgs[name]
            img, cov = render(xyz, rgb, R, t)
            real = np.asarray(Image.open(os.path.join(a.images, name)).convert('RGB'))
            diff = np.abs(real.astype(int) - img.astype(int))[cov].mean() if cov.any() else float('nan')
            print(f'node {n} face {f}: cloud covers {cov.mean() * 100:5.1f}% of the face, '
                  f'mean colour difference there {diff:5.1f}')
            row_real.append(real); row_cloud.append(img)
        sheet = np.vstack([np.hstack(row_real), np.hstack(row_cloud)])
        Image.fromarray(sheet).resize((sheet.shape[1] // 2, sheet.shape[0] // 2)).save(
            os.path.join(a.out, f'node-{n}.png'))


if __name__ == '__main__':
    main()
