#!/usr/bin/env python3
r"""
Cut out of a scene mesh the surface the nodes see through: what lies well in front of what a node sees in
that direction cannot be there, or the node's picture would show it.

    python scene_carve.py MESH_DIR OUT_DIR [--shells DIR] [--front 0.7] [--reach 8] [--votes 2] [--sky]

MESH_DIR is scene_attrs.py's output in the viewer's frame (scene.json with scene.bin or its pieces,
views.json) and scene_shells.py's panoramas of each node's distances (--shells, default MESH_DIR\shells). For every
node and every vertex within --reach of it: the vertex's distance from the node against the nearest the node
sees round that direction (the least of the 3 x 3 cells about it, so an edge between near and far counts as
near). Nearer than --front times that, the node sees through it; within 10% of the cell's own distance, the
node agrees with it. A vertex goes when --votes nodes see through it, or one does and none agrees; with --sky,
a vertex within --reach in a direction a node sees only sky (all nine cells) counts as seen through too. A
triangle goes when two of its vertices go. Such surface is invisible at the node that put it there (its own
picture lands on it from the same direction) and in the way between nodes. Writes OUT_DIR\scene.json and the
scene.bin pieces (vertices kept as they are, triangles fewer) and prints how much went, by room.
Needs numpy, scipy, Pillow.
"""
import argparse
import json
import os

import numpy as np
from PIL import Image
from scipy.ndimage import minimum_filter


def read_scene(d):
    head = json.load(open(os.path.join(d, 'scene.json')))
    raw = b''.join(open(os.path.join(d, f), 'rb').read() for f in head.get('files', ['scene.bin']))
    part = lambda name: np.frombuffer(raw, dtype=head['parts'][name]['type'], count=head['parts'][name]['bytes'] // np.dtype(head['parts'][name]['type']).itemsize,
                                      offset=head['parts'][name]['offset']).reshape(-1, head['parts'][name]['size'])
    return head, {k: part(k) for k in head['parts']}


def write_scene(d, parts, piece=90e6):
    os.makedirs(d, exist_ok=True)
    head, off, blob = {'parts': {}}, 0, bytearray()
    for name in ('position', 'index', 'color', 'albedo', 'roughMetal'):
        arr = parts[name]; b = np.ascontiguousarray(arr).tobytes()
        head['parts'][name] = {'offset': off, 'bytes': len(b), 'type': str(arr.dtype), 'size': arr.shape[1]}
        blob += b; off += len(b); pad = (-off) % 4; blob += b'\0' * pad; off += pad
    head['vertices'] = len(parts['position']); head['triangles'] = len(parts['index']); head['bytes'] = off
    for f in os.listdir(d):
        if f.startswith('scene.bin'):
            os.remove(os.path.join(d, f))
    if off > piece:
        head['files'] = []
        for i in range(0, off, int(piece)):
            name = f'scene.bin.{i // int(piece)}'; open(os.path.join(d, name), 'wb').write(blob[i:i + int(piece)]); head['files'].append(name)
    else:
        open(os.path.join(d, 'scene.bin'), 'wb').write(blob)
    json.dump(head, open(os.path.join(d, 'scene.json'), 'w'), indent=1)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('mesh'); ap.add_argument('out'); ap.add_argument('--shells')
    ap.add_argument('--front', type=float, default=0.7); ap.add_argument('--reach', type=float, default=8)
    ap.add_argument('--votes', type=int, default=2); ap.add_argument('--sky', action='store_true')
    a = ap.parse_args()
    head, parts = read_scene(a.mesh)
    P = parts['position'].astype(np.float64); T = parts['index']
    views = json.load(open(os.path.join(a.mesh, 'views.json')))
    through = np.zeros(len(P), np.int32); agree = np.zeros(len(P), np.int32)
    for n, v in views.items():
        f = os.path.join(a.shells or os.path.join(a.mesh, 'shells'), f'MA-{n}.png')
        if not os.path.exists(f):
            continue
        px = np.asarray(Image.open(f)).astype(np.int64); S = (px[..., 0] * 256 + px[..., 1]) / 1000.0
        H, W = S.shape
        Sinf = np.where(S > 0, S, np.inf)
        # the least of the 3 x 3 cells about each, wrapping round in longitude
        Smin = minimum_filter(np.pad(Sinf, ((0, 0), (1, 1)), mode='wrap'), size=3, mode='nearest')[:, 1:-1]
        pos = np.array(v['pos']); Q = np.array(v['rot'])
        idx = np.nonzero(np.linalg.norm(P - pos, axis=1) < a.reach)[0]
        d = (P[idx] - pos) @ Q.T; r = np.linalg.norm(d, axis=1); ok = r > 1e-6
        idx, d, r = idx[ok], d[ok] / r[ok, None], r[ok]
        lon = np.arctan2(d[:, 0], -d[:, 2]); lat = np.arcsin(np.clip(d[:, 1], -1, 1))
        x = np.clip(((lon / np.pi + 1) / 2 * W).astype(int), 0, W - 1); y = np.clip(((0.5 - lat / np.pi) * H).astype(int), 0, H - 1)
        m = Smin[y, x]; s = S[y, x]
        thr = np.isfinite(m) & (r < a.front * m)
        if a.sky:
            thr |= ~np.isfinite(m)
        through[idx[thr]] += 1
        agr = (s > 0) & (np.abs(np.log(np.maximum(r, 1e-6) / np.maximum(s, 1e-6))) < 0.1)
        agree[idx[agr]] += 1
    gone = (through >= a.votes) | ((through >= 1) & (agree == 0))
    keep = gone[T].sum(1) < 2
    print(f'{gone.mean() * 100:.1f}% of {len(P)} vertices seen through; {(~keep).sum()} of {len(T)} triangles cut ({(~keep).mean() * 100:.1f}%)')
    # by room, from the nearest node
    names = list(views); C = np.array([views[n]['pos'] for n in names])
    cen = P[T].mean(1)
    from scipy.spatial import cKDTree
    _, near = cKDTree(C).query(cen)
    rooms = np.array([names[i][0] for i in near])
    for rm, label in zip('123456', ['MACA', 'MAIS', 'MALL', 'MASS', 'MAWW', 'MATO']):
        sel = rooms == rm
        if sel.any():
            print(f'  {label}: {(~keep[sel]).sum()} of {sel.sum()} triangles cut ({(~keep[sel]).mean() * 100:.1f}%)')
    parts = dict(parts); parts['index'] = T[keep]
    write_scene(a.out, parts)
    print(a.out)


if __name__ == '__main__':
    main()
