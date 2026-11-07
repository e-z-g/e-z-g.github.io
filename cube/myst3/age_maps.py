#!/usr/bin/env python3
"""
Whole-age node maps for Myst III, in two stages.

    python age_maps.py myst3.dat maps/ages

(myst3.dat is ScummVM's engine data: myst3_nodes.py downloads it, or get it
from github.com/scummvm/scummvm, dists/engine-data/myst3.dat. Needs numpy.)

Stage 1, each room alone. Every movement hotspot's heading is a bearing
(all nodes share one world orientation). Walks pull towards one-unit steps
along their bearing; zips (clicking on a distant spot you can see) are
bearings to farther nodes and set how long the steps between them really
are. A direction-only bearing can't tell ahead from behind, so any zip that
comes out pointing backwards is required to point forwards and the room is
solved again.

Stage 2, rooms as rigid blocks. A move into another room is not always a
bearing to where you arrive: its hotspot can be a door, a lift or a cart.
In one fit with everything, such links contradicted each other (Voltaic's
ENSI 35 -> ENPP 1 at 232 deg, the way back at 99 deg) and folded whole
areas. So only cross-room links whose way there and way back agree to
within 20 deg of opposite place one room relative to another, and they can
only move a room, never reshape it. A room with no such link is drawn on
its own.
"""
import importlib.util, json, math, os, sys
from collections import defaultdict
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location('m3', os.path.join(HERE, 'myst3_nodes.py'))
m3 = importlib.util.module_from_spec(spec); spec.loader.exec_module(m3)
if len(sys.argv) < 3:
    sys.exit('usage: python age_maps.py myst3.dat out_dir')
scripts = m3.load_dat(sys.argv[1])
OUT = sys.argv[2]; os.makedirs(OUT, exist_ok=True)

ROOM_ID = {301: 'TOHO', 401: 'TOHB', 501: 'LEIS', 502: 'LEOS', 503: 'LEET', 504: 'LELT', 505: 'LEMT', 506: 'LEOF',
           601: 'LIDR', 602: 'LISW', 603: 'LIFO', 604: 'LISP', 605: 'LINE', 701: 'ENSI', 703: 'ENPP', 704: 'ENEM',
           705: 'ENLC', 706: 'ENDD', 707: 'ENCH', 708: 'ENLI', 801: 'NACH', 1001: 'MACA', 1002: 'MAIS', 1003: 'MALL',
           1004: 'MASS', 1005: 'MAWW', 1006: 'MATO'}
AGES = {'Tomahna': ['TOHO', 'TOHB'], "J'nanin": ['LEIS', 'LEOS', 'LEET', 'LELT', 'LEMT', 'LEOF'],
        'Edanna': ['LIDR', 'LISW', 'LIFO', 'LISP', 'LINE'], 'Voltaic': ['ENSI', 'ENPP', 'ENEM', 'ENLC', 'ENDD', 'ENCH', 'ENLI'],
        'Narayan': ['NACH'], 'Amateria': ['MACA', 'MAIS', 'MALL', 'MASS', 'MAWW', 'MATO']}
W_BEARING, W_LENGTH, W_SAME = 1.0, 0.4, 10.0
CROSS_AGREE_DEG, CROSS_GAP = 20.0, 2.0


def bearing(h):
    a = math.radians(h); return np.array([math.sin(a), math.cos(a)])
def mean_angle(hs):
    v = sum(bearing(h) for h in hs); return math.degrees(math.atan2(v[0], v[1])) % 360
def angdiff(a, b):
    return (a - b + 540) % 360 - 180


def edges(rooms):
    walks, zips, cross, same = defaultdict(list), defaultdict(list), defaultdict(list), set()
    for room in rooms:
        if room not in scripts: continue
        for n, lst in m3.room_hotspots(scripts[room]).items():
            if n >= 32000: continue
            for rects, ops in lst:
                heads = [h for _, h in rects]
                for op, args in ops:
                    if op in (136, 137, 138) and args: d, tgt = walks, (room, args[0])
                    elif op == 164 and args:
                        if args[0] == n or abs(args[0] - n) % 100 == 0:
                            same.add(tuple(sorted([(room, n), (room, args[0])]))); continue
                        d, tgt = walks, (room, args[0])
                    elif op == 140 and args: d, tgt = zips, (room, args[0])
                    elif op in (139, 141, 165) and len(args) >= 2 and ROOM_ID.get(args[0]) in rooms:
                        d, tgt = cross, (ROOM_ID[args[0]], args[1])
                    else: continue
                    if heads and tgt != (room, n): d[((room, n), tgt)] += heads
    return walks, zips, cross, same


