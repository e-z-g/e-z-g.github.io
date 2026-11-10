#!/usr/bin/env python3
r"""
A generated walk made ready for the viewer: its tone matched to the game's own
pictures at both ends, those pictures put in as the first and last frames,
and frames added between by FILM for a smooth frame rate.

    python walk_finish.py WALK.mp4 FIRST.png LAST.png OUT.mp4 [--film film_net_fp32.pt] [--times 4]
        [--fps 16] [--crf 17] [--ffmpeg ffmpeg] [--reverse OUT_BACK.mp4]

Tone: each frame's L, a and b (CIELAB) are given the mean and spread that the
game's first frame has at the start, the last frame's at the end, and the mix
of the two by how far along the frame is: Wan 2.2's clip of MASS 84 to 89
drifted brighter along the way (L 35.0 at the start against the game's 36.6,
40.7 at the end against 37.1) and gained contrast. FILM (TorchScript, as
film_walk.py) then makes --times - 1 frames between each pair (halving, so
--times is a power of two), and the video is written at --fps * --times frames
a second (H.264, every frame its own key frame group of the whole clip), and
reversed for walking back with --reverse. Needs numpy, opencv-python, torch;
ffmpeg.
"""
import argparse
import os
import subprocess
import sys

import cv2
import numpy as np


def stats(lab):
    return lab.reshape(-1, 3).mean(0), lab.reshape(-1, 3).std(0) + 1e-6


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('walk'); ap.add_argument('first'); ap.add_argument('last'); ap.add_argument('out')
    ap.add_argument('--film', default=r'C:\myst3_out\film\film_net_fp32.pt'); ap.add_argument('--times', type=int, default=4)
    ap.add_argument('--fps', type=float, default=16); ap.add_argument('--crf', type=int, default=17)
    ap.add_argument('--ffmpeg', default='ffmpeg'); ap.add_argument('--reverse')
    a = ap.parse_args()
    cap = cv2.VideoCapture(a.walk)
    frames = []
    while True:
        r, f = cap.read()
        if not r:
            break
        frames.append(f)
    n = len(frames)
    H, W = frames[0].shape[:2]
    A = cv2.resize(cv2.imread(a.first), (W, H), interpolation=cv2.INTER_AREA)
    B = cv2.resize(cv2.imread(a.last), (W, H), interpolation=cv2.INTER_AREA)
    lab = lambda im: cv2.cvtColor(im, cv2.COLOR_BGR2LAB).astype(np.float32)
    (ma, sa), (mb, sb) = stats(lab(A)), stats(lab(B))
    fixed = []
    for i, f in enumerate(frames):
        t = i / (n - 1)
        L = lab(f)
        m, s = stats(L)
        tm, ts = (1 - t) * ma + t * mb, (1 - t) * sa + t * sb
        out = (L - m) / s * ts + tm
        fixed.append(cv2.cvtColor(np.clip(out, 0, 255).astype(np.uint8), cv2.COLOR_LAB2BGR))
    fixed[0], fixed[-1] = A, B
    print(f'{n} frames {W}x{H}; tone matched to the ends', flush=True)
    import torch
    dev = 'cuda' if torch.cuda.is_available() else 'cpu'
    net = torch.jit.load(a.film, map_location='cpu').to(dev).eval()

    def mid(p, q):
        with torch.no_grad():
            x0 = torch.from_numpy(p[..., ::-1].copy()).permute(2, 0, 1)[None].float().to(dev) / 255
            x1 = torch.from_numpy(q[..., ::-1].copy()).permute(2, 0, 1)[None].float().to(dev) / 255
            y = net(x0, x1, torch.full((1, 1), 0.5, device=dev))
        return np.clip(y[0].permute(1, 2, 0).cpu().numpy() * 255 + .5, 0, 255).astype(np.uint8)[..., ::-1].copy()

    def between(p, q, k):
        if k == 1:
            return []
        m = mid(p, q)
        return between(p, m, k // 2) + [m] + between(m, q, k // 2)

    allf = []
    for i in range(n - 1):
        allf.append(fixed[i])
        allf.extend(between(fixed[i], fixed[i + 1], a.times))
    allf.append(fixed[-1])
    fps = a.fps * a.times
    print(f'{len(allf)} frames at {fps:g} fps', flush=True)
    for path, seq in ((a.out, allf), (a.reverse, allf[::-1])):
        if not path:
            continue
        p = subprocess.Popen([a.ffmpeg, '-v', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'bgr24', '-s', f'{W}x{H}',
                              '-r', f'{fps:g}', '-i', '-', '-c:v', 'libx264', '-preset', 'slow', '-crf', str(a.crf),
                              '-pix_fmt', 'yuv420p', '-g', str(len(seq)), '-movflags', '+faststart', path], stdin=subprocess.PIPE)
        for f in seq:
            p.stdin.write(f.tobytes())
        p.stdin.close(); p.wait()
        print(path, f'{os.path.getsize(path) / 1e6:.1f} MB', flush=True)


if __name__ == '__main__':
    main()
