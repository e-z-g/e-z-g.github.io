#!/usr/bin/env python3
"""
Build Voltaic's "Layered" version: four sets of six face images, one per
slot of the viewer's two-layer upload, ready for stitcher.html.

    python build_layers.py out_dir              (needs numpy and Pillow)
    node stitch_layers.js http://localhost:8000/cube/stitcher.html out_dir
                                                (then the four 3x2 atlases)

Why. The estimated depth maps (ENCHnodes-*-depth.jpeg) could not see
through wire mesh. Between the walkway's slats (face 280) and through the
floor grate's panels (face 278) they put the canyon floor just behind the
mesh — gaps 92-104 against slats 116-122, panels 62-85 against spokes
93-105 — when the open floor beside it reads ~20. So what you see through
the mesh moved with the mesh, at any mesh density. Setting the floor's real
depth in a single map instead sank pits into the mesh, whose walls streaked
across the view. Two layers do it properly: a foreground with holes and a
backdrop seen through them at its own depth.

The four slots, per face:
  fg colour  the original capture.
  fg depth   red: the estimated depth, filled flat across every hole from
             the metal around, so slats and spokes have no slope to stretch
             down. Green: 0 where the floor shows through, 255 elsewhere —
             the viewer cuts the foreground there (maskAt() in index.html).
  bg colour  the floor: netting closed out of it where it is dark wire on
             lit floor, and filled in under the slats and spokes by a
             pyramid (push-pull) fill ~64px around every hole, about as far
             as the floor slides at full head-tracking range.
  bg depth   the floor's depth over that region, blending back to the
             estimate over 64px more so the backdrop has no step of its own.
"""
import os, sys
import numpy as np
from PIL import Image

VOLTAIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
FACES = (277, 278, 279, 280, 281, 282)


def load(k):
    c = np.asarray(Image.open(os.path.join(VOLTAIC, f'ENCHnodes-{k}_orig.jpeg')).convert('RGB'), dtype=np.float32)
    H, W = c.shape[:2]
    d = np.asarray(Image.open(os.path.join(VOLTAIC, f'ENCHnodes-{k}-depth.jpeg')).convert('L')
                   .resize((W, H), Image.BICUBIC), dtype=np.float32)
    return c, d


def grow(m, r):
    out = m.copy()
    for dy in range(-r, r + 1):
        for dx in range(-r, r + 1):
            out |= np.roll(np.roll(m, dy, 0), dx, 1)
    return out


def shrink(m, r):
    return ~grow(~m, r)


def lum(c):
    return 0.299 * c[..., 0] + 0.587 * c[..., 1] + 0.114 * c[..., 2]


def lit_floor(c):
    """Sunlit sand: bright, and much redder than blue."""
    return (lum(c) > 75) & (c[..., 0] - c[..., 2] > 40)


def box(a, r, fn):
    """Separable max or min over a (2r+1) square, per channel."""
    out = a.copy()
    for ax in (0, 1):
        out = fn(np.stack([np.roll(out, s, ax) for s in range(-r, r + 1)]), axis=0)
    return out


