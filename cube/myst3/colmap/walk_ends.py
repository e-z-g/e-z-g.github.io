#!/usr/bin/env python3
"""
The first and last frames for a walk made by a first-last-frame video model:
each node's panorama drawn as a flat picture looking along the walk.

    python walk_ends.py IMAGES SPARSE_TXT OUT_DIR NODE_A NODE_B [--size 832x480] [--fov 90] [--yaw 0] [--pitch 0]

Both pictures look the same way: level (the model's up from NODE_A's face 1
camera), facing from NODE_A towards NODE_B (turned by --yaw degrees to the
right and --pitch up), with --fov degrees across. Each pixel takes its
colour from whichever of the node's six faces looks most nearly its way.
--equirect, --grid and --cross draw the whole view instead (see their help).
Writes OUT_DIR/first.png (NODE_A) and last.png (NODE_B), and view.json (the
direction and field of view, for the viewer to turn the camera to before the
clip plays). Needs numpy, Pillow, opencv-python; view_check.py beside it.
"""
import argparse
import json
import os
import sys

import cv2
import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from view_check import read_model  # noqa: E402


def faces_of(images, imgs, node):
    out = []
    for k in range(1, 7):
        R, t = imgs[f'f{k}/MA-{node}.jpg'][:2]
        img = np.asarray(Image.open(os.path.join(images, f'f{k}', f'MA-{node}.jpg')).convert('RGB'))
        out.append((R, t, img))
    C = -out[0][0].T @ out[0][1]
    return C, out


def draw(faces, Rcam, W, H, f):
    v, u = np.mgrid[0:H, 0:W].astype(np.float64)
    dirs = np.stack([(u + .5 - W / 2) / f, (v + .5 - H / 2) / f, np.ones_like(u)], -1) @ Rcam
    out = np.zeros((H, W, 3), np.float32); best = np.full((H, W), -np.inf)
    for R, _, img in faces:
        c = dirs @ R.T
        with np.errstate(all='ignore'):
            x = c[..., 0] / c[..., 2]; y = c[..., 1] / c[..., 2]
        ok = (c[..., 2] > 0) & (np.abs(x) <= 1.001) & (np.abs(y) <= 1.001)
        score = np.where(ok, c[..., 2] / np.linalg.norm(c, axis=-1), -np.inf)
        take = score > best
        N = img.shape[0]
        mx = ((x + 1) * N / 2 - .5).astype(np.float32); my = ((y + 1) * N / 2 - .5).astype(np.float32)
        s = cv2.remap(img, np.where(ok, mx, 0), np.where(ok, my, 0), cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)
        out[take] = s[take]; best[take] = score[take]
    return np.clip(np.rint(out), 0, 255).astype(np.uint8)


def draw_equirect(faces, Rcam, W, H):
    """The whole view, equirectangular: longitude across (the camera's forward in
    the middle, right of it to the right), latitude down from straight up."""
    v, u = np.mgrid[0:H, 0:W].astype(np.float64)
    lon = ((u + .5) / W * 2 - 1) * np.pi; lat = (0.5 - (v + .5) / H) * np.pi
    cam = np.stack([np.cos(lat) * np.sin(lon), -np.sin(lat), np.cos(lat) * np.cos(lon)], -1)
    return sample_dirs(faces, cam @ Rcam)


def draw_grid(faces, W, H):
    """The six faces as grid_depth_test.py's 5x3 grid: the walls in a row (and the
    first again), the top and bottom above and below each wall, turned to meet it."""
    from grid_depth_test import layout
    walls, rots = layout()
    cw, ch = W // 5, H // 3
    imgs = {k: np.asarray(Image.fromarray(faces[k - 1][2]).resize((cw, ch), Image.LANCZOS)) for k in range(1, 7)}
    g = np.zeros((3 * ch, 5 * cw, 3), np.uint8)
    for c, w in enumerate(walls + [walls[0]]):
        g[ch:2 * ch, c * cw:(c + 1) * cw] = imgs[w]
        g[:ch, c * cw:(c + 1) * cw] = np.asarray(Image.fromarray(np.rot90(imgs[6], rots[(6, w)])).resize((cw, ch)))
        g[2 * ch:, c * cw:(c + 1) * cw] = np.asarray(Image.fromarray(np.rot90(imgs[2], rots[(2, w)])).resize((cw, ch)))
    return g


def draw_cross_floor(faces, Rcam, W, H):
    """The same cross shape with the floor at its hub: the long row is the back
    wall, the floor, the front wall (the walk's direction) and the sky; the left
    wall above the floor and the right wall below it. Every face is turned to
    meet its neighbours along the cube's own edges (camera axes x right, y down,
    z forward, x cross y = z): the floor has the walk to its right and the left
    wall at its top, so going forward the floor flows along the row."""
    right, down, fwd = Rcam
    up = -down
    cw, ch = W // 4, H // 3
    views = {(1, 0): (down, right, -fwd), (1, 1): (fwd, right, down), (1, 2): (up, right, fwd),
             (1, 3): (-fwd, right, up), (0, 1): (fwd, down, -right), (2, 1): (fwd, up, right)}
    g = np.zeros((3 * ch, 4 * cw, 3), np.uint8)
    for (r, c), axes in views.items():
        g[r * ch:(r + 1) * ch, c * cw:(c + 1) * cw] = draw(faces, np.stack(axes), cw, ch, cw / 2)
    return g


