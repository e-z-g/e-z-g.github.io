#!/usr/bin/env python3
r"""
A walk retimed so it slows into its last frame as it speeds out of its first: H3's walks start slowly (the first
steps move about 40% of the walk's speed) but arrive at full speed. The last --steps steps' distance is covered
again by more, shorter steps, slowing to --floor of the walk's speed; the pictures between frames are made by
warping both neighbours along their optical flow and mixing them, each circle of the two-fisheye layout alone. The
first and last frames stay exact.

    python ease_end.py IN.mp4 OUT_DIR [--steps 4] [--floor 0.4] [--split 2]

Writes OUT_DIR/0000.png ... Needs numpy, opencv-python.
"""
import argparse
import os

import cv2
import numpy as np


def flow(a, b):
    g = lambda x: cv2.cvtColor(x, cv2.COLOR_BGR2GRAY)
    return cv2.calcOpticalFlowFarneback(g(a), g(b), None, 0.5, 5, 31, 3, 7, 1.5, 0)


def warp(img, fl, t):
    h, w = fl.shape[:2]
    x, y = np.meshgrid(np.arange(w, dtype=np.float32), np.arange(h, dtype=np.float32))
    return cv2.remap(img, x - t * fl[..., 0], y - t * fl[..., 1], cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)


def between(a, b, t, split):
    S = a.shape[1] // split; out = np.empty_like(a)
    for c in range(split):
        sl = np.s_[:, c * S:(c + 1) * S]; p, q = a[sl], b[sl]
        f = flow(p, q); g = flow(q, p)
        m = (1 - t) * warp(p, f, t).astype(np.float32) + t * warp(q, g, 1 - t).astype(np.float32)
        out[sl] = np.clip(np.rint(m), 0, 255).astype(np.uint8)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('src'); ap.add_argument('out')
    ap.add_argument('--steps', type=int, default=4); ap.add_argument('--floor', type=float, default=0.4)
    ap.add_argument('--split', type=int, default=2)
    a = ap.parse_args()
    cap = cv2.VideoCapture(a.src); fr = []
    while True:
        ok, f = cap.read()
        if not ok: break
        fr.append(f)
    small = [cv2.resize(f, (f.shape[1] // 4, f.shape[0] // 4)) for f in fr]
    d = np.array([np.median(np.linalg.norm(flow(p, q), axis=2)) for p, q in zip(small, small[1:])])
    C = np.concatenate([[0], np.cumsum(d)])
    n = len(fr) - 1; k0 = n - a.steps                        # source frame where the slowing starts
    cruise = np.mean(d[max(0, k0 - 8):k0]); L = C[n] - C[k0]
    v = []                                                   # steps from full speed down to floor
    while sum(v) < L:
        v.append(None)
        m = len(v)
        u = np.linspace(0, 1, m + 1)[1:]
        sp = cruise * (1 - (1 - a.floor) * (3 * u ** 2 - 2 * u ** 3))
        v = list(sp)
    v = np.array(v) * L / sum(v)
    dist = C[k0] + np.cumsum(v)
    os.makedirs(a.out, exist_ok=True)
    k = 0
    for i in range(k0 + 1):
        cv2.imwrite(os.path.join(a.out, f'{k:04d}.png'), fr[i]); k += 1
    for x in dist[:-1]:
        j = int(np.searchsorted(C, x, side='right') - 1); t = (x - C[j]) / d[j]
        cv2.imwrite(os.path.join(a.out, f'{k:04d}.png'), between(fr[j], fr[j + 1], float(t), a.split)); k += 1
    cv2.imwrite(os.path.join(a.out, f'{k:04d}.png'), fr[n]); k += 1
    print(f'{len(fr)} -> {k} frames; last {a.steps} steps ({L:.1f} px) as {len(v)}: ' + ' '.join(f'{s / cruise:.2f}' for s in v))


if __name__ == '__main__':
    main()
