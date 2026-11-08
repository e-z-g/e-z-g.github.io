#!/usr/bin/env python3
"""
Build a node's "Layered" version: four sets of six face images, one per
slot of the viewer's two-layer upload, ready for stitcher.html. Used for
every site node with a Layered version except Voltaic's ENCH grate
(grate_layers.py); run through build_node.py with the node's file in nodes/,
which holds the settings each node was built with and why.

    python build_layers.py OUT_DIR --src SHARP_DIR --names N1 ... N6
        --colour-suffix _sharp-colour.png --depth-suffix _sharp-depth.png
        [--lama big-lama.pt] [--model-bg DIR] [other settings below]
    node stitch_layers.js http://localhost:8000/cube/stitcher.html OUT_DIR OUT_DIR 1296 PREFIX N1,...,N6
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

A light against the sky (--light K:X0,Y0,X1,Y1, a box on face K in pixels of a
640 px face): MASS 84's lamp glass, pale and glowing in front of the sunset,
was sky in the measured depth, so the glass stayed on the sky while its shade
moved with the post, and the backdrop kept the glass where the lamp had been
taken out. In the box, the sky-depth pixels paler than the box's sky (their
brightness less 100 times their saturation over the median of the sky on the
box's border by more than 20), closed and filled, take one depth: the 90th
percentile of the solid pixels they touch (the shade).

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
Also tried and dropped: GrabCut (OpenCV) round each near object, with a band
of 12 or 24 px either side of the depth's outline left to colour and the
pairwise term to keep the shapes whole. On MASS 84 it dropped face 1's rails
from the near objects and made the floor slats' outlines wobble. The slats'
outlines were off for another reason, a thin ridge in the depth along their
edges (see removed_region), and with that fixed they follow the picture.
"""
import argparse
import os

import cv2
import numpy as np
from PIL import Image

AMATERIA = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'amateria')
# node_depth.py's face numbers (its DIRS) and the site's files: front, bottom,
# back, right, left, top.
FACES = {k: f'MAWWnodes-{n}' for k, n in zip(range(1, 7), range(8, 14))}
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


def load(name, src=AMATERIA, colour='_orig.jpeg', depth='_measured-depth.png'):
    c = np.asarray(Image.open(os.path.join(src, f'{name}{colour}')).convert('RGB'))
    d = np.asarray(Image.open(os.path.join(src, f'{name}{depth}')).convert('L'))
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


def remove_specks(m, area):
    """m without its connected pieces of under area pixels."""
    n, comp, stats, _ = cv2.connectedComponentsWithStats(m.astype(np.uint8), connectivity=8)
    big = stats[:, cv2.CC_STAT_AREA] >= area; big[0] = False
    return big[comp]


def hole_band(q, whole, t, width, step_at, speck=80, rim_px=2):
    """Voltaic's way of cutting, for every near object: the width px outside
    its outline that lie noticeably farther than it become a hole in the
    foreground (green 0), and the object's depth carries on under the hole for
    step_at px, so the mesh's step lies inside it. The mesh has a vertex every
    2.5 px and smooths depth over as much, so a step is a ramp of stretched
    triangles about 5 px wide; cut by the tear test, which reaches about a
    pixel from the step, the rest of that ramp showed as jagged teeth along
    every edge. A hole is cut by the picture's own pixels.

    The band follows the near object's whole outline (removed_region's
    `whole`). Found from the edge pixels where the depth jumps, it was a dashed
    line wherever a softer stretch of the step escaped the jump test: pixels
    of the edge stayed behind between the dashes, a speckle and a saw-toothed
    wiggle along every rail and walkway edge as the eye moved. Its outline is
    smoothed over a pixel or so, and specks under `speck` px go.

    The depth carries on under the hole for 6 px of a 640 px face (12 at
    1280) and the hole is twice that: on a phone the mesh has a vertex every
    2.5 px of a 640 px face and each vertex averages the depth a quad round
    it, so with 3 px the vertices just inside an outline took in some of the
    far side and the rim bent back by a vertex-spaced pattern as the eye moved,
    a wiggle along every thin thing (ENSI 16's spire blades, the slit between
    them)."""
    hole = np.zeros(q.shape, bool)
    if not whole.any():
        return q.copy(), hole
    rim = whole & ~(cv2.erode(whole.astype(np.uint8), np.ones((3, 3), np.uint8)) > 0)
    qmax = cv2.dilate(np.where(whole, q, 0).astype(np.float32), np.ones((5, 5), np.uint8))
    dist, lab = cv2.distanceTransformWithLabels((~rim).astype(np.uint8), cv2.DIST_L2, 5,
                                                labelType=cv2.DIST_LABEL_PIXEL)
    ys, xs = np.nonzero(rim)
    nq_of = np.zeros(lab.max() + 1, np.float32); nq_of[lab[ys, xs]] = qmax[ys, xs]
    nq = nq_of[lab]
    far_side = ~whole & (nq > q + t / 4)
    hole = far_side & (dist <= width)
    hole = cv2.GaussianBlur(hole.astype(np.float32), (0, 0), 1.0) > 0.5
    hole = remove_specks(hole, speck)
    hole = ~remove_specks(~hole, speck)
    hole &= ~whole
    # The object's outermost rim_px px too, where they border the hole: those
    # pixels are the object's colour blended with what was behind it, and
    # over a different backdrop they showed as a pale torn fringe.
    if rim_px > 0:
        din = cv2.distanceTransform(whole.astype(np.uint8), cv2.DIST_L2, 3)
        near_hole = cv2.dilate(hole.astype(np.uint8), np.ones((2 * rim_px + 3,) * 2, np.uint8)) > 0
        hole |= whole & (din <= rim_px) & near_hole
    out = q.copy()
    under = far_side & (dist <= step_at)
    out[under] = nq[under]
    return out, hole


