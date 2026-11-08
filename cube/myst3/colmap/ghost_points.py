#!/usr/bin/env python3
"""
Which nodes make the ghosts in a fused cloud: points that a set of trusted
nodes see straight through.

    python ghost_points.py DENSE SPARSE_TXT TRUSTED [--masks MASKS] [--tol 0.1]
        [--sky-margin 8] [--min-against 2] [--names nodes.json] [--out ghosts.ply]
        [--fused fused.ply]

DENSE is a dense workspace after fusion (fused.ply and fused.ply.vis, or
--fused and its .vis), SPARSE_TXT its model as text (or - for the workspace's
own sparse/images.bin), TRUSTED a file naming the nodes believed right, one image
name per line or a COLMAP images.txt (the 62-node Amateria model, which has no
ghost of the tower; the 131-node one does). Every fused point is projected into
every face of the trusted nodes. A face agrees when its depth there is within
--tol of the point's, and is against it when it sees more than --tol farther,
or, with --masks (sky_masks.py's folder), sky more than --sky-margin px inside
the mask. A point at least --min-against faces are against and none agrees is
a ghost. For each node, prints how many of the points it helped make are
ghosts, and writes the ghosts to --out to look at.

fused.ply.vis lists, for each point, indices into the dense workspace's
images in the order of its sparse/images.bin; this is checked by how often a
point's own images agree with it. Needs numpy, Pillow; depth_fill.py and
model_backdrop.py beside it.
"""
import argparse
import json
import os
import re
import struct
from collections import Counter

import numpy as np

from depth_fill import read_colmap_array
from model_backdrop import read_poses


def read_ply(path):
    with open(path, 'rb') as f:
        props, n = [], 0
        while True:
            line = f.readline().decode().strip()
            if line.startswith('element vertex'):
                n = int(line.split()[-1])
            elif line.startswith('property'):
                _, t, name = line.split()
                props.append((name, {'float': '<f4', 'double': '<f8', 'uchar': 'u1', 'int': '<i4'}[t]))
            elif line == 'end_header':
                break
        return np.frombuffer(f.read(), dtype=np.dtype(props), count=n)


def read_vis(path):
    raw = np.fromfile(path, dtype='<u4')
    n = int(raw[0]) | (int(raw[1]) << 32)
    out, i = [], 2
    for _ in range(n):
        k = int(raw[i]); out.append(raw[i + 1:i + 1 + k]); i += 1 + k
    return out


