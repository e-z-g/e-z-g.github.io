#!/usr/bin/env python3
"""
A walker's path from one node to another round what stands between them, and the directions it leaves and
arrives by: the sparse model's points (the rock, walls and rails it saw) mark a grid's cells as blocked, grown
by --clear; the cheapest path through the free cells (climbing costs --climb times as much as going level) is
cut short wherever a straight line stays free, then smoothed. Its tangent at each end is the direction of
departure and of arrival.

    python route_plan.py SPARSE_TXT PREFIX NODE_A NODE_B [--clear 0.5] [--cell 0.15] [--climb 2] [--out DIR]

Prints the two directions and their angles from the straight line; writes DIR/route_plan.json (path, directions)
and DIR/route_plan.png (the path seen from above and from the side, over the points). Needs numpy, Pillow.
"""
import argparse
import heapq
import json
import os
import sys

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from view_check import qvec2rot  # noqa: E402


def node_pose(sparse, name):
    with open(os.path.join(sparse, 'images.txt')) as fh:
        head = True
        for line in fh:
            if line.startswith('#'):
                continue
            if head:
                p = line.split()
                if p[9] == name:
                    R = qvec2rot(np.array(p[1:5], float)); t = np.array(p[5:8], float)
                    return -R.T @ t, -R[1]                       # centre; up (minus the camera's y)
            head = not head
    raise SystemExit(f'{name} not in the model')


def face_pose(sparse, names):
    out = {}
    with open(os.path.join(sparse, 'images.txt')) as fh:
        head = True
        for line in fh:
            if line.startswith('#'):
                continue
            if head:
                p = line.split()
                if p[9] in names:
                    out[p[9]] = (qvec2rot(np.array(p[1:5], float)), np.array(p[5:8], float))
            head = not head
    return out


def depth_points(sparse, prefix, ddir, step=4, f=320.0, c=320.0):
    """node_depth.py's six maps of one node as points in the model: distance along each ray from the grey level
    (0 is sky or past r_far, 255 is r_near), every step-th pixel."""
    rep = json.load(open(os.path.join(ddir, 'node_depth.json')))
    node, r_far, ratio = rep['node'], rep['r_far'], rep['ratio']
    poses = face_pose(sparse, {f'f{k}/{prefix}-{node}.jpg' for k in range(1, 7)})
    P = []
    for k in range(1, 7):
        g = np.asarray(Image.open(os.path.join(ddir, f'face{k}_measured-depth.png')), float)[::step, ::step] / 255
        v, u = np.mgrid[0:g.shape[0], 0:g.shape[1]] * step + step / 2
        ok = g > 0.02
        r = r_far / (1 + g[ok] * (ratio - 1))
        d = np.stack([(u[ok] - c) / f, (v[ok] - c) / f, np.ones(ok.sum())], -1)
        d /= np.linalg.norm(d, axis=1)[:, None]
        R, t = poses[f'f{k}/{prefix}-{node}.jpg']
        P.append(-R.T @ t + (d * r[:, None]) @ R)
    return np.vstack(P)


