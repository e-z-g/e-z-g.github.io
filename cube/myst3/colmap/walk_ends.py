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
from view_check import read_model, splat  # noqa: E402


PREFIX = 'MA'                    # the faces' file prefix (--prefix): MA Amateria, LE J'nanin


def faces_of(images, imgs, node):
    out = []
    for k in range(1, 7):
        R, t = imgs[f'f{k}/{PREFIX}-{node}.jpg'][:2]
        img = np.asarray(Image.open(os.path.join(images, f'f{k}', f'{PREFIX}-{node}.jpg')).convert('RGB'))
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


def draw_polar_equirect(faces, Rcam, W, H, pad=20.0):
    """The whole view, equirectangular with its poles straight ahead (top edge) and straight behind (bottom edge):
    down the picture the angle from straight ahead (0 to 180 degrees), across it the turn round the line of travel
    (straight up in the middle, right of it to the right), 360 degrees and --polar's PAD more at each side repeated,
    so the join, straight down, is drawn twice. Moving forward, everything slides down the picture."""
    v, u = np.mgrid[0:H, 0:W].astype(np.float64)
    th = (v + .5) / H * np.pi
    ph = ((u + .5) / W * 2 - 1) * (np.pi + np.radians(pad))
    cam = np.stack([np.sin(th) * np.sin(ph), -np.sin(th) * np.cos(ph), np.cos(th)], -1)
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


def fisheye_eyes(Rcam, yaw=0.0, pitch=0.0):
    """Two eyes for --dual-fisheye: looking ahead (up the picture's up) and behind (likewise level, so the
    world's left is on its right), both turned yaw degrees to the right so the seam between them (the ring
    90 degrees from both) misses what matters. Axes (x right, y down, z forward) in the model's frame."""
    right, down, fwd = Rcam
    a = np.radians(yaw)
    f = np.cos(a) * fwd + np.sin(a) * right; r = np.cos(a) * right - np.sin(a) * fwd
    # tilted pitch degrees up (-90: straight down, the way ahead at the top of the picture)
    p = np.radians(pitch)
    f, d = np.cos(p) * f - np.sin(p) * down, np.sin(p) * f + np.cos(p) * down
    return [np.stack([r, d, f]), np.stack([-r, d, -f])]


def horizon_r(th):
    """The horizon-weighted fisheye (360 degrees): r = (theta - sin(2 theta) / 4) / pi, so the pixels per radian
    out from the centre run (1 - cos(2 theta) / 2) / pi of the radius: three times as many at the horizon (90 degrees
    off the centre) as at the centre or the rim."""
    return (th - np.sin(2 * th) / 4) / np.pi


def draw_single_fisheye(faces, Rcam, W, H, fov=360.0, yaw=0.0, pitch=0.0, projection='equidistant', axes=None):
    """The whole view as one circular equidistant fisheye, fov degrees across (360: everything; straight behind
    is the whole rim): ahead at the centre, so nothing is split between pictures. Square, H across. projection
    'equal-area': r = sin(theta / 2) / sin(fov / 4), every solid angle the same share of the circle; 'horizon'
    (360 only): horizon_r, the pixels drawn toward the ring 90 degrees off the centre."""
    S = H
    v, u = np.mgrid[0:S, 0:S].astype(np.float64)
    x = (u + .5) / S * 2 - 1; y = (v + .5) / S * 2 - 1
    r = np.sqrt(x * x + y * y); ph = np.arctan2(y, x)
    if projection == 'equal-area':
        th = 2 * np.arcsin(np.clip(r * np.sin(np.radians(fov) / 4), -1, 1))
    elif projection == 'horizon':
        grid = np.linspace(0, np.pi, 4097)
        th = np.interp(r, horizon_r(grid), grid)        # r rises with theta, so the table inverts it
    else:
        th = r * np.radians(fov) / 2
    cam = np.stack([np.sin(th) * np.cos(ph), np.sin(th) * np.sin(ph), np.cos(th)], -1)
    img = sample_dirs(faces, cam @ (fisheye_eyes(Rcam, yaw, pitch)[0] if axes is None else axes))
    img[r > 1] = 0
    g = np.zeros((H, W, 3), np.uint8); g[:, :S] = img
    return g