def draw_cross(faces, Rcam, W, H):
    """A cube turned to the walk (its front face looking along it), unfolded as
    the usual horizontal cross, 4x3 cells: the top above the front; left,
    front, right and back in a row; the bottom below the front. Each face is
    turned so its edges meet its neighbours' in the cross; the six cells the
    cross does not use are black."""
    right, down, fwd = Rcam
    cw, ch = W // 4, H // 3
    views = {(1, 0): (fwd, down, -right), (1, 1): (right, down, fwd), (1, 2): (-fwd, down, right),
             (1, 3): (-right, down, -fwd), (0, 1): (right, fwd, -down), (2, 1): (right, -fwd, down)}
    g = np.zeros((3 * ch, 4 * cw, 3), np.uint8)
    for (r, c), axes in views.items():
        g[r * ch:(r + 1) * ch, c * cw:(c + 1) * cw] = draw(faces, np.stack(axes), cw, ch, cw / 2)
    return g


def sample_dirs(faces, dirs):
    H, W = dirs.shape[:2]
    out = np.zeros((H, W, 3), np.float32); best = np.full((H, W), -np.inf)
    for R, _, img in faces:
        c = dirs @ R.T
        with np.errstate(all='ignore'):
            x = c[..., 0] / c[..., 2]; y = c[..., 1] / c[..., 2]
        ok = (c[..., 2] > 0) & (np.abs(x) <= 1.001) & (np.abs(y) <= 1.001)
        score = np.where(ok, c[..., 2] / np.linalg.norm(c, axis=-1), -np.inf)
        take = score > best
        N = img.shape[0]
        mx = ((x + 1) * N / 2 - .5).astype(np.float32); my = ((y + 1) * N / 2 - .5).astype(np.float32)
        smp = cv2.remap(img, np.where(ok, mx, 0), np.where(ok, my, 0), cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)
        out[take] = smp[take]; best[take] = score[take]
    return np.clip(np.rint(out), 0, 255).astype(np.uint8)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('images'); ap.add_argument('sparse'); ap.add_argument('out'); ap.add_argument('a'); ap.add_argument('b')
    ap.add_argument('--size', default='832x480'); ap.add_argument('--fov', type=float, default=90.0)
    ap.add_argument('--yaw', type=float, default=0.0); ap.add_argument('--pitch', type=float, default=0.0)
    ap.add_argument('--equirect', action='store_true',
                    help='the whole view instead, equirectangular (--size 2:1), the walk straight ahead in the middle')
    ap.add_argument('--grid', action='store_true',
                    help="the six faces instead, as grid_depth_test.py's 5x3 grid (--size 5:3), the model's own face cameras")
    ap.add_argument('--cross', action='store_true',
                    help='the six faces of a cube turned to the walk, once each, as a 4x3 cross with the rest black (--size 4:3)')
    ap.add_argument('--cross-floor', action='store_true',
                    help='as --cross with the floor at the hub: back wall, floor, front wall, sky in the long row')
    a = ap.parse_args()
    W, H = (int(x) for x in a.size.split('x'))
    _, imgs = read_model(a.sparse)
    CA, FA = faces_of(a.images, imgs, a.a)
    CB, FB = faces_of(a.images, imgs, a.b)
    up = -FA[0][0][1]                                        # minus the y axis of face 1's camera
    fwd = CB - CA; fwd -= up * (fwd @ up); fwd /= np.linalg.norm(fwd)
    yaw, pitch = np.radians(a.yaw), np.radians(a.pitch)
    right = np.cross(fwd, up); right /= np.linalg.norm(right)
    fwd = np.cos(yaw) * fwd + np.sin(yaw) * right
    right = np.cross(fwd, up); right /= np.linalg.norm(right)
    fwd = np.cos(pitch) * fwd + np.sin(pitch) * up
    down = np.cross(fwd, right); down /= np.linalg.norm(down)
    Rcam = np.stack([right, down, fwd])                     # world -> camera rows: x right, y down, z forward
    f = W / 2 / np.tan(np.radians(a.fov) / 2)
    os.makedirs(a.out, exist_ok=True)
    if a.equirect:
        render = lambda F: draw_equirect(F, Rcam, W, H)
    elif a.cross_floor:
        render = lambda F: draw_cross_floor(F, Rcam, W, H)
    elif a.cross:
        render = lambda F: draw_cross(F, Rcam, W, H)
    elif a.grid:
        render = lambda F: draw_grid(F, W, H)
    else:
        render = lambda F: draw(F, Rcam, W, H, f)
    Image.fromarray(render(FA)).save(os.path.join(a.out, 'first.png'))
    Image.fromarray(render(FB)).save(os.path.join(a.out, 'last.png'))
    # the direction in the nodes' own frame (node_depth.py's: face 1 looking along -z, y up), for the viewer
    M = FA[0][0].T @ np.diag([1.0, -1.0, -1.0])             # node frame -> model frame (walk_scene.py's)
    look = M.T @ fwd
    with open(os.path.join(a.out, 'view.json'), 'w') as fh:
        json.dump({'from': a.a, 'to': a.b, 'look_node_frame': look.tolist(), 'hfov': a.fov, 'size': [W, H],
                   'apart': float(np.linalg.norm(CB - CA))}, fh, indent=1)
    print(f'{a.a} -> {a.b}: {np.linalg.norm(CB - CA):.3f} apart; looking {np.round(look, 3)} in the nodes\' frame; {W}x{H}, {a.fov} deg')


if __name__ == '__main__':
    main()
