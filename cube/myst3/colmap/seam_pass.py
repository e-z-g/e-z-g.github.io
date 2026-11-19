#!/usr/bin/env python3
r"""
A second video-model pass over a two-fisheye walk's seam: the walk redrawn as ONE fisheye in which the seam is a ring
inside the picture, sampled again at low denoise (h3_flf.py --init), and the band round the seam taken back.

    python seam_pass.py single DUAL_DIR OUT_DIR --dual 190 [--fill-square] [--squash A] [--size 2304]
    python seam_pass.py back DUAL_DIR SINGLE_DIR OUT_DIR --dual 190 [--fill-square] [--squash A] [--width 12]

DUAL_DIR holds the walk's frames (0000.png ...) drawn as walk_ends.py --dual-fisheye --along-motion: two fisheyes,
ahead and behind, that meet in a ring square to the walk. The two halves of that ring are drawn by the model apart from
each other, and mid-walk they show different things (seam_fix.py's colour matching cannot help that).
  single: every frame redrawn as one equidistant fisheye of --single-fov degrees (360 by default; 240 gives the seam
          1.5 times the pixels, the ring three quarters of the way out) looking ahead (the angle from straight ahead
          proportional to the distance from the centre: straight ahead in the middle, the seam ring half way out, straight
          behind all round the rim), --size px square; writes OUT_DIR/frames/0000.png ..., first.png, last.png and
          init.mp4 (near lossless) for h3_flf.py first.png last.png ... --init init.mp4 --denoise 0.3.
  back:   the second pass's frames (SINGLE_DIR, any size, square) looked up for every pixel of the two fisheyes within
          --width degrees of the seam, faded in by a smoothstep (whole at the seam, none at --width), the rest kept.
Needs numpy, opencv-python, ffmpeg for init.mp4; walk_ends.py and seam_fix.py beside it.
"""
import argparse
import glob
import os
import subprocess
import sys

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import walk_ends as we  # noqa: E402
from seam_fix import pixel_dirs  # noqa: E402
from seam_score import maps  # noqa: E402


def single_dirs(N, fov=360.0):
    """Directions (right, down, forward) of an equidistant fisheye's pixels (fov degrees across), looking forward."""
    v, u = np.mgrid[0:N, 0:N].astype(np.float64)
    x, y = (u + .5) / N * 2 - 1, (v + .5) / N * 2 - 1
    r = np.minimum(np.hypot(x, y), 1); ph = np.arctan2(y, x); th = r * np.radians(fov / 2)
    return np.stack([np.sin(th) * np.cos(ph), np.sin(th) * np.sin(ph), np.cos(th)], -1)


def to_single(a):
    os.makedirs(os.path.join(a.out, 'frames'), exist_ok=True)
    paths = sorted(glob.glob(os.path.join(a.dual_dir, '*.png')))
    S = cv2.imread(paths[0]).shape[0]
    w = single_dirs(a.size, a.single_fov).reshape(-1, 3)
    side = (w[:, 2] < 0).astype(int)                      # ahead or behind: each direction from the eye it is nearer
    mx, my = np.zeros(len(w), np.float32), np.zeros(len(w), np.float32)
    for s in (0, 1):
        m = side == s
        x, y = maps(w[m], S, a.dual, a.fill_square, a.squash, s)
        mx[m], my[m] = x, y
    mx, my = mx.reshape(a.size, a.size), my.reshape(a.size, a.size)
    g = (np.arange(a.size) + .5) / a.size * 2 - 1
    outside = np.hypot(*np.meshgrid(g, g)) > 1
    for p in paths:
        out = cv2.remap(cv2.imread(p), mx, my, cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)
        out[outside] = 0                                   # black round the circle, as the model was shown before
        cv2.imwrite(os.path.join(a.out, 'frames', os.path.basename(p)), out)
    fr = sorted(glob.glob(os.path.join(a.out, 'frames', '*.png')))
    cv2.imwrite(os.path.join(a.out, 'first.png'), cv2.imread(fr[0])); cv2.imwrite(os.path.join(a.out, 'last.png'), cv2.imread(fr[-1]))
    subprocess.run(['ffmpeg', '-y', '-loglevel', 'error', '-framerate', '24', '-i', os.path.join(a.out, 'frames', '%04d.png'),
                    '-c:v', 'libx264', '-crf', '6', '-pix_fmt', 'yuv444p', os.path.join(a.out, 'init.mp4')], check=True)
    print(f'{len(paths)} frames -> {a.out} ({a.size} px)')


def back(a):
    os.makedirs(a.out, exist_ok=True)
    dp = sorted(glob.glob(os.path.join(a.dual_dir, '*.png'))); sp = sorted(glob.glob(os.path.join(a.single_dir, '*.png')))
    if len(dp) != len(sp):
        raise SystemExit(f'{len(dp)} frames against {len(sp)}')
    S = cv2.imread(dp[0]).shape[0]; N = cv2.imread(sp[0]).shape[0]
    W = np.radians(a.width)
    look = []
    for s in (0, 1):
        A, E = pixel_dirs(S, a.dual, a.fill_square, a.squash, s)
        t = np.clip(1 - np.abs(np.nan_to_num(E, nan=np.pi)) / W, 0, 1)
        fade = (t * t * (3 - 2 * t)).astype(np.float32)
        th = np.pi / 2 - np.nan_to_num(E)                  # angle from straight ahead
        r = th / np.radians(a.single_fov / 2)
        look.append((((r * np.cos(A) + 1) / 2 * N - .5).astype(np.float32), ((r * np.sin(A) + 1) / 2 * N - .5).astype(np.float32), fade))
    for d, s in zip(dp, sp):
        im, si = cv2.imread(d).astype(np.float32), cv2.imread(s)
        for c, (mx, my, fade) in enumerate(look):
            sl = np.s_[:, c * S:(c + 1) * S]
            got = cv2.remap(si, mx, my, cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE).astype(np.float32)
            im[sl] += fade[..., None] * (got - im[sl])
        cv2.imwrite(os.path.join(a.out, os.path.basename(d)), np.clip(np.rint(im), 0, 255).astype(np.uint8))
    print(f'{len(dp)} frames -> {a.out}')


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    for name in ('single', 'back'):
        p = sub.add_parser(name)
        p.add_argument('dual_dir')
        if name == 'back':
            p.add_argument('single_dir')
        p.add_argument('out'); p.add_argument('--dual', type=float, required=True)
        p.add_argument('--fill-square', action='store_true'); p.add_argument('--squash', type=float, default=0.0)
        p.add_argument('--size', type=int, default=2304); p.add_argument('--width', type=float, default=12.0)
        p.add_argument('--single-fov', type=float, default=360.0)
    a = ap.parse_args()
    (to_single if a.cmd == 'single' else back)(a)


if __name__ == '__main__':
    main()
