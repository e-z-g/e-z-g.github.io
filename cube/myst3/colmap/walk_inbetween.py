#!/usr/bin/env python3
"""
Frames drawn between a walk's frames from the motion between them, so that a short walk (22 frames, under a second at
24 a second) plays longer and smoother. The first and last frames stay the node pictures.

    python walk_inbetween.py IN.mp4 OUT.mp4 [--n 3] [--wide 1280]

For each pair of frames, DIS optical flow is measured both ways at --wide pixels across (then scaled up), and each of
the --n frames between is both neighbours warped part of the way and mixed by nearness in time. Writes 24 a second,
H.264, CRF 16. Needs numpy, opencv-python, ffmpeg.
"""
import argparse
import subprocess

import cv2
import numpy as np


def frames(path):
    p = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v', '-show_entries', 'stream=width,height',
                        '-of', 'csv=p=0', path], capture_output=True, text=True, check=True)
    W, H = map(int, p.stdout.strip().split(','))
    raw = subprocess.run(['ffmpeg', '-v', 'error', '-i', path, '-f', 'rawvideo', '-pix_fmt', 'bgr24', '-'],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(-1, H, W, 3)


def flow(a, b, wide, dis):
    H, W = a.shape[:2]
    s = wide / W
    g = lambda x: cv2.cvtColor(cv2.resize(x, (wide, round(H * s)), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY)
    f = dis.calc(g(a), g(b), None)
    return cv2.resize(f, (W, H), interpolation=cv2.INTER_LINEAR) / s


def warp(img, f, t):
    # IMG moved by T of the flow F measured from IMG: sample IMG at x - t f(x) (a backward approximation)
    H, W = img.shape[:2]
    x, y = np.meshgrid(np.arange(W, dtype=np.float32), np.arange(H, dtype=np.float32))
    return cv2.remap(img, x - t * f[..., 0], y - t * f[..., 1], cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('src'); ap.add_argument('out')
    ap.add_argument('--n', type=int, default=3); ap.add_argument('--wide', type=int, default=1280)
    a = ap.parse_args()
    F = frames(a.src)
    H, W = F.shape[1:3]
    dis = cv2.DISOpticalFlow_create(cv2.DISOPTICAL_FLOW_PRESET_MEDIUM)
    enc = subprocess.Popen(['ffmpeg', '-v', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'bgr24', '-s', f'{W}x{H}',
                            '-r', '24', '-i', '-', '-c:v', 'libx264', '-crf', '16', '-preset', 'slow',
                            '-pix_fmt', 'yuv420p', '-movflags', '+faststart', a.out], stdin=subprocess.PIPE)
    for i in range(len(F) - 1):
        A, B = F[i], F[i + 1]
        enc.stdin.write(A.tobytes())
        fab, fba = flow(A, B, a.wide, dis), flow(B, A, a.wide, dis)
        for k in range(1, a.n + 1):
            t = k / (a.n + 1)
            # the flow at the in-between point is taken as the start's flow there (small steps)
            m = (1 - t) * warp(A.astype(np.float32), fab, t) + t * warp(B.astype(np.float32), fba, 1 - t)
            enc.stdin.write(np.clip(m + .5, 0, 255).astype(np.uint8).tobytes())
    enc.stdin.write(F[-1].tobytes())
    enc.stdin.close(); enc.wait()
    print(f'{a.src}: {len(F)} frames -> {a.out}: {(len(F) - 1) * (a.n + 1) + 1} frames')


if __name__ == '__main__':
    main()
