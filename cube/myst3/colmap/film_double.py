#!/usr/bin/env python3
r"""
A walk video's frames doubled (or more) by FILM, the frame interpolator film_walk.py uses: a picture made halfway
between each pair of neighbouring frames.

    python film_double.py FRAMES_DIR OUT_DIR [--levels 1] [--split 2] [--model C:\myst3_out\film\film_net_fp32.pt]

FRAMES_DIR holds the frames (0000.png ...). --levels 1 puts one picture between each pair (22 frames give 43), 2
puts three (85). --split cuts each frame into that many squares side by side and interpolates each alone (2 for
the two-fisheye layout, so no motion is matched across the seam). Writes OUT_DIR/0000.png ... Needs torch, numpy,
opencv-python; the TorchScript FILM from github.com/dajes/frame-interpolation-pytorch.
"""
import argparse
import glob
import os
import time

import cv2
import numpy as np
import torch


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('frames'); ap.add_argument('out')
    ap.add_argument('--levels', type=int, default=1); ap.add_argument('--split', type=int, default=2)
    ap.add_argument('--model', default=r'C:\myst3_out\film\film_net_fp32.pt')
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    dev = 'cuda' if torch.cuda.is_available() else 'cpu'
    net = torch.jit.load(a.model, map_location='cpu').to(dev).eval()
    frames = [cv2.imread(p) for p in sorted(glob.glob(os.path.join(a.frames, '*.png')))]
    H, W = frames[0].shape[:2]
    S = W // a.split

    def mid(p, q):
        out = np.empty_like(p)
        for c in range(a.split):
            sl = np.s_[:, c * S:(c + 1) * S]
            with torch.no_grad():
                x0 = torch.from_numpy(np.ascontiguousarray(p[sl])).permute(2, 0, 1)[None].float().to(dev) / 255
                x1 = torch.from_numpy(np.ascontiguousarray(q[sl])).permute(2, 0, 1)[None].float().to(dev) / 255
                y = net(x0, x1, torch.full((1, 1), 0.5, device=dev))
            out[sl] = np.clip(np.rint(y[0].clamp(0, 1).permute(1, 2, 0).cpu().numpy() * 255), 0, 255).astype(np.uint8)
            del x0, x1, y
        return out

    t0 = time.time()
    for _ in range(a.levels):
        more = [frames[0]]
        for p, q in zip(frames, frames[1:]):
            more += [mid(p, q), q]
        frames = more
        print(f'{len(frames)} frames, {time.time() - t0:.0f} s', flush=True)
    for i, f in enumerate(frames):
        cv2.imwrite(os.path.join(a.out, f'{i:04d}.png'), f)


if __name__ == '__main__':
    main()
