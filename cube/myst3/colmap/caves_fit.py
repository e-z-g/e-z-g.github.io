#!/usr/bin/env python3
r"""
MACA's upper caves placed again from the game's hotspots: MACA 1, 2, the stairs (28-31), 3, 4, 5 and 6 fitted by
least squares between MAIS 1 and MACA 7, which stay where the model has them.

    python caves_fit.py LAYOUT.json WALK.json OUT.json [--eye 0.226]

LAYOUT.json is node_walk.py's layout.json (the model's places, scene_mesh.py's frame), WALK.json its walk.json.
Sam, 12 November 2026: MACA 1 is one normal step from MAIS 1 (the model had 4.5 spacings), MACA 1-2 and 3-4 are
normal steps, MACA 2-3 goes down a steep staircase of several nodes, and MACA 4-7 looked squished (MACA 5 and 6
were placed nodes, 0.33 and 0.12 apart). Fitted in x and z: every hotspot heading between two nodes of which one
is free (10 degrees for walks, 15 for zips), the three steps Sam called normal at 1 +- 0.25 spacings, the other walks
at 1 +- 0.5 (the stair steps 1 +- 0.8). Heights: the model's, but MACA 1 0.1 above MAIS 1 and MACA 2 level with it
(their hotspots' pitches), and MACA 5, 6 level with MACA 4 (pitch pairs within 0.1). Writes {node: [x, y, z]}
for node_walk.py --proposed and warp_model.py. Needs numpy and scipy.
"""
import argparse
import json
import math

import numpy as np
from scipy.optimize import least_squares

FREE = ['1001', '1002', '1028', '1029', '1030', '1031', '1003', '1004', '1005', '1006']
NORMAL = {('2001', '1001'), ('1001', '1002'), ('1003', '1004')}
STAIRS = {('1002', '1028'), ('1028', '1029'), ('1029', '1030'), ('1030', '1031'), ('1031', '1003')}
ROOM = {'MACA': '1', 'MAIS': '2', 'MALL': '3', 'MASS': '4', 'MAWW': '5', 'MATO': '6'}


def num(s):
    return ROOM[s[:4]] + s[5:].lstrip('0').zfill(3)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('layout'); ap.add_argument('walk'); ap.add_argument('out')
    a = ap.parse_args()
    L = json.load(open(a.layout))['nodes']
    P = {n: np.array(v['pos'], float) for n, v in L.items()}
    W = json.load(open(a.walk))['nodes']
    H, pairs = [], set()
    for nm, spots in W.items():
        if nm[:4] not in ROOM:
            continue
        n = num(nm)
        for s in spots:
            if not s['to'] or s['to'][:4] not in ROOM:
                continue
            m = num(s['to'])
            if n in P and m in P and (n in FREE or m in FREE):
                H.append((n, m, s['rects'][0][1], 10.0 if 'walk' in s['kind'] else 15.0))
                if 'walk' in s['kind']:
                    pairs.add(tuple(sorted((n, m))))
    idx = {n: i for i, n in enumerate(FREE)}

    def xz(x):
        p = {n: P[n][[0, 2]] for n in P}
        for n, i in idx.items():
            p[n] = x[2 * i:2 * i + 2]
        return p

    def res(x):
        p, r = xz(x), []
        for n, m, h, sg in H:
            d = p[m] - p[n]
            r.append(((math.degrees(math.atan2(-d[0], d[1])) - h + 180) % 360 - 180) / sg)
        for e in pairs:
            d = np.linalg.norm(p[e[0]] - p[e[1]])
            sg = 0.25 if e in {tuple(sorted(q)) for q in NORMAL} else 0.8 if e in {tuple(sorted(q)) for q in STAIRS} else 0.5
            r.append((d - 1.0) / sg)
        return r

    best = None
    shift = np.array([-math.sin(math.radians(217)), math.cos(math.radians(217))])
    for k in (0, 1.5, 3, 4.5):
        x0 = np.concatenate([P[n][[0, 2]] + (k * shift if n not in ('1005', '1006') else k / 2 * shift) for n in FREE])
        s = least_squares(res, x0)
        if best is None or s.cost < best.cost:
            best = s
    p = xz(best.x)
    print(f'cost {best.cost:.2f}')
    for n, m, h, sg in H:
        d = p[m] - p[n]; b = math.degrees(math.atan2(-d[0], d[1])) % 360
        if abs((b - h + 180) % 360 - 180) > 15:
            print(f'  {n}->{m}: heading {h}, fitted bearing {b:.0f}')
    y = {n: P[n][1] for n in FREE}
    y['1001'] = P['2001'][1] + 0.1; y['1002'] = y['1001']; y['1005'] = y['1006'] = P['1004'][1]
    out = {n: [round(float(p[n][0]), 4), round(float(y[n]), 4), round(float(p[n][1]), 4)] for n in FREE}
    for n in FREE:
        print(f'{n}: moved {np.linalg.norm(p[n] - P[n][[0, 2]]):.2f}')
    for e in sorted(pairs):
        print(f'  walk {e[0]}-{e[1]}: {np.linalg.norm(p[e[0]] - p[e[1]]):.2f}')
    json.dump(out, open(a.out, 'w'), indent=1)


if __name__ == '__main__':
    main()