def weak_spot(faces, Rcam, cap=40.0, n=2000):
    """The direction with the least detail around it (the mean gradient within cap degrees, weighted toward the
    middle): where a single fisheye's one bad point (the rim, straight behind its centre) costs least. In the walk's
    axes (x right, y down, z forward)."""
    grad = []
    for R, t, img in faces:
        g = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY).astype(np.float32)
        m = np.hypot(cv2.Sobel(g, cv2.CV_32F, 1, 0), cv2.Sobel(g, cv2.CV_32F, 0, 1))
        m = cv2.GaussianBlur(m, (0, 0), 3)
        grad.append((R, t, np.repeat(np.clip(m / 4, 0, 255).astype(np.uint8)[..., None], 3, 2)))
    k = np.arange(n) + .5
    th, ph = np.arccos(1 - 2 * k / n), np.pi * (1 + 5 ** .5) * k
    D = np.stack([np.sin(th) * np.cos(ph), np.sin(th) * np.sin(ph), np.cos(th)], 1)      # walk axes
    d = sample_dirs(grad, (D @ Rcam)[None])[0, :, 0].astype(np.float64)
    c = D @ D.T
    w = np.clip((c - np.cos(np.radians(cap))) / (1 - np.cos(np.radians(cap))), 0, None)
    score = (w @ d) / w.sum(1)
    return D[np.argmin(score)], float(score.min()), float(np.median(score))


def aim_of(weak):
    """--eye-yaw and --eye-pitch that put a single fisheye's centre straight away from weak (its rim on it)."""
    c = -weak
    return float(np.degrees(np.arctan2(c[0], c[2]))), float(np.degrees(np.arcsin(np.clip(-c[1], -1, 1))))


def turned_eye(E0, c1):
    """The eye E0 (rows x, y, z in the model's frame) turned the shortest way to look along c1: the last end's eye
    for aimed ends, so the two differ by the least turn and no spin about the centre (aiming each end by yaw and
    pitch alone spun MACA 1 to 2's last picture half round, a 174 degree turn that H3 made as a dissolve)."""
    a = E0[2]; b = c1 / np.linalg.norm(c1)
    v = np.cross(a, b); s_, c_ = np.linalg.norm(v), float(a @ b)
    if s_ < 1e-9:
        return E0.copy()
    k = v / s_; K = np.array([[0, -k[2], k[1]], [k[2], 0, -k[0]], [-k[1], k[0], 0]])
    R = np.eye(3) + s_ * K + (1 - c_) * K @ K
    return E0 @ R.T


def squash_y(yf, a):
    """--squash: a fisheye's height (-1 top, 1 bottom) to the picture's, y + a (sin(pi y / 2) - y): the rows round the
    middle (the horizon, for eyes along a level walk) drawn 1 + a (pi / 2 - 1) times taller, the top and bottom
    rows 1 - a times as tall."""
    return yf + a * (np.sin(np.pi * yf / 2) - yf)


def square_to_disc(x, y):
    """--fill-square: the elliptical grid mapping, the square [-1, 1]^2 onto the unit disc (its edges onto the rim, a corner
    onto the rim at 45 degrees), so a fisheye's circle fills its whole square and no pixel is black."""
    return x * np.sqrt(np.clip(1 - y * y / 2, 0, None)), y * np.sqrt(np.clip(1 - x * x / 2, 0, None))


def disc_to_square(u, v):
    """The inverse of square_to_disc (for the viewer and walk_fidelity)."""
    s2 = 2 * np.sqrt(2)
    a, b = 2 + u * u - v * v, 2 - u * u + v * v
    x = (np.sqrt(np.clip(a + s2 * u, 0, None)) - np.sqrt(np.clip(a - s2 * u, 0, None))) / 2
    y = (np.sqrt(np.clip(b + s2 * v, 0, None)) - np.sqrt(np.clip(b - s2 * v, 0, None))) / 2
    return x, y


