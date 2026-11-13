#!/usr/bin/env python3
r"""
MACA's upper caves placed again as caves_fit.py places them, but with the nodes COLMAP placed (MACA 2, the stairs
28-31, 3 and 4) moved as one piece, a shift and one scale about their middle, so that their depth maps, scaled by
the same factor, still agree with one another when the dense workspace is fused again; MACA 1, 5 and 6 (placed by
hand before, place_nodes.py) are free, in height too.

    python caves_rigid.py LAYOUT.json WALK.json OUT.json [--eye 0.226]

Fused with caves_fit.py's layout, which stretches the caves unevenly, the cloud round the moved nodes all but
vanished (MACA 29: 26,884 points within 1.5 spacings to 1): each depth map was made for the old places and no longer
meets its neighbours'. Fitted in x, y, z: every hotspot heading between two nodes of which one moves (10 degrees for
walks, 15 for zips), walk lengths as caves_fit.py has them (the rigid piece's own walks too, which set its scale), and each walk's climb from the pitches of its pair of
hotspots (climb = d (tan(-p_ba) - tan(-p_ab)) / 2 at the fitted distance d, 0.15 spacings). Writes {node: [x, y, z]}
and prints the scale (the depth scale for the rigid nodes). Needs numpy and scipy.
"""
import argparse
import json
import math

import numpy as np
from scipy.optimize import least_squares

RIGID = ['1002', '1028', '1029', '1030', '1031', '1003', '1004']
FREE = ['1001', '1005', '1006']
NORMAL = {('1001', '2001'), ('1001', '1002'), ('1003', '1004')}
STAIRS = {('1002', '1028'), ('1028', '1029'), ('1029', '1030'), ('1030', '1031'), ('1003', '1031')}
ROOM = {'MACA': '1', 'MAIS': '2', 'MALL': '3', 'MASS': '4', 'MAWW': '5', 'MATO': '6'}


def num(s):
    return ROOM[s[:4]] + s[5:].lstrip('0').zfill(3)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('layout'); ap.add_argument('walk'); ap.add_argument('out')
    a = ap.parse_args()
    P = {n: np.array(v['pos'], float) for n, v in json.load(open(a.layout))['nodes'].items()}
    W = json.load(open(a.walk))['nodes']
    moving = set(RIGID) | set(FREE)
    H, spot = [], {}
    for nm, spots in W.items():
        if nm[:4] not in ROOM:
            continue
        n = num(nm)
        for s in spots:
            if not s['to'] or s['to'][:4] not in ROOM:
                continue
            m = num(s['to'])
            if n in P and m in P and (n in moving or m in moving) and not (n in RIGID and m in RIGID):
                H.append((n, m, s['rects'][0][1], 10.0 if 'walk' in s['kind'] else 15.0))
            if 'walk' in s['kind'] and n in P and m in P and (n in moving or m in moving):
                spot[(n, m)] = s['rects'][0][0]
    pairs = sorted({tuple(sorted(k)) for k in spot})              # lengths: the rigid piece's own walks too (the scale)
    climbs = [(p, q, spot[(p, q)], spot[(q, p)]) for p, q in pairs if (q, p) in spot and not (p in RIGID and q in RIGID)]
    mid = np.mean([P[n] for n in RIGID], 0)

    def place(x):
        t, s = x[:3], math.exp(x[3])
        p = dict(P)
        for n in RIGID:
            p[n] = mid + t + s * (P[n] - mid)
        for i, n in enumerate(FREE):
            p[n] = x[4 + 3 * i:7 + 3 * i]
        return p

    def res(x):
        p, r = place(x), []
        for n, m, h, sg in H:
            d = p[m] - p[n]
            r.append(((math.degrees(math.atan2(-d[0], d[2])) - h + 180) % 360 - 180) / sg)
        for e in pairs:
            d = np.linalg.norm((p[e[0]] - p[e[1]])[[0, 2]])
            sg = 0.25 if e in NORMAL else 0.8 if e in STAIRS else 0.5
            r.append((d - 1.0) / sg)
        for n, m, pa, pb in climbs:
            d = np.linalg.norm((p[m] - p[n])[[0, 2]])
            want = d * (math.tan(math.radians(-pb)) - math.tan(math.radians(-pa))) / 2
            r.append((p[m][1] - p[n][1] - want) / 0.15)
        return r

    best = None
    sh = np.array([-math.sin(math.radians(217)), 0, math.cos(math.radians(217))])
    for k in (0, 1.5, 3):
        for ls in (0, 0.25):
            x0 = np.concatenate([k * sh, [ls]] + [P[n] + k * sh for n in FREE])
            s = least_squares(res, x0)
            if best is None or s.cost < best.cost:
                best = s
    p = place(best.x); sc = math.exp(best.x[3])
    print(f'cost {best.cost:.2f}; rigid piece shifted {np.linalg.norm(best.x[[0, 2]]):.2f} across, {best.x[1]:+.2f} up, scale {sc:.3f}')
    for n, m, h, sg in H:
        d = p[m] - p[n]; b = math.degrees(math.atan2(-d[0], d[2])) % 360
        if abs((b - h + 180) % 360 - 180) > 15:
            print(f'  {n}->{m}: heading {h}, fitted bearing {b:.0f}')
    for n in RIGID + FREE:
        print(f'{n}: moved {np.linalg.norm(p[n] - P[n]):.2f}, height {P[n][1]:.2f} -> {p[n][1]:.2f}')
    for e in pairs:
        print(f'  walk {e[0]}-{e[1]}: {np.linalg.norm((p[e[0]] - p[e[1]])[[0, 2]]):.2f}')
    for n, m, pa, pb in climbs:
        d = np.linalg.norm((p[m] - p[n])[[0, 2]])
        print(f'  climb {n}->{m}: {p[m][1] - p[n][1]:+.2f}, pitches say {d * (math.tan(math.radians(-pb)) - math.tan(math.radians(-pa))) / 2:+.2f}')
    json.dump({'scale': sc, 'nodes': {n: [round(float(c), 4) for c in p[n]] for n in RIGID + FREE}}, open(a.out, 'w'), indent=1)


if __name__ == '__main__':
    main()
