#!/usr/bin/env python3
"""
The files for walk.html: two or more nodes' faces and depths, and where each
node stands and which way it faces, from the model.

    python walk_scene.py IMAGES SPARSE_TXT OUT_DIR --node 4084 DEPTH_DIR R_FAR_JSON
        --node 4089 DEPTH_DIR R_FAR_JSON [...] [--suffix _measured-depth.png]

IMAGES holds the faces (f<k>/MA-<node>.jpg), SPARSE_TXT the text model with
their poses; each node's depth is DEPTH_DIR/MA-<node>-<k><suffix> in
node_depth.py's encoding, r_far from its JSON (in the model's units). Writes
OUT_DIR/MA-<node>-<k>.jpg and MA-<node>-<k>-depth.png, and OUT_DIR/scene.json:
for each node its centre (model units, the first node at the origin) and the
3x3 matrix that turns node_depth.py's face directions (face 1 looking along
-z, y up) into the model's frame, measured from its face 1 camera
(COLMAP's camera: x right, y down, z forward, so the node's frame is that
with y and z turned round), with up, the first node's up, for the viewer to
stand on. Needs numpy, Pillow.
"""
import argparse
import json
import os
import shutil
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from view_check import read_model  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('images'); ap.add_argument('sparse'); ap.add_argument('out')
    ap.add_argument('--node', nargs=3, action='append', required=True, metavar=('NODE', 'DEPTH_DIR', 'R_FAR_JSON'))
    ap.add_argument('--suffix', default='_measured-depth.png')
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    _, imgs = read_model(a.sparse)
    flip = np.diag([1.0, -1.0, -1.0])
    nodes, origin = [], None
    for node, ddir, js in a.node:
        R, t, _ = imgs[f'f1/MA-{node}.jpg']
        C = -R.T @ t
        if origin is None:
            origin = C
        M = R.T @ flip                     # node frame -> model frame
        for k in range(1, 7):
            shutil.copy(os.path.join(a.images, f'f{k}', f'MA-{node}.jpg'), os.path.join(a.out, f'MA-{node}-{k}.jpg'))
            shutil.copy(os.path.join(ddir, f'MA-{node}-{k}{a.suffix}'), os.path.join(a.out, f'MA-{node}-{k}-depth.png'))
        nodes.append({'node': node, 'centre': (C - origin).tolist(), 'matrix': M.tolist(),
                      'r_far': json.load(open(js))['r_far'], 'ratio': 20.0})
        print(f'MA-{node}: centre {np.round(C - origin, 3)}')
    up = (np.array(nodes[0]['matrix']) @ np.array([0.0, 1.0, 0.0])).tolist()
    with open(os.path.join(a.out, 'scene.json'), 'w') as fh:
        json.dump({'nodes': nodes, 'up': up}, fh, indent=1)


if __name__ == '__main__':
    main()
