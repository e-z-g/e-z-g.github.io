#!/usr/bin/env python3
"""
A node's depth from one prediction over its whole panorama, instead of one per
cube face, so that the faces agree at their seams by construction.

    python pano_depth.py SITE OUT_DIR --names N1 ... N6 --dap DAP_DIR
        [--colour-suffix _orig.jpg] [--depth-suffix _measured-depth.png]
        [--erp-height 1024] [--size 1280] [--sharp SHARP_DIR]

The six faces (node_depth.py's order and directions: front, bottom, back,
right, left, top) are sewn into one equirectangular picture, --erp-height high
and twice as wide, and Depth Any Panoramas (Insta360's DAP, Depth Anything V2
with a DINOv3 encoder trained on panoramas; its repository with model.pth in
DAP_DIR) predicts the distance along every ray and where the sky is. The
prediction is sampled back onto each face at --size and fitted to the
measured depth (node_depth.py's, d = (r_far / r - 1) / (RATIO - 1), 0 on the
sky) with one factor for the whole sphere, so the seams stay continuous: the
median of q_measured * r over pixels away from the measured outlines. Prints
the relative step across the seams and the distance from the measured depth,
and the same for SHARP_DIR's redrawn depth if given (<name>_sharp-depth.png),
and writes OUT_DIR/<name>_pano-depth.png in the site's encoding,
OUT_DIR/erp_colour.png and erp_depth.npy, and OUT_DIR/compare.png (measured,
redrawn, panoramic, a row per face). Needs numpy, Pillow, opencv-python,
torch; DAP's own code (its one use of einops is an unused import, so a stub
stands in for it).
"""
import argparse
import os
import sys
import types

import cv2
import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from node_depth import DIRS  # noqa: E402
from sharpen_depth import RATIO, seam_steps  # noqa: E402


def directions_erp(H):
    W = 2 * H
    lon = (np.arange(W) + 0.5) / W * 2 * np.pi - np.pi
    lat = np.pi / 2 - (np.arange(H) + 0.5) / H * np.pi
    lon, lat = np.meshgrid(lon, lat)
    return np.cos(lat) * np.sin(lon), np.sin(lat), -np.cos(lat) * np.cos(lon)    # face 1 (-z) at the centre


def face_of_v(x, y, z):
    """face_of for arrays: face number and (s, t)."""
    ax, ay, az = np.abs(x), np.abs(y), np.abs(z)
    k = np.zeros(x.shape, int); s = np.zeros(x.shape); t = np.zeros(x.shape)
    zm = (az >= ax) & (az >= ay); xm = ~zm & (ax >= ay); ym = ~zm & ~xm
    for m, kk, ss, tt in (
            (zm & (z < 0), 1, (x / az + 1) / 2, (1 - y / az) / 2),
            (zm & (z >= 0), 3, (1 - x / az) / 2, (1 - y / az) / 2),
            (xm & (x > 0), 4, (z / ax + 1) / 2, (1 - y / ax) / 2),
            (xm & (x <= 0), 5, (1 - z / ax) / 2, (1 - y / ax) / 2),
            (ym & (y > 0), 6, (1 - x / ay) / 2, (z / ay + 1) / 2),
            (ym & (y <= 0), 2, (1 - x / ay) / 2, (1 - z / ay) / 2)):
        k[m] = kk; s[m] = ss[m]; t[m] = tt[m]
    return k, s, t


def sew(faces, H):
    """Six square faces (k -> HxWx3 uint8) into one equirectangular picture."""
    x, y, z = directions_erp(H)
    k, s, t = face_of_v(x, y, z)
    out = np.zeros((H, 2 * H, 3), np.float32)
    for kk, img in faces.items():
        m = k == kk
        n = img.shape[0]
        mx = (s * n - 0.5).astype(np.float32); my = (t * n - 0.5).astype(np.float32)   # full maps: remap
        out[m] = cv2.remap(img.astype(np.float32), mx, my, cv2.INTER_LINEAR,          # takes no long rows
                           borderMode=cv2.BORDER_REPLICATE)[m]
    return np.clip(out, 0, 255).astype(np.uint8)


def unsew(erp, k, N):
    """The equirectangular map erp sampled at face k's pixels (N x N), bilinear, longitude wrapping."""
    H, W = erp.shape[:2]
    u = (np.arange(N) + 0.5) / N
    s, t = np.meshgrid(u, u)
    x, y, z = DIRS[k](s, t)
    r = np.sqrt(x * x + y * y + z * z)
    lat = np.arcsin(y / r); lon = np.arctan2(x, -z)
    mx = ((lon + np.pi) / (2 * np.pi) * W - 0.5).astype(np.float32)
    my = ((np.pi / 2 - lat) / np.pi * H - 0.5).astype(np.float32)
    wide = np.concatenate([erp[:, -1:], erp, erp[:, :1]], 1).astype(np.float32)     # wrap in longitude
    return cv2.remap(wide, mx + 1, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)