def draw_dual_fisheye(faces, Rcam, W, H, fov, yaw=0.0, squash=0.0, fill=False):
    """Two circular equidistant fisheyes side by side, each H across and fov degrees wide (over 180 they
    overlap at the rim): the walk's way ahead on the left, behind on the right; black outside the circles.
    Ahead, the ground runs from the horizon down into the circle's lower part in one picture, where a cube
    turns it 90 degrees across an edge."""
    S = H
    v, u = np.mgrid[0:S, 0:S].astype(np.float64)
    x = (u + .5) / S * 2 - 1; y = (v + .5) / S * 2 - 1
    if squash:                                           # the picture's rows back to the fisheye's (the table inverts it)
        g = np.linspace(-1, 1, 8193)
        y = np.interp(y, squash_y(g, squash), g)
    if fill:                                             # the square's pixel to its point in the circle
        x, y = square_to_disc(x, y)
    r = np.sqrt(x * x + y * y); th = r * np.radians(fov) / 2; ph = np.arctan2(y, x)
    cam = np.stack([np.sin(th) * np.cos(ph), np.sin(th) * np.sin(ph), np.cos(th)], -1)
    g = np.zeros((H, W, 3), np.uint8)
    for i, E in enumerate(fisheye_eyes(Rcam, yaw)):
        img = sample_dirs(faces, cam @ E)
        if not fill:
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


def depth_cloud(ddir, faces):
    """node_depth.py's six maps of a node (DDIR/face<k>_measured-depth.png, node_depth.json) as coloured points in
    the model: grey 0 is sky (left out), 255 is r_near; distance along the ray r = r_far / (1 + g (ratio - 1))."""
    rep = json.load(open(os.path.join(ddir, 'node_depth.json')))
    P, cols = [], []
    for k, (R, t, img) in enumerate(faces, 1):
        N = img.shape[0]
        g = np.asarray(Image.open(os.path.join(ddir, f'face{k}_measured-depth.png')).convert('L').resize((N, N), Image.NEAREST), float) / 255
        v, u = np.mgrid[0:N, 0:N] + 0.5
        ok = g > 0.02
        r = rep['r_far'] / (1 + g[ok] * (rep['ratio'] - 1))
        d = np.stack([(u[ok] - N / 2) / (N / 2), (v[ok] - N / 2) / (N / 2), np.ones(ok.sum())], -1)
        d /= np.linalg.norm(d, axis=1)[:, None]
        P.append(-R.T @ t + (d * r[:, None]) @ R); cols.append(img[ok].astype(np.float32))
    return np.vstack(P), np.vstack(cols)


