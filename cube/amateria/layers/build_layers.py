#!/usr/bin/env python3
"""
Build Amateria's "Layered" version (MAWW node 101): four sets of six face
images, one per slot of the viewer's two-layer upload, ready for stitcher.html.

    python sharpen_depth.py SITE_DIR SHARP_DIR       (myst3/colmap; 1280 px depth)
    python build_layers.py OUT_DIR --src SHARP_DIR --colour-suffix _sharp-colour.png
        --depth-suffix _sharp-depth.png [--lama big-lama.pt] [--band 160] [--jump 0.8]
        [--fringe 6] [--hole 6] [--hole-step 3]
    node stitch_layers.js http://localhost:8000/cube/stitcher.html OUT_DIR OUT_DIR 1296
                                                (then the four 3x2 atlases)

Pixel distances are given for 640 px faces and scale with the faces read
(doubled for the site's 1280 px build). Without --src it reads the 640 px
captures and their measured depth; on those the depth's outlines are rounder
than the picture, the eaves of the spire roof sat at sky depth and were left
behind in blocks, which is why the site's version uses sharpen_depth.py's.

Needs numpy, Pillow, opencv-python and torch, and LaMa's weights as TorchScript
(big-lama.pt, from the simple-lama-inpainting release v0.1.0); a GPU helps.

Why. With one depth map, a near object's edge is a step in the mesh, and the
mesh's wall across that step is drawn with the colours either side of it: when
the eye moves, the near object stretches across whatever it hid. Two layers
fix it the way Voltaic's do (cube/README.md, "Two layers: holes and tears"):
the foreground tears at the step and the backdrop shows what was behind.

The four slots, per face:
  fg colour  the faces read (the site's: the 4K faces at 1280 px).
  fg depth   red and blue: the depth read, with the near depth carried
             --hole-step px past every step. Green: 0 in --hole px on the far
             side of every step (a hole, cut like Voltaic's: see hole_band),
             255 elsewhere; with green equal to red the sky (depth 0) would be
             cut away as a hole too.
  bg colour  the near side of every depth jump taken out within --band pixels
             of the jump (160; the farthest anything slides at full
             head-tracking range is about 48 px) and painted in by LaMa. LaMa
             sees none of the near object, however far it reaches: shown part
             of one, it carries it on into the gap (with a 64 px band a ghost
             of the machinery's box came back beside it on face 8). Each face is padded with 128 px of its
             neighbours, and faces done earlier lend their finished backdrop,
             so the painting carries on across the seams. The painted region
             reaches --fringe px (6) into the far side, past the edge's mixed
             pixels, which LaMa otherwise drew on as dark outlines.
  bg depth   the measured depth, and in the removed region the depth of the
             far side of the nearest jump, so the backdrop there lies where
             the hidden surface would be.

A jump: two pixels 2 px apart whose inverse distance differs by more than
--jump, in units of the farthest distance the encoding keeps (q = 1 + 19 d,
proportional to 1/r; the depth maps are d = (r_far/r - 1)/19). The viewer's
tear slider at its middle tears at 1 to 2 in these units, so everything that
tears has a backdrop behind it.

Tried and dropped: moving the depth's edges onto the picture's (each pixel
within 14-18 px of a jump relabelled near or far by its colour against
confident pixels around it). In these dark, low-contrast faces the labels came
out speckled, every speckle was a step and every step a tear: the rings and
arcs broke into fragments. The measured depth's rounder outlines leave less
wrong.
"""
import argparse
import os

import cv2
import numpy as np
from PIL import Image

