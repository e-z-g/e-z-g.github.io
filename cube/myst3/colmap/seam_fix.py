#!/usr/bin/env python3
r"""
The colour mismatch at a two-fisheye walk's seam, measured and evened out after the video is made.

    python seam_fix.py FRAMES_DIR OUT_DIR --dual 190 [--fill-square] [--squash A] [--mode gain|ring|both]
        [--width 25] [--blur 8] [--smooth 10]

FRAMES_DIR holds the walk's frames (0000.png ...) drawn as walk_ends.py --dual-fisheye (seam_score.py scores them).
For each frame, directions over the overlap band are looked up in both pictures, blurred (--blur px) so only colour and
light are compared, not detail:
  - gain: one factor per colour channel and per circle, from the two circles' mean colours over the band, so that both
    meet at their average; the whole circle is scaled. Prints how far apart the circles are overall.
  - ring: the difference left at each angle round the ring, smoothed along it (--smooth degrees), split half to each
    circle and faded out over --width degrees either side of the seam (a smoothstep), so the change does not show.
  - both: gain, then ring.
Fine detail is not touched. Writes OUT_DIR/0000.png ... Needs numpy, opencv-python; walk_ends.py beside it.
"""
import argparse
import glob
import os
import sys

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import walk_ends as we  # noqa: E402
from seam_score import maps  # noqa: E402


def pixel_dirs(S, fov, fill, squash, side):
    """Ring angle A and angle from the ring E (radians) of every pixel of one eye; nan off the circle."""
    v, u = np.mgrid[0:S, 0:S].astype(np.float64)
    x, y = (u + .5) / S * 2 - 1, (v + .5) / S * 2 - 1
    if squash:                                           # undo squash_y (monotonic): by table
        t = np.linspace(-1, 1, 4001)
        y = np.interp(y, we.squash_y(t, squash), t)
    if fill:
        x, y = we.square_to_disc(x, y)
    r, ph = np.hypot(x, y), np.arctan2(y, x)
    th = r * np.radians(fov / 2)
    q = np.stack([np.sin(th) * np.cos(ph), np.sin(th) * np.sin(ph), np.cos(th)], -1)
    if side:
        q = q * np.array([-1, 1, -1])
    A = np.arctan2(q[..., 1], q[..., 0]); E = np.arcsin(np.clip(q[..., 2], -1, 1))
    E[r > 1.0001] = np.nan
    return A, E


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('frames'); ap.add_argument('out'); ap.add_argument('--dual', type=float, required=True)
    ap.add_argument('--fill-square', action='store_true'); ap.add_argument('--squash', type=float, default=0.0)
    ap.add_argument('--mode', choices=['gain', 'ring', 'both'], default='both')
    ap.add_argument('--width', type=float, default=25.0); ap.add_argument('--blur', type=float, default=8.0)
    ap.add_argument('--smooth', type=float, default=10.0)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    paths = sorted(glob.glob(os.path.join(a.frames, '*.png')))
    S = cv2.imread(paths[0]).shape[0]
    band = np.radians((a.dual - 180) / 2)
    nA = 720
    az = np.linspace(-np.pi, np.pi, nA, endpoint=False)
    el = np.linspace(-band, band, 9)
    Aa, Ee = np.meshgrid(az, el)
    w = np.stack([np.cos(Aa).ravel() * np.cos(Ee).ravel(), np.sin(Aa).ravel() * np.cos(Ee).ravel(), np.sin(Ee).ravel()], 1)
    mf, mb = maps(w, S, a.dual, a.fill_square, a.squash, 0), maps(w, S, a.dual, a.fill_square, a.squash, 1)
    eyes = [pixel_dirs(S, a.dual, a.fill_square, a.squash, s) for s in (0, 1)]
    W = np.radians(a.width)
    fade = []
    for A, E in eyes:
        t = np.clip(1 - np.abs(np.nan_to_num(E, nan=np.pi)) / W, 0, 1)
        fade.append((t * t * (3 - 2 * t)).astype(np.float32))
    idx = [np.clip(((A + np.pi) / (2 * np.pi) * nA).astype(int) % nA, 0, nA - 1) for A, _ in eyes]
    k = max(1, int(a.smooth / 360 * nA))
    for p in paths:
        im = cv2.imread(p).astype(np.float32)
        circ = [im[:, :S].copy(), im[:, S:].copy()]
        def sample():
            bl = [cv2.GaussianBlur(c, (0, 0), a.blur) for c in circ]
            f = cv2.remap(bl[0], mf[0][None], mf[1][None], cv2.INTER_LINEAR)[0]
            b = cv2.remap(bl[1], (mb[0] - S)[None], mb[1][None], cv2.INTER_LINEAR)[0]
            return f.reshape(len(el), nA, 3), b.reshape(len(el), nA, 3)
        f, b = sample()
        msg = f'{os.path.basename(p)}: circles {np.abs(f - b).mean():5.2f} apart'
        if a.mode in ('gain', 'both'):
            mF, mB = f.mean((0, 1)), b.mean((0, 1)); m = (mF + mB) / 2
            circ[0] *= m / np.maximum(mF, 1); circ[1] *= m / np.maximum(mB, 1)
            msg += f'; gain ahead {np.round(m / np.maximum(mF, 1), 3)} behind {np.round(m / np.maximum(mB, 1), 3)}'
            f, b = sample(); msg += f', then {np.abs(f - b).mean():5.2f}'
        if a.mode in ('ring', 'both'):
            d = (f - b).mean(0)                                   # nA x 3
            d = np.concatenate([d[-k:], d, d[:k]])
            d = cv2.blur(d[None], (2 * k + 1, 1))[0][k:-k] if k > 0 else d
            circ[0] -= fade[0][..., None] * d[idx[0]] / 2
            circ[1] += fade[1][..., None] * d[idx[1]] / 2
            f, b = sample(); msg += f'; ring {np.abs(f - b).mean():5.2f}'
        print(msg, flush=True)
        cv2.imwrite(os.path.join(a.out, os.path.basename(p)), np.clip(np.rint(np.concatenate(circ, 1)), 0, 255).astype(np.uint8))


if __name__ == '__main__':
    main()
