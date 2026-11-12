#!/usr/bin/env python3
r"""
Nodes the model lacks or misplaces, placed in a scene by their own depth and the game's moves.

    python place_nodes.py MESH_DIR ROOMS OUT.json --nodes 3005 3006 ... [--reach 8] [--size 128]

MESH_DIR is scene_mesh.py's OUT (views.json and scales.json for the placed nodes, the mesh as scene.json with
scene.bin or its pieces, moge\<node>_moge_depth.npy and _moge_mask.npy for every node, and _anchored.npy for the
placed ones); ROOMS myst3_nodes.py's maps\rooms. Every node of the age faces the same way (the placed ones to
within 2.5 degrees), so a node is placed by its position and the scale of its MoGe distances alone, its turn
taken from a placed node it links to. The --nodes are placed one at a time, each once it links to a node already
placed (walks and zips both ways), in the order that reaches most placed neighbours first.

For a node: from each trial position, the scene's nearest surface in every direction (the mesh's vertices and
the points of nodes placed before it, kept nearest per cell of a --size wide panorama) against the node's own
MoGe distances there (sky masked), with the one scale that best fits them (the median ratio): the share of cells
where the two agree to 5%, less --heading-weight times the mean angle (radians) between the directions to its
placed neighbours and the game's headings of the moves between them. The placed neighbours' own anchored
distances count as surface too (the mesh's vertices leave gaps that far surfaces show through). The trials: from each placed neighbour along the game's heading of
the move between them (either way round), 0.3 to 2.5 node spacings, 0.4 to either side and 0.3 up or down;
then the best one refined on finer steps. Writes OUT.json: per node its position and turn in the viewer's
frame, the scale from MoGe's distances to the viewer's units, its score, and the neighbour and start it came from. A --nodes node the scene already has is placed as if it had not
(a test), and its distance from its place in the scene reported. Needs numpy, scipy, opencv-python.
"""
import argparse
import json
import math
import os
import sys

import cv2
import numpy as np
from scipy.spatial import cKDTree

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from scene_carve import read_scene  # noqa: E402

ROOMS = {'MACA': 1, 'MAIS': 2, 'MALL': 3, 'MASS': 4, 'MAWW': 5, 'MATO': 6}
MOVE = {138, 164, 139, 165, 140, 141}


def links(rooms):
    """(from, to, heading) for every move between nodes, mesh names."""
    out = []
    for room, num in ROOMS.items():
        f = os.path.join(rooms, room + '.json')
        if not os.path.exists(f):
            continue
        for l in json.load(open(f))['links']:
            if l['opcode'] in MOVE and l['heading'] is not None:
                dst = str((l['args'][0] - 1000) * 1000 + l['args'][1]) if len(l['args']) == 2 else str(num * 1000 + l['args'][0])
                out.append((str(num * 1000 + l['from']), dst, float(l['heading'])))
    return out


def ray_dirs(W, H):
    """Each cell's direction in a node's frame (x right, y up, -z face 1), moge_depth.py's panorama."""
    lon = ((np.arange(W) + 0.5) / W * 2 - 1) * np.pi; lat = (0.5 - (np.arange(H) + 0.5) / H) * np.pi
    lo, la = np.meshgrid(lon, lat)
    return np.stack([np.cos(la) * np.sin(lo), np.sin(la), -np.cos(la) * np.cos(lo)], -1)


def heading_dir(h):
    """The game's heading (0 along +z, as scene_links.py found) as a direction in the node's frame."""
    r = math.radians(h)
    return np.array([-math.sin(r), 0.0, math.cos(r)])


def load_depth(mesh, n, W, H, anchored=False, unit=1.0):
    pre = os.path.join(mesh, 'moge', n)
    D = np.load(pre + ('_anchored.npy' if anchored else '_moge_depth.npy')).astype(np.float32)
    D = cv2.resize(D, (W, H), interpolation=cv2.INTER_NEAREST)
    m = pre + '_moge_mask.npy'
    if os.path.exists(m):
        M = cv2.resize(np.load(m).astype(np.float32), (W, H), interpolation=cv2.INTER_NEAREST) > 0.5
        D = np.where(M, D, np.nan)
    D = np.where(np.isfinite(D) & (D > 0), D, np.nan)
    return D / unit if anchored else D


