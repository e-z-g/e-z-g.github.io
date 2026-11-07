#!/usr/bin/env python3
"""
Node positions with the lengths of the steps measured, for nodes that all face
one way (solve_nodes.py --same-rotation has been run and its turn checked with
turn_scan.py).

    python link_scales.py WORK [--solve WORK/solve_same] [--out WORK/solve_scaled]
                          [--sources shared,floor,map] [--features images_feat]
                          [--min-inliers 20] [--min-front 0.8] [--verbose]

Why: a link's matches give the direction of the step from one node to the next,
not its length, so solve_nodes.py makes every step along a chain the shortest
allowed, and bundle adjustment can only correct that where enough points join
the nodes. Here each link's log length is solved from up to three sources:

shared  A point that node B sees on two of its links, (A, B) and (B, C), is one
        point at one distance from B, so the ratio of its two distances from B
        (each triangulated with that link's step as one unit) is the ratio of the
        two steps' lengths. Median over the points seen with over 1 degree of
        parallax on both links; weight from their number and spread.
floor   A node stands at eye height above the floor under it. Each link's points
        that lie under one of its nodes (within 0.25 of the step sideways, 0.15
        to 2 below) give that node's height in the link's units; the floor is
        the highest cluster of them (things further down, such as the sea, are
        ignored). Each node gets an unknown height H_n, the same on all its links,
        so the floor ties two links at a node exactly whatever the node's height;
        and every H_n is drawn towards one common eye height (log sigma 0.1: in
        Voltaic's ENSI, flat-platform nodes stand 0.546-0.565 steps above the
        floor, stairs and walkways 0.42-0.53). The common eye height is the unit.
map     The age map's distance between the two nodes, in map steps (walks there
        are one step each, so this says little), times one unknown scale: a weak
        pull (log sigma 0.7) for links nothing else measures.

The fit is reweighted against equations that disagree (Cauchy). Parts of the
link graph with no absolute measure (no floor, no map) have one length held at 1;
parts with one (a floor, or the map) all share the one unit and are placed together.

Each link's direction is checked against the hotspots between its two nodes
(heading h looks along (-sin h, 0, cos h)): more than 120 degrees off and the
direction is reversed (the sign is what a distant, level scene leaves open),
between 60 and 120 it is dropped. Links with no hotspot keep their measured
direction.

The centres are the least-squares fit to c_y - c_x = length * direction over the
largest part joined by measurements, reweighted against links that do not fit.
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


def floor_height(P):
    """Height of the floor under a node from points P relative to it (y up), in the link's units."""
    side = np.hypot(P[:, 0], P[:, 2])
    h = -P[:, 1]
    cand = np.sort(h[(side < 0.25) & (h > 0.15) & (h < 2.0)])
    if len(cand) < 3:
        return None
    top = cand[cand <= 1.15 * np.percentile(cand, 20)]   # the highest surface below the node
    if len(top) < 3:
        return None
    lg = np.log(top)
    return float(np.exp(np.median(lg))), len(top), float(np.median(np.abs(lg - np.median(lg))))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('work')
    ap.add_argument('--solve'); ap.add_argument('--out')
    ap.add_argument('--sources', default='shared,floor,map')
    ap.add_argument('--features', default='images_feat')
    ap.add_argument('--min-inliers', type=int, default=20)
    ap.add_argument('--min-front', type=float, default=0.8)
    ap.add_argument('--verbose', action='store_true', help='counts per link and per pair of links')
    ap.add_argument('--compare', action='append', default=[],
                    help='a COLMAP text model to compare the centres with (after the best similarity); repeatable')
    a = ap.parse_args()
    sources = set(a.sources.split(','))
    solve = a.solve or os.path.join(a.work, 'solve_same')
    out = a.out or os.path.join(a.work, 'solve_scaled')
    os.makedirs(out, exist_ok=True)
    meta = json.load(open(os.path.join(a.work, 'nodes.json')))
    names = meta.get('rooms', {})
    nm = lambda n: names.get(str(n), str(n))
    ln = lambda L: f'{nm(L[0])}-{nm(L[1])}'
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
                    c = -c; notes.append(f'{ln((x, y))} reversed ({ang:.0f} deg from its hotspots)')
                elif ang > 60:
                    notes.append(f'{ln((x, y))} dropped ({ang:.0f} deg from its hotspots)')
                    continue
        links[(x, y)] = c
    print(f'{len(links)} links kept of {len(rel)}; length sources: {", ".join(sorted(sources))}')
    for s in notes:
        print('  ' + s)

    # triangulated points per link: distances from each end keyed by feature index, and floors
    sift = cv2.SIFT_create(nfeatures=5000, contrastThreshold=0.01)
    folder = os.path.join(a.work, a.features)
    feats, depth, floors = {}, {}, {}
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
        P = la[ok, None] * A[ok]                     # points relative to x
        fx, fy = floor_height(P), floor_height(P - c)
        if fx: floors[((x, y), x)] = fx
        if fy: floors[((x, y), y)] = fy
        if a.verbose:
            fl = '  '.join(f'floor under {nm(n)} {f[0]:.3f} ({f[1]} pts)' for n, f in ((x, fx), (y, fy)) if f)
            print(f'  {ln((x, y))}: {len(m)} matches, {int(par.sum())} with parallax, '
                  f'{int(inl.sum())} fit the direction, {int(ok.sum())} in front of both  {fl}')

    # equations on the unknowns: log length per link, log height per node with a floor, log map scale
    lidx = {L: k for k, L in enumerate(links)}
    fnodes = sorted({n for (_, n) in floors}) if 'floor' in sources else []
    hidx = {n: len(links) + k for k, n in enumerate(fnodes)}
    kidx = len(links) + len(fnodes)
    nunk = kidx + 1
    eqs = []                                          # (coefficients dict, rhs, weight, kind, label)
    if 'shared' in sources:
        at = defaultdict(list)
        for (L, n) in depth:
            at[n].append(L)
        for n, Ls in at.items():
            for i in range(len(Ls)):
                for j in range(i + 1, len(Ls)):
                    d1, d2 = depth[(Ls[i], n)], depth[(Ls[j], n)]
                    common = d1.keys() & d2.keys()
                    if a.verbose:
                        print(f'  at {nm(n)}: {ln(Ls[i])} and {ln(Ls[j])} share {len(common)} points')
                    if len(common) < 5:
                        continue
                    r = np.array([math.log(d1[k] / d2[k]) for k in common])   # log(s_j / s_i)
                    med = float(np.median(r)); spread = float(np.median(np.abs(r - med)))
                    eqs.append(({lidx[Ls[j]]: 1, lidx[Ls[i]]: -1}, med, math.sqrt(len(common)) / (0.05 + spread),
                                'shared', f'{ln(Ls[i])} / {ln(Ls[j])} at {nm(n)}'))
    if 'floor' in sources:
        for (L, n), (h, cnt, spread) in floors.items():   # s_L * h = H_n
            eqs.append(({lidx[L]: 1, hidx[n]: -1}, -math.log(h), math.sqrt(cnt) / (0.05 + spread),
                        'floor', f'floor under {nm(n)} on {ln(L)}'))
        for n in fnodes:                                  # H_n near the common eye height, the unit
            eqs.append(({hidx[n]: 1}, 0.0, 1 / 0.1, 'eye', f'eye height at {nm(n)}'))
    if 'map' in sources:
        pos = meta['age_map_positions_steps']
        for (x, y) in links:
            p, q = pos.get(str(x)), pos.get(str(y))
            if p and q and math.dist(p, q) > 0.2:
                eqs.append(({lidx[(x, y)]: 1, kidx: -1}, math.log(math.dist(p, q)), 1 / 0.7, 'map', f'map {ln((x, y))}'))

    # parts: links joined through any equation; parts with no absolute measure get one length held
    adj = defaultdict(set)
    for co, *_ in eqs:
        ks = list(co)
        for u in ks:
            for v in ks:
                if u != v:
                    adj[u].add(v)
    comp, part = {}, 0
    for u in range(nunk):
        if u in comp:
            continue
        stack = [u]; comp[u] = part
        while stack:
            w_ = stack.pop()
            for v in adj[w_]:
                if v not in comp:
                    comp[v] = part; stack.append(v)
        part += 1
    absolute = {comp[k] for co, _, _, kind, _ in eqs if kind == 'eye' for k in co}
    if 'map' in sources and not fnodes:
        eqs.append(({kidx: 1}, 0.0, 1e3, 'gauge', 'map scale held'))
        absolute.add(comp[kidx])
    for p in range(part):
        if p not in absolute:
            first = next(k for k in range(len(links)) if comp[k] == p) if any(comp[k] == p for k in range(len(links))) else None
            if first is not None:
                eqs.append(({first: 1}, 0.0, 1e3, 'gauge', 'held'))
    M = np.zeros((len(eqs), nunk)); y = np.zeros(len(eqs)); w0 = np.zeros(len(eqs))
    for i, (co, r, wt, _, _) in enumerate(eqs):
        for k, v in co.items():
            M[i, k] = v
        y[i], w0[i] = r, wt
    hard = np.array([kind in ('gauge', 'eye') for _, _, _, kind, _ in eqs])
    w = w0.copy()
    for it in range(15):
        sol = np.linalg.lstsq(M * w[:, None], y * w, rcond=None)[0]
        res = M @ sol - y
        w = np.where(hard, w0, w0 / (1 + (res / 0.15) ** 2))
    length = {L: math.exp(sol[lidx[L]]) for L in links}
    kinds = defaultdict(int)
    for _, _, _, kind, _ in eqs:
        kinds[kind] += 1
    print('equations: ' + ', '.join(f'{k} {v}' for k, v in sorted(kinds.items())))
    if fnodes:
        hs = sorted(math.exp(sol[hidx[n]]) for n in fnodes)
        print(f'nodes with a floor measured: {len(fnodes)}; their heights relative to the common one: '
              f'median {hs[len(hs) // 2]:.2f}, 10-90% {hs[len(hs) // 10]:.2f}-{hs[len(hs) * 9 // 10]:.2f}')
    if 'map' in sources:
        print(f'one age-map step = {math.exp(sol[kidx]):.3f} units')
    bad = sorted(((abs(r_), lab) for r_, (_, _, _, kind, lab) in zip(res, eqs) if kind not in ('gauge',)), reverse=True)[:8]
    for r_, lab in bad:
        print(f'  off by a factor {math.exp(r_):.2f}: {lab}')
    group = lambda k: -1 if comp[k] in absolute else comp[k]   # every absolute part shares one unit
    lsizes = defaultdict(int)
    for L in links:
        lsizes[group(lidx[L])] += 1
    big = max(lsizes, key=lsizes.get)
    print(f'link parts joined by measurements: {len(lsizes)}; largest {lsizes[big]} links; '
          f'others: {sorted((s for p, s in lsizes.items() if p != big), reverse=True)}')

    # centres, from the links of the largest part
    use = [L for L in links if group(lidx[L]) == big]
    nadj = defaultdict(set)                          # and of those, the largest set of nodes they connect
    for x, yy in use:
        nadj[x].add(yy); nadj[yy].add(x)
    seen, best = set(), set()
    for n0 in nadj:
        if n0 in seen:
            continue
        cc, stack = {n0}, [n0]
        while stack:
            for v in nadj[stack.pop()]:
                if v not in cc:
                    cc.add(v); stack.append(v)
        seen |= cc
        if len(cc) > len(best):
            best = cc
    use = [L for L in use if L[0] in best]
    nodes = sorted(best)
    ni = {n: k for k, n in enumerate(nodes)}
    lw = np.array([float(rel[L]['inliers']) ** 0.5 for L in use])
    w = lw.copy()
    for it in range(20):
        rows = np.zeros((3 * len(use) + 3, 3 * len(nodes))); rhs = np.zeros(3 * len(use) + 3)
        ws = np.zeros(3 * len(use) + 3)
        for i, ((x, yy), wt) in enumerate(zip(use, w)):
            d = length[(x, yy)] * links[(x, yy)]
            for k in range(3):
                rows[3 * i + k, 3 * ni[yy] + k] = 1; rows[3 * i + k, 3 * ni[x] + k] = -1
                rhs[3 * i + k] = d[k]; ws[3 * i + k] = wt
        for k in range(3):
            rows[3 * len(use) + k, k] = 1; ws[3 * len(use) + k] = 1e3
        C = np.linalg.lstsq(rows * ws[:, None], rhs * ws, rcond=None)[0].reshape(-1, 3)
        res = np.array([np.linalg.norm(C[ni[yy]] - C[ni[x]] - length[(x, yy)] * links[(x, yy)]) / length[(x, yy)]
                        for x, yy in use])
        w = lw / (1 + (res / 0.1) ** 2)
    worst = sorted(zip(res, use), reverse=True)[:6]
    print(f'{len(nodes)} nodes placed from {len(use)} links; step misfit (in step lengths) median '
          f'{np.median(res):.3f}; worst ' + ', '.join(f'{ln(L)} {r_:.2f}' for r_, L in worst))
    others = sorted(n for n in meta['nodes'] if n not in ni)
    print(f'not placed: {[nm(n) for n in others]}')

    if a.compare:
        from evaluate_model import read_frames
        step = float(np.median([length[L] for L in use]))
        for path in a.compare:
            other = read_frames(path)
            com = [n for n in nodes if n in other]
            if len(com) < 3:
                print(f'against {path}: {len(com)} nodes in common, not compared')
                continue
            X = np.array([other[n][1] for n in com]); Y = np.array([C[ni[n]] for n in com])
            Xm, Ym = X.mean(0), Y.mean(0)
            U, S, Vt = np.linalg.svd((X - Xm).T @ (Y - Ym))
            D = np.diag([1, 1, np.sign(np.linalg.det(U @ Vt))])
            Rs_ = (U @ D @ Vt).T
            sc = (S * np.diag(D)).sum() / ((X - Xm) ** 2).sum()
            r_ = np.linalg.norm((sc * (Rs_ @ (X - Xm).T)).T + Ym - Y, axis=1) / step
            print(f'against {path}: {len(com)} nodes, centres differ by median {np.median(r_):.3f}, '
                  f'max {r_.max():.3f} median steps (node {nm(com[int(np.argmax(r_))])})')

    I = np.eye(3).tolist()
    json.dump({'nodes': {str(n): {'node_from_ref': I, 'centre': C[ni[n]].tolist(), 'yaw_pitch_tilt_deg': [0, 0, 0]}
                         for n in nodes}},
              open(os.path.join(out, 'nodes_solved.json'), 'w'), indent=1)
    json.dump({'sources': sorted(sources),
               'lengths': {f'{x}-{y}': length[(x, y)] for x, y in links},
               'directions': {f'{x}-{y}': links[(x, y)].tolist() for x, y in links},
               'floors': {f'{L[0]}-{L[1]}@{n}': list(f) for (L, n), f in floors.items()},
               'equations': [{'label': lab, 'kind': kind, 'residual': float(r_)}
                             for r_, (_, _, _, kind, lab) in zip(M @ sol - y, eqs)],
               'notes': notes}, open(os.path.join(out, 'scales.json'), 'w'), indent=0)


if __name__ == '__main__':
    main()
