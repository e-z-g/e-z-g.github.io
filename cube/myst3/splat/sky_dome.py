#!/usr/bin/env python3
"""
A splat trained with the sky masked out, given its sky back as a shell of
splats far away.

    python sky_dome.py DATASET SPLAT.ply OUT.ply [--radius 1000] [--points 400000]
        [--grid 2048] [--centre x,y,z]

DATASET is the masked dataset the splat was trained on (splat_dataset.py
--masks: images/, masks/ black on the sky, sparse/0/*.txt). Every image's
masked pixels are turned into world directions (the sky is at infinity, so
where an image was taken does not matter, only which way it looked) and
averaged into an equirectangular map of --grid x --grid/2; directions no image
saw as sky (below the walkways, behind the towers) are filled from their
neighbours, and so is everything more than --lowest degrees below the horizon:
the masks also take in water, and near the nodes the sea reflects the scene. The map is then sampled at --points directions spread evenly over
the sphere (a Fibonacci lattice), each a round splat --radius away from
--centre (default the cameras' mean centre), sized to touch its neighbours,
opaque, with the colour as its zeroth spherical harmonic. OUT is SPLAT with
these appended, in the same layout, so any viewer of 3DGS .ply files shows the
sky behind the scene. Needs numpy, Pillow.
"""
import argparse
import os
import re

import numpy as np
from PIL import Image

C0 = 0.28209479177387814


def read_ply(path):
    with open(path, 'rb') as f:
        head = b''
        while not head.endswith(b'end_header\n'):
            head += f.readline()
        n = int(re.search(rb'element vertex (\d+)', head).group(1))
        props = [p.decode() for p in re.findall(rb'property float (\S+)', head)]
        data = np.fromfile(f, dtype='<f4', count=n * len(props)).reshape(n, len(props))
    return head, props, data