AMATERIA = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
# node_depth.py's face numbers (its DIRS) and the site's files: front, bottom,
# back, right, left, top.
FACES = {1: 8, 2: 9, 3: 10, 4: 11, 5: 12, 6: 13}
ORDER = (6, 1, 3, 4, 5, 2)   # top first (sky only), bottom last (it borders all four sides)
DIRS = {1: lambda s, t: (2 * s - 1, 1 - 2 * t, -np.ones_like(s)),
        2: lambda s, t: (1 - 2 * s, -np.ones_like(s), 1 - 2 * t),
        3: lambda s, t: (1 - 2 * s, 1 - 2 * t, np.ones_like(s)),
        4: lambda s, t: (np.ones_like(s), 1 - 2 * t, 2 * s - 1),
        5: lambda s, t: (-np.ones_like(s), 1 - 2 * t, 1 - 2 * s),
        6: lambda s, t: (1 - 2 * s, np.ones_like(s), 2 * t - 1)}
RATIO = 20.0
PAD = 128


def face_of(x, y, z):
    """Face and (s, t) of each direction: the inverse of DIRS, on arrays."""
    ax, ay, az = np.abs(x), np.abs(y), np.abs(z)
    zf = (az >= ax) & (az >= ay)
    xf = ~zf & (ax >= ay)
    yf = ~zf & ~xf
    k = np.where(zf, np.where(z < 0, 1, 3), np.where(xf, np.where(x > 0, 4, 5), np.where(y > 0, 6, 2)))
    with np.errstate(divide='ignore', invalid='ignore'):
        cases = [
            (k == 1, (x / az + 1) / 2, (1 - y / az) / 2),
            (k == 3, (1 - x / az) / 2, (1 - y / az) / 2),
            (k == 4, (z / ax + 1) / 2, (1 - y / ax) / 2),
            (k == 5, (1 - z / ax) / 2, (1 - y / ax) / 2),
            (k == 6, (1 - x / ay) / 2, (z / ay + 1) / 2),
            (k == 2, (1 - x / ay) / 2, (1 - z / ay) / 2)]
    s = np.select([c[0] for c in cases], [c[1] for c in cases])
    t = np.select([c[0] for c in cases], [c[2] for c in cases])
    return k, s, t


def pad_lookup(k, n, pad):
    """For face k padded by pad pixels on every side: the face, row and column
    each padded pixel's direction lands on (nearest pixel)."""
    u = (np.arange(n + 2 * pad) - pad + 0.5) / n
    s, t = np.meshgrid(u, u)
    kk, s2, t2 = face_of(*DIRS[k](s, t))
    col = np.clip((s2 * n).astype(int), 0, n - 1); row = np.clip((t2 * n).astype(int), 0, n - 1)
    return kk, row, col


def sample(stack, look):
    kk, row, col = look
    return stack[kk - 1, row, col]


def load(n, src=AMATERIA, colour='_orig.jpeg', depth='_measured-depth.png'):
    c = np.asarray(Image.open(os.path.join(src, f'MAWWnodes-{n}{colour}')).convert('RGB'))
    d = np.asarray(Image.open(os.path.join(src, f'MAWWnodes-{n}{depth}')).convert('L'))
    return c, d


def jumps(q, t):
    """Near-side and far-side pixels of every step of more than t in q between
    pixels 2 apart (four directions)."""
    near = np.zeros(q.shape, bool); far = np.zeros(q.shape, bool)
    for dy, dx in ((0, 2), (2, 0), (2, 2), (2, -2)):
        other = np.roll(np.roll(q, -dy, 0), -dx, 1)   # q at (y + dy, x + dx)
        a = q - other > t        # this pixel nearer
        b = other - q > t        # the other one nearer
        near |= a; far |= b
        near |= np.roll(np.roll(b, dy, 0), dx, 1)
        far |= np.roll(np.roll(a, dy, 0), dx, 1)
    return near & ~far, far & ~near


