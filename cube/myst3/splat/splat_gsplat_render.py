#!/usr/bin/env python3
r"""
Render a 3DGS .ply (Brush's or splat_depth_train.py's) from a COLMAP text dataset's cameras with gsplat, one PNG
a camera, and the mean change from frame to frame (for a walk_dataset.py walk: how smoothly it moves).

    python splat_gsplat_render.py SPLAT.ply DATASET OUT_DIR [--every 1]

Needs torch with CUDA, gsplat, numpy, Pillow, plyfile (as splat_depth_train.py).
"""
import argparse
import os

import numpy as np
import torch
from PIL import Image
from plyfile import PlyData

from splat_depth_train import read_cameras, read_images


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('ply'); ap.add_argument('dataset'); ap.add_argument('out'); ap.add_argument('--every', type=int, default=1)
    a = ap.parse_args()
    from gsplat import rasterization
    dev = 'cuda'
    el = PlyData.read(a.ply)['vertex']; g = lambda k: np.asarray(el[k], np.float32)
    nrest = len([p.name for p in el.properties if p.name.startswith('f_rest_')])
    t = lambda x: torch.tensor(x, device=dev)
    means = t(np.stack([g('x'), g('y'), g('z')], 1)); scales = torch.exp(t(np.stack([g(f'scale_{i}') for i in range(3)], 1)))
    quats = t(np.stack([g(f'rot_{i}') for i in range(4)], 1)); opac = torch.sigmoid(t(g('opacity')))
    sh0 = t(np.stack([g(f'f_dc_{i}') for i in range(3)], 1))[:, None]
    shN = t(np.stack([g(f'f_rest_{i}') for i in range(nrest)], 1).reshape(-1, 3, nrest // 3).transpose(0, 2, 1).copy())
    colors = torch.cat([sh0, shN], 1); deg = int(round(np.sqrt(colors.shape[1]))) - 1
    sp = os.path.join(a.dataset, 'sparse', '0')
    cams = read_cameras(os.path.join(sp, 'cameras.txt')); ims = read_images(os.path.join(sp, 'images.txt'))
    os.makedirs(a.out, exist_ok=True)
    prev, diffs = None, []
    for nm in sorted(ims)[::a.every]:
        R, tv, cid = ims[nm]; w, h, K = cams[cid]
        V = np.eye(4); V[:3, :3] = R; V[:3, 3] = tv
        with torch.no_grad():
            out, _, _ = rasterization(means, quats, scales, opac, colors, t(V.astype(np.float32))[None], t(K.astype(np.float32))[None],
                                      w, h, sh_degree=deg, near_plane=0.01, far_plane=1e5)
        img = (out[0].clamp(0, 1).cpu().numpy() * 255).round().astype(np.uint8)
        Image.fromarray(img).save(os.path.join(a.out, os.path.splitext(nm)[0] + '.png'))
        if prev is not None:
            diffs.append(float(np.abs(img.astype(np.float32) - prev).mean()))
        prev = img.astype(np.float32)
    if diffs:
        d = np.array(diffs)
        print(f'{len(d) + 1} frames; change from frame to frame: median {np.median(d):.2f}, largest {d.max():.2f} (frame {int(d.argmax()) + 1})', flush=True)


if __name__ == '__main__':
    main()