def agreement(x, rot, pts, D, W, H, reach):
    """From x: the nearest of pts per cell (directions in the node's frame, rot viewer to node) against D.
    Returns the share of D's cells that agree to 5% at the best scale, and that scale."""
    v = (pts - x) @ rot.T; r = np.linalg.norm(v, axis=1)
    k = (r > 0.05) & (r < reach); v, r = v[k], r[k]
    v = v / r[:, None]
    lon = np.arctan2(v[:, 0], -v[:, 2]); lat = np.arcsin(np.clip(v[:, 1], -1, 1))
    xi = np.clip(((lon / np.pi + 1) / 2 * W).astype(int), 0, W - 1); yi = np.clip(((0.5 - lat / np.pi) * H).astype(int), 0, H - 1)
    zb = np.full(H * W, np.inf); np.minimum.at(zb, yi * W + xi, r)
    zb = zb.reshape(H, W)
    both = np.isfinite(zb) & np.isfinite(D)
    if both.sum() < 100:
        return 0.0, 1.0
    s = float(np.median(zb[both] / D[both]))
    agree = both & (np.abs(np.log(zb / np.where(np.isfinite(D), D * s, 1.0))) < 0.05)
    return float(agree.sum() / np.isfinite(D).sum()), s


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('mesh'); ap.add_argument('rooms'); ap.add_argument('out')
    ap.add_argument('--nodes', nargs='+', required=True); ap.add_argument('--reach', type=float, default=8)
    ap.add_argument('--size', type=int, default=128)
    ap.add_argument('--heading-weight', type=float, default=0.5, help='score lost per radian of mean heading error')
    a = ap.parse_args()
    W, H = a.size, a.size // 2
    views = json.load(open(os.path.join(a.mesh, 'views.json')))
    unit = json.load(open(os.path.join(a.mesh, 'scales.json')))['unit']
    _, parts = read_scene(a.mesh)
    mesh_pts = parts['position'].astype(np.float64)
    L = links(a.rooms)
    dirs = ray_dirs(W, H)
    placed = {n: {'pos': np.array(v['pos']), 'rot': np.array(v['rot'])} for n, v in views.items() if n not in a.nodes}
    truth = {n: np.array(views[n]['pos']) for n in a.nodes if n in views}   # placed nodes given: a test
    clouds = []                                               # the clouds of nodes placed here, for the next
    anchored = {}
    todo, result = list(a.nodes), {}
    while todo:
        # the next: the one with most placed neighbours
        nb = {n: sorted({b for x, b, _ in L if x == n and b in placed} | {x for x, b, _ in L if b == n and x in placed}) for n in todo}
        n = max(todo, key=lambda n: len(nb[n]))
        if not nb[n]:
            print('left unplaced (no move to a placed node):', ' '.join(todo)); break
        todo.remove(n)
        D = load_depth(a.mesh, n, W, H)
        rot = placed[nb[n][0]]['rot']
        # the scene near the neighbours
        cen = np.array([placed[p]['pos'] for p in nb[n]])
        near = np.zeros(len(mesh_pts), bool)
        for c in cen:
            near |= np.linalg.norm(mesh_pts - c, axis=1) < a.reach + 2.5
        # and each placed neighbour's own anchored distances as points (dense where the mesh's vertices leave gaps)
        own = []
        for p in nb[n]:
            if os.path.exists(os.path.join(a.mesh, 'moge', p + '_anchored.npy')):
                A = load_depth(a.mesh, p, 4 * W, 2 * W, True, unit); ok = np.isfinite(A)
                own.append((ray_dirs(4 * W, 2 * W)[ok] * A[ok][:, None]) @ placed[p]['rot'] + placed[p]['pos'])
        pts = np.concatenate([mesh_pts[near]] + own + clouds)
        # the game's headings of the moves with placed neighbours, as directions in the viewer's frame
        heads = []
        for x, b, h in L:
            if x == n and b in placed:
                heads.append((placed[b]['pos'], rot.T @ heading_dir(h), 1))      # n to b
            elif b == n and x in placed:
                heads.append((placed[x]['pos'], placed[x]['rot'].T @ heading_dir(h), -1))   # x to n
        def total(y):
            ag, sc = agreement(y, rot, pts, D, W, H, a.reach)
            err = []
            for q, d, sgn in heads:
                v = (q - y) * sgn; v[1] = 0; dd = d.copy(); dd[1] = 0
                err.append(math.acos(np.clip(v @ dd / (np.linalg.norm(v) * np.linalg.norm(dd) + 1e-9), -1, 1)))
            return ag - a.heading_weight * (float(np.mean(err)) if err else 0.0), ag, sc
        trials = []
        for p in nb[n]:
            P = placed[p]
            for x, b, h in L:
                if x == p and b == n:
                    d = P['rot'].T @ heading_dir(h)                       # p to n
                elif x == n and b == p:
                    d = -(P['rot'].T @ heading_dir(h))                    # n to p, turned round (shared orientation)
                else:
                    continue
                side = np.cross(d, [0, 1, 0]); side /= np.linalg.norm(side) + 1e-9
                for dist in np.arange(0.3, 2.51, 0.2):
                    for lat in (-0.4, -0.2, 0, 0.2, 0.4):
                        for up in (-0.3, 0, 0.3):
                            trials.append((p, P['pos'] + d * dist + side * lat + np.array([0, up, 0]), dist))
        if not trials:
            print(f'node {n}: no heading to start from'); continue
        scored = [(total(x)[0], p, x, dist) for p, x, dist in trials]
        sc, p, x, dist = max(scored, key=lambda t: t[0])
        # finer steps round the best
        for step in (0.1, 0.05, 0.025):
            improved = True
            while improved:
                improved = False
                for dx in np.eye(3) * step:
                    for sgn in (1, -1):
                        y = x + sgn * dx; s2 = total(y)[0]
                        if s2 > sc:
                            sc, x, improved = s2, y, True
        sc, ag, scale = total(x)
        best = {'pos': x.tolist(), 'rot': rot.tolist(), 'scale': scale, 'score': sc, 'agree': ag, 'from': p, 'start': float(dist),
                'step': float(np.linalg.norm(x - placed[p]['pos'])), 'trials': len(trials)}
        if n in truth:
            best['error'] = float(np.linalg.norm(np.array(best['pos']) - truth[n]))
        result[n] = best
        placed[n] = {'pos': np.array(best['pos']), 'rot': rot}
        ok = np.isfinite(D)
        clouds.append(np.asarray((ray_dirs(W, H)[ok] * (D[ok] * scale)[:, None]) @ rot + x))
        print(f"node {n}: from {best['from']} ({best['step']:.2f} spacings away), scale {best['scale']:.3f}, "
              f"{best['agree'] * 100:.0f}% of its panorama agrees, score {best['score']:.3f}; "
              f"neighbours {' '.join(nb[n])}" + (f"; {best['error']:.3f} spacings from where the model has it" if 'error' in best else ''), flush=True)
        json.dump(result, open(a.out, 'w'), indent=1)
    # how far each placed node is from its other placed neighbours, against the game's headings
    for n, r in result.items():
        for x, b, h in L:
            if x == n and b in placed:
                d = placed[b]['pos'] - np.array(r['pos']); d = np.array(r['rot']) @ d
                bearing = math.degrees(math.atan2(-d[0], d[2])) % 360
                print(f'  {n} -> {b}: {np.linalg.norm(d):.2f} spacings, bearing {bearing:.0f} against heading {h:.0f}')


if __name__ == '__main__':
    main()
