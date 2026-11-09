#!/usr/bin/env python3
"""
Depth Anything on a node's six faces laid out as one 5x3 grid (the walls in a
row, the top face above each wall and the bottom face below it, turned so that
neighbouring cells are neighbours on the cube, and the first wall again at the
end, as the stitcher's 5x3 atlas), against the same network on each face alone.

    python grid_depth_test.py SITE --names N1 ... N6 [--face-input 364]
        [--colour-suffix _orig.jpg] [--depth-suffix _measured-depth.png] [--out DIR]

SITE holds the faces and node_depth.py's measured depth (names in its order:
front, bottom, back, right, left, top). How each face is turned is found from
the cube's geometry (node_depth.DIRS), not assumed: each wall is followed by
the wall whose left edge looks where its right edge does, and the top and
bottom are turned so their edge beside a wall looks where the wall's does.
The grid is predicted at --face-input px a cell, and each face alone at the
same; walls are read from their cell, the top and bottom as the mean of their
four turned-back copies. Each face's prediction is fitted to the measured
depth as sharpen_depth.py fits (1/z = a p + b away from the outlines, sky at
0), and printed: the step across the cube's seams before any blending
(sharpen_depth.seam_steps) and the distance from the measured depth.
Needs numpy, Pillow, opencv-python, torch, transformers.
"""
import argparse
import os
import sys

import cv2
import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from node_depth import DIRS  # noqa: E402
from sharpen_depth import RATIO, fit, seam_steps  # noqa: E402

N = 640


def edge_dirs(k, side, n=33):
    """Unit directions along one edge of face k: side in 'left', 'right', 'top', 'bottom' of the picture."""
    u = np.linspace(0, 1, n)
    s, t = {'left': (0 * u, u), 'right': (1 + 0 * u, u), 'top': (u, 0 * u), 'bottom': (u, 1 + 0 * u)}[side]
    d = np.stack(DIRS[k](s, t), -1).astype(float)
    return d / np.linalg.norm(d, axis=-1, keepdims=True)


def layout():
    walls = [1]                                          # front first, then whatever is right of it
    while len(walls) < 4:
        right = edge_dirs(walls[-1], 'right')
        walls.append(min((k for k in (3, 4, 5) if k not in walls), key=lambda k: np.abs(edge_dirs(k, 'left') - right).max()))
    rots = {}
    for w in walls:
        top_edge, bot_edge = edge_dirs(w, 'top'), edge_dirs(w, 'bottom')
        rots[(6, w)] = min(range(4), key=lambda r: exact(6, r, 'bottom', top_edge))
        rots[(2, w)] = min(range(4), key=lambda r: exact(2, r, 'top', bot_edge))
    return walls, rots


def exact(k, r, side, target, n=33):
    """How far side of face k's picture, turned by r quarter turns (np.rot90), is from target, read left to right / top to bottom."""
    u = (np.arange(n) + 0.5) / n
    s, t = np.meshgrid(u, u)
    d = np.stack(DIRS[k](s, t), -1).astype(float)
    d = np.rot90(d, r)
    e = {'top': d[0], 'bottom': d[-1], 'left': d[:, 0], 'right': d[:, -1]}[side]
    e = e / np.linalg.norm(e, axis=-1, keepdims=True)
    tt = np.linspace(0, 1, n)
    want = target[np.round(tt * (len(target) - 1)).astype(int)]
    return np.abs(e - want).max()


def predict(net, proc, img_rgb, out_hw, inp_hw):
    import torch
    x = proc(images=Image.fromarray(img_rgb), return_tensors='pt', size={'height': inp_hw[0], 'width': inp_hw[1]},
             do_resize=True, keep_aspect_ratio=False)
    with torch.no_grad():
        p = net(**x.to(net.device)).predicted_depth
        p = torch.nn.functional.interpolate(p[:, None], size=out_hw, mode='bicubic', align_corners=False)
    return p[0, 0].cpu().numpy().astype(np.float64)


