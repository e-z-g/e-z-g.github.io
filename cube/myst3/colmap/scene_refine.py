#!/usr/bin/env python3
r"""
A scene mesh moved to fit the node pictures with OpenMVS's RefineMesh: the vertices are shifted until the
pictures of the nodes that see a surface, projected onto it, agree with each other (the error the viewer
shows between nodes, where neighbours' pictures land on the wrong shape).

    python scene_refine.py prepare ROOT SPARSE_TXT MESH_DIR WORK --nodes 4002 4006 ... [--radius 8]
        [--moge DIR] [--points 300000]
    (RefineMesh on WORK, see below)
    python scene_refine.py back MESH_DIR WORK\refined.ply OUT_DIR

prepare: WORK gets the faces of every node in MESH_DIR's views.json within --radius of a --nodes node
(images\f<k>_MA-<node>.jpg from ROOT\images\f<k>\MA-<node>.jpg), their cameras, poses and shared points from
SPARSE_TXT (sparse\cameras.txt, images.txt, points3D.txt: the points seen by two kept faces or more; with
--moge, scene_mesh.py's moge\ folder, --points of the mesh's vertices instead, each seen by the faces whose
node's anchored distance in that direction agrees with it to 10%: RefineMesh picks the pictures it compares
from shared points, and the model has too few of them among node faces), and
MESH_DIR's mesh (scene.json and scene.bin or its pieces, the viewer's frame) in the model's frame as
mesh.ply. The viewer's frame is scene_attrs.py's: v = F R0 (p - C0) / unit, R0 and C0 face 1 of the first
node in views.json, unit from scales.json (in MESH_DIR, or WORK if copied there). Then, in WORK:

    InterfaceCOLMAP -i WORK -o scene.mvs --image-folder WORK\images
    RefineMesh scene.mvs -m mesh.ply -o refined.mvs --decimate 1 --close-holes 0

back: the refined mesh (model frame) to the viewer's frame as OUT_DIR\scene.json and scene.bin, every
vertex grey (the viewer's projection does not use the vertex colours), with views.json, nodes.json and
links.json copied from MESH_DIR. Needs numpy.
"""
import argparse
import json
import os
import shutil
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from scene_carve import read_scene, write_scene  # noqa: E402

F = np.diag([1.0, -1.0, -1.0])


def qrot(qw, qx, qy, qz):
    return np.array([[1 - 2 * (qy * qy + qz * qz), 2 * (qx * qy - qz * qw), 2 * (qx * qz + qy * qw)],
                     [2 * (qx * qy + qz * qw), 1 - 2 * (qx * qx + qz * qz), 2 * (qy * qz - qx * qw)],
                     [2 * (qx * qz - qy * qw), 2 * (qy * qz + qx * qw), 1 - 2 * (qx * qx + qy * qy)]])


def read_images(path):
    """images.txt as {name: (head fields, points line)}."""
    body = [l for l in open(path).read().splitlines() if not l.startswith('#')]
    return {h.split()[9]: (h.split(), p) for h, p in zip(body[0::2], body[1::2])}


def frame(mesh_dir, imgs, first, unit):
    h = imgs[f'f1/MA-{first}.jpg'][0]
    R0 = qrot(*map(float, h[1:5])); C0 = -R0.T @ np.array(list(map(float, h[5:8])))
    return F @ R0 / unit, C0                                # v = A (p - C0)


def write_ply(path, V, T):
    with open(path, 'wb') as f:
        f.write((f'ply\nformat binary_little_endian 1.0\nelement vertex {len(V)}\nproperty float x\nproperty float y\n'
                 f'property float z\nelement face {len(T)}\nproperty list uchar int vertex_indices\nend_header\n').encode())
        f.write(np.ascontiguousarray(V, '<f4').tobytes())
        fa = np.zeros(len(T), [('n', 'u1'), ('v', '<i4', 3)]); fa['n'] = 3; fa['v'] = T
        f.write(fa.tobytes())


