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
the last is B's face looking the same way, not FILM's.

With --video the walk is written as a video instead: the six faces as one 3x2
picture a frame, --fps frames over --seconds timed by the viewer's ease
(smoothstep), each the nearest of the 2^levels steps (use --levels 8 at 60
frames a second, or near things moving fast step visibly), and a reversed
copy for walking back. Mixing one picture into the next, as the viewer first
did with 33 pictures a face, drew MASS 84's near rails twice a few pixels
apart (they move about 6 px a step): a video frame is one picture. Needs
numpy, opencv-python, Pillow, torch (and ffmpeg for --video); view_check.py
and walk_flow.py beside it.
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
    ap.add_argument('--video', help='write the walk as this .mp4 (and <name>-back.mp4 reversed) instead of the pictures')
    ap.add_argument('--fps', type=float, default=60); ap.add_argument('--seconds', type=float, default=3.5)
    ap.add_argument('--border', type=int, default=8); ap.add_argument('--crf', type=int, default=16)
    ap.add_argument('--ffmpeg', default='ffmpeg')
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

    o = None
    crops = {}
    for k, fc in A['faces'].items():
        N = fc['N']
        o = (W - N) // 2
        pa, _ = wide_view(A, fc['R'], W, N / 2)
        pb, _ = wide_view(B, fc['R'], W, N / 2)
        face = {0: fc['img'], steps: np.clip(np.rint(pb[o:o + N, o:o + N]), 0, 255).astype(np.uint8)}

        def fill(i, j, p, q):                           # depth first: only the pictures on the way down are kept
            if j - i < 2:
                return
            m = (i + j) // 2
            r = mid(p, q)
            face[m] = np.clip(np.rint(r[o:o + N, o:o + N]), 0, 255).astype(np.uint8)
            fill(i, m, p, r); fill(m, j, r, q)
        fill(0, steps, pa, pb)
        crops[k] = face
        if not a.video:
            for i in range(steps + 1):
                Image.fromarray(face[i]).save(os.path.join(a.out, f'MA-{a.a}-{k}-{i:02d}.jpg'), quality=a.quality)
        print(f'face {k}: {steps + 1} pictures', flush=True)
    if a.video:
        write_video(a, crops, steps)


def write_video(a, crops, steps):
    """The six faces as one 3x2 picture a frame (each face in a cell --border px
    wider, its edges repeated, so filtering at a face's edge never reads the
    next), --fps frames over --seconds, timed by the walk's ease (smoothstep):
    the frame at u of the way shows the step nearest smoothstep(u). Written as
    frames, then H.264 forward and reversed (for walking back)."""
    import subprocess
    N = crops[1][0].shape[0]; b = a.border; C = N + 2 * b
    fdir = os.path.join(a.out, 'atlas_frames'); os.makedirs(fdir, exist_ok=True)
    F = int(round(a.fps * a.seconds)) + 1
    for n in range(F):
        u = n / (F - 1); t = u * u * (3 - 2 * u)
        i = int(round(t * steps))
        atlas = np.zeros((2 * C, 3 * C, 3), np.uint8)
        for k in range(1, 7):
            col, row = (k - 1) % 3, (k - 1) // 3
            atlas[row * C:(row + 1) * C, col * C:(col + 1) * C] = cv2.copyMakeBorder(crops[k][i], b, b, b, b, cv2.BORDER_REPLICATE)
        Image.fromarray(atlas).save(os.path.join(fdir, f'{n:04d}.png'))
    for name, vf in ((a.video, 'null'), (os.path.splitext(a.video)[0] + '-back.mp4', 'reverse')):
        subprocess.run([a.ffmpeg, '-v', 'error', '-y', '-framerate', str(a.fps), '-i', os.path.join(fdir, '%04d.png'),
                        '-vf', vf, '-c:v', 'libx264', '-preset', 'slow', '-crf', str(a.crf), '-pix_fmt', 'yuv420p',
                        '-g', str(F), '-movflags', '+faststart', name], check=True)
        print(name, f'{os.path.getsize(name) / 1e6:.1f} MB', flush=True)
    print(f'{F} frames of {3 * C}x{2 * C}; faces in cells of {C} px, {b} px of repeated edge round each')


if __name__ == '__main__':
    main()
