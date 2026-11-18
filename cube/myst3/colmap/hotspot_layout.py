#!/usr/bin/env python3
r"""
Every node of an age placed from the game's hotspots alone, as priors for COLMAP's pose_prior_mapper.

    python hotspot_layout.py WALK.json OUT.json [--rooms MACA MAIS ...] [--eye 0.226] [--model VIEWS.json]

WALK.json is node_walk.py's walk.json. A node of another state (n >= 100) stands where n % 100 does. Unknowns: each
node's x, y, z in node spacings (y up, heading h along (-sin h, 0, cos h), as scene_mesh.py's frame). Residuals, for
each walk or zip between two nodes:
  - the hotspot's heading against the bearing to the other node (10 degrees for walks, 20 for zips);
  - the distance: from the pair of hotspots' pitches when both exist (d = 2e / (tan(-p_ab) + tan(-p_ba)), each
    pitch to the other's floor from an eye e above one's own), held to 0.3-3, at 30%; otherwise 1 +- 0.5 for a walk
    and 3 +- 2 for a zip;
  - the climb from the same pitches (d (tan(-p_ba) - tan(-p_ab)) / 2, +-0.15), or level +-0.5 with one hotspot.
Movies are left out (a lift's hotspot is a lever). The first node is held at the origin; the walks fix turn and
scale. Each linked group is solved alone; groups after the first are left where they fall (their places mean
nothing against the first's) and marked. With --model (a scene's views.json, the same node numbers: room's place in
--rooms times 1000 plus the node), the layout is fitted to the model by a similarity and the distances printed.
Writes {node: {"pos": [x, y, z], "group": k}}. Needs numpy, scipy.
"""
import argparse
import json
import math

