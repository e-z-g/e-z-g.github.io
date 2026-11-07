#!/usr/bin/env python3
"""
Node positions with the lengths of the steps measured, for nodes that all face
one way (solve_nodes.py --same-rotation has been run and its turn checked with
turn_scan.py).

    python link_scales.py WORK [--solve WORK/solve_same] [--out WORK/solve_scaled]
                          [--features images_feat] [--min-inliers 20] [--min-front 0.8]

Why: a link's matches give the direction of the step from one node to the next,
not its length, so solve_nodes.py makes every step along a chain the shortest
allowed, and bundle adjustment can only correct that where enough points join
the nodes. Here the lengths are measured directly:

1. For each link (A, B), the matches that fit its direction (each ray within 0.5
   degrees of the other's epipolar plane) are triangulated with the step taken as one unit; each
   gets a distance from A and from B.
2. A point that node B sees on two of its links, (A, B) and (B, C), is one
   point at one distance from B, so the ratio of its two distances from B is the
   ratio of the two steps' lengths. The median over all such points (each seen
   with over 1 degree of parallax on both links) is that pair's ratio.
3. Every link's log length is the least-squares fit to those ratios, weighted by
   the number of points, one length held at 1 in each connected part.
4. The centres are the least-squares fit to c_y - c_x = length * direction,
   reweighted against links that do not fit (Cauchy, at a tenth of the length).

Each link's direction is checked against the hotspots between its two nodes
(heading h looks along (-sin h, 0, cos h)): more than 120 degrees off and the
direction is reversed (the measured direction's sign is the one thing a
distant, level scene leaves open), between 60 and 120 it is dropped. Links
with no hotspot keep their measured direction.

Writes OUT/nodes_solved.json in solve_nodes.py's form (for build_model.py and
join_model.ps1) and OUT/scales.json. Needs numpy and opencv-python.
"""
import argparse
import json
import math
import os
import sys
from collections import defaultdict

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from solve_nodes import features, match  # noqa: E402

THR = math.sin(math.radians(0.5))
MIN_PARALLAX = math.cos(math.radians(1.0))