def run_dap(dap_dir, erp_rgb):
    import torch
    # DAP imports einops but never calls it: a stub stands in.
    sys.modules.setdefault('einops', types.SimpleNamespace(rearrange=None))
    # DINOv3's hub entry (hubconf) also imports its segmentation and evaluation code, with
    # dependencies of their own; DAP only needs the backbone, so it is built from
    # dinov3.hub.backbones directly (pretrained=False: DAP's model.pth holds the weights).
    def local_hub_load(repo_dir, arch, source='local', pretrained=False, **kw):
        sys.path.insert(0, repo_dir)
        from dinov3.hub import backbones
        return getattr(backbones, arch)(pretrained=pretrained, **kw)
    torch.hub.load = local_hub_load
    here = os.getcwd()
    os.chdir(dap_dir)                       # DAP finds its DINOv3 code by a relative path
    sys.path.insert(0, dap_dir)
    try:
        from networks.models import make
        import networks.dap  # noqa: F401  (registers 'dap')
        dev = 'cuda' if torch.cuda.is_available() else 'cpu'
        state = torch.load(os.path.join(dap_dir, 'model.pth'), map_location=dev)
        m = make({'name': 'dap', 'args': {'midas_model_type': 'vitl', 'fine_tune_type': 'hypersim',
                                          'min_depth': 0.01, 'max_depth': 1.0, 'train_decoder': True}})
        if any(k.startswith('module') for k in state):
            m = torch.nn.DataParallel(m)
        m = m.to(dev)
        ms = m.state_dict()
        missing = [k for k in ms if k not in state]
        m.load_state_dict({k: v for k, v in state.items() if k in ms}, strict=False)
        m.eval()
        x = torch.from_numpy(erp_rgb.astype(np.float32).transpose(2, 0, 1) / 255).unsqueeze(0).to(dev)
        with torch.inference_mode():
            o = m(x)
        depth = o['pred_depth'][0, 0].float().cpu().numpy()
        sky = (o['pred_mask'][0, 0].float().cpu().numpy() > 0.5)
    finally:
        os.chdir(here)
    return depth, sky, len(missing)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('site'); ap.add_argument('out')
    ap.add_argument('--names', nargs=6, required=True); ap.add_argument('--dap', required=True)
    ap.add_argument('--colour-suffix', default='_orig.jpg'); ap.add_argument('--depth-suffix', default='_measured-depth.png')
    ap.add_argument('--erp-height', type=int, default=1024); ap.add_argument('--size', type=int, default=1280)
    ap.add_argument('--sharp')
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    faces = {k: np.asarray(Image.open(os.path.join(a.site, n + a.colour_suffix)).convert('RGB'))
             for k, n in enumerate(a.names, 1)}
    H = a.erp_height // 16 * 16
    erp = sew(faces, H)
    Image.fromarray(erp).save(os.path.join(a.out, 'erp_colour.png'))
    depth, sky, missing = run_dap(os.path.abspath(a.dap), erp)
    print(f'DAP at {H}x{2 * H}: {missing} weights missing from model.pth; sky {sky.mean() * 100:.1f}% of the panorama')
    np.save(os.path.join(a.out, 'erp_depth.npy'), depth); np.save(os.path.join(a.out, 'erp_sky.npy'), sky)
    N = a.size

    def q_of(path):
        d8 = cv2.resize(np.asarray(Image.open(path).convert('L')).astype(np.float32), (N, N), interpolation=cv2.INTER_NEAREST)
        return np.where(d8 > 0, 1 + (RATIO - 1) * d8 / 255, 0.0)

    qm = {k: q_of(os.path.join(a.site, n + a.depth_suffix)) for k, n in enumerate(a.names, 1)}
    r = {k: unsew(depth, k, N) for k in range(1, 7)}
    sk = {k: unsew(sky.astype(np.float32), k, N) > 0.5 for k in range(1, 7)}
    # one factor for the sphere, from pixels away from the measured outlines
    vals = []
    for k in range(1, 7):
        g = np.hypot(*np.gradient(qm[k]))
        solid = (qm[k] > 0) & ~sk[k] & (cv2.dilate((g > 0.15).astype(np.uint8), np.ones((25, 25), np.uint8)) == 0)
        vals.append(qm[k][solid] * r[k][solid])
    c = float(np.median(np.concatenate(vals)))
    qp = {k: np.where(sk[k] | (r[k] <= 0), 0.0, c / np.maximum(r[k], 1e-9)) for k in range(1, 7)}
    print(f'one factor for the sphere: r_far = {c:.4f} in DAP\'s units')
    sets = [('measured', qm), ('panoramic (DAP)', qp)]
    if a.sharp:
        sets.insert(1, ('redrawn (per face, blended)', {k: q_of(os.path.join(a.sharp, n + '_sharp-depth.png'))
                                                        for k, n in enumerate(a.names, 1)}))
    for label, qq in sets:
        med, p90 = seam_steps(qq, N)
        line = f'{label:28s} seams: median {med:5.1f}%, 90% within {p90:5.1f}%'
        if label != 'measured':
            both = [(qq[k] > 0) & (qm[k] > 0) for k in range(1, 7)]
            rel = np.concatenate([np.abs(qq[k] - qm[k])[b] / qm[k][b] for k, b in zip(range(1, 7), both)])
            agree = np.mean([((qq[k] > 0) == (qm[k] > 0)).mean() for k in range(1, 7)])
            line += (f'; from the measured: median {np.median(rel) * 100:.1f}%, 90% within '
                     f'{np.percentile(rel, 90) * 100:.1f}%; sky agrees on {agree * 100:.0f}% of pixels')
        print(line)
    enc = lambda q: (np.rint(np.clip((q - 1) / (RATIO - 1), 0, 1) * 255) * (q > 0)).astype(np.uint8)
    tiles = []
    for k, n in enumerate(a.names, 1):
        Image.fromarray(enc(qp[k])).save(os.path.join(a.out, n + '_pano-depth.png'))
        row = [cv2.resize(enc(qq[k]), (320, 320), interpolation=cv2.INTER_AREA) for _, qq in sets]
        tiles.append(np.concatenate([np.pad(t_, ((0, 0), (0, 6))) for t_ in row], 1))
        tiles.append(np.zeros((6, tiles[-1].shape[1]), np.uint8))
    Image.fromarray(np.concatenate(tiles)).save(os.path.join(a.out, 'compare.png'))


if __name__ == '__main__':
    main()
