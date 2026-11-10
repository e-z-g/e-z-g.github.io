#!/usr/bin/env python3
"""
The pictures in between two nodes, made by frame interpolation (FILM), for
the viewer's walk: each face's picture going from one node's view to the
other's, with no depth involved.

    python film_walk.py IMAGES SPARSE_TXT OUT_DIR NODE_A NODE_B --model film_net_fp32.pt
        [--levels 5] [--wide 1024] [--quality 92]

For each of A's six faces both nodes' panoramas are drawn as one wide picture
looking that way (--wide px, the face in the middle at its own scale, the
neighbouring faces round it, so that what moves into the face from beside it
is there to move in); the model's rotations are used, which for two nodes of
one room agree, so the two pictures differ by the step between the nodes
only. FILM (Google's Frame Interpolation for Large Motion, as TorchScript:
github.com/dajes/frame-interpolation-pytorch) makes the picture halfway
between, then halfway between each pair, --levels times: 2^levels steps.
Each in-between's middle, the face itself, is written as
OUT_DIR/MA-<A>-<k>-<i>.jpg, i = 0 .. 2^levels; picture 0 is A's own face and
the last is B's face looking the same way, not FILM's. Needs numpy,
opencv-python, Pillow, torch; view_check.py and walk_flow.py beside it.
"""
import argparse
import os
import sys

import cv2
import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from view_check import read_model  # noqa: E402
from walk_flow import wide_view  # noqa: E402


def node(images, imgs, n):
    faces = {}
    for k in range(1, 7):
        R, t = imgs[f'f{k}/MA-{n}.jpg'][:2]
        img = np.asarray(Image.open(os.path.join(images, f'f{k}', f'MA-{n}.jpg')).convert('RGB'))
        faces[k] = dict(R=R, t=t, img=img, N=img.shape[0])
    return dict(node=n, C=-faces[1]['R'].T @ faces[1]['t'], faces=faces)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('images'); ap.add_argument('sparse'); ap.add_argument('out'); ap.add_argument('a'); ap.add_argument('b')
    ap.add_argument('--model', required=True); ap.add_argument('--levels', type=int, default=5)
    ap.add_argument('--wide', type=int, default=1024); ap.add_argument('--quality', type=int, default=92)
    a = ap.parse_args()
    import torch
    dev = 'cuda' if torch.cuda.is_available() else 'cpu'
    net = torch.jit.load(a.model, map_location='cpu').to(dev).eval()
    _, imgs = read_model(a.sparse)
    A, B = node(a.images, imgs, a.a), node(a.images, imgs, a.b)
    os.makedirs(a.out, exist_ok=True)
    steps = 2 ** a.levels
    W = a.wide

    def mid(p, q):
        with torch.no_grad():
            x0 = torch.from_numpy(p).permute(2, 0, 1)[None].float().to(dev) / 255
            x1 = torch.from_numpy(q).permute(2, 0, 1)[None].float().to(dev) / 255
            y = net(x0, x1, torch.full((1, 1), 0.5, device=dev))
        return (y[0].clamp(0, 1).permute(1, 2, 0).cpu().numpy() * 255).astype(np.float32)

    for k, fc in A['faces'].items():
        N = fc['N']
        pa, _ = wide_view(A, fc['R'], W, N / 2)
        pb, _ = wide_view(B, fc['R'], W, N / 2)
        frames = {0: pa, steps: pb}
        span = steps
        while span > 1:                                  # halfway, then halfway again
            for i in range(0, steps, span):
                frames[i + span // 2] = mid(frames[i], frames[i + span])
            span //= 2
        o = (W - N) // 2
        for i in range(steps + 1):
            face = (fc['img'] if i == 0 else frames[i][o:o + N, o:o + N])
            Image.fromarray(np.clip(np.rint(face), 0, 255).astype(np.uint8)).save(
                os.path.join(a.out, f'MA-{a.a}-{k}-{i:02d}.jpg'), quality=a.quality)
        print(f'face {k}: {steps + 1} pictures', flush=True)


if __name__ == '__main__':
    main()