def triangulate(a, b, c):
    """Distances la, lb with la a = c + lb b, least squares, for unit rows a, b and B's centre c."""
    ab = np.sum(a * b, 1)
    ac, bc = a @ c, b @ c
    den = 1 - ab ** 2
    den = np.where(den > 1e-9, den, np.nan)
    la = (ac - ab * bc) / den
    lb = (ab * ac - bc) / den
    return la, lb


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('work')
    ap.add_argument('--solve'); ap.add_argument('--out')
    ap.add_argument('--features', default='images_feat')
    ap.add_argument('--min-inliers', type=int, default=20)
    ap.add_argument('--min-front', type=float, default=0.8)
    ap.add_argument('--verbose', action='store_true', help='counts per link and per pair of links')
    a = ap.parse_args()
    solve = a.solve or os.path.join(a.work, 'solve_same')
    out = a.out or os.path.join(a.work, 'solve_scaled')
    os.makedirs(out, exist_ok=True)
    meta = json.load(open(os.path.join(a.work, 'nodes.json')))
    names = meta.get('rooms', {})
    nm = lambda n: names.get(str(n), str(n))
    rel = {tuple(map(int, k.split('-'))): v for k, v in json.load(open(os.path.join(solve, 'relposes.json'))).items()}

    # directions, checked against the hotspots
    hot = defaultdict(list)
    for l in meta['links_used']:
        hot[(l['from'], l['to'])].append(l['heading'])
    links, notes = {}, []
    for (x, y), v in rel.items():
        if v.get('inliers', 0) < a.min_inliers or v.get('front', 0) < a.min_front:
            continue
        c = -np.array(v['t'], float)                 # y's centre seen from x (rotation is the identity)
        c /= np.linalg.norm(c)
        hs = [(-math.sin(math.radians(h)), 0.0, math.cos(math.radians(h))) for h in hot[(x, y)]]
        hs += [(math.sin(math.radians(h)), 0.0, -math.cos(math.radians(h))) for h in hot[(y, x)]]
        if hs:
            ch = np.array([c[0], 0, c[2]])
            if np.linalg.norm(ch) > 0.2:             # a mostly vertical step says little about heading
                ang = np.median([math.degrees(math.acos(np.clip(ch @ np.array(h) / np.linalg.norm(ch), -1, 1)))
                                 for h in hs])
                if ang > 120:
                    c = -c; notes.append(f'{nm(x)}-{nm(y)} reversed ({ang:.0f} deg from its hotspots)')
                elif ang > 60:
                    notes.append(f'{nm(x)}-{nm(y)} dropped ({ang:.0f} deg from its hotspots)')
                    continue
        links[(x, y)] = c
    print(f'{len(links)} links kept of {len(rel)}')
    for s in notes:
        print('  ' + s)

    # 1. distances from each node, per link, keyed by the node's feature index
    sift = cv2.SIFT_create(nfeatures=5000, contrastThreshold=0.01)
    folder = os.path.join(a.work, a.features)
    feats = {}
    depth = {}                                       # (link, node) -> {feature index: distance}
    for (x, y), c in links.items():
        for n in (x, y):
            if n not in feats:
                feats[n] = features(folder, meta['room'], n, sift)
        (da, fa), (db, fb) = feats[x], feats[y]
        m = match(fa, fb)
        if len(m) < 8:
            continue
        A, B = da[m[:, 0]], db[m[:, 1]]
        par = np.sum(A * B, 1) < MIN_PARALLAX
        na = np.cross(A, c); na /= np.maximum(np.linalg.norm(na, axis=1), 1e-12)[:, None]
        nb = np.cross(B, c); nb /= np.maximum(np.linalg.norm(nb, axis=1), 1e-12)[:, None]
        err = np.maximum(np.abs(np.sum(B * na, 1)), np.abs(np.sum(A * nb, 1)))  # ray to the other's epipolar plane
        inl = par & (err < THR)
        la, lb = triangulate(A, B, c)
        ok = inl & (la > 0) & (lb > 0)
        depth[((x, y), x)] = dict(zip(m[ok, 0].tolist(), la[ok].tolist()))
        depth[((x, y), y)] = dict(zip(m[ok, 1].tolist(), lb[ok].tolist()))
        if a.verbose:
            print(f'  {nm(x)}-{nm(y)}: {len(m)} matches, {int(par.sum())} with parallax, '
                  f'{int(inl.sum())} fit the direction, {int(ok.sum())} in front of both')

    # 2. ratios between two links at a shared node
    at = defaultdict(list)
    for (L, n) in depth:
        at[n].append(L)
    ratios = []
    for n, Ls in at.items():
        for i in range(len(Ls)):
            for j in range(i + 1, len(Ls)):
                d1, d2 = depth[(Ls[i], n)], depth[(Ls[j], n)]
                common = d1.keys() & d2.keys()
                if a.verbose:
                    print(f'  at {nm(n)}: {nm(Ls[i][0])}-{nm(Ls[i][1])} and {nm(Ls[j][0])}-{nm(Ls[j][1])} '
                          f'share {len(common)} points')
                if len(common) < 5:
                    continue
                r = np.array([math.log(d1[k] / d2[k]) for k in common])   # log(s_j / s_i)
                med = float(np.median(r))
                spread = float(np.median(np.abs(r - med)))
                ratios.append((Ls[i], Ls[j], med, len(common), spread, n))
    print(f'{len(ratios)} pairs of links with at least 5 points in common')

    # 3. log lengths
    idx = {L: k for k, L in enumerate(links)}
    adj = defaultdict(set)
    for L1, L2, *_ in ratios:
        adj[L1].add(L2); adj[L2].add(L1)
    comp, part = {}, 0
    for L in links:
        if L in comp:
            continue
        stack = [L]; comp[L] = part
        while stack:
            u = stack.pop()
            for v in adj[u]:
                if v not in comp:
                    comp[v] = part; stack.append(v)
        part += 1
    rows, rhs, wts = [], [], []
    for L1, L2, med, cnt, spread, n in ratios:
        r = np.zeros(len(links)); r[idx[L2]] = 1; r[idx[L1]] = -1
        rows.append(r); rhs.append(med); wts.append(math.sqrt(cnt) / (0.05 + spread))
    for p in range(part):                            # one length per part held at 1
        first = next(L for L in links if comp[L] == p)
        r = np.zeros(len(links)); r[idx[first]] = 1
        rows.append(r); rhs.append(0.0); wts.append(1e3)
    M, y, w = np.array(rows), np.array(rhs), np.array(wts)
    for it in range(10):                             # reweight ratios that disagree
        sol = np.linalg.lstsq(M * w[:, None], y * w, rcond=None)[0]
        res = M @ sol - y
        base_w = np.array(wts)
        w = base_w / (1 + (res / 0.15) ** 2)
        w[len(ratios):] = 1e3
    length = {L: math.exp(sol[idx[L]]) for L in links}
    sizes = defaultdict(int)
    for L in links:
        sizes[comp[L]] += 1
    big = max(sizes, key=sizes.get)
    print(f'link parts joined by shared points: {len(sizes)}; largest {sizes[big]} links; '
          f'others: {sorted((s for p, s in sizes.items() if p != big), reverse=True)}')
    bad = sorted(((abs(r), L1, L2, n) for r, (L1, L2, *_ , n) in zip(res[:len(ratios)], ratios)), reverse=True)[:6]
    for r, L1, L2, n in bad:
        print(f'  ratio off by a factor {math.exp(r):.2f}: {nm(L1[0])}-{nm(L1[1])} vs {nm(L2[0])}-{nm(L2[1])} at {nm(n)}')

    # 4. centres, from the links of the largest part (others have no common scale)
    use = [L for L in links if comp[L] == big]
    nodes = sorted({n for L in use for n in L})
    ni = {n: k for k, n in enumerate(nodes)}
    lw = np.array([float(rel[L]['inliers']) ** 0.5 for L in use])
    w = lw.copy()
    for it in range(20):
        rows, rhs, ws = [], [], []
        for (x, y), wt in zip(use, w):
            d = length[(x, y)] * links[(x, y)]
            for k in range(3):
                r = np.zeros(3 * len(nodes)); r[3 * ni[y] + k] = 1; r[3 * ni[x] + k] = -1
                rows.append(r); rhs.append(d[k]); ws.append(wt)
        for k in range(3):
            r = np.zeros(3 * len(nodes)); r[3 * 0 + k] = 1
            rows.append(r); rhs.append(0.0); ws.append(1e3)
        M, yv, ws = np.array(rows), np.array(rhs), np.array(ws)
        C = np.linalg.lstsq(M * ws[:, None], yv * ws, rcond=None)[0].reshape(-1, 3)
        res = np.array([np.linalg.norm(C[ni[y]] - C[ni[x]] - length[(x, y)] * links[(x, y)]) / length[(x, y)]
                        for x, y in use])
        w = lw / (1 + (res / 0.1) ** 2)
    worst = sorted(zip(res, use), reverse=True)[:6]
    print(f'{len(nodes)} nodes placed from {len(use)} links; step misfit (in step lengths) median '
          f'{np.median(res):.3f}; worst ' + ', '.join(f'{nm(x)}-{nm(y)} {r:.2f}' for r, (x, y) in worst))
    others = sorted(n for n in meta['nodes'] if n not in ni)
    print(f'not placed: {[nm(n) for n in others]}')

    I = np.eye(3).tolist()
    json.dump({'nodes': {str(n): {'node_from_ref': I, 'centre': C[ni[n]].tolist(), 'yaw_pitch_tilt_deg': [0, 0, 0]}
                         for n in nodes}},
              open(os.path.join(out, 'nodes_solved.json'), 'w'), indent=1)
    json.dump({'lengths': {f'{x}-{y}': length[(x, y)] for x, y in links},
               'directions': {f'{x}-{y}': links[(x, y)].tolist() for x, y in links},
               'ratios': [{'a': f'{L1[0]}-{L1[1]}', 'b': f'{L2[0]}-{L2[1]}', 'at': n, 'log_b_over_a': med,
                           'points': cnt, 'spread': spread} for L1, L2, med, cnt, spread, n in ratios],
               'notes': notes}, open(os.path.join(out, 'scales.json'), 'w'), indent=0)


if __name__ == '__main__':
    main()