def image_names_bin(path, poses=None):
    """Image names of a COLMAP images.bin in the file's order, and by id;
    fills poses (name -> (R, t)) if given."""
    from evaluate_model import qvec2rot
    names = []
    with open(path, 'rb') as f:
        (count,) = struct.unpack('<Q', f.read(8))
        for _ in range(count):
            (iid,) = struct.unpack('<I', f.read(4))
            qt = struct.unpack('<7d', f.read(56)); f.read(4)
            name = b''
            while True:
                c = f.read(1)
                if c == b'\0':
                    break
                name += c
            (np2,) = struct.unpack('<Q', f.read(8))
            f.seek(24 * np2, 1)
            names.append((iid, name.decode()))
            if poses is not None:
                poses[name.decode()] = (qvec2rot(np.array(qt[:4])), np.array(qt[4:]))
    return [n for _, n in names], [n for _, n in sorted(names)]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('dense'); ap.add_argument('sparse_txt'); ap.add_argument('trusted')
    ap.add_argument('--masks'); ap.add_argument('--tol', type=float, default=0.1)
    ap.add_argument('--sky-margin', type=int, default=8)
    ap.add_argument('--min-against', type=int, default=2)
    ap.add_argument('--names'); ap.add_argument('--out', default='ghosts.ply')
    ap.add_argument('--fused', default='fused.ply')
    a = ap.parse_args()

    bin_poses = {}
    order_file, order_id = image_names_bin(os.path.join(a.dense, 'sparse', 'images.bin'), bin_poses)
    poses = bin_poses if a.sparse_txt == '-' else read_poses(a.sparse_txt)
    node_re = re.compile(r'f\d/(.*)\.jpg')
    trusted = set()
    for line in open(a.trusted):
        for tok in line.split():
            m = node_re.fullmatch(tok) or re.fullmatch(r'(MA-\d+|[A-Z]+-\d+)', tok)
            if m:
                trusted.add(m.group(1))
    faces = [nm for nm in poses if (m := node_re.fullmatch(nm)) and m.group(1) in trusted]
    print(f'{len(trusted)} trusted nodes, {len(faces)} of their faces in the model')

    fused = os.path.join(a.dense, a.fused)
    pts = read_ply(fused)
    X = np.stack([pts['x'], pts['y'], pts['z']], 1).astype(np.float64)
    vis = read_vis(fused + '.vis')
    print(f'{len(X)} fused points')

    def dmap(name):
        p = os.path.join(a.dense, 'stereo', 'depth_maps', name + '.geometric.bin')
        return read_colmap_array(p) if os.path.exists(p) else None

    def skymap(name, shape):
        if not a.masks:
            return None
        p = os.path.join(a.masks, name + '.png')
        if not os.path.exists(p):
            return None
        from PIL import Image, ImageFilter
        m = Image.open(p).convert('L')
        if a.sky_margin:
            m = m.filter(ImageFilter.MaxFilter(2 * a.sky_margin + 1))
        return np.asarray(m.resize((shape[1], shape[0]), Image.NEAREST)) < 128

    def look(name, z, P):
        """For points P: in view, depth along the ray, and pixel."""
        H, W = z.shape
        R, t = poses[name]
        Y = P @ R.T + t
        ok = Y[:, 2] > 1e-6
        x = Y[:, 0] / np.where(ok, Y[:, 2], 1); y = Y[:, 1] / np.where(ok, Y[:, 2], 1)
        ok &= (np.abs(x) < 1) & (np.abs(y) < 1)
        px = np.clip(((x + 1) * W / 2).astype(int), 0, W - 1); py = np.clip(((y + 1) * H / 2).astype(int), 0, H - 1)
        return ok, Y[:, 2], px, py

    # Which order fused.ply.vis counts images in: the one under which a point's
    # own images most often agree with it.
    rng = np.random.default_rng(0)
    sample = rng.choice(len(X), min(400, len(X)), replace=False)
    best = None
    for label, order in (('file', order_file), ('id', order_id)):
        good = tot = 0
        cache = {}
        for i in sample:
            for j in vis[i][:3]:
                name = order[j]
                if name not in poses:
                    continue
                if name not in cache:
                    cache[name] = dmap(name)
                z = cache[name]
                if z is None:
                    continue
                ok, d, px, py = look(name, z, X[i:i + 1])
                tot += 1
                if ok[0] and z[py[0], px[0]] > 0 and abs(z[py[0], px[0]] - d[0]) / d[0] < a.tol:
                    good += 1
        print(f'vis read in {label} order: {good} of {tot} own views agree')
        if best is None or good > best[0]:
            best = (good, order)
    order = best[1]

    agree = np.zeros(len(X), np.int32); against = np.zeros(len(X), np.int32)
    for k, name in enumerate(faces):
        z = dmap(name)
        if z is None:
            continue
        ok, d, px, py = look(name, z, X)
        zn = np.where(ok, z[py, px], 0)
        has = ok & (zn > 0)
        rel = np.zeros(len(X)); rel[has] = (zn[has] - d[has]) / d[has]
        agree += has & (np.abs(rel) <= a.tol)
        against += has & (rel > a.tol)
        sm = skymap(name, z.shape)
        if sm is not None:
            against += ok & (zn <= 0) & sm[py, px]
        if k % 60 == 0:
            print(f'  {k}/{len(faces)} faces')
    ghost = (against >= a.min_against) & (agree == 0)
    seen = (agree + against) > 0
    print(f'{ghost.sum()} ghost points of {seen.sum()} that trusted faces see ({len(X)} in all)')

    labels = {}
    if a.names:
        rooms = json.load(open(a.names)).get('rooms', {})
        labels = {n: rooms.get(n.split('-')[-1], n) for n in trusted | {node_re.fullmatch(nm).group(1) for nm in poses if node_re.fullmatch(nm)}}
    made, made_ghost = Counter(), Counter()
    for i in np.nonzero(seen)[0]:
        nodes = {node_re.fullmatch(order[j]).group(1) if node_re.fullmatch(order[j]) else order[j].split('/')[0]
                 for j in vis[i]}
        for n in nodes:
            made[n] += 1
            if ghost[i]:
                made_ghost[n] += 1
    print('node        trusted  ghost points  of points made that trusted faces see')
    for n, g in made_ghost.most_common(30):
        print(f'{labels.get(n, n):>10} {n:>10}  {"yes" if n in trusted else "no ":>3}  {g:7d}  {g / made[n] * 100:5.1f}% of {made[n]}')

    G = pts[ghost]
    with open(a.out, 'wb') as f:
        f.write(('ply\nformat binary_little_endian 1.0\nelement vertex %d\n' % len(G)).encode())
        for name in G.dtype.names:
            f.write(('property %s %s\n' % ({'<f4': 'float', '<f8': 'double', 'u1': 'uchar', '<i4': 'int'}[G.dtype[name].str.replace('|', '')], name)).encode())
        f.write(b'end_header\n'); f.write(G.tobytes())
    print('ghosts written to', a.out)


if __name__ == '__main__':
    main()
