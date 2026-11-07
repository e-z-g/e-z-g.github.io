#!/usr/bin/env python3
"""
Is a COLMAP model of a Myst III room right? Check it against what is already known.

    python evaluate_model.py WORK TAG [MODEL]     (MODEL defaults to 0)

Reads the model as text (inspect_run.py writes WORK/runs/TAG/sparse_txt/<MODEL>/)
and WORK/nodes.json, and reports three things the reconstruction was never told:

1. Rotation. Every node shares one world orientation, so every frame's rotation
   should come out the same. The spread is each frame's angle from their mean.
2. Bearings. A hotspot's heading is the direction from its node to the next
   (heading h looks along (-sin h, 0, cos h) in the node's cube frame; see the
   README). The direction between two reconstructed node centres, turned into
   the node frame, is read as a heading and compared; its vertical angle is the
   climb.
3. The age map. The nodes' horizontal positions, fitted to the map's by a
   similarity (rotation, scale, shift), and what is left over, in map steps.

Each frame's node_from_world rotation is cam_from_node(face 1) transposed times
face 1's cam_from_world, so it does not matter which way COLMAP's own axes
point. Needs numpy.
"""
import json
import math
import os
import re
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from face_geometry import cam_from_node  # noqa: E402


def qvec2rot(q):
    w, x, y, z = q
    return np.array([[1 - 2 * y * y - 2 * z * z, 2 * x * y - 2 * w * z, 2 * x * z + 2 * w * y],
                     [2 * x * y + 2 * w * z, 1 - 2 * x * x - 2 * z * z, 2 * y * z - 2 * w * x],
                     [2 * x * z - 2 * w * y, 2 * y * z + 2 * w * x, 1 - 2 * x * x - 2 * y * y]])


def read_frames(txt_dir):
    """node -> (node_from_world 3x3, centre in world) from each node's face-1 image."""
    out = {}
    lines = [l for l in open(os.path.join(txt_dir, 'images.txt')) if not l.startswith('#')]
    f1 = np.array(cam_from_node(1))
    for l in lines[::2]:
        p = l.split()
        if len(p) < 10 or not p[-1].startswith('f1/'):
            continue
        node = int(re.search(r'-(\d+)\.jpg$', p[-1]).group(1))
        R = qvec2rot([float(v) for v in p[1:5]])
        t = np.array([float(v) for v in p[5:8]])
        out[node] = (f1.T @ R, -R.T @ t)
    return out


def rot_angle(R):
    return math.degrees(math.acos(max(-1.0, min(1.0, (np.trace(R) - 1) / 2))))


def main():
    work, tag = sys.argv[1], sys.argv[2]
    model = sys.argv[3] if len(sys.argv) > 3 else '0'
    frames = read_frames(os.path.join(work, 'runs', tag, 'sparse_txt', model))
    nodes = json.load(open(os.path.join(work, 'nodes.json')))
    print(f'{tag} model {model}: {len(frames)} nodes')

    # 1. rotation spread, about the chordal mean
    M = sum(R for R, _ in frames.values())
    U, _, Vt = np.linalg.svd(M)
    Rm = U @ Vt
    spread = {n: rot_angle(R @ Rm.T) for n, (R, _) in frames.items()}
    s = sorted(spread.values())
    worst = sorted(spread, key=spread.get)[-3:]
    print(f'1. rotation spread: median {s[len(s) // 2]:.2f} deg, max {s[-1]:.2f} '
          f'(worst nodes {", ".join(f"{n} {spread[n]:.1f}" for n in reversed(worst))})')

    # 2. bearings: every hotspot between two placed nodes
    errs, rows = [], []
    for l in nodes['links_used']:
        a, b = l['from'], l['to'] % 100 if 100 <= l['to'] < 1000 else l['to']
        if a not in frames or b not in frames or a == b:
            continue
        Ra, Ca = frames[a]
        d = Ra @ (frames[b][1] - Ca)
        d /= np.linalg.norm(d)
        h = math.degrees(math.atan2(-d[0], d[2])) % 360
        e = (h - l['heading'] + 180) % 360 - 180
        errs.append(abs(e))
        rows.append((a, b, l['kind'], l['heading'], h, e, math.degrees(math.asin(d[1]))))
    e = sorted(errs)
    print(f'2. bearings: {len(e)} hotspots, error median {e[len(e) // 2]:.1f} deg, '
          f'90% within {e[int(len(e) * 0.9)]:.1f}, worst {e[-1]:.1f}')
    for a, b, k, hh, h, er, c in sorted(rows, key=lambda r: -abs(r[5]))[:8]:
        print(f'     {a:3d} -> {b:3d} {k:4s} hotspot {hh:5.0f}  model {h:5.1f}  ({er:+6.1f})  climb {c:+5.1f}')

    # 3. the age map: horizontal positions in the node frame (x east-ish is -x here:
    #    the map's step for heading h is (sin h, cos h), the node frame's (-sin h, cos h))
    Rm_node = Rm
    pos = nodes['age_map_positions_steps']
    common = [n for n in frames if pos.get(str(n))]
    P = np.array([[-(Rm_node @ frames[n][1])[0], (Rm_node @ frames[n][1])[2]] for n in common])
    Q = np.array([pos[str(n)] for n in common])
    Pm, Qm = P.mean(0), Q.mean(0)
    P0, Q0 = P - Pm, Q - Qm
    U, S, Vt = np.linalg.svd(P0.T @ Q0)
    D = np.diag([1, np.sign(np.linalg.det(U @ Vt))])
    R2 = (U @ D @ Vt).T
    scale = (S * np.diag(D)).sum() / (P0 ** 2).sum()
    fit = (scale * (R2 @ P0.T)).T + Qm
    res = np.linalg.norm(fit - Q, axis=1)
    turn = math.degrees(math.atan2(R2[1, 0], R2[0, 0]))
    r = sorted(res)
    print(f'3. age map: {len(common)} nodes; fitted turn {turn:+.1f} deg, '
          f'1 map step = {1 / scale:.3f} model units; residual median {r[len(r) // 2]:.2f} steps, '
          f'max {r[-1]:.2f} (node {common[int(np.argmax(res))]})')
    heights = {n: float((Rm_node @ frames[n][1])[1] * scale) for n in frames}
    lo = min(heights.values())
    print('   heights above the lowest node, in map steps: ' +
          ', '.join(f'{n}:{heights[n] - lo:.2f}' for n in sorted(heights)))


if __name__ == '__main__':
    main()