def read_ply(path):
    """A binary little-endian PLY's vertex x y z and triangles (other vertex properties skipped)."""
    raw = open(path, 'rb').read(); end = raw.index(b'end_header') + len(b'end_header\n')
    head = raw[:end].decode('latin-1').splitlines()
    types = {'float': '<f4', 'double': '<f8', 'uchar': 'u1', 'char': 'i1', 'int': '<i4', 'uint': '<u4',
             'short': '<i2', 'ushort': '<u2', 'float32': '<f4', 'int32': '<i4', 'uint32': '<u4', 'uint8': 'u1'}
    elems, cur = [], None
    for l in head:
        p = l.split()
        if p[0] == 'element':
            cur = [p[1], int(p[2]), []]; elems.append(cur)
        elif p[0] == 'property':
            cur[2].append(p[1:])
    off, V, T = end, None, None
    for name, n, props in elems:
        if name == 'vertex':
            dt = np.dtype([(q[-1], types[q[0]]) for q in props])
            a = np.frombuffer(raw, dt, n, off); off += n * dt.itemsize
            V = np.stack([a['x'], a['y'], a['z']], 1).astype(np.float64)
        elif name == 'face':
            q = props[0]; cnt, idx = types[q[1]], types[q[2]]
            dt = np.dtype([('n', cnt), ('v', idx, 3)] + [(r[-1], types[r[0]]) for r in props[1:]])
            a = np.frombuffer(raw, dt, n, off); off += n * dt.itemsize
            assert (a['n'] == 3).all(), 'triangles only'
            T = a['v'].astype(np.uint32)
    return V, T


