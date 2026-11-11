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


HUB_AXES = {   # the hub's camera axes (x right, y down, z forward in the picture), in the walk's right, down, forward
    'front': lambda r, d, f: (r, d, f), 'floor': lambda r, d, f: (f, r, d), 'right': lambda r, d, f: (-f, d, r),
    'left': lambda r, d, f: (f, d, -r), 'back': lambda r, d, f: (-r, d, -f), 'sky': lambda r, d, f: (r, f, -d)}


def cross_layout(Rcam, hub):
    """A cube unfolded as the 4x3 cross with `hub` at row 1, column 1: the long row is the face left of it, the
    hub, the face right of it and the hub's opposite; one face above the hub and one below. Each cell is a
    camera (x right, y down, z forward, x cross y = z), turned so it meets its neighbours along the cube's own
    edges. Returns [(name, (row, col), (x, y, z))] with the axes in the model's frame."""
    right, down, fwd = Rcam
    x, y, z = (np.asarray(v, float) for v in HUB_AXES[hub](right, down, fwd))
    cells = {(1, 1): (x, y, z), (1, 2): (-z, y, x), (1, 0): (z, y, -x), (0, 1): (x, z, -y), (2, 1): (x, -z, y),
             (1, 3): (-x, y, -z)}
    name = lambda v: min({'front': fwd, 'back': -fwd, 'right': right, 'left': -right, 'floor': down, 'sky': -down}.items(),
                         key=lambda kv: np.linalg.norm(kv[1] - v))[0]
    return [(name(ax[2]), rc, ax) for rc, ax in cells.items()]


# Other nets: rows, columns, the cells used, the first cell and its camera axes (in the walk's right, down,
# forward); every other cell is reached across a shared side and turned to meet it along the cube's edge.
NETS = {
    # two strips of three, the second hanging below the end of the first: left wall, sky, right wall;
    # then front wall, floor, back wall. The right wall meets the sky and the front wall in the picture.
    'staircase': (2, 5, [(0, 0), (0, 1), (0, 2), (1, 2), (1, 3), (1, 4)], (0, 1), lambda r, d, f: (r, f, -d)),
}
# Copies in a net's empty cells: (cell, the used or earlier-filled cell it continues). Each copy is the face
# that truly lies beyond that neighbour's edge, turned to meet it, so edges the net leaves apart also appear
# joined somewhere in the picture; its other sides may border cells it is not next to on the cube ("false").
FILLS = {
    # floor' beyond the right wall, left' beyond floor'; sky' beyond the front wall, back' beyond sky'
    ('staircase', 'skycopy'): [((0, 3), (0, 2)), ((0, 4), (0, 3)), ((1, 1), (1, 2)), ((1, 0), (1, 1))],
    # the sky once: floor' and left' as above; front' below the left wall and below the sky. 9 of 12 edges
    # joined somewhere, as many as any fill with the sky once; the three left apart are all the back wall's
    ('staircase', 'skyonce'): [((0, 3), (0, 2)), ((0, 4), (0, 3)), ((1, 0), (0, 0)), ((1, 1), (0, 1))],
}
STEP = {(0, 1): lambda x, y, z: (-z, y, x), (0, -1): lambda x, y, z: (z, y, -x),
        (-1, 0): lambda x, y, z: (x, z, -y), (1, 0): lambda x, y, z: (x, -z, y)}


def fill_layout(Rcam, net, fill='skycopy'):
    """The copies for a net's empty cells, and the picture edges between cells that do not truly meet."""
    rows, cols, cells = net_layout(Rcam, net)
    ax = {rc: a for _, rc, a in cells}
    copies = []
    for cell, parent in FILLS.get((net, fill), []):
        ax[cell] = STEP[(cell[0] - parent[0], cell[1] - parent[1])](*ax[parent])
        copies.append(cell)
    false = []
    for (r, c), a in ax.items():
        for dr, dc in ((0, 1), (1, 0)):
            n = (r + dr, c + dc)
            if n in ax and not np.allclose(np.stack(STEP[(dr, dc)](*a)), np.stack(ax[n])):
                false.append(((r, c), n))
    right, down, fwd = Rcam
    name = lambda v: min({'front': fwd, 'back': -fwd, 'right': right, 'left': -right, 'floor': down, 'sky': -down}.items(),
                         key=lambda kv: np.linalg.norm(kv[1] - v))[0]
    return [(name(ax[rc][2]), rc, ax[rc]) for rc in copies], false


