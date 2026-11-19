#!/usr/bin/env python3
r"""
A walk moved between the two-fisheye layout (walk_ends.py draw_dual_fisheye: front left, back right) and a 5x3 grid
of cube faces: the four walls in a row round the line of travel (ahead, right, behind, left) and ahead again, the
sky above each wall and the floor below it, each turned to meet that wall (so every wall's top and bottom edges
join truly, and each wall its neighbours).

    python cube_grid.py to-grid DUAL_DIR_OR_PNG OUT [--size 2560x1536] [--dual 180] [--fill-square] [--squash 0.35]
    python cube_grid.py to-dual GRID_DIR OUT [--size 2560x1280] [--dual 180] [--fill-square] [--squash 0.35]

to-grid takes a folder of frames or one picture (OUT then a .png); to-dual a folder. Writes OUT/0000.png ...
Needs numpy, opencv-python.
"""
import argparse
import glob
import os
import sys

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import walk_ends as we  # noqa: E402
from seam_fix import pixel_dirs  # noqa: E402

R, D, F = np.eye(3)                                         # camera: x right, y down, z ahead
WALLS = [(R, F), (-F, R), (-R, -F), (F, -R), (R, F)]        # each wall's (cell right, cell forward)


def cells():
    """{(row, col): (x, y, z)}: each cell's right, down and forward axes."""
    ax = {}
    for c, (x, z) in enumerate(WALLS):
        y = D
        ax[(1, c)] = (x, y, z)
        ax[(0, c)] = (x, z, -y)                              # the sky beyond the wall's top edge
        ax[(2, c)] = (x, -z, y)                              # the floor beyond its bottom edge
    return ax


def grid_dirs(W, H):
    cw, ch = W // 5, H // 3
    v, u = np.mgrid[0:H, 0:W].astype(np.float64)
    r, c = np.minimum(v // ch, 2).astype(int), np.minimum(u // cw, 4).astype(int)
    a = ((u - c * cw) + .5) / cw * 2 - 1; b = ((v - r * ch) + .5) / ch * 2 - 1
    out = np.zeros((H, W, 3))
    for (rr, cc), (x, y, z) in cells().items():
        m = (r == rr) & (c == cc)
        out[m] = z + a[m, None] * x + b[m, None] * y
    return out / np.linalg.norm(out, axis=-1, keepdims=True)


def dual_xy(d, S, fov, fill, squash):
    """Directions (camera) to pixel positions in the two-fisheye picture of eyes S across."""
    back = d[..., 2] < 0
    q = np.where(back[..., None], d * np.array([-1, 1, -1]), d)
    th = np.arccos(np.clip(q[..., 2], -1, 1)); ph = np.arctan2(q[..., 1], q[..., 0])
    r = th / np.radians(fov / 2)
    x, y = r * np.cos(ph), r * np.sin(ph)
    if fill:
        x, y = we.disc_to_square(np.clip(x, -1, 1), np.clip(y, -1, 1))
    if squash:
        y = we.squash_y(y, squash)
    return ((x + 1) / 2 * S - .5 + back * S).astype(np.float32), ((y + 1) / 2 * S - .5).astype(np.float32)


def grid_xy(d, W, H):
    """Directions to pixel positions in the grid: walls on the middle row (ahead from column 0), sky and floor from the
    column of the wall they lie over."""
    cw, ch = W // 5, H // 3
    ax = cells()
    ang = np.arctan2(d[..., 0], d[..., 2])                   # turn round from ahead toward the right
    col = np.mod(np.rint(ang / (np.pi / 2)), 4).astype(int)
    k = np.argmax(np.abs(d), -1)
    row = np.where((k == 1) & (d[..., 1] < 0), 0, np.where((k == 1) & (d[..., 1] > 0), 2, 1))
    X = np.zeros(d.shape[:-1], np.float32); Y = np.zeros(d.shape[:-1], np.float32)
    for (rr, cc), (x, y, z) in ax.items():
        if cc == 4:
            continue
        m = (row == rr) & (col == cc)
        dz = d[m] @ z; a = (d[m] @ x) / dz; b = (d[m] @ y) / dz
        X[m] = (a + 1) / 2 * cw - .5 + cc * cw; Y[m] = (b + 1) / 2 * ch - .5 + rr * ch
    return X, Y


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('cmd', choices=['to-grid', 'to-dual']); ap.add_argument('src'); ap.add_argument('out')
    ap.add_argument('--size'); ap.add_argument('--dual', type=float, default=180.0)
    ap.add_argument('--fill-square', action='store_true'); ap.add_argument('--squash', type=float, default=0.0)
    a = ap.parse_args()
    paths = [a.src] if a.src.lower().endswith('.png') else sorted(glob.glob(os.path.join(a.src, '*.png')))
    h0, w0 = cv2.imread(paths[0]).shape[:2]
    if a.cmd == 'to-grid':
        W, H = (int(x) for x in (a.size or '2560x1536').split('x'))
        mx, my = dual_xy(grid_dirs(W, H), h0, a.dual, a.fill_square, a.squash)
    else:
        W, H = (int(x) for x in (a.size or '2560x1280').split('x')); S = W // 2
        ds = []
        for s in (0, 1):
            A, E = pixel_dirs(S, a.dual, a.fill_square, a.squash, s)
            A = np.nan_to_num(A); E = np.nan_to_num(E)
            ds.append(np.stack([np.cos(E) * np.cos(A), np.cos(E) * np.sin(A), np.sin(E)], -1))
        mx, my = grid_xy(np.concatenate(ds, 1), w0, h0)
    one = a.src.lower().endswith('.png')
    if not one:
        os.makedirs(a.out, exist_ok=True)
    for i, p in enumerate(paths):
        o = cv2.remap(cv2.imread(p), mx, my, cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)
        cv2.imwrite(a.out if one else os.path.join(a.out, f'{i:04d}.png'), o)
    print(f'{len(paths)} -> {a.out} ({W}x{H})')


if __name__ == '__main__':
    main()
