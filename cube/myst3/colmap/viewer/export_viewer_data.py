#!/usr/bin/env python3
"""
Pack a dense reconstruction of a Myst III room for viewer/index.html.

    python export_viewer_data.py FUSED.ply FACE1_POSES.txt OUT_DIR [--mesh MESH.ply]
                                 [--names NODES.json] [--title TEXT]
                                 [--faces DIR --face-pattern 'f{f}/ENSI-{n:04d}.jpg']
                                 [--fill FILL.ply --fill-max 600000] [--rooms MACA,MAIS]

FACE1_POSES.txt is the face-1 lines of the sparse model's images.txt (one line per
node: id, qw qx qy qz, tx ty tz, camera, f1/ROOM-NNNN.jpg). The world is the model's
turned into the nodes' common cube frame (the mean of their node_from_world
rotations), so y is up and node frames' front faces look along -z, whatever axes
the model has (COLMAP's own mapper picks arbitrary ones). --names takes
prepare_age.py's nodes.json, whose 'rooms' turn node numbers into ROOM:node labels.

Writes to OUT_DIR:
  points.bin  float32 x,y,z for every point, then uint8 r,g,b for every point
  mesh.bin    (with --mesh) float32 x,y,z per vertex, uint8 r,g,b per vertex,
              uint32 three vertex indices per triangle; a COLMAP Delaunay mesh has
              no colours, so each vertex takes the mean colour of the fused points
              in its grid cell (or the nearest filled cell around it)
  scene.json  counts, the centre and size of the scene, and each node's centre,
              node_from_world rotation and floor height, for the node markers, the
              views from a node and the floor patches
  face-<n>-<f>.jpg  (with --faces) each node's six faces, copied: the viewer puts
              them round the camera as a backdrop at infinity when standing at a
              node (what has no parallax, sky and far scenery, is exactly that),
              and lays each bottom face flat at the node's floor height
  fill.bin    (with --fill) depth_fill.py's points, thinned to one per cell of a grid
              sized so that at most --fill-max remain, in points.bin's layout
--rooms (with --names) keeps only those rooms: their nodes, and the points whose
nearest node is one of them (the mesh is left out).
Floor height: how far the dense points straight under a node (within a tenth of
the nodes' median spacing sideways) lie below it, the nearest tenth of them; where
fewer than five points are there, the median over the nodes that have them.
Where they lie more than 1.3 times that median down, the node stands on a platform
the cloud lacks (a lift has raised it; the points are the ground below), so the
floor is laid at the median eye height and the drop kept as ground_below.
Everything is moved so the nodes' mean centre is at the origin. Needs numpy.
"""
import argparse
import json
import os
import re
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from evaluate_model import qvec2rot  # noqa: E402
from face_geometry import cam_from_node  # noqa: E402
from render_cloud import read_ply  # noqa: E402


def read_ply_mesh(path):
    with open(path, 'rb') as fh:
        nv = nf = 0
        while True:
            line = fh.readline().decode().strip()
            if line.startswith('element vertex'):
                nv = int(line.split()[-1])
            elif line.startswith('element face'):
                nf = int(line.split()[-1])
            elif line == 'end_header':
                break
        v = np.frombuffer(fh.read(nv * 12), '<f4').reshape(nv, 3)
        f = np.frombuffer(fh.read(nf * 13), dtype=[('n', 'u1'), ('i', '<i4', 3)])
    assert (f['n'] == 3).all()
    return v.astype(np.float64), f['i'].astype(np.uint32)


