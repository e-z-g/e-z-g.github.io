#!/usr/bin/env python3
"""
polar_stereo.py's matching with the rows spaced by cot(theta) in place of theta, so a wall parallel to the line of
travel slides down its column without stretching. A trial on the cliff walk (LEIS 1060 to 1067, README).

    python polar_stereo_cot.py ROWS_SCALE MAX_DISPARITY BLOCK     (run in a folder with ends_polar_first.png,
        ends_polar_last.png and sift_matches.npy; e.g. 2 384 5)

Writes cot_A.jpg, cot_B.jpg, cot_dA.npy, cot_dB.npy. Needs numpy, opencv-python.
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cv2, numpy as np, polar_stereo as ps  # noqa: E402
APART = 4.380869                                          # LEIS 1060 to 1067
A0 = cv2.imread('ends_polar_first.png'); B0 = cv2.imread('ends_polar_last.png')
H0, W0 = A0.shape[:2]
W = W0 // 2; cmax = 1 / np.tan(np.radians(4)); dc = np.pi / 640 * float(sys.argv[1])   # rows per cot unit
R = int(2 * cmax / dc)
c = cmax - (np.arange(R) + .5) * dc                       # top: straight ahead
th = np.arctan2(1, c)                                     # 0..pi
mapy = np.repeat((th / np.pi * H0 - .5)[:, None], W, 1).astype(np.float32)
mapx = np.repeat(((np.arange(W) + .5) * 2 - .5)[None], R, 0).astype(np.float32)
Ac = cv2.remap(A0, mapx, mapy, cv2.INTER_LINEAR)
Bc = cv2.remap(B0, mapx, mapy, cv2.INTER_LINEAR)
D = int(sys.argv[2]); blk = int(sys.argv[3])
a, b = cv2.cvtColor(Ac, 6).T.copy(), cv2.cvtColor(Bc, 6).T.copy()
dB = ps.sgbm(b, a, D, blk).T; dA = ps.sgbm(a[:, ::-1].copy(), b[:, ::-1].copy(), D, blk)[:, ::-1].T
print(f'{W}x{R}, D {D} rows = {D*dc:.2f} cot units (r down to {APART/(D*dc):.2f}); raw found A {np.isfinite(dA).mean():.2f} B {np.isfinite(dB).mean():.2f}')
# check against SIFT
M = np.load('sift_matches.npy'); xa, ya, xb, yb = M.T
cA = 1 / np.tan((ya + .5) / H0 * np.pi); cB = 1 / np.tan((yb + .5) / H0 * np.pi)
ra = np.rint((cmax - cA) / dc - .5).astype(int); ua = np.clip(np.rint(xa / 2 - .5).astype(int), 0, W - 1)
k = (ra >= 0) & (ra < R); got = np.full(len(M), np.nan); got[k] = dA[ra[k], ua[k]]
true = (cA - cB) / dc; f = np.isfinite(got)
r_true = APART / (cA - cB)
print(f'check: {f.sum()} of {len(M)}; error in r median {np.median(np.abs(APART/(got[f]*dc) - r_true[f]) / r_true[f]):.1%}, 90% {np.percentile(np.abs(APART/(got[f]*dc) - r_true[f]) / r_true[f], 90):.1%}')
np.save('cot_dA.npy', dA); np.save('cot_dB.npy', dB)
cv2.imwrite('cot_A.jpg', Ac); cv2.imwrite('cot_B.jpg', Bc)
