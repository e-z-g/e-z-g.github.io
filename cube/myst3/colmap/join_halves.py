#!/usr/bin/env python3
r"""
Two overlapping runs of a walk's frames joined into one, crossfaded over the frames they share.

    python join_halves.py FIRST_DIR SECOND_DIR OUT_DIR --start 17

SECOND_DIR's frame 0 is FIRST_DIR's frame --start; the frames from there to FIRST_DIR's last are in both and are
mixed, from all FIRST at the start of the overlap to all SECOND at its end. Writes OUT_DIR/0000.png ... Needs numpy,
opencv-python.
"""
import argparse
import glob
import os

import cv2
import numpy as np


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('first'); ap.add_argument('second'); ap.add_argument('out'); ap.add_argument('--start', type=int, required=True)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    fa = sorted(glob.glob(os.path.join(a.first, '*.png'))); fb = sorted(glob.glob(os.path.join(a.second, '*.png')))
    n = len(fa) - a.start                                    # frames in both
    k = 0
    for i in range(a.start):
        cv2.imwrite(os.path.join(a.out, f'{k:04d}.png'), cv2.imread(fa[i])); k += 1
    for j in range(n):
        t = (j + 1) / (n + 1)
        m = (1 - t) * cv2.imread(fa[a.start + j]).astype(np.float32) + t * cv2.imread(fb[j]).astype(np.float32)
        cv2.imwrite(os.path.join(a.out, f'{k:04d}.png'), np.clip(np.rint(m), 0, 255).astype(np.uint8)); k += 1
    for j in range(n, len(fb)):
        cv2.imwrite(os.path.join(a.out, f'{k:04d}.png'), cv2.imread(fb[j])); k += 1
    print(f'{k} frames -> {a.out}')


if __name__ == '__main__':
    main()
