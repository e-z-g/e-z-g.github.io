#!/usr/bin/env python3
"""
Take out of a splat trained with the sky masked the splats that float in front
of the sky above the horizon.

    python sky_floaters.py DATASET SPLAT.ply OUT.ply [--margin 8] [--min-views 2]

With the sky masked, nothing in training stops a splat from sitting where some
view sees only sky, and such splats show as haze in front of it from views that
were not trained on. The sky has nothing in it, so a splat whose centre falls
deep inside the sky (more than --margin pixels inside a mask, which keeps a
silhouette's own splats) in at least --min-views of the dataset's images, in
front of the camera and more than --above degrees above its horizon, is
dropped. Below the horizon the masks also take in the sea, where splats stand
for the water and its reflections and must stay. DATASET is splat_dataset.py's (images/,
masks/ black on the sky, sparse/0/*.txt). Needs numpy, Pillow, torch (CUDA if
there is one).
"""
import argparse
import os
import re

import numpy as np
import torch
from PIL import Image, ImageFilter


def qrot(q):
    w, x, y, z = q
    return np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)],
                     [2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)],
                     [2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)]])


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('dataset'); ap.add_argument('splat'); ap.add_argument('out')
    ap.add_argument('--margin', type=int, default=8); ap.add_argument('--min-views', type=int, default=2)
    ap.add_argument('--up', default='0,1,0'); ap.add_argument('--above', type=float, default=2.0,
                    help='only splats more than this many degrees above the camera\'s horizon count: the masks also take in water')
    a = ap.parse_args()
    dev = 'cuda' if torch.cuda.is_available() else 'cpu'
    with open(a.splat, 'rb') as f:
        head = b''
        while not head.endswith(b'end_header\n'):
            head += f.readline()
        n = int(re.search(rb'element vertex (\d+)', head).group(1))
        props = [p.decode() for p in re.findall(rb'property float (\S+)', head)]
        data = np.fromfile(f, dtype='<f4', count=n * len(props)).reshape(n, len(props))
    ix = {p: i for i, p in enumerate(props)}
    X = torch.tensor(data[:, [ix['x'], ix['y'], ix['z']]], device=dev)
    sp = os.path.join(a.dataset, 'sparse', '0')
    cams = {}
    for l in open(os.path.join(sp, 'cameras.txt')):
        p = l.split()
        if l.startswith('#') or len(p) < 5:
            continue
        prm = [float(v) for v in p[4:]]
        cams[int(p[0])] = (prm[0], prm[0], prm[1], prm[2]) if p[1] == 'SIMPLE_PINHOLE' else tuple(prm[:4])
    hits = torch.zeros(n, dtype=torch.int32, device=dev)
    up = torch.tensor([float(v) for v in a.up.split(',')], device=dev); up = up / up.norm()
    min_sin = float(np.sin(np.radians(a.above)))
    views = 0
    for l in open(os.path.join(sp, 'images.txt')):
        p = l.split()
        if l.startswith('#') or len(p) < 10:
            continue
        mp = os.path.join(a.dataset, 'masks', os.path.splitext(p[9])[0] + '.png')
        if not os.path.exists(mp):
            continue
        m = Image.open(mp).convert('L')
        if a.margin:
            m = m.filter(ImageFilter.MaxFilter(2 * a.margin + 1))   # grow the kept part: sky only deep inside
        sky = torch.tensor(np.asarray(m) < 128, device=dev)
        if not sky.any():
            continue
        H, W = sky.shape
        R = torch.tensor(qrot([float(v) for v in p[1:5]]), dtype=torch.float32, device=dev)
        t = torch.tensor([float(v) for v in p[5:8]], dtype=torch.float32, device=dev)
        fx, fy, cx, cy = cams[int(p[8])]
        Y = X @ R.T + t
        z = Y[:, 2]
        C = -R.T @ t
        D = X - C
        ok = (z > 1e-3) & ((D @ up) > min_sin * D.norm(dim=1))   # above the horizon, where the sky is empty
        u = (fx * Y[:, 0] / z.clamp(min=1e-3) + cx).floor().long(); v = (fy * Y[:, 1] / z.clamp(min=1e-3) + cy).floor().long()
        ok &= (u >= 0) & (u < W) & (v >= 0) & (v < H)
        on = torch.zeros(n, dtype=torch.bool, device=dev)
        on[ok] = sky[v[ok], u[ok]]
        hits += on.int(); views += 1
    drop = (hits >= a.min_views).cpu().numpy()
    out = data[~drop]
    head = re.sub(rb'element vertex \d+', b'element vertex %d' % len(out), head)
    with open(a.out, 'wb') as f:
        f.write(head); f.write(out.astype('<f4').tobytes())
    print(f'{views} views; {drop.sum()} of {n} splats ({drop.mean() * 100:.1f}%) seen in the deep sky of '
          f'{a.min_views}+ views, dropped -> {a.out}')


if __name__ == '__main__':
    main()