# Not nets: rows of faces joined only within each row, the rows touching in the picture but not on the cube
# (a 2x3 rectangle cannot fold into a cube). Each row: its cells and one cell's axes; --gap px of black between rows.
STRIPS = {
    # left wall, sky, right wall above front wall, floor, back wall: each row as the staircase's
    'strips3x2': (2, 3, [([(0, 0), (0, 1), (0, 2)], (0, 1), lambda r, d, f: (r, f, -d)),
                         ([(1, 0), (1, 1), (1, 2)], (1, 0), lambda r, d, f: (d, -r, f))]),
}


def net_layout(Rcam, net):
    right, down, fwd = Rcam
    if net in STRIPS:
        rows, cols, groups = STRIPS[net]
        ax = {}
        for used, first, axes0 in groups:
            ax.update(_spread(used, first, tuple(np.asarray(v, float) for v in axes0(right, down, fwd))))
    else:
        rows, cols, used, first, axes0 = NETS[net]
        ax = _spread(used, first, tuple(np.asarray(v, float) for v in axes0(right, down, fwd)))
    name = lambda v: min({'front': fwd, 'back': -fwd, 'right': right, 'left': -right, 'floor': down, 'sky': -down}.items(),
                         key=lambda kv: np.linalg.norm(kv[1] - v))[0]
    return rows, cols, [(name(a[2]), rc, a) for rc, a in ax.items()]


def _spread(used, first, axes):
    ax = {first: axes}
    todo = [first]
    while todo:
        rc = todo.pop(); x, y, z = ax[rc]
        for (dr, dc), new in (((0, 1), (-z, y, x)), ((0, -1), (z, y, -x)), ((-1, 0), (x, z, -y)), ((1, 0), (x, -z, y))):
            n = (rc[0] + dr, rc[1] + dc)
            if n in used and n not in ax:
                ax[n] = new; todo.append(n)
    return ax


def cell_rects(W, H, rows, cols, gap):
    """Each cell's x, y, width and height in pixels: square cells across the width, gap px between rows."""
    cw = W // cols
    ch = (H - gap * (rows - 1)) // rows
    return {(r, c): (c * cw, r * (ch + gap), cw, ch) for r in range(rows) for c in range(cols)}


def draw_net(faces, Rcam, W, H, net, gap=0, fill=None, line=0):
    rows, cols, cells = net_layout(Rcam, net)
    R = cell_rects(W, H, rows, cols, gap)
    g = np.zeros((H, W, 3), np.uint8)
    copies, false = fill_layout(Rcam, net, fill) if fill else ([], [])
    for _, rc, axes in cells + copies:
        x, y, cw, ch = R[rc]
        g[y:y + ch, x:x + cw] = draw(faces, np.stack(axes), cw, ch, cw / 2)
    # A black line along each false join, wholly inside the copy's cell: the originals are what the viewer and
    # cube_edges.py read, and a line centred on the join put 2 px of black inside three of them, which the
    # score read as perfectly steady edges.
    copy_cells = {rc for _, rc, _ in copies}
    for a, b in false if line else []:            # a is left of or above b
        horiz = b[0] == a[0]
        inside = b if b in copy_cells else a
        if inside not in copy_cells:
            continue                              # no copy either side: leave both originals clean
        x, y, cw, ch = R[inside]
        if horiz:
            g[y:y + ch, (x if inside == b else x + cw - line):(x + line if inside == b else x + cw)] = 0
        else:
            g[(y if inside == b else y + ch - line):(y + line if inside == b else y + ch), x:x + cw] = 0
    return g


def draw_cross_hub(faces, Rcam, W, H, hub):
    cw, ch = W // 4, H // 3
    g = np.zeros((3 * ch, 4 * cw, 3), np.uint8)
    for _, (r, c), axes in cross_layout(Rcam, hub):
        g[r * ch:(r + 1) * ch, c * cw:(c + 1) * cw] = draw(faces, np.stack(axes), cw, ch, cw / 2)
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


def fisheye_eyes(Rcam):
    """Two eyes for --dual-fisheye: looking ahead (up the picture's up) and behind (likewise level, so the
    world's left is on its right). Axes (x right, y down, z forward) in the model's frame."""
    right, down, fwd = Rcam
    return [np.stack([right, down, fwd]), np.stack([-right, down, -fwd])]


