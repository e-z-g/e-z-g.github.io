#!/usr/bin/env python3
"""
usage: fisheye_seam.py VIDEO layout.json. How well the two eyes of a walk_ends.py --dual-fisheye video agree
where they overlap (directions 85-95 degrees from ahead, all the way round): the mean colour difference
(0-255) between what each eye shows there, per frame. Prints the same SCORE line as cube_edges.py: the mean
rise over the walk above the first frame (lower is better), and the worst. Needs numpy, opencv-python.
"""
import json
import sys

import cv2
import numpy as np

cap = cv2.VideoCapture(sys.argv[1]); L = json.load(open(sys.argv[2]))
half = np.radians(L['fov']) / 2; SW, SH = L['size']
eyes = [(np.array(e['axes']), e['rect']) for e in L['eyes']]
fwd = eyes[0][0][2]
ph = np.linspace(0, 2 * np.pi, 180, endpoint=False)
dirs = []
X0, Y0, Z0 = eyes[0][0]                          # round the first eye's own axis (turned by --eye-yaw)
for ang in np.radians([86, 88, 90, 92, 94]):
    dirs.append(np.sin(ang) * np.cos(ph)[:, None] * X0 + np.sin(ang) * np.sin(ph)[:, None] * Y0 + np.cos(ang) * Z0)
dirs = np.concatenate(dirs)


def coords(E, rect, W, H):
    x, y, z = E
    th = np.arccos(np.clip(dirs @ z, -1, 1)); a = np.arctan2(dirs @ y, dirs @ x)
    f = 0.5 + 0.5 * (th / half)[:, None] * np.stack([np.cos(a), np.sin(a)], -1)
    rx, ry, rw, rh = rect
    return ((rx + f[:, 0] * rw) * W / SW - .5).astype(np.float32), ((ry + f[:, 1] * rh) * H / SH - .5).astype(np.float32)


series = []
while True:
    r, f = cap.read()
    if not r:
        break
    H, W = f.shape[:2]
    s = [cv2.remap(f, *[c[None] for c in coords(E, rect, W, H)], cv2.INTER_LINEAR)[0].astype(float) for E, rect in eyes]
    series.append(np.abs(s[0] - s[1]).mean())
d = np.array(series); rise = d - d[0]
print(f'overlap of the two eyes: start {d[0]:.1f}  median {np.median(d):.1f}  worst {d.max():.1f}')
print(f'SCORE (the eyes\' overlap, mean rise over the walk above the first frame; lower is better): {rise.mean():.2f}; worst rise {rise.max():.1f}')