def mid_faces(FA, FB, CA, CB, T, dirs):
    """Six faces seen from the point T of the way from A to B, in A's faces' orientations: both nodes' pictures
    moved there by their depth (view_check.splat, nearest point wins). Each pixel takes the nearer node's point
    (B's at T = 0.5), the other node's where only it has one, and where neither has (sky, and what neither saw)
    the node pictures at infinity, (1 - T) A + T B. No two pictures are mixed where either has a point, so
    nothing is drawn twice."""
    M = CA + T * (CB - CA)
    (PA, cA), (PB, cB) = depth_cloud(dirs[0], FA), depth_cloud(dirs[1], FB)
    first, second = ((PA, cA), (PB, cB)) if T < 0.5 else ((PB, cB), (PA, cA))
    out, cover = [], []
    for R, _, img in FA:
        N = img.shape[0]; tt = -R @ M; cam = (N, N, N / 2, N / 2, N / 2, N / 2)
        i1, v1 = splat(*first, R, tt, cam, N / 2, grow=2.5); i2, v2 = splat(*second, R, tt, cam, N / 2, grow=2.5)
        inf = (1 - T) * draw(FA, R, N, N, N / 2).astype(np.float32) + T * draw(FB, R, N, N, N / 2).astype(np.float32)
        f = np.where(v1[..., None], i1, np.where(v2[..., None], i2, inf))
        out.append((R, tt, np.clip(np.rint(f), 0, 255).astype(np.uint8)))
        cover.append((v1.mean(), (v2 & ~v1).mean()))
    print('mid view at %.2f: from the nearer node %s; from the other %s' % (
        T, ' '.join(f'{c[0]:.2f}' for c in cover), ' '.join(f'{c[1]:.2f}' for c in cover)))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('images'); ap.add_argument('sparse'); ap.add_argument('out'); ap.add_argument('a'); ap.add_argument('b')
    ap.add_argument('--prefix', default='MA', help="the faces' file prefix: MA (Amateria), LE (J'nanin)")
    ap.add_argument('--via', nargs='+', default=[], metavar='NODE',
                    help='nodes passed on the way from A to B, drawn with the same orientation as via1.png ...; '
                         'route.json gives each one\'s share of the route\'s length')
    ap.add_argument('--mid', type=float, metavar='T',
                    help='with --mid-depth: a picture from the point T (0.5) of the way from NODE_A to NODE_B, drawn '
                         'from both nodes moved by their depth, written as via1.png with route.json, to hold the walk '
                         'there (walk_polar3.ps1 -Mid)')
    ap.add_argument('--mid-depth', nargs=2, metavar=('DIR_A', 'DIR_B'), help="node_depth.py's maps for NODE_A and NODE_B")
    ap.add_argument('--plan', metavar='JSON',
                    help="route_plan.py's route_plan.json: A drawn facing the path's direction of departure, B its direction of arrival")
    ap.add_argument('--turn', action='store_true',
                    help='with --via: each node faces its own way, level, halfway between the step in and the step out '
                         '(A along its first step, B along its last), so the view turns with the walk; route.json gives each look')
    ap.add_argument('--size', default='832x480'); ap.add_argument('--fov', type=float, default=90.0)
    ap.add_argument('--yaw', type=float, default=0.0); ap.add_argument('--pitch', type=float, default=0.0)
    ap.add_argument('--equirect', action='store_true',
                    help='the whole view instead, equirectangular (--size 2:1), the walk straight ahead in the middle')
    ap.add_argument('--polar', type=float, nargs='?', const=20.0, metavar='PAD',
                    help='the whole view, equirectangular with poles straight ahead (top) and behind (bottom), '
                         'PAD degrees (20) repeated at each side (draw_polar_equirect)')
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
    ap.add_argument('--single-fisheye', type=float, nargs='?', const=360.0,
                    help='the whole view as one circular fisheye of this many degrees (360) ahead (--size square)')
    ap.add_argument('--squash', type=float, default=0.0,
                    help='with --dual-fisheye: rows moved toward the middle, picture y = y + A (sin(pi y / 2) - y) of the '
                         "fisheye's y: the band round the horizon drawn 1 + A (pi / 2 - 1) times taller, the top and "
                         'bottom 1 - A times (0.35: 1.2 and 0.65)')
    ap.add_argument('--fill-square', action='store_true',
                    help="with --dual-fisheye: each circle stretched to fill its square (square_to_disc), no black corners")
    ap.add_argument('--along-motion', action='store_true',
                    help='forward is the straight line from NODE_A to NODE_B, climb included (not levelled): with '
                         '--dual-fisheye the two eyes look straight along the walk and straight back')
    ap.add_argument('--eye-yaw', type=float, default=0.0, help='with --dual-fisheye: both eyes turned this many degrees to the right')
    ap.add_argument('--equal-area', action='store_true', help='with --single-fisheye: the equal-area fisheye (as --projection equal-area)')
    ap.add_argument('--projection', choices=['equidistant', 'equal-area', 'horizon'], default='equidistant',
                    help='with --single-fisheye: how angle from the centre maps to radius (horizon: the pixels drawn to the horizon)')
    ap.add_argument('--eye-pitch', type=float, default=0.0, help='with --single-fisheye: tilted this many degrees up (-90: straight down)')
    ap.add_argument('--last-eye', type=float, nargs=2, metavar=('YAW', 'PITCH'),
                    help='with --single-fisheye: the last frame aimed apart (the video model then makes the turn; the '
                         'viewer takes it out). Default: as the first')
    ap.add_argument('--auto-aim', action='store_true',
                    help="with --single-fisheye: each end aimed so its rim (the fisheye's one bad point) falls where that "
                         "node's view has least detail (weak_spot); overrides --eye-yaw, --eye-pitch and --last-eye")
    ap.add_argument('--net', choices=sorted(NETS) + sorted(STRIPS), help='another cube net (NETS) or rows of faces (STRIPS); writes layout.json')
    ap.add_argument('--gap', type=int, default=0, help='px of black between rows (with --net)')
    ap.add_argument('--fill', nargs='?', const='skycopy', help="the net's empty cells filled with copies (FILLS: skycopy, skyonce)")
    ap.add_argument('--false-line', type=int, default=0, help='px of black along joins between cells that do not truly meet (with --fill)')
    a = ap.parse_args()
    global PREFIX
    PREFIX = a.prefix
    W, H = (int(x) for x in a.size.split('x'))
    _, imgs = read_model(a.sparse)
    CA, FA = faces_of(a.images, imgs, a.a)
    CB, FB = faces_of(a.images, imgs, a.b)
    up = -FA[0][0][1]                                        # minus the y axis of face 1's camera
    fwd = CB - CA
    if np.linalg.norm(fwd) < 1e-6 and a.via:                 # a loop (A is B): face the first step
        fwd = faces_of(a.images, imgs, a.via[0])[0] - CA
    if not a.along_motion:
        fwd -= up * (fwd @ up)
    fwd /= np.linalg.norm(fwd)
    yaw, pitch = np.radians(a.yaw), np.radians(a.pitch)
    right = np.cross(fwd, up); right /= np.linalg.norm(right)
    fwd = np.cos(yaw) * fwd + np.sin(yaw) * right
    right = np.cross(fwd, up); right /= np.linalg.norm(right)
    fwd = np.cos(pitch) * fwd + np.sin(pitch) * up
    down = np.cross(fwd, right); down /= np.linalg.norm(down)
    Rcam = np.stack([right, down, fwd])                     # world -> camera rows: x right, y down, z forward
    f = W / 2 / np.tan(np.radians(a.fov) / 2)
    os.makedirs(a.out, exist_ok=True)
    def renderer(Rcam):
        if a.polar is not None:
            render = lambda F: draw_polar_equirect(F, Rcam, W, H, a.polar)
        elif a.equirect:
            render = lambda F: draw_equirect(F, Rcam, W, H)
        elif a.single_fisheye:
            proj = 'equal-area' if a.equal_area else a.projection
            aims = [(a.eye_yaw, a.eye_pitch), tuple(a.last_eye) if a.last_eye else (a.eye_yaw, a.eye_pitch)]
            if a.auto_aim:
                for i, F in enumerate((FA, FB)):
                    wk, lo, med = weak_spot(F, Rcam)
                    aims[i] = aim_of(wk)
                    print(f"{'first' if i == 0 else 'last'}: weakest spot {np.round(wk, 3)} (detail {lo:.1f}, median {med:.1f}); "
                          f"aimed yaw {aims[i][0]:.1f} pitch {aims[i][1]:.1f}")
            E0 = fisheye_eyes(Rcam, *aims[0])[0]
            E1 = turned_eye(E0, fisheye_eyes(Rcam, *aims[1])[0][2])
            ends = {id(FA): E0, id(FB): E1}
            render = lambda F: draw_single_fisheye(F, Rcam, W, H, a.single_fisheye, projection=proj, axes=ends[id(F)])
        elif a.dual_fisheye:
            render = lambda F: draw_dual_fisheye(F, Rcam, W, H, a.dual_fisheye, a.eye_yaw, a.squash, a.fill_square)
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
        return render
    render = renderer(Rcam)
    Image.fromarray(render(FA)).save(os.path.join(a.out, 'first.png'))
    Image.fromarray(render(FB)).save(os.path.join(a.out, 'last.png'))
    if a.plan:
        pl = json.load(open(a.plan))
        def pframe(fw):                                 # right kept near the straight line's right: no roll past vertical
            fw = np.array(fw) / np.linalg.norm(fw); r = right - fw * (right @ fw); r /= np.linalg.norm(r)
            return np.stack([r, np.cross(fw, r), fw])
        Image.fromarray(renderer(pframe(pl['departure_model']))(FA)).save(os.path.join(a.out, 'first.png'))
        Image.fromarray(renderer(pframe(pl['arrival_model']))(FB)).save(os.path.join(a.out, 'last.png'))
        print(f"planned: departure {pl['departure_off_deg']:.1f} deg, arrival {pl['arrival_off_deg']:.1f} deg off the straight line")
    if a.mid is not None:
        Image.fromarray(render(mid_faces(FA, FB, CA, CB, a.mid, a.mid_depth))).save(os.path.join(a.out, 'via1.png'))
        L = float(np.linalg.norm(CB - CA))
        json.dump({'nodes': [a.a, 'mid', a.b], 'lengths': [a.mid * L, (1 - a.mid) * L], 'share': [0.0, a.mid, 1.0],
                   'looks_model': None}, open(os.path.join(a.out, 'route.json'), 'w'), indent=1)
    if a.via:
        cs, Fs = [CA], []
        for n in a.via:
            Cn, Fn = faces_of(a.images, imgs, n); cs.append(Cn); Fs.append(Fn)
        cs.append(CB)
        looks = None
        if a.turn:
            st = [q - p for p, q in zip(cs, cs[1:])]
            st = [(d - up * (d @ up)) / np.linalg.norm(d - up * (d @ up)) for d in st]
            looks = [st[0]] + [(si + so) / np.linalg.norm(si + so) if np.linalg.norm(si + so) > 1e-3 else so
                               for si, so in zip(st, st[1:])] + [st[-1]]
            def frame(fw):
                r = np.cross(fw, up); r /= np.linalg.norm(r); return np.stack([r, np.cross(fw, r), fw])
            Image.fromarray(renderer(frame(looks[0]))(FA)).save(os.path.join(a.out, 'first.png'))
            Image.fromarray(renderer(frame(looks[-1]))(FB)).save(os.path.join(a.out, 'last.png'))
            for k, (fw, si, so) in enumerate(zip(looks, [None] + st, st + [None])):
                print(f'node {([a.a] + a.via + [a.b])[k]}: looks ' + ' '.join(
                    f'{lab} {np.degrees(np.arccos(np.clip(fw @ d, -1, 1))):.1f}' for lab, d in (('off in', si), ('off out', so)) if d is not None))
        for k, Fn in enumerate(Fs):
            R = Rcam if looks is None else frame(looks[k + 1])
            Image.fromarray(renderer(R)(Fn)).save(os.path.join(a.out, f'via{k + 1}.png'))
        seg = [float(np.linalg.norm(q - p)) for p, q in zip(cs, cs[1:])]
        cum = np.cumsum(seg) / sum(seg)
        json.dump({'nodes': [a.a] + a.via + [a.b], 'lengths': seg, 'share': [0.0] + [float(c) for c in cum],
                   'looks_model': None if looks is None else [[float(x) for x in fw] for fw in looks]},
                  open(os.path.join(a.out, 'route.json'), 'w'), indent=1)
        print('route ' + ' '.join([a.a] + a.via + [a.b]) + ': lengths ' + ' '.join(f'{x:.3f}' for x in seg))
    # the direction in the nodes' own frame (node_depth.py's: face 1 looking along -z, y up), for the viewer
    M = FA[0][0].T @ np.diag([1.0, -1.0, -1.0])             # node frame -> model frame (walk_scene.py's)
    look = M.T @ fwd
    if a.single_fisheye:
        E, E2 = E0, E1
        json.dump({'net': 'single-fisheye', 'projection': 'equal-area' if a.equal_area else a.projection, 'fov': a.single_fisheye,
                   'yaw': aims[0][0], 'pitch': aims[0][1], 'last_yaw': aims[1][0], 'last_pitch': aims[1][1], 'size': [W, H],
                   'eyes': [{'rect': [0, 0, H, H], 'axes': [[round(float(v), 6) for v in Rcam @ ax] for ax in E]}],
                   'last_eyes': [{'rect': [0, 0, H, H], 'axes': [[round(float(v), 6) for v in Rcam @ ax] for ax in E2]}]},
                  open(os.path.join(a.out, 'layout.json'), 'w'), indent=1)
    if a.dual_fisheye:
        json.dump({'net': 'dual-fisheye', 'fov': a.dual_fisheye, 'yaw': a.eye_yaw, 'size': [W, H],
                   'eyes': [{'rect': [i * H, 0, H, H], 'axes': [[round(float(v), 6) for v in Rcam @ ax] for ax in E]}
                            for i, E in enumerate(fisheye_eyes(Rcam, a.eye_yaw))]},
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
