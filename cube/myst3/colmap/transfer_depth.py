#!/usr/bin/env python3
"""
Depth for a node's poorly covered faces from a neighbouring node's view of the
same surfaces.

    python transfer_depth.py IMAGES SPARSE_TXT OUT_DIR --target 4089 DEPTH_DIR JSON
        --source 4084 DEPTH_DIR JSON --faces 6 [--gate 3] [--blur 4]

Both nodes' depths are node_depth.py's encoding (DEPTH_DIR/MA-<node>-<k>
_measured-depth.png, r_far in JSON, the model's units: SPARSE_TXT the model
both were measured in). The source node's points, from all six faces, are
drawn into each of the target's --faces (nearest wins, pinholes closed);
where the target has depth (not sky) and the source lands within --gate times
its distance either way (further off is taken for something else seen past
the edge of a thing), the target takes the source's distance, as a
correction spread over --blur px so its edges do not step. With
--fill-uncovered, what the source does not see of a solid shape it partly
covers takes the distance of the nearest covered pixel of the same shape. Sky stays sky;
the target's other faces are copied unchanged; r_far is the target's.

Made for MASS 89's top face: the model is reliable on 5% of it, and the depth
network drew the roof corner and its insignia receding to 9 units, where the
walls beside it, and MASS 84's top face seeing the same roof, have it at about
2; the insignia stood still as the eye moved. Needs numpy, Pillow,
opencv-python; view_check.py and walk_joint.py beside it.
"""
import argparse
import json
import os
import shutil
import sys

import cv2
import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from view_check import read_model  # noqa: E402
from walk_joint import load, project  # noqa: E402

RATIO = 20.0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('images'); ap.add_argument('sparse'); ap.add_argument('out')
    ap.add_argument('--target', nargs=3, required=True, metavar=('NODE', 'DEPTH_DIR', 'JSON'))
    ap.add_argument('--source', nargs=3, required=True, metavar=('NODE', 'DEPTH_DIR', 'JSON'))
    ap.add_argument('--faces', type=int, nargs='+', required=True)
    ap.add_argument('--gate', type=float, default=3.0); ap.add_argument('--blur', type=float, default=4.0)
    ap.add_argument('--fill-uncovered', action='store_true',
                    help="what the source does not see of a solid shape it partly covers takes the nearest covered distance (needs scipy)")
    a = ap.parse_args()
    _, imgs = read_model(a.sparse)
    T = load(a.images, imgs, *a.target, None)
    S = load(a.images, imgs, *a.source, None)
    os.makedirs(a.out, exist_ok=True)
    report = {}
    for k, fc in T['faces'].items():
        name = f'MA-{T["node"]}-{k}_measured-depth.png'
        if k not in a.faces:
            shutil.copy(os.path.join(a.target[1], name), os.path.join(a.out, name))
            continue
        r0 = fc['r']
        rs = project(S, fc)
        has = np.isfinite(rs) & np.isfinite(r0) & ~fc['sky']
        has &= (rs < r0 * a.gate) & (rs > r0 / a.gate)
        lc = np.where(has, np.log(np.where(has, rs, 1) / np.where(has, r0, 1)), 0.0)
        wt = cv2.GaussianBlur(has.astype(np.float32), (0, 0), a.blur)
        cs = cv2.GaussianBlur(lc.astype(np.float32), (0, 0), a.blur) / np.maximum(wt, 1e-6)
        corr = np.where(has, lc, np.where(wt > 0.02, cs * np.clip(wt / 0.2, 0, 1), 0.0))
        r = np.where(fc['sky'], np.nan, r0 * np.exp(corr))
        solid = np.isfinite(r0) & ~fc['sky']
        if a.fill_uncovered:
            # what the source does not see of a solid shape it partly covers (MASS 89's
            # roof insignia, hidden from MASS 84 behind the eave) takes the distance of
            # the nearest covered pixel of the same shape, then a light smoothing
            from scipy import ndimage
            n, lab = cv2.connectedComponents(solid.astype(np.uint8))
            fill = solid & ~has
            for i in range(1, n):
                part = lab == i
                if not (part & has).any() or not (part & fill).any():
                    continue
                _, (iy, ix) = ndimage.distance_transform_edt(~(part & has), return_indices=True)
                src = r[iy, ix]
                m = part & fill
                r[m] = src[m]
            rs_ = cv2.GaussianBlur(np.where(solid, np.log(np.where(solid, r, 1)), 0).astype(np.float32), (0, 0), 2)
            ws_ = cv2.GaussianBlur(solid.astype(np.float32), (0, 0), 2)
            r = np.where(fill, np.exp(rs_ / np.maximum(ws_, 1e-6)), r)
        q = np.where(fc['sky'], 0.0, T['r_far'] / np.maximum(np.where(np.isfinite(r), r, T['r_far']), 1e-9))
        d8 = np.where(fc['sky'], 0, np.maximum(np.rint(np.clip((q - 1) / (RATIO - 1), 0, 1) * 255), 1)).astype(np.uint8)
        Image.fromarray(d8).save(os.path.join(a.out, name))
        report[k] = {'covered_by_source': float(has.sum() / max(1, solid.sum())),
                     'median_before': float(np.nanmedian(r0[solid])) if solid.any() else None,
                     'median_after': float(np.nanmedian(r[solid])) if solid.any() else None}
        print(f'face {k}: {T["node"]}\'s depth taken from {S["node"]}\'s on {has.sum() / max(1, solid.sum()) * 100:.0f}% '
              f'of what is not sky; distance median {report[k]["median_before"]:.2f} -> {report[k]["median_after"]:.2f}', flush=True)
    with open(os.path.join(a.out, 'agree_depth.json'), 'w') as fh:
        json.dump({'r_far': T['r_far'], 'transfer': {'from': S['node'], 'faces': report}}, fh, indent=1)


if __name__ == '__main__':
    main()