def mesh_points(a, keep, Pm, work, sparse):
    """points3D.txt and images.txt from --points of the mesh's vertices, seen where the nodes' depth agrees."""
    import cv2
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from moge_depth import dirs_to_equirect_px
    rng = np.random.default_rng(0)
    X = Pm[rng.choice(len(Pm), min(a.points, len(Pm)), replace=False)]
    cams = {}
    for l in open(os.path.join(sparse, 'cameras.txt')):
        if not l.startswith('#') and l.strip():
            p = l.split(); cams[p[0]] = list(map(float, p[2:]))
    obs = {nm: [] for nm in keep}; track = [[] for _ in X]
    depth = {}
    for nm, (h, _) in keep.items():
        node = nm.split('/')[-1][3:-4]
        if node not in depth:
            D = np.load(os.path.join(a.moge, node + '_anchored.npy')).astype(np.float32)
            h1 = next(v[0] for k, v in keep.items() if k == f'f1/MA-{node}.jpg')
            R1 = qrot(*map(float, h1[1:5])); C1 = -R1.T @ np.array(list(map(float, h1[5:8])))
            v = (X - C1) @ R1.T @ F; r = np.linalg.norm(v, axis=1)
            mx, my = dirs_to_equirect_px(v / r[:, None], D.shape[1], D.shape[0])
            d = D[np.clip(np.rint(my).astype(int), 0, D.shape[0] - 1), np.rint(mx).astype(int) % D.shape[1]]
            depth[node] = np.abs(r / d - 1) < 0.1
        R = qrot(*map(float, h[1:5])); t = np.array(list(map(float, h[5:8])))
        w, hh, fx, fy, cx, cy = cams[h[8]][:6] if len(cams[h[8]]) >= 6 else (*cams[h[8]][:2], cams[h[8]][2], cams[h[8]][2], *cams[h[8]][3:5])
        pc = X @ R.T + t; z = pc[:, 2]
        with np.errstate(all='ignore'):
            u = fx * pc[:, 0] / z + cx; v = fy * pc[:, 1] / z + cy
        ok = depth[node] & (z > 0) & (u >= 0) & (u < w) & (v >= 0) & (v < hh)
        for i in np.nonzero(ok)[0]:
            track[i].append((int(h[0]), len(obs[nm]))); obs[nm].append((u[i], v[i], i + 1))
    good = {i for i, tr in enumerate(track) if len(tr) >= 2}
    with open(os.path.join(work, 'sparse', 'points3D.txt'), 'w') as f:
        for i in sorted(good):
            f.write(f'{i + 1} {X[i, 0]} {X[i, 1]} {X[i, 2]} 128 128 128 0 ' + ' '.join(f'{im} {k}' for im, k in track[i]) + '\n')
    with open(os.path.join(work, 'sparse', 'images.txt'), 'w') as f:
        for nm, (h, _) in keep.items():
            f.write(' '.join(h[:9] + [nm.replace('/', '_')]) + '\n')
            f.write(' '.join(f'{u:.2f} {v:.2f} {pid if pid - 1 in good else -1}' for u, v, pid in obs[nm]) + '\n')
    print(f'{len(good)} of {len(X)} mesh points seen by two faces or more', flush=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('stage', choices=['prepare', 'back']); ap.add_argument('args', nargs='+')
    ap.add_argument('--nodes', nargs='*', default=[]); ap.add_argument('--radius', type=float, default=8)
    ap.add_argument('--moge'); ap.add_argument('--points', type=int, default=300000)
    a = ap.parse_args()
    if a.stage == 'prepare':
        root, sparse, mesh, work = a.args
        views = json.load(open(os.path.join(mesh, 'views.json')))
        scales = os.path.join(mesh, 'scales.json') if os.path.exists(os.path.join(mesh, 'scales.json')) else os.path.join(work, 'scales.json')
        unit = json.load(open(scales))['unit']
        C = np.array([views[n]['pos'] for n in a.nodes])
        near = [n for n, v in views.items() if np.min(np.linalg.norm(C - np.array(v['pos']), axis=1)) < a.radius]
        first = next(iter(views))
        if first not in near:                                 # its face 1 sets the frame
            near.append(first)
        imgs = read_images(os.path.join(sparse, 'images.txt'))
        keep = {nm: v for nm, v in imgs.items() if nm.split('/')[-1][3:-4] in near and nm.startswith('f') and '/MA-' in nm}
        os.makedirs(os.path.join(work, 'images'), exist_ok=True); os.makedirs(os.path.join(work, 'sparse'), exist_ok=True)
        ids = {int(h[0]) for h, _ in keep.values()}
        A, C0 = frame(mesh, imgs, first, unit)
        _, parts = read_scene(mesh)
        Pm = parts['position'].astype(np.float64) @ np.linalg.inv(A).T + C0
        if a.moge:
            mesh_points(a, keep, Pm, work, sparse)
        # the points seen by two kept faces or more
        pts, seen = [], set()
        for l in open(os.path.join(sparse, 'points3D.txt')) if not a.moge else []:
            if l.startswith('#') or not l.strip():
                continue
            p = l.split(); tr = p[8:]
            track = [(int(tr[i]), tr[i + 1]) for i in range(0, len(tr), 2) if int(tr[i]) in ids]
            if len(track) >= 2:
                pts.append(' '.join(p[:8] + [f'{i} {j}' for i, j in track])); seen.add(int(p[0]))
        with open(os.path.join(work, 'sparse', 'images.txt'), 'w') if not a.moge else open(os.devnull, 'w') as f:
            for nm, (h, p2) in keep.items():
                flat = nm.replace('/', '_')
                q = p2.split(); q[2::3] = [x if int(x) in seen else '-1' for x in q[2::3]]
                f.write(' '.join(h[:9] + [flat]) + '\n' + ' '.join(q) + '\n')
                shutil.copy(os.path.join(root, 'images', nm), os.path.join(work, 'images', flat))
        if not a.moge:
            open(os.path.join(work, 'sparse', 'points3D.txt'), 'w').write('\n'.join(pts) + '\n')
        shutil.copy(os.path.join(sparse, 'cameras.txt'), os.path.join(work, 'sparse', 'cameras.txt'))
        write_ply(os.path.join(work, 'mesh.ply'), Pm, parts['index'])
        json.dump({'first': first, 'unit': unit, 'nodes': near}, open(os.path.join(work, 'refine.json'), 'w'), indent=1)
        print(f'{len(near)} nodes, {len(keep)} faces, {len(pts)} points, {len(parts["index"])} triangles -> {work}')
    else:
        mesh, ply, out = a.args
        work = os.path.dirname(os.path.abspath(ply))
        info = json.load(open(os.path.join(work, 'refine.json')))
        imgs = read_images(os.path.join(work, 'sparse', 'images.txt'))
        imgs = {nm.replace('_', '/', 1): v for nm, v in imgs.items()}
        A, C0 = frame(mesh, imgs, info['first'], info['unit'])
        V, T = read_ply(ply)
        Pv = ((V - C0) @ A.T).astype(np.float32)
        g = np.full((len(V), 3), 128, np.uint8)
        write_scene(out, {'position': Pv, 'index': T, 'color': g, 'albedo': g.copy(), 'roughMetal': g[:, :2].copy()})
        for f in ('views.json', 'nodes.json', 'links.json'):
            if os.path.exists(os.path.join(mesh, f)):
                shutil.copy(os.path.join(mesh, f), out)
        print(f'{len(V)} vertices, {len(T)} triangles -> {out}')


if __name__ == '__main__':
    main()