def pushpull(img, known):
    """Fill unknown pixels from known ones at ever coarser scales, then blend
    back down: smooth, no streaks, every pixel reachable. img is HxWxC."""
    H, W = known.shape
    if min(H, W) <= 2 or known.all():
        out = img.copy()
        if not known.all():
            out[~known] = img[known].mean(0) if known.any() else 0
        return out
    Hp, Wp = H + H % 2, W + W % 2
    ip = np.pad(img * known[..., None], ((0, Hp - H), (0, Wp - W), (0, 0)), mode='edge')
    kp = np.pad(known.astype(float), ((0, Hp - H), (0, Wp - W)), mode='edge')
    s_img = ip.reshape(Hp // 2, 2, Wp // 2, 2, -1).sum((1, 3))
    s_k = kp.reshape(Hp // 2, 2, Wp // 2, 2).sum((1, 3))
    small = pushpull(s_img / np.maximum(s_k, 1e-6)[..., None], s_k > 0)
    up = np.stack([np.asarray(Image.fromarray(small[..., ch].astype(np.float32), mode='F')
                              .resize((Wp, Hp), Image.BILINEAR)) for ch in range(small.shape[-1])], -1)[:H, :W]
    out = img.copy(); out[~known] = up[~known]
    return out


def walkway_holes():
    """Face 280: the gaps between the slats in the walkway's two channels.
    The channels' edges are read off the colour image (far point, near
    point per edge); along each, a row brighter than the slats around it
    is a gap, lit or in shadow. Plus any lit floor in or at the walkway."""
    c, d = load(280); H, W = d.shape
    L = lum(c)
    at = lambda p, q, y: p[0] + (q[0] - p[0]) * (y - p[1]) / (q[1] - p[1])
    channels = [((355, 380), (298, 620), (364, 380), (345, 620)),
                ((398, 385), (455, 620), (408, 385), (500, 620))]
    holes = np.zeros((H, W), bool)
    for a, b, cc, dd in channels:
        rows = list(range(388, H))
        med = []
        for y in rows:
            xl, xr = at(a, b, y) + 1.5, at(cc, dd, y) - 1.5
            med.append(np.median(L[y, int(np.ceil(xl)):int(np.floor(xr)) + 1]) if xr - xl >= 2 else 0.0)
        med = np.array(med)
        for i, y in enumerate(rows):
            if med[i] > max(34, med[max(0, i - 8):i + 9].min() + 8):
                holes[y, int(np.ceil(at(a, b, y) + 1)):int(np.floor(at(cc, dd, y) - 1)) + 1] = True
    holes |= lit_floor(c) & grow(d > 85, 2)
    # The floor's depth on each row, from the open floor left of the walkway.
    floor = np.clip(np.array([np.median(d[y, 30:100]) for y in range(H)]), 15, 30)
    return holes, floor[:, None]


def grate_holes():
    """Face 278, looking down: the panels between the grate's spokes read
    well below the metal (62-85 against 93-105). Plus sunlit floor through
    the netting in and around the grate, which is never metal."""
    c, d = load(278); H, W = d.shape
    yy, xx = np.mgrid[0:H, 0:W]
    r = np.hypot(xx - W / 2, yy - H / 2)
    panels = grow(shrink(shrink(grow((d < 88) & (r < 0.47 * W), 1), 1), 1), 1)
    lit = grow(shrink(shrink(grow(lit_floor(c), 3), 3), 2), 2) & (r < 0.55 * W)
    return (panels & (d < 92)) | lit, 30.0   # nearer straight down than at the walkway's slant


def layer_face(k, holes, floor_depth):
    c, d = load(k); H, W = d.shape
    closed = box(box(c, 2, np.max), 2, np.min)          # wipes lines narrower than 5px
    # Wires are dark lines across lit floor. Over dark floor they are faint
    # and lighter than it; a dark-line test there caught only spoke edges.
    wires = holes & (lum(closed) - lum(c) > 18) & (lum(closed) > 70)
    see_through = holes & ~wires
    flat = pushpull(d[..., None], ~holes)[..., 0]
    fg = np.stack([flat, np.where(see_through, 0, 255), flat], -1)
    region = grow(holes, 64)
    lit_holes = holes & (lum(closed) > 70)   # closing over dark floor wiped its detail
    floor_only = c.copy(); floor_only[lit_holes] = closed[lit_holes]
    filled = pushpull(floor_only, holes)
    # Where the foreground can tear (steep depth), keep the original picture,
    # so a tear looks as it always did, not like reconstructed floor.
    gy, gx = np.gradient(flat)
    steep = grow(np.hypot(gx, gy) > 6, 3) & ~holes
    bg = c.copy(); keep = region & ~steep; bg[keep] = filled[keep]
    fd = np.broadcast_to(np.asarray(floor_depth, dtype=np.float32), (H, W))
    dist = np.full((H, W), 64.0, np.float32); reach = region.copy()
    for step in range(4, 65, 4):
        grown = grow(reach, 4); dist[grown & ~reach] = step; reach = grown
    dist[region] = 0
    w = np.clip(dist / 64.0, 0, 1)
    return c, fg, bg, fd * (1 - w) + d * w, see_through, wires


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else 'layer_faces'
    os.makedirs(out, exist_ok=True)
    specs = {280: walkway_holes(), 278: grate_holes()}
    q = lambda a: np.clip(np.rint(a), 0, 255).astype(np.uint8)
    for k in FACES:
        c, d = load(k)
        if k in specs:
            c, fg, bg, bgd, st, wires = layer_face(k, *specs[k])
            print(f'{k}: {int(st.sum())} see-through px, {int(wires.sum())} wire px kept solid')
        else:
            fg = np.stack([d, np.full_like(d, 255), d], -1); bg, bgd = c, d
        for slot, img in (('fg-color', c), ('fg-depth', fg), ('bg-color', bg), ('bg-depth', bgd)):
            Image.fromarray(q(img)).save(os.path.join(out, f'{slot}-{k}.png'))
    print(f'Face images in {out}/. Stitch them with stitch_layers.js (or by hand in stitcher.html, 3x2, 656px).')


if __name__ == '__main__':
    main()
