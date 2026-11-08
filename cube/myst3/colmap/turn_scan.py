#!/usr/bin/env python3
"""
Does a node face a different way from the node it links to? Scan every turn and
see which one the pictures pick.

    python turn_scan.py WORK [--features images_feat] [--links 1004-1007,2010-2011] [--out FILE]

For each linked pair in WORK/nodes.json, the six faces of both nodes are matched
(SIFT on the brightened copies, as solve_nodes.py does). Then for every turn
about the vertical from -180 to +179 degrees, one degree apart, the second node's
viewing directions are turned by it and the direction of travel t that the most
matches agree with is found (candidates from random pairs of matches). A match
agrees when |(a x R b) . t| < sin(0.3 deg): its two rays lie in one plane with t.
A distant point (sky, sea, far cliffs) has a x R b near zero at the right turn and
so agrees with every t there, and with none at a wrong turn: the far scenery
pins the turn on its own, and the near scenery adds the travel.

Printed per link: the turn with the most agreeing matches, that count, the count
at a turn of zero, and the best count more than 10 degrees away from the winner.
A real turn shows as a clear peak away from zero; a link with no clear peak
cannot say. Nodes are assumed level (no pitch or roll); solve_nodes.py's free
solve measures those where the matches allow. Needs numpy and opencv-python.
"""
import argparse
import math
import os
import sys

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from solve_nodes import features, match, roty  # noqa: E402

RNG = np.random.default_rng(0)
THR = math.sin(math.radians(0.3))


def scan(a, b, pairs=600):
    i = RNG.integers(0, len(a), pairs); j = RNG.integers(0, len(a), pairs)
    counts = np.zeros(360, int)
    for k, deg in enumerate(range(-180, 180)):
        n = np.cross(a, b @ roty(math.radians(deg)).T)          # a x R b, unnormalised
        nn = np.linalg.norm(n, axis=1)
        nu = n / np.maximum(nn, 1e-9)[:, None]
        T = np.cross(nu[i], nu[j])
        tn = np.linalg.norm(T, axis=1)
        ok = tn > 1e-6
        T = T[ok] / tn[ok, None]
        if not len(T):
            continue
        counts[k] = int((np.abs(n @ T.T) < THR).sum(0).max())
    return counts


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('work'); ap.add_argument('--features', default='images_feat')
    ap.add_argument('--links'); ap.add_argument('--out')
    a = ap.parse_args()
    import json
    meta = json.load(open(os.path.join(a.work, 'nodes.json')))
    names = meta.get('rooms', {})
    nm = lambda n: names.get(str(n), str(n))
    links = [tuple(l) for l in meta['links']]
    if a.links:
        want = {tuple(int(v) for v in p.split('-')) for p in a.links.split(',')}
        links = [l for l in links if l in want]
    sift = cv2.SIFT_create(nfeatures=5000, contrastThreshold=0.01)
    feats, rows = {}, {}
    folder = os.path.join(a.work, a.features)
    print('link                      matches   best turn  agree   at 0   next best (>10 deg away)')
    for x, y in links:
        for n in (x, y):
            if n not in feats:
                feats[n] = features(folder, meta['room'], n, sift)
        (da, fa), (db, fb) = feats[x], feats[y]
        m = match(fa, fb)
        if len(m) < 10:
            print(f'{nm(x):>9}-{nm(y):<10} {len(m):7d}   too few matches', flush=True)
            continue
        c = scan(da[m[:, 0]], db[m[:, 1]])
        k = int(np.argmax(c)); best = k - 180
        away = [(c[i], i - 180) for i in range(360) if abs((i - 180 - best + 180) % 360 - 180) > 10]
        nb, nbdeg = max(away)
        rows[f'{x}-{y}'] = {'matches': int(len(m)), 'best_turn': best, 'agree': int(c[k]), 'at_zero': int(c[180]),
                            'next_best': int(nb), 'next_best_turn': nbdeg, 'profile': c.tolist()}
        print(f'{nm(x):>9}-{nm(y):<10} {len(m):7d}   {best:+5d}    {c[k]:5d}  {c[180]:5d}   {nb:5d} at {nbdeg:+d}',
              flush=True)
    if a.out:
        json.dump(rows, open(a.out, 'w'), indent=0)


if __name__ == '__main__':
    main()