def hole_band(q, whole, t, width, step_at):
    """Voltaic's way of cutting, for every step: the width px on its far side
    become a hole in the foreground (green 0), and the near depth carries on
    under the hole for step_at px, so the mesh's step lies inside it. The mesh
    has a vertex every 2.5 px and smooths depth over as much, so a step is a
    ramp of stretched triangles about 5 px wide; cut by the tear test, which
    reaches about a pixel from the step, the rest of that ramp showed as
    jagged teeth along every edge. A hole is cut by the picture's own pixels."""
    near_e, _ = jumps(q, t)
    hole = np.zeros(q.shape, bool)
    if not near_e.any():
        return q.copy(), hole
    qmax = cv2.dilate(q.astype(np.float32), np.ones((5, 5), np.uint8))
    dist, lab = cv2.distanceTransformWithLabels((~near_e).astype(np.uint8), cv2.DIST_L2, 5,
                                                labelType=cv2.DIST_LABEL_PIXEL)
    ys, xs = np.nonzero(near_e)
    nq_of = np.zeros(lab.max() + 1, np.float32); nq_of[lab[ys, xs]] = qmax[ys, xs]
    nq = nq_of[lab]
    far_side = ~whole & ~near_e & (nq > q + t / 2)
    hole = far_side & (dist <= width)
    out = q.copy()
    under = far_side & (dist <= step_at)
    out[under] = nq[under]
    return out, hole


def removed_region(q, t, band):
    """The near side of every jump within band px of it; the whole near object
    (all of it nearer than the far side of its nearest jump, connected to a
    jump's near side), which LaMa must not see; and the far side's q for every
    pixel (that of the nearest far-side pixel, taken as the least q within 2 px
    of it, since a step is soft over a pixel or two)."""
    near, far = jumps(q, t)
    if not far.any():
        none = np.zeros(q.shape, bool)
        return none, none, q.copy()
    qmin = cv2.erode(q.astype(np.float32), np.ones((5, 5), np.uint8))
    dist, lab = cv2.distanceTransformWithLabels((~far).astype(np.uint8), cv2.DIST_L2, 5,
                                                labelType=cv2.DIST_LABEL_PIXEL)
    ys, xs = np.nonzero(far)
    order = lab[ys, xs]
    fq_of = np.zeros(order.max() + 1, np.float32); fq_of[order] = qmin[ys, xs]
    fq = fq_of[lab]
    nearer = q > fq + t / 2
    _, comp = cv2.connectedComponents(nearer.astype(np.uint8), connectivity=8)
    keep = np.unique(comp[near & nearer]); keep = keep[keep > 0]
    whole = np.isin(comp, keep)
    return whole & (dist <= band), whole, fq


