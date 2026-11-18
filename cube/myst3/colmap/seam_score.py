#!/usr/bin/env python3
r"""
How well a two-fisheye walk's two pictures agree where they overlap: the seam.

    python seam_score.py FRAMES_DIR --dual 190 [--fill-square] [--squash A] [--every 1]

FRAMES_DIR holds the walk's frames (0000.png ...), drawn as walk_ends.py --dual-fisheye: two fisheyes of --dual
degrees side by side, ahead and behind, which overlap in a band (dual - 180) / 2 degrees either side of the ring
square to the walk. Directions spread evenly over that band are looked up in both pictures (bilinear); per frame:
the mean absolute difference of the colours (0-255) and of their fine detail (the picture less its 2 px blur), the
seam's misfit. A drawing straight from the game's faces scores near 0 (only resampling); the video model's
pictures disagree where it drew the two rims apart. Prints each frame and the walk's median and worst.
Needs numpy, opencv-python; walk_ends.py beside it.
"""
import argparse
import glob
import os
import sys

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import walk_ends as we  # noqa: E402


def maps(w, S, fov, fill, squash, side):
    """Picture coordinates (x, y in px) of walk-frame directions w (right, down, forward) in one eye."""
    q = w if side == 0 else w * np.array([-1, 1, -1])
    th = np.arccos(np.clip(q[:, 2], -1, 1)); ph = np.arctan2(q[:, 1], q[:, 0])
    r = th / np.radians(fov / 2)
    x, y = r * np.cos(ph), r * np.sin(ph)
    if fill:
        x, y = we.disc_to_square(x, y)
    if squash:
        y = we.squash_y(y, squash)
    return ((x + 1) / 2 * S + side * S - .5).astype(np.float32), ((y + 1) / 2 * S - .5).astype(np.float32)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('frames'); ap.add_argument('--dual', type=float, required=True)
    ap.add_argument('--fill-square', action='store_true'); ap.add_argument('--squash', type=float, default=0.0)
    ap.add_argument('--every', type=int, default=1)
    a = ap.parse_args()
    paths = sorted(glob.glob(os.path.join(a.frames, '*.png')))[::a.every]
    img0 = cv2.imread(paths[0]); H = img0.shape[0]; S = H
    band = np.radians((a.dual - 180) / 2)
    # directions over the band: around the ring every half pixel's worth, across it in 9 rows
    n = int(2 * np.pi * S / 2 / np.radians(a.dual / 2))
    az = np.linspace(-np.pi, np.pi, n, endpoint=False)
    el = np.linspace(-band, band, 9)
    A, E = np.meshgrid(az, el)
    w = np.stack([np.cos(A).ravel() * np.cos(E).ravel(), np.sin(A).ravel() * np.cos(E).ravel(), np.sin(E).ravel()], 1)
    mf, mb = maps(w, S, a.dual, a.fill_square, a.squash, 0), maps(w, S, a.dual, a.fill_square, a.squash, 1)
    hf = lambda g: g - cv2.GaussianBlur(g, (0, 0), 2)
    rows = []
    for p in paths:
        im = cv2.imread(p).astype(np.float32)
        f = cv2.remap(im, mf[0][None], mf[1][None], cv2.INTER_LINEAR)[0]
        b = cv2.remap(im, mb[0][None], mb[1][None], cv2.INTER_LINEAR)[0]
        g = cv2.cvtColor(im, cv2.COLOR_BGR2GRAY); h = hf(g)
        hf_f = cv2.remap(h, mf[0][None], mf[1][None], cv2.INTER_LINEAR)[0]
        hf_b = cv2.remap(h, mb[0][None], mb[1][None], cv2.INTER_LINEAR)[0]
        rows.append((os.path.basename(p), float(np.abs(f - b).mean()), float(np.abs(hf_f - hf_b).mean())))
    for nm, c, d in rows:
        print(f'  {nm}: colour {c:5.2f}  detail {d:5.2f}')
    C = np.array([r[1] for r in rows]); D = np.array([r[2] for r in rows])
    print(f'{a.frames}: seam colour median {np.median(C):.2f} worst {C.max():.2f}; detail median {np.median(D):.2f} worst {D.max():.2f}')


if __name__ == '__main__':
    main()
