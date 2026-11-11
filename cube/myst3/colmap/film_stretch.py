#!/usr/bin/env python3
"""
A short video made longer by frame interpolation (FILM): between each pair of frames the picture halfway
between, then halfway between each pair, --levels times, so n frames become (n - 1) * 2^levels + 1.

    python film_stretch.py IN.mp4 OUT.mp4 --model film_net_fp32.pt [--levels 3] [--seconds 3] [--crf 14]

The frames are written at whatever rate makes them last --seconds (22 frames at 3 levels: 169 frames, 56 a
second for 3 s). The sound is left out. FILM is Google's Frame Interpolation for Large Motion as TorchScript
(github.com/dajes/frame-interpolation-pytorch), as film_walk.py uses it. Needs numpy, opencv-python, torch;
ffmpeg.
"""
import argparse
import subprocess

import cv2
import numpy as np


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('inp'); ap.add_argument('out'); ap.add_argument('--model', required=True)
    ap.add_argument('--levels', type=int, default=3); ap.add_argument('--seconds', type=float, default=3)
    ap.add_argument('--crf', type=int, default=14); ap.add_argument('--ffmpeg', default='ffmpeg')
    a = ap.parse_args()
    import torch
    dev = 'cuda' if torch.cuda.is_available() else 'cpu'
    net = torch.jit.load(a.model, map_location='cpu').to(dev).eval()
    cap, frames = cv2.VideoCapture(a.inp), []
    while True:
        ok, f = cap.read()
        if not ok:
            break
        frames.append(f)
    H, W = frames[0].shape[:2]
    n_out = (len(frames) - 1) * 2 ** a.levels + 1
    fps = n_out / a.seconds

    def t(img):
        return torch.from_numpy(img).permute(2, 0, 1)[None].float().to(dev) / 255

    def mid(p, q):
        with torch.no_grad():
            y = net(p, q, torch.full((1, 1), 0.5, device=dev))
        return y.clamp(0, 1)

    def between(p, q, level):                            # the frames strictly between p and q, in order
        if level == 0:
            return []
        m = mid(p, q)
        return between(p, m, level - 1) + [m] + between(m, q, level - 1)

    p = subprocess.Popen([a.ffmpeg, '-v', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'bgr24', '-s', f'{W}x{H}',
                          '-r', f'{fps:.6f}', '-i', '-', '-c:v', 'libx264', '-crf', str(a.crf), '-preset', 'slow',
                          '-pix_fmt', 'yuv420p', '-movflags', '+faststart', a.out], stdin=subprocess.PIPE)

    def put(x):
        img = x if isinstance(x, np.ndarray) else (x[0].permute(1, 2, 0).cpu().numpy() * 255 + .5).astype(np.uint8)
        p.stdin.write(np.ascontiguousarray(img).tobytes())

    for i in range(len(frames) - 1):
        put(frames[i])
        for m in between(t(frames[i]), t(frames[i + 1]), a.levels):
            put(m)
        print(f'pair {i + 1}/{len(frames) - 1}', flush=True)
    put(frames[-1])
    p.stdin.close(); p.wait()
    print(f'{a.out}: {n_out} frames at {fps:.2f} a second', flush=True)


if __name__ == '__main__':
    main()
