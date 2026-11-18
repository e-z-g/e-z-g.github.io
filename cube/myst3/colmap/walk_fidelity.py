#!/usr/bin/env python3
r"""
How much of the game's own picture a walk video keeps: its first (or last) frame turned back into the node's six
faces and compared with them.

    python walk_fidelity.py IMAGES SPARSE_TXT NODE_A NODE_B VIDEO_OR_PNG [--last] [--prefix LE]
        (--single [--projection equidistant|equal-area|horizon] | --dual 190 [--squash A]) [--along-motion]

The layout is given as walk_ends.py drew it (--single: ONE 360-degree fisheye looking straight down; --dual: two
fisheyes of that many degrees straight ahead and back, with --squash). Each pixel of NODE_A's six 640 px faces (or
NODE_B's with --last) looks some way; that way is looked up in the frame (bilinear), which gives the faces again as
the video has them. They are compared by the angle below the horizon, in bands of 30 degrees:
  - PSNR (dB) against the game's faces;
  - detail kept: the energy of the fine detail (the picture less its 2 px blur) as a share of the game's;
  - SSIM.
A PNG in place of the video scores walk_ends' own drawing (the layout's loss alone, before the video model).
Needs numpy, opencv-python; walk_ends.py and view_check.py beside it.
"""
import argparse
import os
import sys

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import walk_ends as we  # noqa: E402
from view_check import read_model  # noqa: E402


def ssim_map(a, b):
    C1, C2 = (0.01 * 255) ** 2, (0.03 * 255) ** 2
    bl = lambda x: cv2.GaussianBlur(x, (0, 0), 1.5)
    ma, mb = bl(a), bl(b)
    va, vb, cab = bl(a * a) - ma * ma, bl(b * b) - mb * mb, bl(a * b) - ma * mb
    return ((2 * ma * mb + C1) * (2 * cab + C2)) / ((ma * ma + mb * mb + C1) * (va + vb + C2))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('images'); ap.add_argument('sparse'); ap.add_argument('a'); ap.add_argument('b'); ap.add_argument('frame')
    ap.add_argument('--last', action='store_true'); ap.add_argument('--prefix', default='LE')
    ap.add_argument('--single', action='store_true'); ap.add_argument('--projection', default='equidistant')
    ap.add_argument('--dual', type=float); ap.add_argument('--squash', type=float, default=0.0)
    ap.add_argument('--fill', action='store_true', help="walk_ends --fill: each circle stretched to fill its square")
    ap.add_argument('--along-motion', action='store_true')
    a = ap.parse_args()
    we.PREFIX = a.prefix
    _, imgs = read_model(a.sparse)
    CA, FA = we.faces_of(a.images, imgs, a.a)
    CB, FB = we.faces_of(a.images, imgs, a.b)
    # the walk's frame, as walk_ends.main makes it (no --yaw or --pitch)
    up = -FA[0][0][1]
    fwd = CB - CA
    if not a.along_motion:
        fwd -= up * (fwd @ up)
    fwd /= np.linalg.norm(fwd)
    right = np.cross(fwd, up); right /= np.linalg.norm(right)
    down = np.cross(fwd, right); down /= np.linalg.norm(down)
    Rcam = np.stack([right, down, fwd])
    if a.frame.lower().endswith('.png'):
        img = cv2.cvtColor(cv2.imread(a.frame), cv2.COLOR_BGR2RGB)
    else:
        cap = cv2.VideoCapture(a.frame)
        n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        cap.set(cv2.CAP_PROP_POS_FRAMES, n - 1 if a.last else 0)
        ok, f = cap.read()
        img = cv2.cvtColor(f, cv2.COLOR_BGR2RGB)
    H, W = img.shape[:2]
    faces = FB if a.last else FA
    bands = np.arange(-90, 91, 30)
    acc = {k: [] for k in range(len(bands) - 1)}
    for R, _, orig in faces:
        N = orig.shape[0]
        v, u = np.mgrid[0:N, 0:N].astype(np.float64)
        c = np.stack([(u + .5) / N * 2 - 1, (v + .5) / N * 2 - 1, np.ones_like(u)], -1)
        d = c @ R                                    # face camera -> model frame (rows of R are the camera's axes)
        d /= np.linalg.norm(d, axis=-1, keepdims=True)
        elev = np.degrees(np.arcsin(np.clip(d @ up, -1, 1)))
        if a.single:
            E = we.fisheye_eyes(Rcam, 0.0, -90.0)[0]
            q = d @ E.T
            th = np.arccos(np.clip(q[..., 2], -1, 1)); ph = np.arctan2(q[..., 1], q[..., 0])
            r = {'equal-area': lambda t: np.sin(t / 2), 'horizon': we.horizon_r}.get(a.projection, lambda t: t / np.pi)(th)
            x, y, x0, S = r * np.cos(ph), r * np.sin(ph), 0.0, H
        else:
            Ef, Eb = we.fisheye_eyes(Rcam)
            qf, qb = d @ Ef.T, d @ Eb.T
            front = qf[..., 2] >= 0
            q = np.where(front[..., None], qf, qb)
            th = np.arccos(np.clip(q[..., 2], -1, 1)); ph = np.arctan2(q[..., 1], q[..., 0])
            r = th / np.radians(a.dual / 2)
            x, y = r * np.cos(ph), r * np.sin(ph)
            if a.fill:
                x, y = we.disc_to_square(x, y)
            if a.squash:
                y = we.squash_y(y, a.squash)
            x0, S = np.where(front, 0.0, H), H
        mx = ((x + 1) / 2 * S + x0 - .5).astype(np.float32); my = ((y + 1) / 2 * S - .5).astype(np.float32)
        got = cv2.remap(img, mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE).astype(np.float32)
        o = orig.astype(np.float32)
        go, gg = cv2.cvtColor(o, cv2.COLOR_RGB2GRAY), cv2.cvtColor(got, cv2.COLOR_RGB2GRAY)
        hf = lambda g: g - cv2.GaussianBlur(g, (0, 0), 2)
        ss = ssim_map(go, gg)
        se = ((o - got) ** 2).mean(-1)
        for k in range(len(bands) - 1):
            m = (elev >= bands[k]) & (elev < bands[k + 1])
            if m.any():
                acc[k].append((se[m].sum(), m.sum(), (hf(gg)[m] ** 2).sum(), (hf(go)[m] ** 2).sum(), ss[m].sum()))
    print(f'{os.path.basename(os.path.dirname(a.frame))}/{os.path.basename(a.frame)} ({"last" if a.last else "first"} frame)')
    print('  band (deg from horizon)   PSNR dB   detail kept   SSIM')
    tot = np.zeros(5)
    for k in range(len(bands) - 1):
        if not acc[k]:
            continue
        s = np.array(acc[k]).sum(0); tot += s
        print(f'  {bands[k]:+4d} to {bands[k + 1]:+4d}            {10 * np.log10(255 ** 2 / (s[0] / s[1])):6.2f}     {s[2] / s[3]:6.2f}     {s[4] / s[1]:.3f}')
    print(f'  all                      {10 * np.log10(255 ** 2 / (tot[0] / tot[1])):6.2f}     {tot[2] / tot[3]:6.2f}     {tot[4] / tot[1]:.3f}')


if __name__ == '__main__':
    main()