def solve_room(nodes, walks, zips, same):
    """Positions for one room's nodes; returns {node: xy} and its connected groups."""
    skip = set()
    for (a, b), hs in walks.items():
        if (b, a) in walks and abs(angdiff(mean_angle(walks[(b, a)]), mean_angle(hs) + 180)) > 45:
            skip |= {(a, b), (b, a)}                     # ladders, turn-arounds
    W = [(e, mean_angle(h)) for e, h in walks.items() if e not in skip]
    Z = [(e, mean_angle(h)) for e, h in zips.items()]
    parent = {n: n for n in nodes}
    def f(x):
        while parent[x] != x: parent[x] = parent[parent[x]]; x = parent[x]
        return x
    for (a, b), _ in W + Z:
        if a in parent and b in parent: parent[f(a)] = f(b)
    for a, b in same:
        if a in parent and b in parent: parent[f(a)] = f(b)
    groups = defaultdict(list)
    for n in nodes: groups[f(n)].append(n)
    pos, errs, lens = {}, [], []
    for g in groups.values():
        idx = {n: i for i, n in enumerate(g)}
        rows, rhs = [], []
        def eq(coef, val, w):
            r = np.zeros(2 * len(g))
            for (n, ax), c in coef.items(): r[2 * idx[n] + ax] += c
            rows.append(r * w); rhs.append(val * w)
        Wg = [(e, h) for e, h in W if e[0] in idx and e[1] in idx]
        Zg = [(e, h) for e, h in Z if e[0] in idx and e[1] in idx]
        for (a, b), h in Wg + Zg:
            u = bearing(h); nr = np.array([-u[1], u[0]])
            eq({(b, 0): nr[0], (b, 1): nr[1], (a, 0): -nr[0], (a, 1): -nr[1]}, 0.0, W_BEARING)
        for (a, b), h in Wg:
            u = bearing(h)
            for ax in (0, 1): eq({(b, ax): 1.0, (a, ax): -1.0}, u[ax], W_LENGTH)
        for a, b in same:
            if a in idx and b in idx:
                for ax in (0, 1): eq({(b, ax): 1.0, (a, ax): -1.0}, 0.0, W_SAME)
        for ax in (0, 1): eq({(g[0], ax): 1.0}, 0.0, 100.0)
        forced = set()
        for _ in range(20):
            x, *_ = np.linalg.lstsq(np.array(rows), np.array(rhs), rcond=None)
            P = {n: x[2 * idx[n]:2 * idx[n] + 2] for n in g}
            wrong = [((a, b), h) for (a, b), h in Zg if (a, b) not in forced and bearing(h) @ (P[b] - P[a]) < 0.5]
            if not wrong: break
            for (a, b), h in wrong:
                u = bearing(h); forced.add((a, b))
                eq({(b, 0): u[0], (b, 1): u[1], (a, 0): -u[0], (a, 1): -u[1]}, 1.0, W_BEARING)
        pos.update(P)
        for (a, b), h in Wg + Zg:
            v = P[b] - P[a]
            if np.linalg.norm(v) > 1e-6: errs.append(abs(angdiff(math.degrees(math.atan2(v[0], v[1])), h)))
        lens += [float(np.linalg.norm(P[b] - P[a])) for (a, b), _ in Wg]
    return pos, list(groups.values()), skip, errs, lens


