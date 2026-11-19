#!/usr/bin/env python3
r"""
Two walks in the two-fisheye layout mixed by angle from the line of travel: OTHER kept whole near the two circles'
centres (straight ahead and straight behind, within FROM degrees), BASE beyond TO degrees, a smooth fade between.
For a walk drawn as walk_ends.py --polar, whose poles (the circles' centres) are smeared, with the centres taken
from a two-circle walk.

    python pole_blend.py BASE_DIR OTHER_DIR OUT_DIR --fade 35 55 [--dual 180] [--fill-square] [--squash 0.35]

Writes OUT_DIR/0000.png ... Needs numpy, opencv-python.
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
    ap.add_argument('base'); ap.add_argument('other'); ap.add_argument('out')
    ap.add_argument('--fade', type=float, nargs=2, default=[35.0, 55.0], metavar=('FROM', 'TO'))
    ap.add_argument('--dual', type=float, default=180.0); ap.add_argument('--fill-square', action='store_true')
    ap.add_argument('--squash', type=float, default=0.0)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    pb = sorted(glob.glob(os.path.join(a.base, '*.png'))); po = sorted(glob.glob(os.path.join(a.other, '*.png')))
    if len(pb) != len(po):
        raise SystemExit(f'{len(pb)} frames against {len(po)}')
    H, W = cv2.imread(pb[0]).shape[:2]; S = W // 2
    lo, hi = np.radians(a.fade)
    w = []
    for s in (0, 1):
        _, E = pixel_dirs(S, a.dual, a.fill_square, a.squash, s)
        ax = np.pi / 2 - np.abs(np.nan_to_num(E, nan=0.0))          # angle from straight ahead or straight behind
        t = np.clip((hi - ax) / (hi - lo), 0, 1)
        w.append((t * t * (3 - 2 * t)).astype(np.float32)[..., None])
    wt = np.concatenate(w, 1)
    for b, o in zip(pb, po):
        B = cv2.imread(b).astype(np.float32); O = cv2.imread(o).astype(np.float32)
        cv2.imwrite(os.path.join(a.out, os.path.basename(b)), np.clip(np.rint(B + wt * (O - B)), 0, 255).astype(np.uint8))
    print(f'{len(pb)} frames -> {a.out}')


if __name__ == '__main__':
    main()
