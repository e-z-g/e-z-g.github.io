#!/usr/bin/env python3
"""
A walk from one node to another, rendered from the two nodes' panoramas and
depths: what a transition between nodes could look like.

    python walk_render.py IMAGES SPARSE_TXT OUT_DIR
        --from 4084 DEPTH_DIR SUFFIX R_FAR_JSON --to 4089 DEPTH_DIR SUFFIX R_FAR_JSON
        [--frames 48] [--size 640x360] [--fov 90] [--scale 1] [--names-from N1..N6] [--names-to N1..N6]

IMAGES holds the nodes' faces (f<k>/MA-<node>.jpg), SPARSE_TXT a text model
with their poses. Each node's depth is DEPTH_DIR/<name>SUFFIX in node_depth.py's
encoding (r_far from R_FAR_JSON; --scale times it is the model's units); names
default to MA-<node>-1 ... 6. The eye moves in a straight line from the first
node's centre to the second's, level, facing the way it goes, over --frames
frames. Each frame, both nodes' faces are moved by their depth to the eye
(view_check.splat: nearest point wins, each point its own footprint), and
the two pictures blended by how far along the eye is (each point drawn
--grow times its footprint); where only one covers a
pixel it is used alone, and where neither does, the nearer node's faces at
infinity (the sky, and what neither saw). Writes OUT_DIR/frame-NNN.png; with
ffmpeg on the path, OUT_DIR/walk.mp4 too (there and back).
Needs numpy, Pillow; view_check.py beside it.
"""
import argparse
import json
import os
import subprocess
import sys

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from view_check import read_model, splat  # noqa: E402

RATIO = 20.0


def node_points(images, imgs, node, names, ddir, suffix, r_far, scale, infinity=False):
    own = {k: f'f{k}/MA-{node}.jpg' for k in range(1, 7)}
    C = -imgs[own[1]][0].T @ imgs[own[1]][1]
    P, cols = [], []
    for k, nm in enumerate(names, 1):
        img = np.asarray(Image.open(os.path.join(images, own[k])).convert('RGB'), np.float32)
        N = img.shape[0]
        u = (np.arange(N) + .5) / N * 2 - 1
        xx, yy = np.meshgrid(u, u)
        d = np.stack([xx, yy, np.ones_like(xx)], -1).reshape(-1, 3) @ imgs[own[k]][0]
        d /= np.linalg.norm(d, axis=1, keepdims=True)
        if infinity:
            r = np.full(N * N, 1e4)
        else:
            d8 = np.asarray(Image.open(os.path.join(ddir, nm + suffix)).convert('L').resize((N, N), Image.NEAREST)).astype(float).ravel()
            r = np.where(d8 > 0, r_far / (1 + (RATIO - 1) * d8 / 255) * scale, np.nan)
        ok = np.isfinite(r)
        P.append(C + d[ok] * r[ok, None]); cols.append(img.reshape(-1, 3)[ok])
    return C, np.concatenate(P), np.concatenate(cols), N


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('images'); ap.add_argument('sparse'); ap.add_argument('out')
    ap.add_argument('--from', dest='a', nargs=4, required=True, metavar=('NODE', 'DIR', 'SUFFIX', 'JSON'))
    ap.add_argument('--to', dest='b', nargs=4, required=True, metavar=('NODE', 'DIR', 'SUFFIX', 'JSON'))
    ap.add_argument('--frames', type=int, default=48); ap.add_argument('--size', default='640x360')
    ap.add_argument('--fov', type=float, default=90.0); ap.add_argument('--scale', type=float, default=1.0)
    ap.add_argument('--grow', type=float, default=1.8,
                    help="each point drawn this much larger than its footprint: toward a view's edges the faces are "
                         'seen at a slant and the footprint alone left a grid of gaps the sky showed through')
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    cams, imgs = read_model(a.sparse)
    W, H = (int(v) for v in a.size.split('x'))
    f = W / 2 / np.tan(np.radians(a.fov) / 2)
    cam = (W, H, f, f, W / 2, H / 2)
    sides = []
    for node, ddir, suffix, js in (a.a, a.b):
        names = [f'MA-{node}-{k}' for k in range(1, 7)]
        r_far = json.load(open(js))['r_far']
        C, P, cols, N = node_points(a.images, imgs, node, names, ddir, suffix, r_far, a.scale)
        _, Pi, ci, _ = node_points(a.images, imgs, node, names, None, None, None, a.scale, infinity=True)
        sides.append((C, P, cols, Pi, ci, N))
    CA, CB = sides[0][0], sides[1][0]
    # the model's up: minus the y axis of the nodes' face 1 camera (y points down in a COLMAP image)
    up = -imgs[f'f1/MA-{a.a[0]}.jpg'][0][1]
    fwd = CB - CA; fwd -= up * (fwd @ up); fwd /= np.linalg.norm(fwd)
    right = np.cross(fwd, up); right /= np.linalg.norm(right)
    R = np.stack([right, -up, fwd])            # world -> camera rows: x right, y down, z forward
    print(f'from {a.a[0]} to {a.b[0]}: {np.linalg.norm(CB - CA):.3f} apart; {a.frames} frames {W}x{H}, {a.fov} deg', flush=True)
    for i in range(a.frames):
        t = i / (a.frames - 1)
        E = CA + t * (CB - CA)
        tt = -R @ E
        pics = []
        for (C, P, cols, Pi, ci, N) in sides:
            img, cov = splat(P, cols, R, tt, cam, N / 2, grow=a.grow)
            pics.append((img, cov))
        (ia, ca), (ib, cb) = pics
        w = t
        out = np.zeros((H, W, 3), np.float32)
        both = ca & cb
        out[both] = (1 - w) * ia[both] + w * ib[both]
        out[ca & ~cb] = ia[ca & ~cb]; out[cb & ~ca] = ib[cb & ~ca]
        hole = ~(ca | cb)
        if hole.any():
            C, P, cols, Pi, ci, N = sides[0] if t < 0.5 else sides[1]
            sky, scov = splat(Pi, ci, R, tt, cam, N / 2, grow=a.grow)
            out[hole] = sky[hole]
            hole &= ~scov
        if hole.any():                                   # pinholes neither side nor the sky reached
            import cv2
            out = cv2.inpaint(np.clip(out, 0, 255).astype(np.uint8), hole.astype(np.uint8), 3, cv2.INPAINT_TELEA).astype(np.float32)
        Image.fromarray(np.clip(out, 0, 255).astype(np.uint8)).save(os.path.join(a.out, f'frame-{i:03d}.png'))
        print(f'{i + 1}/{a.frames}', end='\r', flush=True)
    print()
    try:
        n = a.frames
        for j in range(n):                                    # back again
            src = os.path.join(a.out, f'frame-{n - 1 - j:03d}.png')
            Image.open(src).save(os.path.join(a.out, f'frame-{n + j:03d}.png'))
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-framerate', '24', '-i', os.path.join(a.out, 'frame-%03d.png'),
                        '-pix_fmt', 'yuv420p', '-vf', 'scale=trunc(iw/2)*2:trunc(ih/2)*2', os.path.join(a.out, 'walk.mp4')], check=True)
        print('walk.mp4 written')
    except (OSError, subprocess.CalledProcessError) as e:
        print(f'no video: {e}')


if __name__ == '__main__':
    main()
