#!/usr/bin/env python3
"""
Each frame's turn of a walk's sphere in the VR viewer, so the world holds still and stays level while the walk's
camera turns or climbs: the walk is drawn in its camera's frame (right, down, forward), which at frame k is
eased from the first end's frame to the last's (spherical interpolation, linear in time); the sphere is turned
by world-from-camera, with the world's up as the viewer's up and the level part of the first frame's forward as
the way ahead.

    python viewer_orient.py SPARSE PREFIX A B FRAMES OUT.json [--plan route_plan.json] [--fps 24]

Without --plan both ends face from A to B (walk_ends.py --along-motion). Writes {"fps", "q": [[x, y, z, w], ...]}
(three.js quaternions, one a frame). Needs numpy.
"""
import argparse
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from route_plan import node_pose  # noqa: E402


def frame(fw, up, rref=None):
    fw = np.asarray(fw, float); fw = fw / np.linalg.norm(fw)
    r = np.cross(fw, up) if rref is None else rref - fw * (rref @ fw); r /= np.linalg.norm(r)
    return np.stack([r, np.cross(fw, r), fw])               # rows: right, down, forward (world -> camera)


def quat(R):
    t = np.trace(R)
    if t > 0:
        s = np.sqrt(t + 1) * 2; return np.array([(R[2, 1] - R[1, 2]) / s, (R[0, 2] - R[2, 0]) / s, (R[1, 0] - R[0, 1]) / s, s / 4])
    i = int(np.argmax(np.diag(R))); j, k = (i + 1) % 3, (i + 2) % 3
    s = np.sqrt(1 + R[i, i] - R[j, j] - R[k, k]) * 2
    q = np.zeros(4); q[i] = s / 4; q[j] = (R[j, i] + R[i, j]) / s; q[k] = (R[k, i] + R[i, k]) / s; q[3] = (R[k, j] - R[j, k]) / s
    return q


def slerp(a, b, t):
    if a @ b < 0:
        b = -b
    d = np.clip(a @ b, -1, 1); w = np.arccos(d)
    if w < 1e-6:
        return a
    return (np.sin((1 - t) * w) * a + np.sin(t * w) * b) / np.sin(w)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('sparse'); ap.add_argument('prefix'); ap.add_argument('a'); ap.add_argument('b')
    ap.add_argument('frames', type=int); ap.add_argument('out')
    ap.add_argument('--plan'); ap.add_argument('--fps', type=float, default=24.0)
    a = ap.parse_args()
    CA, up = node_pose(a.sparse, f'f1/{a.prefix}-{a.a}.jpg'); CB, _ = node_pose(a.sparse, f'f1/{a.prefix}-{a.b}.jpg')
    up = up / np.linalg.norm(up)
    if a.plan:
        pl = json.load(open(a.plan)); dA, dB = pl['departure_model'], pl['arrival_model']
    else:
        dA = dB = CB - CA
    rl = frame(CB - CA, up)[0]                             # the straight line's right, as walk_ends.py keeps
    R0, R1 = frame(dA, up, rl), frame(dB, up, rl)
    f = np.asarray(CB - CA, float); f = f - up * (f @ up); f /= np.linalg.norm(f)
    G = np.stack([np.cross(f, up), up, -f])                  # world -> viewer (x right, y up, z back)
    S = np.diag([1.0, -1.0, -1.0])                           # the sphere's own coordinates -> the camera's
    q0, q1 = quat(R0), quat(R1); out = []
    for k in range(a.frames):
        q = slerp(q0, q1, k / max(1, a.frames - 1)); q /= np.linalg.norm(q)
        x, y, z, w = q
        R = np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                      [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                      [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])
        out.append([round(float(v), 6) for v in quat(G @ R.T @ S)])
    json.dump({'fps': a.fps, 'q': out}, open(a.out, 'w'))
    print(a.out, len(out), 'frames; first', out[0], 'last', out[-1])


if __name__ == '__main__':
    main()