def removed_region(q, t, band, reach, belong=0.5):
    """The near side of every jump within band px of it; the whole near object
    (all of it nearer than the far side behind it, connected to a jump's near
    side), which LaMa must not see; and the q of what is behind, for every
    pixel: the farthest far side of any jump within reach px (a far side's q
    taken as the least within 2 px, since a step is soft over a pixel or two),
    else that of the nearest jump.

    The farthest within reach, not the nearest: an object with steps of its
    own (ENSI 16's pod, a ball in front of its frame in front of the sky) had
    its frame taken for what is behind the ball, so the frame stayed out of
    the region, LaMa drew on it and painted more pod, and the backdrop got the
    frame's depth: a dark pod-shaped blob that streaked as the eye moved.
    Only a middle layer that belongs to the near object goes with it: one
    whose gap to the near side is under belong (0.5) times its gap to the
    farthest far side (the frame, a little behind the ball and far in front of
    the sky). Taking every middle layer took the rocks round ENSI 16's walkway
    too, painted as sea at sea depth: a grey outline round the walkway.
    reach is about as far as anything slides. Two layers cannot hold three,
    though: under MAWW 101's floor slats it took the beams below for part of
    the slats (the sea is in reach through the gaps), and the gaps showed flat
    painted grey; keeping only small middle pieces did not tell the beams from
    the pod's frame. So it is a choice per node: reach 0 is the nearest step,
    as MAWW 101's floor is built (--nearest-faces 2), while its other faces,
    the spire and the machinery among them, are cleaner with reach."""
    # Steps are found on the depth with a 5 px median: the sharpened depth has
    # a ridge a pixel or two wide along the edge of MASS 84's floor slats,
    # about 0.8 nearer than the slat, and against it a strip of every slat read
    # as the far side of a step. The near objects broke into half-disc blobs
    # and the holes cut round them fell on the wood. The median takes thin
    # ridges away and leaves steps where they are.
    near, far = jumps(cv2.medianBlur(q.astype(np.float32), 5), t)
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
    if reach > 0:
        # The farthest far side within reach, and the q of the nearest near side.
        BIG = np.float32(1e6)
        far_q = np.where(far, qmin, BIG).astype(np.float32)
        behind = cv2.erode(far_q, np.ones((2 * reach + 1, 2 * reach + 1), np.uint8))
        fq_far = np.where(behind < BIG, np.minimum(behind, fq), fq)
        qmax = cv2.dilate(q.astype(np.float32), np.ones((5, 5), np.uint8))
        _, nlab = cv2.distanceTransformWithLabels((~near).astype(np.uint8), cv2.DIST_L2, 5,
                                                  labelType=cv2.DIST_LABEL_PIXEL)
        ny, nx = np.nonzero(near)
        nq_of = np.zeros(nlab.max() + 1, np.float32); nq_of[nlab[ny, nx]] = qmax[ny, nx]
        nq = nq_of[nlab]
        # A middle layer belongs to the near object when it lies only a little
        # behind it next to how far the farthest far side lies behind it.
        mid = ~nearer & (q > fq_far + t / 2)
        belongs = mid & (nq - q < belong * (q - fq_far))
        grown = cv2.dilate(belongs.astype(np.uint8), np.ones((2 * reach + 1,) * 2, np.uint8)) > 0
        fq = np.where(belongs | (nearer & grown), fq_far, fq)
        nearer |= belongs
    _, comp = cv2.connectedComponents(nearer.astype(np.uint8), connectivity=8)
    keep = np.unique(comp[near & nearer]); keep = keep[keep > 0]
    whole = np.isin(comp, keep)
    return whole & (dist <= band), whole, fq