def draw_dual_fisheye(faces, Rcam, W, H, fov):
    """Two circular equidistant fisheyes side by side, each H across and fov degrees wide (over 180 they
    overlap at the rim): the walk's way ahead on the left, behind on the right; black outside the circles.
    Ahead, the ground runs from the horizon down into the circle's lower part in one picture, where a cube
    turns it 90 degrees across an edge."""
    S = H
    v, u = np.mgrid[0:S, 0:S].astype(np.float64)
    x = (u + .5) / S * 2 - 1; y = (v + .5) / S * 2 - 1
    r = np.sqrt(x * x + y * y); th = r * np.radians(fov) / 2; ph = np.arctan2(y, x)
    cam = np.stack([np.sin(th) * np.cos(ph), np.sin(th) * np.sin(ph), np.cos(th)], -1)
    g = np.zeros((H, W, 3), np.uint8)
    for i, E in enumerate(fisheye_eyes(Rcam)):
        img = sample_dirs(faces, cam @ E)
        img[r > 1] = 0
        g[:, i * S:(i + 1) * S] = img
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
    ap.add_argument('--cross-hub', choices=sorted(HUB_AXES),
                    help='the cross with this face at its hub (all four of its edges joined in the picture); writes layout.json')
    ap.add_argument('--dual-fisheye', type=float, nargs='?', const=190.0,
                    help='two circular fisheyes of this many degrees (190), ahead and behind, side by side (--size 2:1)')
    ap.add_argument('--net', choices=sorted(NETS) + sorted(STRIPS), help='another cube net (NETS) or rows of faces (STRIPS); writes layout.json')
    ap.add_argument('--gap', type=int, default=0, help='px of black between rows (with --net)')
    ap.add_argument('--fill', nargs='?', const='skycopy', help="the net's empty cells filled with copies (FILLS: skycopy, skyonce)")
    ap.add_argument('--false-line', type=int, default=0, help='px of black along joins between cells that do not truly meet (with --fill)')
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
    elif a.dual_fisheye:
        render = lambda F: draw_dual_fisheye(F, Rcam, W, H, a.dual_fisheye)
    elif a.net:
        render = lambda F: draw_net(F, Rcam, W, H, a.net, a.gap, a.fill, a.false_line)
    elif a.cross_hub:
        render = lambda F: draw_cross_hub(F, Rcam, W, H, a.cross_hub)
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
    if a.dual_fisheye:
        json.dump({'net': 'dual-fisheye', 'fov': a.dual_fisheye, 'size': [W, H],
                   'eyes': [{'rect': [i * H, 0, H, H], 'axes': [[round(float(v), 6) for v in Rcam @ ax] for ax in E]}
                            for i, E in enumerate(fisheye_eyes(Rcam))]},
                  open(os.path.join(a.out, 'layout.json'), 'w'), indent=1)
    if a.cross_hub or a.net:
        # each cell's face and axes in the walk's own frame (right, down, forward), for cube_edges.py and the viewer
        B = Rcam
        rows, cols, cells = (3, 4, cross_layout(Rcam, a.cross_hub)) if a.cross_hub else net_layout(Rcam, a.net)
        R = cell_rects(W, H, rows, cols, a.gap if a.net else 0)
        json.dump({'net': a.net or 'cross', 'hub': a.cross_hub, 'rows': rows, 'cols': cols, 'size': [W, H],
                   'joined_rows_only': bool(a.net in STRIPS), 'filled': a.fill,
                   'cells': [{'face': n, 'row': rc[0], 'col': rc[1], 'rect': list(R[rc]),
                              'axes': [[round(float(v), 6) for v in B @ ax] for ax in axes]} for n, rc, axes in cells]},
                  open(os.path.join(a.out, 'layout.json'), 'w'), indent=1)
    with open(os.path.join(a.out, 'view.json'), 'w') as fh:
        json.dump({'from': a.a, 'to': a.b, 'look_node_frame': look.tolist(), 'hfov': a.fov, 'size': [W, H],
                   'apart': float(np.linalg.norm(CB - CA))}, fh, indent=1)
    print(f'{a.a} -> {a.b}: {np.linalg.norm(CB - CA):.3f} apart; looking {np.round(look, 3)} in the nodes\' frame; {W}x{H}, {a.fov} deg')


if __name__ == '__main__':
    main()
