#!/usr/bin/env python3
r"""
A walk drawn as walk_ends.py --polar (equirectangular, poles straight ahead and behind) redrawn as the two-fisheye
layout the viewer and seam tools take (draw_dual_fisheye: front left, back right).

    python polar_to_dual.py POLAR_DIR OUT_DIR [--pad 20] [--join down|up] [--size 2560x1280] [--dual 180] [--fill-square] [--squash 0.35]

The PAD repeated at the picture's sides is mixed with the other copy of the same directions, fading across it, so
the join shows no line. --join up: the walk was drawn with walk_ends.py --polar-join up (ground in the middle). Writes OUT_DIR/0000.png ... Needs numpy, opencv-python.
"""
import argparse
import glob
import os
import sys

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from seam_fix import pixel_dirs  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('polar'); ap.add_argument('out')
    ap.add_argument('--pad', type=float, default=20.0); ap.add_argument('--size', default='2560x1280')
    ap.add_argument('--dual', type=float, default=180.0); ap.add_argument('--fill-square', action='store_true')
    ap.add_argument('--squash', type=float, default=0.0); ap.add_argument('--join', choices=['down', 'up'], default='down')
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    paths = sorted(glob.glob(os.path.join(a.polar, '*.png')))
    H, W = cv2.imread(paths[0]).shape[:2]
    OW, OH = (int(x) for x in a.size.split('x')); S = OW // 2
    half = np.pi + np.radians(a.pad); P = np.radians(a.pad)
    maps = []
    for s in (0, 1):
        A, E = pixel_dirs(S, a.dual, a.fill_square, a.squash, s)
        A = np.nan_to_num(A); E = np.nan_to_num(E, nan=0.0)
        q = np.stack([np.cos(E) * np.cos(A), np.cos(E) * np.sin(A), np.sin(E)], -1)   # camera: x right, y down, z ahead
        g = 1.0 if a.join == 'down' else -1.0
        th = np.arccos(np.clip(q[..., 2], -1, 1)); ph = np.arctan2(g * q[..., 0], -g * q[..., 1])
        y = (th / np.pi * H - .5).astype(np.float32)
        x1 = ((ph / half + 1) / 2 * W - .5).astype(np.float32)                         # the copy within 180 degrees
        ph2 = ph - np.sign(ph) * 2 * np.pi                                              # the other copy, if in the pad
        x2 = ((ph2 / half + 1) / 2 * W - .5).astype(np.float32)
        w2 = np.clip((np.abs(ph) - (np.pi - P)) / (2 * P), 0, 1) * (np.abs(ph2) <= half)  # 0 at 180-PAD, 0.5 at 180
        w2 = (w2 * w2 * (3 - 2 * w2)).astype(np.float32)[..., None]
        maps.append((x1, x2, y, w2))
    for i, p in enumerate(paths):
        im = cv2.imread(p); out = np.zeros((OH, OW, 3), np.uint8)
        for s, (x1, x2, y, w2) in enumerate(maps):
            a1 = cv2.remap(im, x1, y, cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE).astype(np.float32)
            a2 = cv2.remap(im, x2, y, cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE).astype(np.float32)
            out[:, s * S:(s + 1) * S] = np.clip(np.rint(a1 + w2 * (a2 - a1)), 0, 255).astype(np.uint8)
        cv2.imwrite(os.path.join(a.out, f'{i:04d}.png'), out)
    print(f'{len(paths)} frames -> {a.out}')


if __name__ == '__main__':
    main()
