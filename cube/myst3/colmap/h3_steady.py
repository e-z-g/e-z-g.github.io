#!/usr/bin/env python3
r"""
The sway in an H3 walk measured, for the viewer to take out.

    python h3_steady.py WALK.mp4 OUT.json [--projection equidistant|equal-area|horizon] [--show]

The walk is ONE 360-degree fisheye looking down (walk_ends.py --single-fisheye --eye-pitch -90). The camera
should only glide forward and never turn. Points over the whole picture are tracked from frame to frame
(Lucas-Kanade) and turned into directions; each step's turn and way of travel are fitted together (the essential
matrix from eight-point samples, RANSAC, refitted on the points that agree; of its two turns the one nearer none).
A turn fitted to far points alone took the glide forward for a pitch. The turns add up to each frame's turn against
the first; the last frame is the same still as the walk's end, so whatever turn is left there (against none, or with --layout
the turn between the two ends' aims) is drift, taken out
evenly along the walk. Also printed: the sway, the spread of the way of travel to the side and up and down (a
walking gait sways it from side to side about once a second; a turn of the picture cannot take that out).

Writes {"fps": F, "rot": [[r00 r01 r02 r10 ... r22] per frame]}: R takes a direction in the first frame's fisheye
axes (x right in the picture, y down in it, z the picture's centre) to the same far point's direction in that frame.
The viewer looks a direction q up at R q, so the scene keeps still. --show prints each frame's turn in degrees.
Needs numpy, opencv-python.
"""
import argparse
import json
import math

import cv2
import numpy as np


def r_of(th, proj):
    if proj == 'equal-area':
        return np.sin(th / 2)
    if proj == 'horizon':
        return (th - np.sin(2 * th) / 4) / np.pi
    return th / np.pi


def bearings(pts, size, proj):
    """Pixel (column, row) to unit direction in the fisheye's axes."""
    c = pts / size * 2 - 1
    r = np.linalg.norm(c, axis=1)
    grid = np.linspace(0, np.pi, 2001)
    th = np.interp(r, r_of(grid, proj), grid)
    ph = np.arctan2(c[:, 1], c[:, 0])
    return np.stack([np.sin(th) * np.cos(ph), np.sin(th) * np.sin(ph), np.cos(th)], 1)


def kabsch(a, b):
    """R with R a ~ b."""
    U, _, Vt = np.linalg.svd(b.T @ a)
    D = np.diag([1, 1, np.sign(np.linalg.det(U @ Vt))])
    return U @ D @ Vt


def essential(A, B):
    """E with B^T E A = 0 (linear eight-point on unit directions)."""
    M = np.einsum('ni,nj->nij', B, A).reshape(len(A), 9)
    E = np.linalg.svd(M)[2][-1].reshape(3, 3)
    U, _, Vt = np.linalg.svd(E)
    return U @ np.diag([1, 1, 0]) @ Vt


def turn_of(E):
    U, _, Vt = np.linalg.svd(E)
    W = np.array([[0, -1, 0], [1, 0, 0], [0, 0, 1]])
    best = None
    for R in (U @ W @ Vt, U @ W.T @ Vt):
        if np.linalg.det(R) < 0:
            R = -R
        if best is None or np.trace(R) > np.trace(best):
            best = R
    return best


def angle(R):
    return math.degrees(math.acos(max(-1.0, min(1.0, (np.trace(R) - 1) / 2))))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('video'); ap.add_argument('out')
    ap.add_argument('--projection', default='equidistant', choices=['equidistant', 'equal-area', 'horizon'])
    ap.add_argument('--show', action='store_true')
    ap.add_argument('--layout', help="walk_ends.py's layout.json: with ends aimed apart (--last-eye, --auto-aim) the last "
                                     "frame's turn is known (the last eye's axes against the first's), not none")
    a = ap.parse_args()
    cap = cv2.VideoCapture(a.video)
    fps = cap.get(cv2.CAP_PROP_FPS)
    frames = []
    while True:
        ok, f = cap.read()
        if not ok:
            break
        frames.append(cv2.cvtColor(f, cv2.COLOR_BGR2GRAY))
    size = frames[0].shape[0]
    # the ring from about the horizon out toward the rim (theta 80-165 degrees)
    yy, xx = np.mgrid[:size, :size]
    rr = np.hypot(xx - size / 2, yy - size / 2) / (size / 2)
    mask = ((rr > 0.05) & (rr < r_of(np.radians(170), a.projection))).astype(np.uint8) * 255
    rng = np.random.default_rng(0)
    T = []
    Rs = [np.eye(3)]
    for k in range(1, len(frames)):
        p0 = cv2.goodFeaturesToTrack(frames[k - 1], 600, 0.01, 8, mask=mask)
        p1, st, _ = cv2.calcOpticalFlowPyrLK(frames[k - 1], frames[k], p0, None, winSize=(21, 21), maxLevel=3)
        st = st.ravel() == 1
        A, B = bearings(p0[st, 0], size, a.projection), bearings(p1[st, 0], size, a.projection)
        best, keep = -1, None
        for _ in range(300):
            i = rng.choice(len(A), 8, replace=False)
            E = essential(A[i], B[i])
            err = np.abs(np.einsum('ni,ij,nj->n', B, E, A))
            ok = err < 0.002
            if ok.sum() > best:
                best, keep = ok.sum(), ok
        E = essential(A[keep], B[keep])
        R = turn_of(E)
        Rs.append(R @ Rs[-1])
        t = np.linalg.svd(E)[0][:, 2]                  # the way the camera moved (fisheye axes: forward is -y)
        T.append(-t if t[1] > 0 else t)
    # the last frame is the end still: any turn left there is drift, taken out evenly
    from scipy.spatial.transform import Rotation as Rot
    end = np.eye(3)
    if a.layout:
        L = json.load(open(a.layout))
        if 'last_eyes' in L:
            end = np.array(L['last_eyes'][0]['axes']) @ np.array(L['eyes'][0]['axes']).T
    left = Rot.from_matrix(end @ Rs[-1].T).as_rotvec()
    n = len(Rs) - 1
    Rs = [Rot.from_rotvec(left * k / n).as_matrix() @ R for k, R in enumerate(Rs)]
    turns = [angle(R) for R in Rs]
    print(f'{a.video}: {len(Rs)} frames, drift taken out {math.degrees(np.linalg.norm(left)):.2f} deg, '
          f'turn median {np.median(turns):.2f} max {max(turns):.2f} deg')
    T = np.array(T)
    print(f'sway: the way of travel sideways {np.degrees(np.std(np.arcsin(np.clip(T[:, 0], -1, 1)))):.1f} deg (sd), '
          f'up and down {np.degrees(np.std(np.arcsin(np.clip(T[:, 2], -1, 1)))):.1f} deg (sd)')
    if a.show:
        print(' '.join(f'{t:.1f}' for t in turns))
    json.dump({'fps': fps, 'rot': [[round(float(x), 5) for x in R.ravel()] for R in Rs]}, open(a.out, 'w'))


if __name__ == '__main__':
    main()
