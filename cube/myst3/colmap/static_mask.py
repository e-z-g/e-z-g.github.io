#!/usr/bin/env python3
"""
A mask of what moves with the camera in a movie (a cockpit, the bars of a glass
ball): pixels that hardly change while the scene behind them does.

    python static_mask.py FRAMES_DIR OUT_MASK.png [--sample 400] [--thr 12] [--grow 6]

Reads up to --sample frames spread over FRAMES_DIR, and per pixel the median
absolute difference between frames five samples apart (grey levels). Where that is
below --thr the pixel is taken as fixed to the camera; the mask (white = use,
black = ignore, as COLMAP wants) has those pixels, grown by --grow pixels, set
black. Also writes OUT_MASK-change.png, the change itself, to check by eye.
Needs numpy and opencv-python.
"""
import argparse
import os

import cv2
import numpy as np


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('frames'); ap.add_argument('out')
    ap.add_argument('--sample', type=int, default=400)
    ap.add_argument('--thr', type=float, default=12)
    ap.add_argument('--grow', type=int, default=6)
    a = ap.parse_args()
    names = sorted(os.listdir(a.frames))
    pick = names[::max(1, len(names) // a.sample)]
    F = np.stack([cv2.imread(os.path.join(a.frames, n), cv2.IMREAD_GRAYSCALE).astype(np.float32) for n in pick])
    change = np.median(np.abs(F[5:] - F[:-5]), axis=0)
    cv2.imwrite(a.out[:-4] + '-change.png', np.clip(change * 4, 0, 255).astype(np.uint8))
    fixed = (change < a.thr).astype(np.uint8)
    if a.grow:
        fixed = cv2.dilate(fixed, np.ones((2 * a.grow + 1, 2 * a.grow + 1), np.uint8))
    mask = np.where(fixed > 0, 0, 255).astype(np.uint8)
    cv2.imwrite(a.out, mask)
    print(f'{len(pick)} frames; {fixed.mean() * 100:.1f}% of the picture fixed to the camera (masked)')


if __name__ == '__main__':
    main()
