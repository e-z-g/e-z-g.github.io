#!/usr/bin/env python3
"""
Depth for a site node's six faces from another network than Depth Anything, to
compare with the stereo.

    python depth_nets.py SITE OUT_DIR --names N1 ... N6 [--net moge2]
        [--colour-suffix _orig.jpg]

Each face is a 90-degree pinhole, so the field of view is given to the network.
--net moge2: MoGe-2 (Microsoft, Ruicheng/moge-2-vitl-normal), which predicts a
point map with metric scale. Writes OUT_DIR/<name>_<net>-z.npy (float32 depth
along the face's axis, 0 where the network masks the pixel out: sky, or
nothing it trusts). Needs torch and the network's own package (pip install
git+https://github.com/microsoft/MoGe.git).

Why: Depth Anything V2 (node_depth.py's Base, sharpen_depth.py's Large) draws
MASS 84's rock wall as a slab per column, each at its own distance, where the
stereo measures one smooth wall; the slabs slide apart in the original and
tear in the layered version. A network that predicts geometry rather than
relative depth may draw the wall whole.
"""
import argparse
import os

import numpy as np
from PIL import Image


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('site'); ap.add_argument('out')
    ap.add_argument('--names', nargs=6, required=True)
    ap.add_argument('--net', default='moge2', choices=['moge2'])
    ap.add_argument('--colour-suffix', default='_orig.jpg')
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    import torch
    dev = 'cuda' if torch.cuda.is_available() else 'cpu'
    if a.net == 'moge2':
        from moge.model.v2 import MoGeModel
        model = MoGeModel.from_pretrained('Ruicheng/moge-2-vitl-normal').to(dev).eval()
    for name in a.names:
        img = np.asarray(Image.open(os.path.join(a.site, name + a.colour_suffix)).convert('RGB'))
        x = torch.tensor(img / 255.0, dtype=torch.float32, device=dev).permute(2, 0, 1)
        with torch.no_grad():
            out = model.infer(x, fov_x=90.0)
        z = out['depth'].float().cpu().numpy()
        m = out['mask'].cpu().numpy().astype(bool) if 'mask' in out else np.isfinite(z)
        z = np.where(m & np.isfinite(z), z, 0).astype(np.float32)
        np.save(os.path.join(a.out, f'{name}_{a.net}-z.npy'), z)
        print(f'{name}: {z.shape[1]}x{z.shape[0]}, {np.mean(z > 0) * 100:.1f}% with depth, '
              f'median {np.median(z[z > 0]):.3f}', flush=True)


if __name__ == '__main__':
    main()