def light_fix(q, rgb, box, S):
    """q with the pale glowing pixels at sky depth in box (x0, y0, x1, y1, at 640 px)
    given the depth of the nearest pixel that has one; and how many changed."""
    x0, y0, x1, y1 = (int(round(v * S)) for v in box)
    qb = q[y0:y1, x0:x1]; c = rgb[y0:y1, x0:x1].astype(np.float32)
    mx = c.max(2); sat = (mx - c.min(2)) / np.maximum(mx, 1)
    pale = c.mean(2) - 100 * sat
    sky = qb <= 1.0001
    border = np.zeros(sky.shape, bool); border[[0, -1], :] = True; border[:, [0, -1]] = True
    if not (sky & border).any():
        return q, 0
    glow = sky & (pale > np.median(pale[sky & border]) + 20)
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    glow = cv2.morphologyEx(glow.astype(np.uint8), cv2.MORPH_CLOSE, k) > 0
    n, lab = cv2.connectedComponents((~glow).astype(np.uint8), connectivity=4)
    outside = np.unique(lab[border & ~glow])
    glow = (glow | ~np.isin(lab, outside)) & sky              # holes in it filled
    if not glow.any():
        return q, 0
    # one depth for the whole light: that of the solid pixels it touches (the
    # shade), its 90th percentile, as the median took in the shade's soft rim
    # and put the glass behind it
    ring = (cv2.dilate(glow.astype(np.uint8), np.ones((5, 5), np.uint8)) > 0) & ~sky
    if not ring.any():
        return q, 0
    out = q.copy()
    out[y0:y1, x0:x1] = np.where(glow, np.percentile(qb[ring], 90), qb)
    return out, int(glow.sum())


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
    ap.add_argument('--rim', type=int, default=1, help="px of a near object's own blended rim cut where it borders a hole")
    ap.add_argument('--hide-fringe', type=int, default=6, help='px past the edge LaMa repaints, not copying the fringe')
    ap.add_argument('--fringe', type=int, default=2, help='px the painted region reaches past the jump into the far side')
    ap.add_argument('--reach', type=int, default=48, help='px within which the farthest far side counts as behind '
                    '(0: the nearest step\'s far side; MAWW 101 is built so)')
    ap.add_argument('--model-bg', help="model_backdrop.py's folder: what other nodes saw behind the near objects")
    ap.add_argument('--belong', type=float, default=0.5,
                    help='a middle layer goes with the near object when its gap to it is under this times its gap to the farthest')
    ap.add_argument('--nearest-faces', type=int, nargs='*', default=[],
                    help="faces (node_depth.py's numbers, 2 the floor) built with the nearest step whatever --reach")
    ap.add_argument('--src', default=AMATERIA, help='folder of the faces and depth maps')
    ap.add_argument('--names', nargs=6, help="the six faces' file names without suffix, in node_depth.py's order "
                    "(front, bottom, back, right, left, top; default MAWWnodes-8 ... -13)")
    ap.add_argument('--colour-suffix', default='_orig.jpeg'); ap.add_argument('--depth-suffix', default='_measured-depth.png')
    ap.add_argument('--hole', type=int, default=12, help='px of the far side of a step cut out of the foreground')
    ap.add_argument('--hole-step', type=int, default=6, help='px of the hole the near depth carries on under')
    ap.add_argument('--keep-gaps', type=int, nargs='*', default=[],
                    help="faces (node_depth.py's numbers) whose gaps between parts of a near object keep the picture "
                         "instead of being painted")
    ap.add_argument('--light', action='extend', nargs='+', default=[],
                    help='K:X0,Y0,X1,Y1: a light against the sky in this box of face K (640 px) given the depth of what holds it')
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    col, dep = {}, {}
    faces = dict(zip(range(1, 7), a.names)) if a.names else FACES
    for k, n in faces.items():
        col[k], dep[k] = load(n, a.src, a.colour_suffix, a.depth_suffix)
    N = dep[1].shape[0]
    # Pixel distances are given for 640 px faces and scale with the face.
    S = N / 640
    sc = lambda v: max(1, int(round(v * S)))
    PAD_ = sc(PAD)
    for spec in a.light:
        k, box = spec.split(':')
        k = int(k)
        q, n = light_fix(1 + (RATIO - 1) * dep[k].astype(np.float32) / 255, col[k], [float(v) for v in box.split(',')], S)
        dep[k] = np.clip(np.rint((q - 1) / (RATIO - 1) * 255), 0, 255).astype(np.uint8)
        print(f'face {faces[k]}: {n} px of a light against the sky given the depth of what holds it')
    C = np.stack([col[k] for k in range(1, 7)]).astype(np.float32)
    D = np.stack([dep[k] for k in range(1, 7)]).astype(np.float32) / 255
    Q = 1 + (RATIO - 1) * D
    lama = Lama(a.lama)
    bg = C.copy()                     # finished backdrops replace these face by face
    done = np.zeros(6, bool)
    masks, hide, fqs, fgq, holes, wholes = {}, {}, {}, {}, {}, {}
    # What the model's other nodes saw behind the near objects (model_backdrop.py).
    MQ = np.zeros((6, N, N), np.float32); MC = np.zeros((6, N, N, 3), np.float32)
    used = np.zeros((6, N, N), bool)
    if a.model_bg:
        for k, n in faces.items():
            qf = os.path.join(a.model_bg, n + '_model-bg-q.npy')
            if os.path.exists(qf):
                MQ[k - 1] = np.load(qf)
                MC[k - 1] = np.asarray(Image.open(os.path.join(a.model_bg, n + '_model-bg.png')).convert('RGB'))
    # The removed region and far-side depth of every face first, each on the
    # face padded with its neighbours so a jump at a seam is seen whole.
    for k in range(1, 7):
        look = pad_lookup(k, N, PAD_)
        region, whole, fq = removed_region(sample(Q, look), a.jump, sc(a.band),
                                             0 if k in a.nearest_faces else sc(a.reach), a.belong)
        grow = lambda m: cv2.dilate(m.astype(np.uint8), np.ones((2 * sc(a.fringe) + 1,) * 2, np.uint8)) > 0
        # Gaps narrower than the cut between parts of a near object (the slit
        # between ENSI 16's spire blades): what shows through them is paler or
        # mixed with the object's edges, and left in the backdrop at the far
        # side's depth it stayed behind as a pale ghost of the slit.
        k_gap = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * sc(a.hole) + 1,) * 2)
        slits = (cv2.morphologyEx(whole.astype(np.uint8), cv2.MORPH_CLOSE, k_gap) > 0) & ~whole
        # Not on --keep-gaps faces: MASS 84's floor looks between its slats at
        # the sea far below, real far side, not a pale slit. Painted over, the
        # backdrop under the whole floor was plain dark, and wherever a hole
        # (placed from the depth's outlines, several px off the slats') fell
        # on a slat its wood was gone.
        if k in a.keep_gaps:
            slits[:] = False
        # LaMa repaints --hide-fringe px past the edge, so it never copies the
        # object's colour fringe (a 4 px margin let the spire's rust into the
        # sky as a pink smudge); the backdrop keeps only --fringe px of that,
        # and the real far side beyond (a 12 px strip of painted water was
        # darker than the water beside it, a jagged line along every edge).
        hgrow = lambda m: cv2.dilate(m.astype(np.uint8), np.ones((2 * sc(a.hide_fringe) + 1,) * 2, np.uint8)) > 0
        masks[k], hide[k], fqs[k], wholes[k] = grow(region) | slits, hgrow(whole) | slits, fq, whole
        fgq[k], holes[k] = hole_band(sample(Q, look), whole, a.jump, sc(a.hole), sc(a.hole_step),
                                           speck=int(20 * S * S), rim_px=sc(a.rim))
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
        # Inside a near object, what another node saw behind it is known, not
        # painted; LaMa fills only what no node saw. (On the far side of an
        # edge the backdrop is that surface itself, so the model is not used.)
        # Only where the model is dense: scattered points (a dotted outline
        # of ENSI 16's pod) given to LaMa as known were clues it joined up
        # into a ghost pod; there it paints instead.
        seen = sample(MQ, look) > 0
        dense = cv2.blur(seen.astype(np.float32), (2 * sc(4) + 1,) * 2) > 0.6
        seen = cv2.erode((seen & dense).astype(np.uint8), np.ones((3, 3), np.uint8)) > 0
        seen &= wholes[k]
        rgb[seen] = sample(MC, look)[seen]
        used[k - 1] = seen[inner]
        m &= ~seen
        if (m[inner] | seen[inner]).any():
            painted = lama(rgb, m)[inner]
            keep = masks[k][inner]
            bg[k - 1][keep] = painted[keep]
        done[k - 1] = True
        inside = wholes[k][inner] & M[k - 1]
        print(f'face {faces[k]}: {int(M[k - 1].sum())} px removed and painted ({M[k - 1].mean() * 100:.1f}%); '
              f'inside near objects {int(inside.sum())} px, {used[k - 1][inside].mean() * 100 if inside.any() else 0:.1f}% '
              f'of it seen by other nodes, the rest painted')
    q8 = lambda x: np.clip(np.rint(x), 0, 255).astype(np.uint8)
    for k, n in faces.items():
        d = dep[k].astype(np.float32)
        fq = cv2.blur(fqs[k], (9, 9))[inner]
        bq = np.where(used[k - 1], MQ[k - 1], fq)
        bq = np.where(wholes[k][inner], bq, fq)
        bgd = np.where(M[k - 1], (bq - 1) / (RATIO - 1) * 255, d)
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
