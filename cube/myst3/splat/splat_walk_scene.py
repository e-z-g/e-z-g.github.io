#!/usr/bin/env python3
"""
splat.json for the viewer's walk: where the walk's nodes stand in a splat's
frame and how the nodes' frame turns into it.

    python splat_walk_scene.py SPARSE_TXT OUT_DIR --nodes 4084 4089 --splat walk84.spz

SPARSE_TXT is the text model the splat was trained in (its images.txt has
f1/MA-<node>.jpg for each node). Writes OUT_DIR/splat.json: the splat's file
name, each node's centre (model units) and the 3x3 matrix M that turns the
nodes' frame (node_depth.py's face directions: face 1 looking along -z, y
up; the viewer's own frame) into the model's, from the first node's face 1
camera, as walk_scene.py does: m = C + M n. Needs numpy.
"""
import argparse
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'colmap'))
from view_check import read_model  # noqa: E402

ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument('sparse'); ap.add_argument('out')
ap.add_argument('--nodes', nargs='+', required=True); ap.add_argument('--splat', required=True)
a = ap.parse_args()
_, imgs = read_model(a.sparse)
flip = np.diag([1.0, -1.0, -1.0])
cs, M = [], None
for n in a.nodes:
    R, t = imgs[f'f1/MA-{n}.jpg'][:2]
    cs.append((-R.T @ t).tolist())
    if M is None:
        M = R.T @ flip
os.makedirs(a.out, exist_ok=True)
with open(os.path.join(a.out, 'splat.json'), 'w') as f:
    json.dump({'splat': a.splat, 'nodes': a.nodes, 'centres': cs, 'matrix': M.tolist()}, f, indent=1)
print('centres', np.round(cs, 3).tolist(), 'apart', round(float(np.linalg.norm(np.subtract(cs[1], cs[0]))), 3))
print('matrix', np.round(M, 3).tolist())