import numpy as np
from scipy.optimize import least_squares
from scipy.sparse import lil_matrix


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('walk'); ap.add_argument('out')
    ap.add_argument('--rooms', nargs='+', default=['MACA', 'MAIS', 'MALL', 'MASS', 'MAWW', 'MATO'])
    ap.add_argument('--eye', type=float, default=0.226); ap.add_argument('--model')
    ap.add_argument('--no-zips', action='store_true', help='leave zips out (their lengths are guesses)')
    ap.add_argument('--dist-sd', type=float, default=0.3, help='a pitch distance\'s standard deviation, as a share of it')
    a = ap.parse_args()
    num = lambda nm: str((a.rooms.index(nm[:4]) + 1) * 1000 + int(nm[5:]) % 100)
    W = json.load(open(a.walk))['nodes']
    spots = {}                                         # (n, m) -> [(heading, pitch, kind)]
    for nm, ss in W.items():
        if nm[:4] not in a.rooms:
            continue
        for s in ss:
            if not s['to'] or s['to'][:4] not in a.rooms or s['kind'] not in ('walk', 'walk-room', 'zip', 'zip-room'):
                continue
            n, m = num(nm), num(s['to'])
            if n != m and not (a.no_zips and s['kind'].startswith('zip')):
                spots.setdefault((n, m), []).append((s['rects'][0][1], s['rects'][0][0], s['kind'].split('-')[0]))
    nodes = sorted({x for k in spots for x in k}, key=int)
    # linked groups
    parent = {n: n for n in nodes}
    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]; x = parent[x]
        return x
    for n, m in spots:
        parent[find(n)] = find(m)
    groups = {}
    for n in nodes:
        groups.setdefault(find(n), []).append(n)
    groups = sorted(groups.values(), key=len, reverse=True)
    t = lambda p: math.tan(math.radians(-p))
    out = {}
    for gi, g in enumerate(groups):
        idx = {n: i for i, n in enumerate(g)}
        H, D, C = [], [], []
        for (n, m), ss in spots.items():
            if n not in idx:
                continue
            h, p, kind = ss[0]
            H.append((idx[n], idx[m], h, 10.0 if kind == 'walk' else 20.0))
            if n < m or (m, n) not in spots:
                back = spots.get((m, n))
                den = t(p) + t(back[0][1]) if back else 0
                if back and den > 0:
                    d = min(3.0, max(0.3, 2 * a.eye / den))
                    D.append((idx[n], idx[m], d, a.dist_sd * d))
                    C.append((idx[n], idx[m], d * (t(back[0][1]) - t(p)) / 2, 0.15))
                else:
                    D.append((idx[n], idx[m], 1.0 if kind == 'walk' else 3.0, 0.5 if kind == 'walk' else 2.0))
                    C.append((idx[n], idx[m], 0.0, 0.5))
        k = len(g)

        def res(x):
            P = x.reshape(k, 3)
            r = []
            for i, j, h, sg in H:
                d = P[j] - P[i]
                r.append(((math.degrees(math.atan2(-d[0], d[2])) - h + 180) % 360 - 180) / sg)
            for i, j, d0, sg in D:
                r.append((np.linalg.norm(P[j] - P[i]) - d0) / sg)
            for i, j, c0, sg in C:
                r.append((P[j][1] - P[i][1] - c0) / sg)
            r += list(P[0] * 100)                      # the first node at the origin
            return np.array(r)

        # start: walk the headings out from the first node, breadth first
        x0 = np.zeros((k, 3)); seen = {0}; todo = [0]
        adj = {}
        for i, j, h, sg in H:
            adj.setdefault(i, []).append((j, h))
        while todo:
            i = todo.pop(0)
            for j, h in adj.get(i, []):
                if j not in seen:
                    seen.add(j); todo.append(j)
                    x0[j] = x0[i] + [-math.sin(math.radians(h)), 0, math.cos(math.radians(h))]
        for j in range(k):
            if j not in seen:
                x0[j] = np.random.default_rng(j).normal(size=3)
        sp = lil_matrix((len(H) + len(D) + len(C) + 3, 3 * k), dtype=int)
        row = 0
        for lst in (H, D, C):
            for e in lst:
                for q in (e[0], e[1]):
                    sp[row, 3 * q:3 * q + 3] = 1
                row += 1
        sp[row:row + 3, 0:3] = 1
        s = least_squares(res, x0.ravel(), jac_sparsity=sp, loss='soft_l1', f_scale=2.0, x_scale='jac')
        P = s.x.reshape(k, 3)
        r = res(s.x)
        hr = np.abs(r[:len(H)]) * np.array([e[3] for e in H])
        print(f'group {gi}: {k} nodes, {len(H)} headings (fit median {np.median(hr):.1f} deg, 90% {np.percentile(hr, 90):.1f}), '
              f'{len(D)} distances' + ('' if gi == 0 else ' (not tied to group 0)'))
        for n in g:
            out[n] = {'pos': [round(float(c), 4) for c in P[idx[n]]], 'group': gi}
    json.dump(out, open(a.out, 'w'), indent=1)
    if a.model:
        V = json.load(open(a.model))
        common = [n for n in out if n in V and out[n]['group'] == 0 and not V[n].get('alone')]
        A = np.array([out[n]['pos'] for n in common]); B = np.array([V[n]['pos'] for n in common])
        ma, mb = A.mean(0), B.mean(0); U, S, Vt = np.linalg.svd((B - mb).T @ (A - ma))
        R = U @ np.diag([1, 1, np.sign(np.linalg.det(U @ Vt))]) @ Vt
        sc = S.sum() / ((A - ma) ** 2).sum()
        E = np.linalg.norm(sc * (A - ma) @ R.T + mb - B, axis=1)
        print(f'against the model ({len(common)} nodes, scale {sc:.3f}): median {np.median(E):.2f} spacings, 90% {np.percentile(E, 90):.2f}')
        for e, n in sorted(zip(E, common), reverse=True)[:12]:
            print(f'  {n}: {e:.2f}')


if __name__ == '__main__':
    main()
