#!/usr/bin/env python3
r"""
Two overlapping runs of a walk's frames joined into one, crossfaded over the frames they share.

    python join_halves.py FIRST_DIR SECOND_DIR OUT_DIR --start 17 [--mode fade|cut|flow] [--split 2]

SECOND_DIR's frame 0 is FIRST_DIR's frame --start; the frames from there to FIRST_DIR's last are in both. --mode
fade (the default) mixes them, from all FIRST at the start of the overlap to all SECOND at its end; cut takes FIRST
up to the shared frame where the two agree best and SECOND after it, with no mixing; flow mixes as fade but warps
each run onto the other along their optical flow first (each of --split squares alone), so moving things are not
doubled. Writes OUT_DIR/0000.png ... Needs numpy, opencv-python.
"""
import argparse
import glob
import os

import cv2
import numpy as np


def flow_mix(p, q, t, split):
    # p and q show the same moment drawn twice: each is moved part of the way toward the other along the flow
    # between them (p by t, q by 1 - t), so both land on one shape before they are mixed
    g = lambda x: cv2.cvtColor(x, cv2.COLOR_BGR2GRAY)
    S = p.shape[1] // split; out = np.empty(p.shape, np.float32)
    for c in range(split):
        sl = np.s_[:, c * S:(c + 1) * S]; a, b = p[sl], q[sl]
        f = cv2.calcOpticalFlowFarneback(g(a), g(b), None, 0.5, 5, 31, 3, 7, 1.5, 0)
        r = cv2.calcOpticalFlowFarneback(g(b), g(a), None, 0.5, 5, 31, 3, 7, 1.5, 0)
        h, w = f.shape[:2]
        x, y = np.meshgrid(np.arange(w, dtype=np.float32), np.arange(h, dtype=np.float32))
        wa = cv2.remap(a, x - t * f[..., 0], y - t * f[..., 1], cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
        wb = cv2.remap(b, x - (1 - t) * r[..., 0], y - (1 - t) * r[..., 1], cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
        out[sl] = (1 - t) * wa.astype(np.float32) + t * wb.astype(np.float32)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('first'); ap.add_argument('second'); ap.add_argument('out'); ap.add_argument('--start', type=int, required=True)
    ap.add_argument('--mode', default='fade', choices=['fade', 'cut', 'flow']); ap.add_argument('--split', type=int, default=2)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    fa = sorted(glob.glob(os.path.join(a.first, '*.png'))); fb = sorted(glob.glob(os.path.join(a.second, '*.png')))
    n = len(fa) - a.start                                    # frames in both
    k = 0
    for i in range(a.start):
        cv2.imwrite(os.path.join(a.out, f'{k:04d}.png'), cv2.imread(fa[i])); k += 1
    if a.mode == 'cut':
        err = [np.abs(cv2.imread(fa[a.start + j]).astype(np.float32) - cv2.imread(fb[j]).astype(np.float32)).mean() for j in range(n)]
        c = int(np.argmin(err)); print('cut at shared frame', c, 'of', n, '(frame', a.start + c, '), differences', ' '.join(f'{e:.1f}' for e in err))
    for j in range(n):
        t = (j + 1) / (n + 1)
        p, q = cv2.imread(fa[a.start + j]), cv2.imread(fb[j])
        if a.mode == 'cut':
            m = p if j < c else q
        elif a.mode == 'flow':
            m = flow_mix(p, q, t, a.split)
        else:
            m = (1 - t) * p.astype(np.float32) + t * q.astype(np.float32)
        cv2.imwrite(os.path.join(a.out, f'{k:04d}.png'), np.clip(np.rint(m), 0, 255).astype(np.uint8)); k += 1
    for j in range(n, len(fb)):
        cv2.imwrite(os.path.join(a.out, f'{k:04d}.png'), cv2.imread(fb[j])); k += 1
    print(f'{k} frames -> {a.out}')


if __name__ == '__main__':
    main()