def qrot(q):
    w, x, y, z = q
    return np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)],
                     [2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)],
                     [2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)]])


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('dataset'); ap.add_argument('splat'); ap.add_argument('out')
    ap.add_argument('--radius', type=float, default=1000.0)
    ap.add_argument('--points', type=int, default=400000)
    ap.add_argument('--grid', type=int, default=2048)
    ap.add_argument('--centre')
    ap.add_argument('--up', default='0,1,0', help='the world up direction (y in the joined model of Amateria)')
    ap.add_argument('--lowest', type=float, default=-15.0,
                    help='masked pixels further below the horizon than this many degrees are not used: there the\n'
                         'masks\' water is near sea reflecting the scene, and the fill carries the horizon down instead')
    a = ap.parse_args()
    sp = os.path.join(a.dataset, 'sparse', '0')
    cams = {}
    for l in open(os.path.join(sp, 'cameras.txt')):
        p = l.split()
        if l.startswith('#') or len(p) < 5:
            continue
        model, W, H, prm = p[1], int(p[2]), int(p[3]), [float(v) for v in p[4:]]
        if model == 'SIMPLE_PINHOLE':
            cams[int(p[0])] = (prm[0], prm[0], prm[1], prm[2])
        else:
            cams[int(p[0])] = (prm[0], prm[1], prm[2], prm[3])
    G = a.grid
    acc = np.zeros((G // 2, G, 3)); cnt = np.zeros((G // 2, G))
    centres = []
    up = np.array([float(v) for v in a.up.split(',')]); up /= np.linalg.norm(up)
    floor_sin = np.sin(np.radians(a.lowest))
    for l in open(os.path.join(sp, 'images.txt')):
        p = l.split()
        if l.startswith('#') or len(p) < 10:
            continue
        q = [float(v) for v in p[1:5]]; t = np.array([float(v) for v in p[5:8]])
        R = qrot(q); centres.append(-R.T @ t)
        name = p[9]
        mp = os.path.join(a.dataset, 'masks', os.path.splitext(name)[0] + '.png')
        if not os.path.exists(mp):
            continue
        m = np.asarray(Image.open(mp).convert('L')) < 128
        if not m.any():
            continue
        img = np.asarray(Image.open(os.path.join(a.dataset, 'images', name)).convert('RGB'), float) / 255
        fx, fy, cx, cy = cams[int(p[8])]
        v, u = np.nonzero(m)
        d = np.stack([(u + 0.5 - cx) / fx, (v + 0.5 - cy) / fy, np.ones(len(u))], 1) @ R   # camera -> world
        d /= np.linalg.norm(d, axis=1, keepdims=True)
        keep = d @ up > floor_sin
        d, v, u = d[keep], v[keep], u[keep]
        lon = np.arctan2(d[:, 0], d[:, 2]); lat = np.arcsin(np.clip(d[:, 1], -1, 1))
        gi = np.clip(((lat / np.pi + 0.5) * (G // 2)).astype(int), 0, G // 2 - 1)
        gj = np.clip(((lon / (2 * np.pi) + 0.5) * G).astype(int), 0, G - 1)
        np.add.at(acc, (gi, gj), img[v, u]); np.add.at(cnt, (gi, gj), 1)
    seen = cnt > 0
    print(f'sky seen in {seen.mean() * 100:.1f}% of the map')
    sky = np.where(seen[..., None], acc / np.maximum(cnt, 1)[..., None], 0)
    # fill what no image saw as sky from the nearest seen cells, coarse to fine
    filled = seen.copy()
    while not filled.all():
        pad = np.pad(sky * filled[..., None], ((1, 1), (0, 0), (0, 0)), mode='edge')
        pw = np.pad(filled.astype(float), ((1, 1), (0, 0)), mode='edge')
        s = np.zeros_like(sky); w = np.zeros(filled.shape)
        for di in (-1, 0, 1):
            for dj in (-1, 0, 1):
                s += np.roll(pad[1 + di:pad.shape[0] - 1 + di], dj, axis=1)
                w += np.roll(pw[1 + di:pw.shape[0] - 1 + di], dj, axis=1)
        new = (~filled) & (w > 0)
        sky[new] = s[new] / w[new][:, None]
        filled |= new
    Image.fromarray((sky * 255).clip(0, 255).astype(np.uint8)).save(os.path.splitext(a.out)[0] + '_sky.png')
    # Fibonacci lattice
    N = a.points
    k = np.arange(N) + 0.5
    lat = np.arcsin(1 - 2 * k / N); lon = (np.pi * (1 + 5 ** 0.5) * k) % (2 * np.pi) - np.pi
    d = np.stack([np.cos(lat) * np.sin(lon), np.sin(lat), np.cos(lat) * np.cos(lon)], 1)
    gi = np.clip(((lat / np.pi + 0.5) * (G // 2)).astype(int), 0, G // 2 - 1)
    gj = np.clip(((lon / (2 * np.pi) + 0.5) * G).astype(int), 0, G - 1)
    col = sky[gi, gj]
    C = np.array([float(v) for v in a.centre.split(',')]) if a.centre else np.mean(centres, 0)
    pos = C + a.radius * d
    size = a.radius * np.sqrt(4 * np.pi / N) * 0.75
    head, props, data = read_ply(a.splat)
    dome = np.zeros((N, len(props)), np.float32)
    ix = {p: i for i, p in enumerate(props)}
    dome[:, ix['x']], dome[:, ix['y']], dome[:, ix['z']] = pos.T
    for c in range(3):
        dome[:, ix[f'f_dc_{c}']] = (col[:, c] - 0.5) / C0
        dome[:, ix[f'scale_{c}']] = np.log(size)
    dome[:, ix['opacity']] = 6.0                      # sigmoid: 0.998
    dome[:, ix['rot_0']] = 1.0
    out = np.concatenate([data, dome])
    head = re.sub(rb'element vertex \d+', b'element vertex %d' % len(out), head)
    with open(a.out, 'wb') as f:
        f.write(head); f.write(out.astype('<f4').tobytes())
    print(f'{len(data)} splats + {N} sky splats {a.radius:g} away -> {a.out}')


if __name__ == '__main__':
    main()