def points(sparse, max_err, min_track):
    P = []
    with open(os.path.join(sparse, 'points3D.txt')) as fh:
        for line in fh:
            if line.startswith('#'):
                continue
            p = line.split()
            if float(p[7]) <= max_err and (len(p) - 8) // 2 >= min_track:
                P.append([float(x) for x in p[1:4]])
    return np.array(P)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('sparse'); ap.add_argument('prefix'); ap.add_argument('a'); ap.add_argument('b')
    ap.add_argument('--clear', type=float, default=0.5, help='room kept round the path, in the straight line\'s lengths x 0.1 (0.5: 5%%)')
    ap.add_argument('--cell', type=float, default=0.03, help='grid cell, as a share of the straight line')
    ap.add_argument('--climb', type=float, default=2.0, help='cost of going up or down, against going level')
    ap.add_argument('--margin', type=float, default=0.6, help='the grid reaches this share of the line beyond the nodes')
    ap.add_argument('--max-err', type=float, default=2.0); ap.add_argument('--min-track', type=int, default=3)
    ap.add_argument('--depth', nargs='+', default=[], metavar='DIR', help="node_depth.py's maps of nodes, as more obstacles")
    ap.add_argument('--no-sparse', action='store_true', help="leave the sparse model's points out")
    ap.add_argument('--out', default='.')
    a = ap.parse_args()
    A, up = node_pose(a.sparse, f'f1/{a.prefix}-{a.a}.jpg'); B, _ = node_pose(a.sparse, f'f1/{a.prefix}-{a.b}.jpg')
    up /= np.linalg.norm(up)
    L = float(np.linalg.norm(B - A)); cell = a.cell * L; clear = a.clear * 0.1 * L
    # a frame with z up: x along the line's level part
    d = B - A; h = d - up * (d @ up)
    ex = h / np.linalg.norm(h) if np.linalg.norm(h) > 1e-6 * L else np.cross(up, [1, 0, 0]) / np.linalg.norm(np.cross(up, [1, 0, 0]))
    ey = np.cross(up, ex); F = np.stack([ex, ey, up])
    to = lambda X: (np.asarray(X) - A) @ F.T; back = lambda Y: A + np.asarray(Y) @ F
    pa, pb = to(A), to(B)
    lo = np.minimum(pa, pb) - a.margin * L; hi = np.maximum(pa, pb) + a.margin * L
    src = [] if a.no_sparse else [points(a.sparse, a.max_err, a.min_track)]
    src += [depth_points(a.sparse, a.prefix, dd) for dd in a.depth]
    P = to(np.vstack(src))
    P = P[np.all((P >= lo - clear) & (P <= hi + clear), 1)]
    n = np.ceil((hi - lo) / cell).astype(int) + 1
    occ = np.zeros(n, bool)
    r = int(np.ceil(clear / cell)); off = np.array([(i, j, k) for i in range(-r, r + 1) for j in range(-r, r + 1) for k in range(-r, r + 1)
                                                    if (i * i + j * j + k * k) * cell * cell <= clear * clear])
    q = np.rint((P - lo) / cell).astype(int)
    for o in off:
        c = q + o; ok = np.all((c >= 0) & (c < n), 1); occ[tuple(c[ok].T)] = True
    ia, ib = tuple(np.rint((pa - lo) / cell).astype(int)), tuple(np.rint((pb - lo) / cell).astype(int))
    for c in (ia, ib):                                   # the nodes themselves stand free
        sl = tuple(slice(max(0, x - 1), x + 2) for x in c); occ[sl] = False
    print(f'{a.a} -> {a.b}: {L:.3f} apart; {len(P)} points; grid {n.tolist()} cells of {cell:.3f}; {occ.mean() * 100:.1f}% blocked')
    steps = [(i, j, k) for i in (-1, 0, 1) for j in (-1, 0, 1) for k in (-1, 0, 1) if (i, j, k) != (0, 0, 0)]
    cost = {s: np.sqrt(s[0] ** 2 + s[1] ** 2 + (a.climb * s[2]) ** 2) for s in steps}
    hz = lambda c: np.sqrt((c[0] - ib[0]) ** 2 + (c[1] - ib[1]) ** 2 + (c[2] - ib[2]) ** 2)
    g = {ia: 0.0}; prev = {}; heap = [(hz(ia), ia)]
    while heap:
        _, c = heapq.heappop(heap)
        if c == ib:
            break
        for s in steps:
            m = (c[0] + s[0], c[1] + s[1], c[2] + s[2])
            if not (0 <= m[0] < n[0] and 0 <= m[1] < n[1] and 0 <= m[2] < n[2]) or occ[m]:
                continue
            ng = g[c] + cost[s]
            if ng < g.get(m, 1e18):
                g[m] = ng; prev[m] = c; heapq.heappush(heap, (ng + hz(m), m))
    if ib not in prev:
        raise SystemExit('no free path inside the grid: lower --clear or raise --margin')
    path = [ib]
    while path[-1] != ia:
        path.append(prev[path[-1]])
    path = np.array(path[::-1], float)

    def free(p, q):
        k = int(np.ceil(np.linalg.norm(q - p) * 2)) + 1
        s = np.rint(p + (q - p) * np.linspace(0, 1, k)[:, None]).astype(int)
        return not occ[tuple(s.T)].any()
    keep = [0]                                           # cut corners while the straight line stays free
    while keep[-1] < len(path) - 1:
        j = len(path) - 1
        while j > keep[-1] + 1 and not free(path[keep[-1]], path[j]):
            j -= 1
        keep.append(j)
    W = lo + path[keep] * cell; W[0], W[-1] = pa, pb
    # a smooth curve through the corners (Catmull-Rom), sampled finely
    E = np.vstack([2 * W[0] - W[1], W, 2 * W[-1] - W[-2]]); S = []
    for i in range(1, len(E) - 2):
        p0, p1, p2, p3 = E[i - 1:i + 3]
        for t in np.linspace(0, 1, 16, endpoint=False):
            S.append(0.5 * (2 * p1 + (p2 - p0) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t * t + (3 * p1 - p0 - 3 * p2 + p3) * t ** 3))
    S.append(W[-1]); S = np.array(S)
    seg = np.cumsum(np.r_[0, np.linalg.norm(np.diff(S, axis=0), axis=1)])
    def tangent(at_end):
        tgt = 0.15 * seg[-1]                             # over the first or last 15% of the path
        i = np.searchsorted(seg, seg[-1] - tgt if at_end else tgt)
        v = S[-1] - S[i] if at_end else S[i] - S[0]
        return v / np.linalg.norm(v)
    dep, arr = tangent(False), tangent(True); st = (pb - pa) / L
    ang = lambda v: float(np.degrees(np.arccos(np.clip(v @ st, -1, 1))))
    elev = lambda v: float(np.degrees(np.arcsin(np.clip(v[2], -1, 1))))
    print(f'path {seg[-1] / L:.2f} x the straight line, {len(keep) - 2} corners; departure {ang(dep):.1f} deg off the line '
          f'({elev(dep):+.1f} up), arrival {ang(arr):.1f} deg off ({elev(arr):+.1f} up); straight line {elev(st):+.1f} up')
    os.makedirs(a.out, exist_ok=True)
    json.dump({'from': a.a, 'to': a.b, 'apart': L, 'length': float(seg[-1]),
               'path_model': [back(p).tolist() for p in S[::4]] + [B.tolist()],
               'departure_model': (dep @ F).tolist(), 'arrival_model': (arr @ F).tolist(),
               'departure_off_deg': ang(dep), 'arrival_off_deg': ang(arr)},
              open(os.path.join(a.out, 'route_plan.json'), 'w'), indent=1)
    # the picture: above (x, y) and side (x, z), points grey, blocked cells pale, path red
    def panel(i, j, size=520):
        span = max(hi[i] - lo[i], hi[j] - lo[j]); s = (size - 20) / span
        im = Image.new('RGB', (size, size), (250, 250, 250)); dr = ImageDraw.Draw(im)
        xy = lambda p: (10 + (p[i] - lo[i]) * s, size - 10 - (p[j] - lo[j]) * s)
        bl = np.argwhere(occ.any(axis=3 - i - j)) if False else None
        for p in P:
            x, y = xy(p); dr.point((x, y), fill=(120, 120, 120))
        dr.line([xy(p) for p in S], fill=(220, 30, 30), width=3)
        dr.line([xy(pa), xy(pb)], fill=(60, 120, 220), width=1)
        for p, c in ((pa, (0, 160, 0)), (pb, (200, 120, 0))):
            x, y = xy(p); dr.ellipse((x - 5, y - 5, x + 5, y + 5), fill=c)
        dr.text((12, 8), ('from above' if j == 1 else 'from the side') + f'  green {a.a}  orange {a.b}  red path  blue straight', fill=(0, 0, 0))
        return im
    pic = Image.new('RGB', (1040, 520)); pic.paste(panel(0, 1), (0, 0)); pic.paste(panel(0, 2), (520, 0))
    pic.save(os.path.join(a.out, 'route_plan.png'))


if __name__ == '__main__':
    main()