def build(age, rooms):
    walks, zips, cross, same = edges(rooms)
    nodes_by_room = defaultdict(set)
    for (a, b) in list(walks) + list(zips) + list(cross):
        nodes_by_room[a[0]].add(a); nodes_by_room[b[0]].add(b)
    for a, b in same: nodes_by_room[a[0]] |= {a, b}
    pos, blocks, skips, errs, lens = {}, [], set(), [], []
    for room in rooms:
        rn = sorted(nodes_by_room[room])
        if not rn: continue
        p, groups, skip, e, l = solve_room(rn, walks, zips, same)
        pos.update(p); skips |= skip; errs += e; lens += l
        blocks += [tuple(sorted(g)) for g in groups]
    block_of = {n: i for i, b in enumerate(blocks) for n in b}
    # Stage 2: trustworthy cross-room links move whole blocks.
    good = []
    for (a, b), hs in cross.items():
        if (b, a) in cross and a < b:
            h1, h2 = mean_angle(hs), mean_angle(cross[(b, a)])
            if abs(angdiff(h2, h1 + 180)) <= CROSS_AGREE_DEG:
                good.append(((a, b), (h1 + angdiff(h2 + 180, h1) / 2) % 360))
    parent = list(range(len(blocks)))
    def f(x):
        while parent[x] != x: parent[x] = parent[parent[x]]; x = parent[x]
        return x
    for (a, b), _ in good: parent[f(block_of[a])] = f(block_of[b])
    clusters = defaultdict(list)
    for i in range(len(blocks)): clusters[f(i)].append(i)
    offset = {}
    for cl in clusters.values():
        idx = {bi: i for i, bi in enumerate(cl)}
        rows, rhs = [], []
        def eq(coef, val, w):
            r = np.zeros(2 * len(cl))
            for (bi, ax), c in coef.items(): r[2 * idx[bi] + ax] += c
            rows.append(r * w); rhs.append(val * w)
        links = [((a, b), h) for (a, b), h in good if block_of[a] in idx and block_of[b] in idx]
        for (a, b), h in links:
            u = bearing(h); nr = np.array([-u[1], u[0]]); A, B = block_of[a], block_of[b]
            d = pos[b] - pos[a]
            # (tB + pb) - (tA + pa) on the bearing, about CROSS_GAP ahead
            eq({(B, 0): nr[0], (B, 1): nr[1], (A, 0): -nr[0], (A, 1): -nr[1]}, -(nr @ d), 1.0)
            eq({(B, 0): u[0], (B, 1): u[1], (A, 0): -u[0], (A, 1): -u[1]}, CROSS_GAP - (u @ d), 0.2)
        for ax in (0, 1): eq({(cl[0], ax): 1.0}, 0.0, 100.0)
        x, *_ = np.linalg.lstsq(np.array(rows), np.array(rhs), rcond=None)
        for bi in cl: offset[bi] = x[2 * idx[bi]:2 * idx[bi] + 2]
    final = {n: pos[n] + offset[block_of[n]] for n in pos}
    cl_list = sorted(clusters.values(), key=lambda c: -sum(len(blocks[i]) for i in c))
    stats = {'nodes': len(final), 'walk_length_5_50_95': [round(float(np.percentile(lens, q)), 2) for q in (5, 50, 95)] if lens else None,
             'bearing_error_deg_50_90': [round(float(np.percentile(errs, q)), 1) for q in (50, 90)] if errs else None,
             'cross_room_links': len({tuple(sorted(k)) for k in cross}), 'cross_room_links_used': len(good),
             'map_pieces': [sum(len(blocks[i]) for i in c) for c in cl_list]}
    key = lambda n: f'{n[0]}:{n[1]}'
    json.dump({'age': age, 'rooms': rooms, 'stats': stats,
               'positions': {key(n): [round(float(v), 3) for v in p] for n, p in final.items()},
               'pieces': [[key(n) for i in c for n in blocks[i]] for c in cl_list],
               'walks': [[key(a), key(b), mean_angle(h)] for (a, b), h in walks.items() if (a, b) not in skips],
               'zips': [[key(a), key(b), mean_angle(h)] for (a, b), h in zips.items()],
               'cross_used': [[key(a), key(b), h] for (a, b), h in good],
               'cross_unused': [[key(a), key(b), mean_angle(h)] for (a, b), h in cross.items()
                                if not any((a, b) == e or (b, a) == e for e, _ in good)],
               'same_place': [[key(a), key(b)] for a, b in same]},
              open(os.path.join(OUT, age.replace("'", '') + '.json'), 'w'), indent=1)
    print(f'{age:9} {stats}')


for age, rooms in AGES.items():
    build(age, rooms)
