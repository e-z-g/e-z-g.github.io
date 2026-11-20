#!/usr/bin/env python3
"""
The route's steps as directions, and the one axis of view nearest all of them: the direction whose largest angle to
any step is smallest (the narrowest cone round every step), searched over the sphere.

    python route_axis.py IMAGES SPARSE PREFIX NODE NODE ... 

Prints each step's angle to A->B (walk_ends.py's axis now) and to the minimax axis, and the axis in the model's frame.
"""
import sys, os
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import walk_ends
from view_check import read_model
images, sparse, prefix, *nodes = sys.argv[1:]
walk_ends.PREFIX = prefix
_, imgs = read_model(sparse)
C = [walk_ends.faces_of(images, imgs, n)[0] for n in nodes]
d = np.array([(b - a) / np.linalg.norm(b - a) for a, b in zip(C, C[1:])])
ab = (C[-1] - C[0]) / np.linalg.norm(C[-1] - C[0])
g = np.random.default_rng(0).normal(size=(200000, 3)); g /= np.linalg.norm(g, axis=1)[:, None]
worst = np.degrees(np.arccos(np.clip(g @ d.T, -1, 1))).max(1); best = g[worst.argmin()]
ang = lambda v: [round(float(np.degrees(np.arccos(np.clip(v @ x, -1, 1)))), 1) for x in d]
print('steps', ' '.join(f'{a}->{b}' for a, b in zip(nodes, nodes[1:])))
print('angle to A->B   ', ang(ab))
print('angle to minimax', ang(best), 'axis', np.round(best, 4).tolist())