def fitted(p, q, sky, ray):
    g = np.hypot(*np.gradient(q))
    edge = cv2.dilate(((g > 0.15) | sky).astype(np.uint8), np.ones((25, 25), np.uint8)) > 0
    solid = ~edge
    skyc = cv2.erode(sky.astype(np.uint8), np.ones((25, 25), np.uint8)) > 0
    sel = np.zeros(q.shape, bool); sel[::3, ::3] = True
    m1, m2 = sel & solid, sel & skyc
    if m1.sum() < 100:
        return np.zeros_like(q), None
    P = np.concatenate([p[m1], p[m2]]); T = np.concatenate([(q * ray)[m1], np.zeros(m2.sum())])
    W = np.concatenate([np.ones(m1.sum()), np.full(m2.sum(), 0.2 * max(1, m1.sum()) / max(1, m2.sum()))])
    A, B = fit(P, T, W)
    qn = (A * p + B) / ray
    rel = np.abs(qn[m1] - q[m1]) / q[m1]
    return np.where(qn >= 1, qn, 0.0), rel


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('site'); ap.add_argument('--names', nargs=6, required=True)
    ap.add_argument('--face-input', type=int, default=364)
    ap.add_argument('--colour-suffix', default='_orig.jpg'); ap.add_argument('--depth-suffix', default='_measured-depth.png')
    ap.add_argument('--model', default='depth-anything/Depth-Anything-V2-Large-hf')
    ap.add_argument('--out')
    a = ap.parse_args()
    import torch
    from transformers import AutoImageProcessor, AutoModelForDepthEstimation
    proc = AutoImageProcessor.from_pretrained(a.model)
    net = AutoModelForDepthEstimation.from_pretrained(a.model).to('cuda' if torch.cuda.is_available() else 'cpu').eval()
    faces = {k: np.asarray(Image.open(os.path.join(a.site, n + a.colour_suffix)).convert('RGB').resize((N, N), Image.LANCZOS))
             for k, n in enumerate(a.names, 1)}
    walls, rots = layout()
    print('walls left to right:', walls, '; top turns', [rots[(6, w)] for w in walls], '; bottom turns', [rots[(2, w)] for w in walls])
    cols = walls + [walls[0]]
    grid = np.zeros((3 * N, 5 * N, 3), np.uint8)
    for c, w in enumerate(cols):
        grid[N:2 * N, c * N:(c + 1) * N] = faces[w]
        grid[:N, c * N:(c + 1) * N] = np.rot90(faces[6], rots[(6, w)])
        grid[2 * N:, c * N:(c + 1) * N] = np.rot90(faces[2], rots[(2, w)])
    # how well the cells meet: mean colour step across each inner cell border against inside the cells
    gl = grid.astype(float).mean(2)
    inner = np.abs(np.diff(gl, axis=1))[:, [N - 1 + c * N for c in range(4)]].mean()
    within = np.abs(np.diff(gl, axis=1)).mean()
    print(f'colour step across the wall borders {inner:.1f}, anywhere {within:.1f} (equal if the cells meet)')
    if a.out:
        os.makedirs(a.out, exist_ok=True)
        Image.fromarray(grid).resize((5 * 256, 3 * 256)).save(os.path.join(a.out, 'grid.jpg'), quality=85)
    fi = a.face_input // 14 * 14
    pg = predict(net, proc, grid, (3 * N, 5 * N), (3 * fi, 5 * fi))
    preds = {'grid': {}, 'alone': {}}
    for c, w in enumerate(walls):
        preds['grid'][w] = pg[N:2 * N, c * N:(c + 1) * N]
    for k in (6, 2):
        row = 0 if k == 6 else 2
        preds['grid'][k] = np.mean([np.rot90(pg[row * N:(row + 1) * N, c * N:(c + 1) * N], -rots[(k, w)])
                                    for c, w in enumerate(walls)], axis=0)
    for k in range(1, 7):
        preds['alone'][k] = predict(net, proc, faces[k], (N, N), (fi, fi))
    u = (np.arange(N) + 0.5) / N
    s, t = np.meshgrid(u, u)
    ray = np.sqrt(1 + (2 * s - 1) ** 2 + (1 - 2 * t) ** 2)
    print(f'face input {fi} px a cell')
    print('version'.ljust(10) + 'seams before blending: median, 90%   from the measured: median, 90%   per face median')
    for label in ('alone', 'grid'):
        qs, rels, per = {}, [], []
        for k, nm in enumerate(a.names, 1):
            d8 = np.asarray(Image.open(os.path.join(a.site, nm + a.depth_suffix)).convert('L').resize((N, N), Image.NEAREST)).astype(float)
            q = np.where(d8 > 0, 1 + (RATIO - 1) * d8 / 255, 0.0)
            qn, rel = fitted(preds[label][k], q, d8 == 0, ray)
            qs[k] = qn
            if rel is not None:
                rels.append(rel); per.append(f'{np.median(rel) * 100:.1f}')
            else:
                per.append('-')
        med, p90 = seam_steps(qs, N)
        r = np.concatenate(rels)
        print(f'{label:10s}{med:8.1f}% {p90:6.1f}%                     {np.median(r) * 100:6.1f}% {np.percentile(r, 90) * 100:6.1f}%      ' + ' '.join(per))


if __name__ == '__main__':
    main()
