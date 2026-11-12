#!/usr/bin/env python3
r"""
Each node's own distances as a small panorama: what scene_carve.py tests the mesh against. (Tried in
scene3d.html as each node's picture on its own shape behind or in front of the mesh, 11 November 2026: no
better between nodes than the mesh alone, so not used there.)

    python scene_shells.py MESH_DIR [--width 256] [--far 60] [--name shells]

MESH_DIR is scene_mesh.py --dense's OUT: moge\<node>_anchored.npy (the anchored distances, in the model's
units), moge\<node>_moge_mask.npy, scales.json (unit) and nodes.json (the nodes). Writes
MESH_DIR\shells\MA-<node>.png: an equirectangular panorama (--width by half that, as moge_depth.py's:
longitude atan2(x, -z) from the left edge's -180 degrees, latitude asin(y) from the top's +90, in the node's
frame, x right, y up, -z face 1) of the distance in the viewer's units (model units over unit) times 1000,
as 16 bits split into red (high byte) and green (low byte); 0 where MoGe has no surface (the sky) or it is
past --far. Each cell takes the median of the full panorama's cells in it. Needs numpy, Pillow.
"""
import argparse
import json
import os

import numpy as np
from PIL import Image


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('mesh'); ap.add_argument('--width', type=int, default=256); ap.add_argument('--far', type=float, default=60)
    ap.add_argument('--name', default='shells', help='the folder under MESH_DIR')
    a = ap.parse_args()
    unit = json.load(open(os.path.join(a.mesh, 'scales.json')))['unit']
    nodes = list(json.load(open(os.path.join(a.mesh, 'nodes.json'))))
    out = os.path.join(a.mesh, a.name); os.makedirs(out, exist_ok=True)
    W, H = a.width, a.width // 2
    for n in nodes:
        f = os.path.join(a.mesh, 'moge', n + '_anchored.npy')
        if not os.path.exists(f):
            print(f'node {n}: no anchored distances'); continue
        D = np.load(f).astype(np.float32) / unit
        mk = os.path.join(a.mesh, 'moge', n + '_moge_mask.npy')
        if os.path.exists(mk):
            M = np.load(mk) > 0.5
            if M.shape != D.shape:
                M = np.asarray(Image.fromarray(M.astype(np.uint8)).resize((D.shape[1], D.shape[0]), Image.NEAREST)) > 0
            D = np.where(M, D, np.nan)
        D = np.where(np.isfinite(D) & (D > 0) & (D < a.far), D, np.nan)
        h, w = D.shape
        by, bx = h // H, w // W
        blk = D[:H * by, :W * bx].reshape(H, by, W, bx).transpose(0, 2, 1, 3).reshape(H, W, by * bx)
        with np.errstate(all='ignore'):
            med = np.nanmedian(blk, axis=2)
            # a cell more than half sky stays sky
            med[np.isnan(blk).mean(axis=2) > 0.5] = np.nan
        q = np.where(np.isfinite(med), np.clip(np.rint(med * 1000), 1, 65535), 0).astype(np.uint16)
        rgb = np.zeros((H, W, 3), np.uint8); rgb[..., 0] = q >> 8; rgb[..., 1] = q & 255
        Image.fromarray(rgb).save(os.path.join(out, f'MA-{n}.png'), optimize=True)
        print(f'node {n}: {np.isfinite(med).mean() * 100:.0f}% surface, median {np.nanmedian(med):.2f}', flush=True)


if __name__ == '__main__':
    main()