class Lama:
    def __init__(self, path):
        import torch
        self.torch = torch
        self.dev = 'cuda' if torch.cuda.is_available() else 'cpu'
        self.net = torch.jit.load(path, map_location=self.dev).eval()

    def __call__(self, rgb, mask):
        torch = self.torch
        h, w = mask.shape
        H, W = (h + 7) // 8 * 8, (w + 7) // 8 * 8
        img = np.pad(rgb.astype(np.float32) / 255, ((0, H - h), (0, W - w), (0, 0)), mode='reflect')
        m = np.pad(mask.astype(np.float32), ((0, H - h), (0, W - w)), mode='reflect')
        with torch.no_grad():
            out = self.net(torch.from_numpy(img).permute(2, 0, 1)[None].to(self.dev),
                           torch.from_numpy(m)[None, None].to(self.dev))
        out = out[0].permute(1, 2, 0).clamp(0, 1).cpu().numpy()[:h, :w] * 255
        return np.where(mask[..., None], out, rgb)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('out'); ap.add_argument('--lama', default='big-lama.pt')
    ap.add_argument('--band', type=int, default=160); ap.add_argument('--jump', type=float, default=0.8)
    ap.add_argument('--fringe', type=int, default=6, help='px the painted region reaches past the jump into the far side')
    ap.add_argument('--src', default=AMATERIA, help='folder of the faces and depth maps')
    ap.add_argument('--colour-suffix', default='_orig.jpeg'); ap.add_argument('--depth-suffix', default='_measured-depth.png')
    ap.add_argument('--hole', type=int, default=6, help='px of the far side of a step cut out of the foreground')
    ap.add_argument('--hole-step', type=int, default=3, help='px of the hole the near depth carries on under')
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    col, dep = {}, {}
    for k, n in FACES.items():
        col[k], dep[k] = load(n, a.src, a.colour_suffix, a.depth_suffix)
    N = dep[1].shape[0]
    # Pixel distances are given for 640 px faces and scale with the face.
    S = N / 640
    sc = lambda v: max(1, int(round(v * S)))
    PAD_ = sc(PAD)
    C = np.stack([col[k] for k in range(1, 7)]).astype(np.float32)
    D = np.stack([dep[k] for k in range(1, 7)]).astype(np.float32) / 255
    Q = 1 + (RATIO - 1) * D
    lama = Lama(a.lama)
    bg = C.copy()                     # finished backdrops replace these face by face
    done = np.zeros(6, bool)
    masks, hide, fqs, fgq, holes = {}, {}, {}, {}, {}
    # The removed region and far-side depth of every face first, each on the
    # face padded with its neighbours so a jump at a seam is seen whole.
    for k in range(1, 7):
        look = pad_lookup(k, N, PAD_)
        region, whole, fq = removed_region(sample(Q, look), a.jump, sc(a.band))
        grow = lambda m: cv2.dilate(m.astype(np.uint8), np.ones((2 * sc(a.fringe) + 1,) * 2, np.uint8)) > 0
        masks[k], hide[k], fqs[k] = grow(region), grow(whole), fq
        fgq[k], holes[k] = hole_band(sample(Q, look), whole, a.jump, sc(a.hole), sc(a.hole_step))
    inner = (slice(PAD_, PAD_ + N), slice(PAD_, PAD_ + N))
    M = np.stack([masks[k][inner] for k in range(1, 7)])
    for k in ORDER:
        look = pad_lookup(k, N, PAD_)
        rgb = sample(bg, look)
        # LaMa paints over the whole near object, so it never sees part of
        # one and carries it on into the gap (with a 64px band, a ghost of the
        # machinery's box came back beside it); the backdrop keeps the
        # painting within the band only. Padding from a face already done
        # is finished backdrop: known, not painted.
        m = hide[k] & ~done[look[0] - 1]
        m[inner] = hide[k][inner]
        if m[inner].any():
            painted = lama(rgb, m)[inner]
            keep = masks[k][inner]
            bg[k - 1][keep] = painted[keep]
        done[k - 1] = True
        print(f'face {FACES[k]}: {int(M[k - 1].sum())} px removed and painted ({M[k - 1].mean() * 100:.1f}%)')
    q8 = lambda x: np.clip(np.rint(x), 0, 255).astype(np.uint8)
    for k, n in FACES.items():
        d = dep[k].astype(np.float32)
        fq = cv2.blur(fqs[k], (9, 9))[inner]
        bgd = np.where(M[k - 1], (fq - 1) / (RATIO - 1) * 255, d)
        bgd = np.minimum(bgd, d)          # the backdrop never in front of the foreground
        fd = (fgq[k][inner] - 1) / (RATIO - 1) * 255
        green = np.where(holes[k][inner], 0, 255)
        fgd = np.stack([fd, green, fd], -1)
        for slot, img in (('fg-color', col[k]), ('fg-depth', fgd), ('bg-color', bg[k - 1]), ('bg-depth', bgd)):
            Image.fromarray(q8(img)).save(os.path.join(a.out, f'{slot}-{n}.png'))
        Image.fromarray(q8(M[k - 1] * 255)).save(os.path.join(a.out, f'removed-{n}.png'))
    print(f'Face images in {a.out}/. Stitch them with stitch_layers.js (or by hand in stitcher.html, 3x2, 656px).')


if __name__ == '__main__':
    main()
