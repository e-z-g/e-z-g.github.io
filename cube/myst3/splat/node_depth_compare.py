#!/usr/bin/env python3
"""
A node's depth from a splat against its depth on the site.

    python node_depth_compare.py SPLAT_RENDERS SITE SHARP OUT_DIR --names MA-4084-1 ... MA-4084-6
        --splat-names f1_MA-4084 ... f6_MA-4084 [--sky-beyond 500]

SPLAT_RENDERS holds splat_render.py --depth's output for the node's six faces
(<splat name>.png, the real face beside the render, and <splat name>_depth.npy,
z along the face's axis, 0 where the render never becomes half covered); SITE
the node's measured depth (<name>_measured-depth.png, node_depth.py's), SHARP
the redrawn one (<name>_sharp-depth.png, sharpen_depth.py's). Both store
d = (r_far / r - 1) / (RATIO - 1), 0 on the sky. The splat's depth has its own
scale (a moved node's model was rescaled), so one factor is fitted, the median
of q_measured * r_splat, and the splat's depth beyond --sky-beyond units is
taken as sky. Prints, for the measured, the redrawn and the splat's depth, the
relative step in inverse distance across the cube's seams (sharpen_depth's
measure) and the redrawn's and the splat's distance from the measured depth;
writes OUT_DIR/compare.png (measured, redrawn, splat, a row per face) and
OUT_DIR/<name>_splat-depth.png in the site's encoding. Needs numpy, Pillow,
opencv-python; ../colmap beside it.
"""
import argparse
import os
import sys

import cv2
import numpy as np
from PIL import Image

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'colmap'))
from sharpen_depth import RATIO, seam_steps  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('renders'); ap.add_argument('site'); ap.add_argument('sharp'); ap.add_argument('out')
    ap.add_argument('--names', nargs=6, required=True); ap.add_argument('--splat-names', nargs=6, required=True)
    ap.add_argument('--sky-beyond', type=float, default=500.0)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    zs = [np.load(os.path.join(a.renders, n + '_depth.npy')) for n in a.splat_names]
    N = zs[0].shape[0]
    u = (np.arange(N) + 0.5) / N
    s, t = np.meshgrid(u, u)
    ray = np.sqrt(1 + (2 * s - 1) ** 2 + (1 - 2 * t) ** 2)          # r / z on a 90-degree face

    def q_of(path):                                               # r_far / r, 0 on the sky
        d8 = np.asarray(Image.open(path).convert('L')).astype(np.float32)
        d8 = cv2.resize(d8, (N, N), interpolation=cv2.INTER_NEAREST)
        return np.where(d8 > 0, 1 + (RATIO - 1) * d8 / 255, 0.0)

    qm = [q_of(os.path.join(a.site, n + '_measured-depth.png')) for n in a.names]
    qh = [q_of(os.path.join(a.sharp, n + '_sharp-depth.png')) for n in a.names]
    rs = [z * ray for z in zs]
    rows = []
    for k in range(6):
        ok = (qm[k] > 0) & (zs[k] > 0) & (rs[k] < a.sky_beyond)
        rows.append(qm[k][ok] * rs[k][ok])
    c = float(np.median(np.concatenate(rows)))                    # r_far in the splat's units
    qsp = [np.where((z > 0) & (r < a.sky_beyond), c / np.maximum(r, 1e-9), 0.0) for z, r in zip(zs, rs)]
    print(f'r_far in the splat\'s units: {c:.3f}')
    for label, qq in (('measured', qm), ('redrawn (Depth Anything)', qh), ('splat', qsp)):
        med, p90 = seam_steps({k + 1: qq[k] for k in range(6)}, N)
        line = f'{label:26s} seams: median step {med:5.1f}%, 90% within {p90:5.1f}%'
        if label != 'measured':
            rel = np.concatenate([np.abs(qq[k] - qm[k])[(qq[k] > 0) & (qm[k] > 0)] / qm[k][(qq[k] > 0) & (qm[k] > 0)]
                                  for k in range(6)])
            cover = np.mean([((qq[k] > 0) == (qm[k] > 0)).mean() for k in range(6)])
            line += f'; from the measured depth median {np.median(rel) * 100:.1f}%, 90% within {np.percentile(rel, 90) * 100:.1f}%' \
                    f'; sky where the measured has sky: {cover * 100:.0f}% of pixels'
        print(line)
    enc = lambda q: np.rint(np.clip((q - 1) / (RATIO - 1), 0, 1) * 255).astype(np.uint8) * (q > 0)
    tiles = []
    for k, n in enumerate(a.names):
        Image.fromarray(enc(qsp[k])).save(os.path.join(a.out, n + '_splat-depth.png'))
        g = lambda q: cv2.resize(enc(q), (320, 320), interpolation=cv2.INTER_AREA)
        tiles.append(np.concatenate([g(qm[k]), np.zeros((320, 6), np.uint8), g(qh[k]), np.zeros((320, 6), np.uint8),
                                     g(qsp[k])], 1))
        tiles.append(np.zeros((6, tiles[-1].shape[1]), np.uint8))
    Image.fromarray(np.concatenate(tiles)).save(os.path.join(a.out, 'compare.png'))


if __name__ == '__main__':
    main()