def colour_vertices(verts, xyz, rgb, cell):
    keys = np.floor(xyz / cell).astype(np.int64)
    lo = keys.min(0) - 2
    dims = keys.max(0) - lo + 3
    flat = lambda k: ((k[:, 0] - lo[0]) * dims[1] + (k[:, 1] - lo[1])) * dims[2] + (k[:, 2] - lo[2])
    fk = flat(keys)
    uniq, inv = np.unique(fk, return_inverse=True)
    sums = np.zeros((len(uniq), 3)); np.add.at(sums, inv, rgb.astype(np.float64))
    cnt = np.bincount(inv, minlength=len(uniq))[:, None]
    mean = sums / cnt
    vk = np.floor(verts / cell).astype(np.int64)
    out = np.full((len(verts), 3), 128.0)
    done = np.zeros(len(verts), bool)
    for r in range(3):                      # this cell, then shells of cells around it
        offs = [(a, b, c) for a in range(-r, r + 1) for b in range(-r, r + 1) for c in range(-r, r + 1)
                if max(abs(a), abs(b), abs(c)) == r]
        acc = np.zeros((len(verts), 3)); n = np.zeros(len(verts))
        for o in offs:
            k = vk + np.array(o)
            inside = np.all((k >= lo) & (k < lo + dims), 1)
            fkv = np.where(inside, flat(np.clip(k, lo, lo + dims - 1)), -1)
            pos = np.searchsorted(uniq, fkv)
            pos = np.clip(pos, 0, len(uniq) - 1)
            hit = inside & (uniq[pos] == fkv) & ~done
            acc[hit] += mean[pos[hit]]; n[hit] += 1
        got = n > 0
        out[got] = acc[got] / n[got, None]
        done |= got
    print(f'mesh colours: {done.mean() * 100:.1f}% of vertices found a point within 2 cells')
    return np.clip(out, 0, 255).astype(np.uint8)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('ply'); ap.add_argument('poses'); ap.add_argument('out')
    ap.add_argument('--mesh')
    ap.add_argument('--names'); ap.add_argument('--title', default='')
    ap.add_argument('--faces', help='folder holding the original faces')
    ap.add_argument('--fill'); ap.add_argument('--fill-max', type=int, default=600000)
    ap.add_argument('--rooms', help='only these rooms (needs --names)')
    ap.add_argument('--face-pattern', default='f{f}/{room}-{n:04d}.jpg',
                    help='path of a face under --faces; {f} face 1-6, {n} node, {room} the poses file\'s prefix')
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)

    f1 = np.array(cam_from_node(1))
    nodes = {}
    for line in open(a.poses):
        p = line.split()
        if len(p) < 10:
            continue
        n = int(re.search(r'-(\d+)\.jpg$', p[-1]).group(1))
        R = qvec2rot([float(v) for v in p[1:5]]); t = np.array([float(v) for v in p[5:8]])
        nodes[n] = (f1.T @ R, -R.T @ t)
    origin = np.mean([c for _, c in nodes.values()], 0)
    U, _, Vt = np.linalg.svd(sum(R for R, _ in nodes.values()))
    Rm = U @ Vt                                  # world -> the nodes' common frame
    if np.linalg.det(Rm) < 0:
        Rm = U @ np.diag([1, 1, -1]) @ Vt
    to_view = lambda P: (P - origin) @ Rm.T
    nodes = {n: (R @ Rm.T, Rm @ (c - origin)) for n, (R, c) in nodes.items()}
    labels = {}
    if a.names:
        rooms = json.load(open(a.names)).get('rooms', {})
        labels = {n: rooms.get(str(n), str(n)) for n in nodes}

    all_nodes = dict(nodes)
    if a.rooms:
        want = set(a.rooms.split(','))
        nodes = {n: v for n, v in nodes.items() if labels[n].split(':')[0] in want}
        a.mesh = None

    def in_rooms(P):
        if not a.rooms:
            return np.ones(len(P), bool)
        ids = np.array(list(all_nodes)); C = np.array([all_nodes[n][1] for n in ids])
        mine = np.isin(ids, list(nodes))
        keep = np.zeros(len(P), bool)
        for i in range(0, len(P), 200000):
            d = ((P[i:i + 200000, None, :] - C[None]) ** 2).sum(2)
            keep[i:i + 200000] = mine[d.argmin(1)]
        return keep

    xyz, rgb = read_ply(a.ply)
    xyz = to_view(xyz)
    k = in_rooms(xyz); xyz, rgb = xyz[k], rgb[k]
    with open(os.path.join(a.out, 'points.bin'), 'wb') as fh:
        fh.write(xyz.astype('<f4').tobytes()); fh.write(np.ascontiguousarray(rgb, np.uint8).tobytes())

    steps = sorted(np.linalg.norm(nodes[i][1] - nodes[j][1]) for i in nodes for j in nodes if i < j)
    step = float(np.median([min(np.linalg.norm(nodes[i][1] - nodes[j][1]) for j in nodes if j != i)
                            for i in nodes]))
    floor = {}
    for n, (_, c) in nodes.items():
        d = xyz - c
        m = (np.hypot(d[:, 0], d[:, 2]) < 0.1 * step) & (d[:, 1] < -0.02 * step) & (d[:, 1] > -3 * step)
        if m.sum() >= 5:
            floor[n] = float(np.percentile(-d[m, 1], 10))
    typical = float(np.median(list(floor.values()))) if floor else 0.55 * step
    print(f'floor heights measured under {len(floor)} of {len(nodes)} nodes; median {typical:.3f} '
          f'({typical / step:.2f} of the node spacing)')
    raised = {n: h for n, h in floor.items() if h > 1.3 * typical}
    for n in raised:                             # a lift has put the node on a platform the cloud
        del floor[n]                             # lacks: what is below is the ground far down
    if raised:
        print(f'raised (points below more than 1.3 times the eye height down; floor laid at the eye '
              f'height): ' + ', '.join(f'{labels.get(n, n)} {h / typical:.1f}x' for n, h in sorted(raised.items())))
    if a.faces:
        import shutil
        prefix = re.search(r'f1/(.+)-\d+\.jpg$', open(a.poses).readline().split()[-1]).group(1)
        for n in nodes:
            for f in range(1, 7):
                shutil.copyfile(os.path.join(a.faces, a.face_pattern.format(f=f, n=n, room=prefix)),
                                os.path.join(a.out, f'face-{n}-{f}.jpg'))
    scene = {
        'title': a.title,
        'faces': bool(a.faces),
        'points': int(len(xyz)),
        'nearest_node_median': step,
        'extent_p2_p98': [np.percentile(xyz, 2, 0).tolist(), np.percentile(xyz, 98, 0).tolist()],
        'nodes': {str(n): {'centre': c.tolist(), 'node_from_world': R.tolist(),
                           'label': labels.get(n, str(n)),
                           'floor': floor.get(n, typical), 'floor_measured': n in floor,
                           'ground_below': raised.get(n)}
                  for n, (R, c) in sorted(nodes.items())},
    }
    if a.mesh:
        verts, tris = read_ply_mesh(a.mesh)
        verts = to_view(verts)
        cols = colour_vertices(verts, xyz, rgb, cell=step / 40)
        with open(os.path.join(a.out, 'mesh.bin'), 'wb') as fh:
            fh.write(verts.astype('<f4').tobytes()); fh.write(cols.tobytes()); fh.write(tris.astype('<u4').tobytes())
        scene['mesh'] = {'vertices': int(len(verts)), 'triangles': int(len(tris))}
    if a.fill:
        fx, fc = read_ply(a.fill)
        fx = to_view(fx)
        k = in_rooms(fx); fx, fc = fx[k], fc[k]
        cell = step / 200
        while True:                              # coarsen the grid until few enough cells are filled
            _, first = np.unique(np.floor(fx / cell).astype(np.int64), axis=0, return_index=True)
            if len(first) <= a.fill_max:
                break
            cell *= 1.25
        fx, fc = fx[first], fc[first]
        with open(os.path.join(a.out, 'fill.bin'), 'wb') as fh:
            fh.write(fx.astype('<f4').tobytes()); fh.write(np.ascontiguousarray(fc, np.uint8).tobytes())
        scene['fill'] = int(len(fx))
        print(f'fill: {len(fx)} points kept, one per {cell / step:.4f}-spacing cell')
    json.dump(scene, open(os.path.join(a.out, 'scene.json'), 'w'), indent=1)
    print(f'{len(xyz)} points, {len(nodes)} nodes, nearest-node distance median {step:.3f}, '
          f'longest node pair {steps[-1]:.3f}')


if __name__ == '__main__':
    main()
