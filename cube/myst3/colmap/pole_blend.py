#!/usr/bin/env python3
r"""
Two walks in the two-fisheye layout mixed by angle from the line of travel: OTHER kept whole near the two circles'
centres (straight ahead and straight behind, within FROM degrees), BASE beyond TO degrees, a smooth fade between.
For a walk drawn as walk_ends.py --polar, whose poles (the circles' centres) are smeared, with the centres taken
from a two-circle walk.

    python pole_blend.py BASE_DIR OTHER_DIR OUT_DIR --fade 35 55 [--flow | --agree 2 6] [--dual 180] [--fill-square]
        [--squash 0.35]

--flow: in the fade OTHER is first moved onto BASE along the optical flow between them, fully where BASE takes over
and not at all where OTHER is whole, so a thing the two drew in slightly different places is not doubled. (On
J'nanin's cliff walk it still doubled the tower: Sam, 23 November 2026.)

--agree LO HI: BASE alone wherever the two disagree, at any angle, and the two mixed only where they agree. The
disagreement is the optical flow (DIS) between them, in pixels of the full frame: none below LO, all above HI;
grown by --grow pixels, softened by --soften, and held over the frames either side, so the change from OTHER to
BASE falls where the two draw the same thing. Mixing two passes that drew a thing in different places draws it twice
(the tower on J'nanin's cliff walk, LEIS 1060 to 1067), and switching between them at a line would tear it.

Writes OUT_DIR/0000.png ... Needs numpy, opencv-python.
"""
import argparse
import glob
import os
import sys

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from seam_fix import pixel_dirs  # noqa: E402


def aligned(B, O, wt, S):
    # O moved toward B along the flow from B to O, by (1 - weight): unchanged where O is whole, onto B where B takes over
    g = lambda x: cv2.cvtColor(x, cv2.COLOR_BGR2GRAY)
    out = O.copy()
    for c in range(2):
        sl = np.s_[:, c * S:(c + 1) * S]
        f = cv2.calcOpticalFlowFarneback(g(B[sl]), g(O[sl]), None, 0.5, 5, 31, 3, 7, 1.5, 0)
        k = (1 - wt[sl])[..., None]
        h, w = f.shape[:2]
        x, y = np.meshgrid(np.arange(w, dtype=np.float32), np.arange(h, dtype=np.float32))
        out[sl] = cv2.remap(O[sl], x + k[..., 0] * f[..., 0], y + k[..., 0] * f[..., 1], cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    return out


def disagreement(B, O, S, a):
    # 0 where the two agree, 1 where they do not, per pixel of the frame, from the flow between them in each circle
    dis = cv2.DISOpticalFlow_create(cv2.DISOPTICAL_FLOW_PRESET_MEDIUM)
    g = lambda x: cv2.resize(cv2.cvtColor(x, cv2.COLOR_BGR2GRAY), None, fx=.5, fy=.5, interpolation=cv2.INTER_AREA)
    out = np.zeros(B.shape[:2], np.float32)
    for c in range(2):
        sl = np.s_[:, c * S:(c + 1) * S]
        f = dis.calc(g(B[sl]), g(O[sl]), None)
        m = cv2.resize(np.hypot(f[..., 0], f[..., 1]) * 2, (S, B.shape[0]), interpolation=cv2.INTER_LINEAR)
        out[sl] = np.clip((m - a.agree[0]) / (a.agree[1] - a.agree[0]), 0, 1)
    if a.grow:
        out = cv2.dilate(out, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * a.grow + 1, 2 * a.grow + 1)))
    if a.soften:
        out = cv2.GaussianBlur(out, (0, 0), a.soften)
    return np.clip(out, 0, 1)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('base'); ap.add_argument('other'); ap.add_argument('out')
    ap.add_argument('--fade', type=float, nargs=2, default=[35.0, 55.0], metavar=('FROM', 'TO'))
    ap.add_argument('--dual', type=float, default=180.0); ap.add_argument('--fill-square', action='store_true')
    ap.add_argument('--squash', type=float, default=0.0)
    ap.add_argument('--flow', action='store_true')
    ap.add_argument('--agree', type=float, nargs=2, metavar=('LO', 'HI'))
    ap.add_argument('--grow', type=int, default=48); ap.add_argument('--soften', type=float, default=24)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    pb = sorted(glob.glob(os.path.join(a.base, '*.png'))); po = sorted(glob.glob(os.path.join(a.other, '*.png')))
    if len(pb) != len(po):
        raise SystemExit(f'{len(pb)} frames against {len(po)}')
    H, W = cv2.imread(pb[0]).shape[:2]; S = W // 2
    lo, hi = np.radians(a.fade)
    w = []
    for s in (0, 1):
        _, E = pixel_dirs(S, a.dual, a.fill_square, a.squash, s)
        ax = np.pi / 2 - np.abs(np.nan_to_num(E, nan=0.0))          # angle from straight ahead or straight behind
        t = np.clip((hi - ax) / (hi - lo), 0, 1)
        w.append((t * t * (3 - 2 * t)).astype(np.float32)[..., None])
    wt = np.concatenate(w, 1)
    D = [disagreement(cv2.imread(b), cv2.imread(o), S, a) for b, o in zip(pb, po)] if a.agree else None
    for i, (b, o) in enumerate(zip(pb, po)):
        B = cv2.imread(b).astype(np.float32); O = cv2.imread(o).astype(np.float32)
        if a.flow:
            O = aligned(cv2.imread(b), cv2.imread(o), wt[..., 0], S).astype(np.float32)
        k = wt
        if D is not None:
            d = np.maximum.reduce(D[max(0, i - 1):i + 2])            # held over the frames either side
            k = wt * (1 - d)[..., None]
            band = (wt[..., 0] > 0.02)
            print(f'frame {i:2d}: BASE alone over {(d > 0.5)[band].mean() * 100:4.1f}% of where OTHER counts')
        cv2.imwrite(os.path.join(a.out, os.path.basename(b)), np.clip(np.rint(B + k * (O - B)), 0, 255).astype(np.uint8))
    print(f'{len(pb)} frames -> {a.out}')


if __name__ == '__main__':
    main()
