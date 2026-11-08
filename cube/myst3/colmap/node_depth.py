#!/usr/bin/env python3
"""
Depth for one node's six faces, as the cube viewer (../../index.html) reads it:
one grey image per face, learned depth scaled to whatever was measured.

    python node_depth.py IMAGES NODE OUT_DIR [--dense DIR] [--sparse TXT] [--cloud fused.ply]
                         [--pair-depths K:FILE ...] [--faces F1,F2,...,F6] [--names N1,...,N6]
                         [--suffix _measured-depth.png] [--ratio 20] [--seam-weight 1]
                         [--sky-weight 1] [--band 48]
                         [--model depth-anything/Depth-Anything-V2-Base-hf]
                         [--sky-model nvidia/segformer-b2-finetuned-ade-512-512]

IMAGES holds the node's faces as f<k>/<prefix>-<NODE>.jpg. What was measured comes
from any of:
  --dense   a workspace with COLMAP's geometric depth maps for the node's faces
            (node_stereo.py or run_dense.ps1): stereo/depth_maps/f<k>/...geometric.bin;
  --sparse  the sparse model as text: the faces' poses and the points each sees;
  --cloud   a dense cloud in that model's frame (needs --sparse for the poses);
  --pair-depths K:FILE  pair_points.py's depths in face K, up to a scale of their
            own: for a node no model places. Not to be mixed with the three above,
            whose scale is the model's.
--faces gives other pictures of the same six views to make the maps for (the
site's copies, or the node in another state: MAWW 101 is node 1 with the console
closed). Everything is fitted on the node's own faces first; a picture that
differs from its face (more than 30 grey levels, grown by 8 pixels) then gets its
own network depth, fitted (as depth_fill.py fits) to the node's distances over the
pixels the two share, so a changed thing gets the depth its own picture shows.
--names are the output names, face 1 to 6, without suffix.

Depth Anything V2 gives each face a relative inverse depth p, right in shape but
with a scale and offset of its own: 1/z = a p + b. The twelve unknowns (a, b for
six faces) are fitted together, by least squares in inverse distance with Cauchy
reweighting, to
  - what was measured: pair_points.py's depths, or the sparse points each face sees (the model's 3D points, at
    the pixels where they were matched), the stereo depths (up to 3,000 a face),
    and with --cloud a dense cloud of the same model (run_dense.ps1's fused.ply, in
    the same frame when the model continued the dense run's with its nodes held)
    projected into each face: the nearest point in each 4 x 4 pixel cell that holds
    at least two (up to 3,000 cells a face). The cloud lacks what no other node saw,
    so a near thing missing from it lets farther points through; the reweighting
    treats those as outliers;
  - the seams: the distance just inside each face edge equals the distance just
    across it on the neighbouring face (--seam-weight per edge pixel);
  - the sky (SegFormer's, up to 2,000 pixels a face) is infinitely far: inverse
    distance 0 (--sky-weight). Depth Anything is trained with sky at zero inverse
    depth, so this fixes each face's offset; without it, measurements that all lie
    at one depth are fitted best by a constant, every face a sphere.
The seams carry the scale from faces with measurements to faces with none (the
floor under a node and the sky over it are seen by no other node). The fit is
checked on half of the measurements, fitted with the other half and the seams:
median and 90th percentile of |fitted - measured| / measured, per face.

Seams: each face's network depth is predicted from that face alone, so after the
fit the faces still disagree a little along their shared edges, and the viewer,
which reads each direction's depth from one face, would draw a crease there.
Half the step (in inverse distance, smoothed along the edge) is added on each
side and faded out over --band pixels (48) inward, so both sides meet at their
mean. The report gives the steps before and after.

Sky: SegFormer's ADE20K sky class, and on a face where that finds sky, every pixel
the network puts as far as the farthest 1% of that sky (a dark sky with stars was
missed by SegFormer). Sky is infinitely far, takes no part in the seams, and its
measurements (points matched on clouds) are not used.

Distance along each ray, r = depth x sqrt(1 + x^2 + y^2) (the faces are 90 degree
pinhole views), is written as the viewer's disparity:
    d = (r_far / r - 1) / (r_far / r_near - 1),  clipped to [0, 1]
with r_near the 0.5th percentile of r over all six faces (sky counted as
infinitely far) and r_far = --ratio x r_near. The viewer stretches its 0.5th to
99.5th percentiles to [0, 1] and draws radius 50 / (1 + d K), so with this
encoding the stretch does nothing and K = ratio - 1 is true proportion: the
slider at its top (K = 19) with the default ratio of 20. Everything beyond r_far
(the sky, far sea) lies on the backdrop sphere.

Writes OUT_DIR/<name><suffix> (8-bit grey PNG), node_depth.json (fits, checks,
r_near in node spacings with --sparse, seams), and preview.jpg (each face beside
its map, measured pixels red). Needs numpy, Pillow, torch, transformers.
"""
import argparse
import glob
import json
import os
import sys

import numpy as np
from PIL import Image, ImageFilter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from depth_fill import fit_inverse, read_colmap_array  # noqa: E402
from evaluate_model import qvec2rot  # noqa: E402

# Face k (1-6) pixel (s, t) in [0, 1] looks along this direction (README, "Where each face points").
DIRS = {1: lambda s, t: (2 * s - 1, 1 - 2 * t, -np.ones_like(s)),
        2: lambda s, t: (1 - 2 * s, -np.ones_like(s), 1 - 2 * t),
        3: lambda s, t: (1 - 2 * s, 1 - 2 * t, np.ones_like(s)),
        4: lambda s, t: (np.ones_like(s), 1 - 2 * t, 2 * s - 1),
        5: lambda s, t: (-np.ones_like(s), 1 - 2 * t, 1 - 2 * s),
        6: lambda s, t: (1 - 2 * s, np.ones_like(s), 2 * t - 1)}


def face_of(x, y, z):
    """Face and (s, t) a direction falls on: the inverse of DIRS."""
    ax, ay, az = abs(x), abs(y), abs(z)
    if az >= ax and az >= ay:
        return (1, (x / az + 1) / 2, (1 - y / az) / 2) if z < 0 else (3, (1 - x / az) / 2, (1 - y / az) / 2)
    if ax >= ay:
        return (4, (z / ax + 1) / 2, (1 - y / ax) / 2) if x > 0 else (5, (1 - z / ax) / 2, (1 - y / ax) / 2)
    return (6, (1 - x / ay) / 2, (z / ay + 1) / 2) if y > 0 else (2, (1 - x / ay) / 2, (1 - z / ay) / 2)


def seam_pairs(W, H, inset=1.5):
    """For each face, (row, col, other face, row, col): a pixel just inside each edge
    and the pixel just across it on the neighbouring face."""
    out = {}
    for k in range(1, 7):
        lst = []
        for i in range(W):
            for s_, t_, ds, dt in ((i + .5, inset, 0, -2 * inset), (i + .5, H - inset, 0, 2 * inset),
                                   (inset, i + .5, -2 * inset, 0), (W - inset, i + .5, 2 * inset, 0)):
                x, y, z = (float(v) for v in DIRS[k](np.float64((s_ + ds) / W), np.float64((t_ + dt) / H)))
                k2, s2, t2 = face_of(x, y, z)
                if k2 != k:
                    lst.append((int(t_), int(s_), k2, min(H - 1, int(t2 * H)), min(W - 1, int(s2 * W))))
        out[k] = lst
    return out


def edge_pairs(W, H, inset=1.5):
    """(face, edge) -> rows, columns along that edge (just inside) and the face, rows and
    columns just across it; edges 'top', 'bottom', 'left', 'right' of the picture."""
    out = {}
    for k in range(1, 7):
        for edge in ('top', 'bottom', 'left', 'right'):
            lst = []
            for i in range(W):
                s_, t_, ds, dt = {'top': (i + .5, inset, 0, -2 * inset), 'bottom': (i + .5, H - inset, 0, 2 * inset),
                                  'left': (inset, i + .5, -2 * inset, 0), 'right': (W - inset, i + .5, 2 * inset, 0)}[edge]
                x, y, z = (float(v) for v in DIRS[k](np.float64((s_ + ds) / W), np.float64((t_ + dt) / H)))
                k2, s2, t2 = face_of(x, y, z)
                lst.append((int(t_), int(s_), k2, min(H - 1, int(t2 * H)), min(W - 1, int(s2 * W))))
            out[(k, edge)] = np.array(lst)
    return out


def feather(faces, W, H, band):
    """Close the steps left at the seams: along each face edge, half the difference in
    inverse distance to the neighbouring face (smoothed along the edge), added to the
    face and faded out over band pixels inward, so both sides meet at their mean. Sky
    and seams where one side is sky are left alone."""
    if band <= 0:
        return
    q = {k: np.where(np.isfinite(f['r']), 1.0 / f['r'], 0.0) for k, f in faces.items()}
    add = {k: np.zeros((H, W)) for k in faces}
    ep = edge_pairs(W, H)
    rows, cols = np.mgrid[0:H, 0:W]
    ker = np.ones(9) / 9
    for (k, edge), e in ep.items():
        v, u, j, v2, u2 = e.T
        q1 = q[k][v, u]; q2 = np.empty(len(j))
        for jj in np.unique(j):                        # the face across (another one at a corner)
            m = j == jj
            q2[m] = q[jj][v2[m], u2[m]]
        ok = (q1 > 0) & (q2 > 0)
        delta = np.where(ok, (q2 - q1) / 2, 0.0)
        w = np.convolve(ok.astype(float), ker, 'same')
        delta = np.where(w > 0, np.convolve(delta, ker, 'same') / np.maximum(w, 1e-9), 0.0) * ok
        d, along = {'top': (rows, cols), 'bottom': (H - 1 - rows, cols),
                    'left': (cols, rows), 'right': (W - 1 - cols, rows)}[edge]
        add[k] += delta[along] * np.clip(1 - d / band, 0, None)
    for k, f in faces.items():
        qq = np.where(q[k] > 0, q[k] + add[k], 0.0)
        f['r'] = np.where(qq > 0, 1.0 / np.maximum(qq, 1e-12), np.inf)


def read_sparse(txt, faces):
    """Poses and observed points of the named images, the centres of every face 1, and
    the 3D points they see, streamed from a text model (images.txt can be large)."""
    pose, obs, centres = {}, {}, []
    with open(os.path.join(txt, 'images.txt')) as fh:
        lines = (l for l in fh if not l.startswith('#'))
        for head in lines:
            pts = next(lines, '')
            p = head.split()
            if len(p) < 10:
                continue
            R = qvec2rot([float(v) for v in p[1:5]]); t = np.array([float(v) for v in p[5:8]])
            if p[-1].startswith('f1/'):
                centres.append(-R.T @ t)
            if p[-1] in faces:
                pose[p[-1]] = (R, t)
                q = pts.split()
                obs[p[-1]] = [(float(q[i]), float(q[i + 1]), int(q[i + 2])) for i in range(0, len(q), 3)
                              if q[i + 2] != '-1']
    want = {pid for o in obs.values() for _, _, pid in o}
    xyz = {}
    with open(os.path.join(txt, 'points3D.txt')) as fh:
        for l in fh:
            if not l.startswith('#'):
                p = l.split(maxsplit=4)
                if int(p[0]) in want:
                    xyz[int(p[0])] = np.array([float(v) for v in p[1:4]])
    return pose, obs, xyz, np.array(centres)


def read_ply_xyz(path):
    """x, y, z of a binary little-endian PLY's vertices (COLMAP's fused.ply, depth_fill.py's)."""
    with open(path, 'rb') as fh:
        props, n = [], 0
        while True:
            l = fh.readline().decode().strip()
            if l.startswith('element vertex'):
                n = int(l.split()[-1])
            elif l.startswith('property'):
                _, typ, name = l.split()
                props.append((name, {'float': '<f4', 'double': '<f8', 'uchar': 'u1', 'int': '<i4'}[typ]))
            elif l == 'end_header':
                break
        rec = np.fromfile(fh, dtype=np.dtype(props), count=n)
    return np.stack([rec['x'], rec['y'], rec['z']], 1).astype(np.float64)


def project_cloud(xyz, R, t, W, H, cell=4, min_count=2):
    """The nearest cloud point in each cell x cell block of a 90 degree face (pinhole,
    f = W / 2), where the block holds at least min_count: rows, columns (block centres), depths."""
    if not len(xyz):
        return np.zeros(0, int), np.zeros(0, int), np.zeros(0)
    c = xyz @ R.T + t
    c = c[c[:, 2] > 1e-6]
    u = c[:, 0] / c[:, 2] * (W / 2) + W / 2; v = c[:, 1] / c[:, 2] * (H / 2) + H / 2
    ok = (u >= 0) & (u < W) & (v >= 0) & (v < H)
    u, v, z = u[ok], v[ok], c[ok, 2]
    gw, gh = W // cell, H // cell
    idx = (v // cell).astype(int) * gw + (u // cell).astype(int)
    zmin = np.full(gw * gh, np.inf); np.minimum.at(zmin, idx, z)
    cnt = np.bincount(idx, minlength=gw * gh)
    good = np.nonzero((cnt >= min_count) & np.isfinite(zmin))[0]
    return (good // gw) * cell + cell // 2, (good % gw) * cell + cell // 2, zmin[good]


def compress_relief(q, factor=0.5, range_log=0.5, sigma_px=12, passes=2):
    """q (any inverse distance, 0 where nothing) with its fine relief scaled by
    factor. The log of q is split into a base, two passes of a bilateral
    filter (sigma_px across, range_log in log q, so a step of more than about
    1.6 times stays in the base: rails against the floor, the house against
    the sky), and the detail above it, which is scaled.

    Why: Depth Anything V2 reads lit rock as near and shaded rock as far, and
    drew MASS 84's rock wall as a slab per column, 2.4 to 3.6 in r_far / r
    along one row where the stereo measures 3.1 to 3.3; the slabs slid apart
    in the original and tore in the layered version. MoGe-2 drew them deeper,
    and holding the depth to the stereo blurred the rails, where the stereo
    is wrong (README). Halved, the slabs' steps are about a third of what
    they were. A rule, not a measurement: every fine relief is scaled, the
    real with the drawn."""
    import cv2
    ok = q > 0
    lq = np.log(np.where(ok, np.maximum(q, 1e-6), 1.0)).astype(np.float32)
    fill = float(np.median(lq[ok])) if ok.any() else 0.0
    lq0 = np.where(ok, lq, fill).astype(np.float32)
    base = lq0.copy()
    for _ in range(passes):
        base = cv2.bilateralFilter(base, -1, range_log, sigma_px)
    return np.where(ok, np.exp(base + factor * (lq0 - base)), 0.0)


def follow_stereo(d, s, ok, has, lam=1.0, sigma=0.1, rounds=3, tol=0.15):
    """Inverse depth that is d (the fitted network depth) plus a correction e,
    held to s (the stereo's, same units) at the pixels in `has`, over the
    pixels in `ok` (not sky). It minimises, over e, the sum over neighbouring
    pixel pairs of w_ij (e_i - e_j)^2 plus lam times the sum over measured
    pixels of c_i (e_i - (s_i - d_i))^2: a sparse linear system, solved
    directly (scipy). w_ij = exp(-(|d_i - d_j| / (sigma min(d_i, d_j)))^2),
    a step of sigma (10%) of the value, floored at 0.01,
    so the correction is smooth within each surface the network drew and free
    to change across its steps: each surface takes the level the stereo
    measured on it. Where the network split one surface into slabs (MASS 84's
    rock wall, a step at every column), each slab is brought to the stereo
    and the steps go; where it drew a real edge, the stereo has the same edge.
    The correction being smooth within a surface, a stereo pixel that leaves
    it (a reflection on the wet walkway) stands out; the c_i start at 1 and
    are reweighted (Cauchy, scale tol of the value) over `rounds` solves.
    Returns the new inverse depth (d where not ok) and the final weights."""
    import scipy.sparse as sp
    import scipy.sparse.linalg as spl
    H, W = d.shape
    idx = -np.ones((H, W), np.int64); idx[ok] = np.arange(int(ok.sum()))
    n = int(ok.sum())
    rows, cols, vals = [], [], []
    for (a0, a1), (b0, b1) in ((((slice(None), slice(1, None))), (slice(None), slice(None, -1))),
                               (((slice(1, None), slice(None))), (slice(None, -1), slice(None)))):
        pa, pb = idx[a0, a1], idx[b0, b1]
        m = (pa >= 0) & (pb >= 0)
        da, db = d[a0, a1], d[b0, b1]
        w = np.maximum(np.exp(-(np.abs(da - db) / (sigma * np.maximum(np.minimum(da, db), 1e-9))) ** 2), 0.01)[m]
        i, j = pa[m], pb[m]
        rows += [i, j, i, j]; cols += [i, j, j, i]; vals += [w, w, -w, -w]
    L = sp.csr_matrix((np.concatenate(vals), (np.concatenate(rows), np.concatenate(cols))), shape=(n, n))
    r = (s - d)[ok]
    meas = has[ok]
    c = meas.astype(float)
    e = np.zeros(n)
    for _ in range(rounds):
        A = L + sp.diags(lam * c + 1e-9)
        e = spl.spsolve(A.tocsc(), lam * c * r)
        rel = np.abs(e - r) / np.maximum(np.abs(s[ok]), 1e-9)
        c = np.where(meas, 1.0 / (1.0 + (rel / tol) ** 2), 0.0)
    out = d.copy(); out[ok] = d[ok] + e
    cw = np.zeros((H, W)); cw[ok] = c
    return out, cw


def joint_fit(meas, seams, w_seam, far=None, w_far=1.0, iters=8):
    """a, b per face (1-6) fitting 1/r = (a p + b) / n to meas[k] = (p, n, 1/r),
    (a_k p_k + b_k) / n_k = (a_j p_j + b_j) / n_j to seams = [(k, p, n, j, p2, n2) arrays],
    and (a p + b) / n = 0 to far[k] = (p, n): sky."""
    rows, ys, grp = [], [], []
    for k, (p, n, y) in meas.items():
        A = np.zeros((len(p), 12)); A[:, 2 * k - 2] = p / n; A[:, 2 * k - 1] = 1 / n
        rows.append(A); ys.append(y); grp.append(np.zeros(len(p), int))
    for k, (p, n) in (far or {}).items():
        A = np.zeros((len(p), 12)); A[:, 2 * k - 2] = p / n; A[:, 2 * k - 1] = 1 / n
        rows.append(A); ys.append(np.zeros(len(p))); grp.append(np.full(len(p), 2))
    k, p, n, j, p2, n2 = seams
    A = np.zeros((len(k), 12)); idx = np.arange(len(k))
    A[idx, 2 * k - 2] = p / n; A[idx, 2 * k - 1] = 1 / n
    A[idx, 2 * j - 2] -= p2 / n2; A[idx, 2 * j - 1] -= 1 / n2
    rows.append(A); ys.append(np.zeros(len(k))); grp.append(np.ones(len(k), int))
    A = np.concatenate(rows); y = np.concatenate(ys); g = np.concatenate(grp)
    base = np.select([g == 1, g == 2], [w_seam, w_far], 1.0)
    w = base.copy()
    for _ in range(iters):
        x = np.linalg.lstsq(A * w[:, None], y * w, rcond=None)[0]
        r = A @ x - y
        w = base.copy()
        for gi in (0, 1, 2):
            m = g == gi
            if not m.any():
                continue
            c = 2.0 * np.median(np.abs(r[m])) + 1e-12
            w[m] *= 1.0 / np.sqrt(1 + (r[m] / c) ** 2)
    return {kk: (x[2 * kk - 2], x[2 * kk - 1]) for kk in range(1, 7)}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('images'); ap.add_argument('node'); ap.add_argument('out')
    # the node as in the file names: ENSI's are 0016, which as a number loses its zeros
    ap.add_argument('--dense'); ap.add_argument('--sparse'); ap.add_argument('--cloud')
    ap.add_argument('--follow-stereo', type=float, default=0.0,
                    help='after the fit, hold each face to its own stereo depths with this weight (follow_stereo; 0: off)')
    ap.add_argument('--relief', type=float, default=1.0,
                    help="scale the depth's fine relief by this (compress_relief; 1: off), before the seams are blended")
    ap.add_argument('--edge-px', type=int, default=6, help="with --follow-stereo: stereo within this many px of the "
                    "network's own steps is not followed")
    ap.add_argument('--masks', help="sky_masks.py's folder (MASKS/f<k>/<name>.png, black on sky, sea, water): "
                    "stereo depths there are not followed")
    ap.add_argument('--pair-depths', action='append', default=[])
    ap.add_argument('--faces'); ap.add_argument('--names')
    ap.add_argument('--suffix', default='_measured-depth.png')
    ap.add_argument('--ratio', type=float, default=20.0)
    ap.add_argument('--seam-weight', type=float, default=1.0)
    ap.add_argument('--sky-weight', type=float, default=1.0)
    ap.add_argument('--band', type=int, default=48)
    ap.add_argument('--model', default='depth-anything/Depth-Anything-V2-Base-hf')
    ap.add_argument('--sky-model', default='nvidia/segformer-b2-finetuned-ade-512-512')
    a = ap.parse_args()
    if a.pair_depths and (a.dense or a.sparse or a.cloud):
        ap.error('--pair-depths has a scale of its own; not with --dense, --sparse or --cloud')
    if a.cloud and not a.sparse:
        ap.error('--cloud needs --sparse for the faces\' poses')
    os.makedirs(a.out, exist_ok=True)
    pair = {}
    for spec in a.pair_depths:
        k, path = spec.split(':', 1)
        pair[int(k)] = np.loadtxt(path, ndmin=2)

    import torch
    from transformers import (AutoImageProcessor, AutoModelForDepthEstimation,
                              SegformerForSemanticSegmentation, SegformerImageProcessor)
    dev = 'cuda' if torch.cuda.is_available() else 'cpu'
    proc = AutoImageProcessor.from_pretrained(a.model)
    net = AutoModelForDepthEstimation.from_pretrained(a.model).to(dev).eval()
    seg_proc = SegformerImageProcessor.from_pretrained(a.sky_model)
    seg = SegformerForSemanticSegmentation.from_pretrained(a.sky_model).to(dev).eval()
    sky_id = next(int(k) for k, v in seg.config.id2label.items() if v == 'sky')

    def look(img):
        """SegFormer's sky and Depth Anything's relative inverse depth for one picture."""
        W, H = img.size
        with torch.no_grad():
            logits = seg(**seg_proc(images=img, return_tensors='pt').to(dev)).logits
            sky = torch.nn.functional.interpolate(logits, size=(H, W), mode='bilinear',
                                                  align_corners=False).argmax(1)[0].cpu().numpy() == sky_id
            pred = net(**proc(images=img, return_tensors='pt').to(dev)).predicted_depth
            pred = torch.nn.functional.interpolate(pred[:, None], size=(H, W), mode='bicubic',
                                                   align_corners=False)[0, 0].float().cpu().numpy()
        return sky, pred

    alt = a.faces.split(',') if a.faces else [None] * 6
    names = a.names.split(',') if a.names else [None] * 6
    rels = {}
    for k in range(1, 7):
        own = glob.glob(os.path.join(a.images, f'f{k}', f'*-{a.node}.jpg'))[0]
        rels[k] = os.path.relpath(own, a.images).replace(os.sep, '/')
    pose, obs, xyz, spacing = {}, {}, {}, None
    if a.sparse:
        pose, obs, xyz, centres = read_sparse(a.sparse, set(rels.values()))
        spacing = float(np.median([np.sort(np.linalg.norm(centres - c, axis=1))[1] for c in centres]))
    cloud = read_ply_xyz(a.cloud) if a.cloud else np.zeros((0, 3))
    rng = np.random.default_rng(0)
    faces, report, meas = {}, {}, {}
    for k in range(1, 7):
        own = os.path.join(a.images, rels[k])
        img = Image.open(own).convert('RGB')
        W, H = img.size
        dpath = os.path.join(a.dense, 'stereo', 'depth_maps', rels[k] + '.geometric.bin') if a.dense else ''
        D = read_colmap_array(dpath) if os.path.exists(dpath) else np.zeros((H, W), np.float32)
        changed = np.zeros((H, W), bool)
        sky, pred = look(img)
        seg_sky = float(sky.mean())
        sv, su = np.nonzero(sky)
        if len(sv) > 2000:
            pick = rng.choice(len(sv), 2000, replace=False); sv, su = sv[pick], su[pick]
        if sky.mean() > 0.02:
            sky |= pred <= np.percentile(pred[sky], 99)
        s_, t_ = np.meshgrid((np.arange(W) + 0.5) / W, (np.arange(H) + 0.5) / H)
        norm = np.sqrt(1 + (2 * s_ - 1) ** 2 + (2 * t_ - 1) ** 2)    # radial distance / depth
        # measured: sparse points seen by this face, then stereo depths
        sp = []
        for x, y, z in pair.get(k, ()):                # pair_points.py: pixel and depth, own scale
            u, v = int(x), int(y)
            if 0 <= u < W and 0 <= v < H and not sky[v, u] and not changed[v, u] and z > 0:
                sp.append((v, u, z))
        R, t = pose.get(rels[k], (np.eye(3), np.zeros(3)))
        for x, y, pid in obs.get(rels[k], ()):
            u, v = int(x), int(y)
            if 0 <= u < W and 0 <= v < H and not sky[v, u] and not changed[v, u]:
                z = (R @ xyz[pid] + t)[2]
                if z > 0:
                    sp.append((v, u, z))
        sp = np.array(sp).reshape(-1, 3)
        vv, uu = np.nonzero((D > 0) & ~sky & ~changed)
        if len(vv) > 3000:
            pick = rng.choice(len(vv), 3000, replace=False); vv, uu = vv[pick], uu[pick]
        cv, cu, cz = project_cloud(cloud if rels[k] in pose else cloud[:0], R, t, W, H)
        keep = ~sky[cv, cu] & ~changed[cv, cu]
        cv, cu, cz = cv[keep], cu[keep], cz[keep]
        if len(cv) > 3000:
            pick = rng.choice(len(cv), 3000, replace=False); cv, cu, cz = cv[pick], cu[pick], cz[pick]
        V = np.concatenate([sp[:, 0].astype(int), vv, cv]); U = np.concatenate([sp[:, 1].astype(int), uu, cu])
        Z = np.concatenate([sp[:, 2], D[vv, uu], cz])
        meas[k] = (pred[V, U], norm[V, U], 1.0 / (Z * norm[V, U]))
        faces[k] = {'img': img, 'pred': pred, 'sky': sky, 'norm': norm, 'marks': (V, U), 'stereo': D,
                    'far': (pred[sv, su], norm[sv, su])}
        report[f'face{k}'] = {'image': rels[k], 'sparse_points': int(len(sp)), 'stereo_samples': int(len(vv)),
                              'cloud_cells': int(len(cv)),
                              'sky': round(float(sky.mean()), 4), 'sky_segformer': round(seg_sky, 4)}
        print(f'face {k}: sky {sky.mean() * 100:5.1f}% (SegFormer {seg_sky * 100:4.1f}%), {len(sp)} sparse or pair points, '
              f'{len(vv)} stereo depths, {len(cv)} cloud cells', flush=True)
    H, W = faces[1]['pred'].shape
    pairs = seam_pairs(W, H)
    sk = [[], [], [], [], [], []]
    for k in faces:
        for (v, u, j, v2, u2) in pairs[k]:
            if not faces[k]['sky'][v, u] and not faces[j]['sky'][v2, u2]:
                for lst, val in zip(sk, (k, faces[k]['pred'][v, u], faces[k]['norm'][v, u],
                                         j, faces[j]['pred'][v2, u2], faces[j]['norm'][v2, u2])):
                    lst.append(val)
    seams = tuple(np.array(l) for l in sk)
    seams = (seams[0].astype(int), seams[1], seams[2], seams[3].astype(int), seams[4], seams[5])
    # check: fit on half the measurements (and all seams), judged on the other half
    halves = {k: rng.random(len(m[0])) < 0.5 for k, m in meas.items()}
    far = {k: f['far'] for k, f in faces.items() if len(f['far'][0])}
    fit = joint_fit({k: tuple(c[halves[k]] for c in m) for k, m in meas.items()}, seams, a.seam_weight, far, a.sky_weight)
    for k, m in meas.items():
        p, n, y = (c[~halves[k]] for c in m)
        if len(p):
            aa, bb = fit[k]
            r_fit = n / np.maximum(aa * p + bb, 1e-9); r_meas = 1.0 / y
            err = np.abs(r_fit - r_meas) / r_meas
            report[f'face{k}'].update(check_median=round(float(np.median(err)), 4),
                                      check_p90=round(float(np.percentile(err, 90)), 4), check_n=int(len(p)))
    fit = joint_fit(meas, seams, a.seam_weight, far, a.sky_weight)
    for k, f in faces.items():
        aa, bb = fit[k]
        report[f'face{k}']['fit'] = [float(aa), float(bb)]
        inv = aa * f['pred'] + bb
        f['r'] = np.where((inv > 0) & ~f['sky'], f['norm'] / np.maximum(inv, 1e-12), np.inf)
        rec = report[f'face{k}']
        D = f['stereo']
        f['inv'] = inv; f['followed'] = False
        ok_k = (inv > 0) & ~f['sky']
        if a.follow_stereo > 0 and (D[ok_k] > 0).mean() >= 0.05:
            # The fit gives each face the network's shape with one scale and
            # offset; where the network split one surface into slabs (MASS
            # 84's rock wall: a step at every column, which the stereo does
            # not have) the steps stayed, in the original and as tears in the
            # layered version. Held to the stereo, each slab takes the level
            # measured on it.
            ok = (inv > 0) & ~f['sky']
            has = (D > 0) & ok
            if a.masks:
                mp = os.path.join(a.masks, rels[k] + '.png')
                if os.path.exists(mp):
                    has &= np.asarray(Image.open(mp).convert('L').resize((W, H), Image.NEAREST)) > 127
            # Not within --edge-px of the network's own steps (over 10% between
            # pixels 2 apart, on the depth after a 5 px median): stereo is
            # least sure at edges, and on thin things (rails, slats) it is all
            # edge; holding to it there blurred MASS 84's rails into blobs.
            # Those keep the network's shape, with the correction of what is
            # round them; a slab of the wall, wider, keeps stereo inside it.
            import cv2
            qmed = cv2.medianBlur(np.where(ok, inv, 0).astype(np.float32), 5)
            st = np.zeros(qmed.shape, bool)
            for dy, dx in ((0, 2), (2, 0)):
                o = np.roll(np.roll(qmed, -dy, 0), -dx, 1)
                st |= np.abs(qmed - o) > 0.1 * np.maximum(np.minimum(qmed, o), 1e-9)
            has &= ~(cv2.dilate(st.astype(np.uint8), np.ones((2 * a.edge_px + 1,) * 2, np.uint8)) > 0)
            before = np.abs(inv[has] - 1.0 / D[has]) * D[has]
            inv2, cw = follow_stereo(inv, np.where(D > 0, 1.0 / np.maximum(D, 1e-9), 0.0), ok, has, lam=a.follow_stereo)
            after = np.abs(inv2[has] - 1.0 / D[has]) * D[has]
            f['r'] = np.where((inv2 > 0) & ok, f['norm'] / np.maximum(inv2, 1e-12), np.inf)
            f['followed'] = True
            rec['follow_stereo'] = {'pixels': int(has.sum()), 'before_median': round(float(np.median(before)), 4),
                                    'before_p90': round(float(np.percentile(before, 90)), 4),
                                    'after_median': round(float(np.median(after)), 4),
                                    'after_p90': round(float(np.percentile(after, 90)), 4)}
            print(f'face {k}: held to {has.sum()} stereo depths: off by median {np.median(before) * 100:.1f}%, 90% '
                  f'{np.percentile(before, 90) * 100:.1f}% before; {np.median(after) * 100:.1f}%, '
                  f'{np.percentile(after, 90) * 100:.1f}% after', flush=True)
        print(f'face {k}: a {aa:.4g}, b {bb:.4g}' + (f'; checked on {rec["check_n"]} held-out measurements: median '
              f'{rec["check_median"] * 100:.1f}%, 90% within {rec["check_p90"] * 100:.1f}%' if 'check_n' in rec else
              '; nothing measured, from its seams'), flush=True)
    # Faces whose stereo was too sparse to follow (under 5% of what is not sky:
    # the floor, which no other node sees, the sky overhead with a few stray
    # depths on the roof's edge) were fitted to their neighbours before those
    # were held to their stereo, so the seams no longer met (MASS 84's floor
    # and face 3: 14% at the 90th percentile). They are held at their edges
    # to the neighbours as followed, by the same solve.
    if a.follow_stereo > 0 and any(f['followed'] for f in faces.values()):
        for k, f in faces.items():
            if f['followed']:
                continue
            ok = np.isfinite(f['r'])
            sv_ = np.zeros((H, W)); has = np.zeros((H, W), bool)
            for (v, u, j, v2, u2) in pairs[k]:
                rj = faces[j]['r'][v2, u2]
                if faces[j]['followed'] and np.isfinite(rj) and ok[v, u]:
                    sv_[v, u] = f['norm'][v, u] / rj; has[v, u] = True
            if has.sum() < 20:
                continue
            inv0 = np.where(ok, f['norm'] / np.where(ok, f['r'], 1.0), 0.0)
            inv2, _ = follow_stereo(inv0, sv_, ok, has, lam=a.follow_stereo)
            f['r'] = np.where(ok & (inv2 > 0), f['norm'] / np.maximum(inv2, 1e-12), np.inf)
            report[f'face{k}']['follow_seams'] = int(has.sum())
            print(f'face {k}: held at {has.sum()} edge pixels to its followed neighbours', flush=True)
    # the other pictures (--faces): where one differs from the node's own face, its own
    # network depth fitted to the node's distances over the pixels the two share
    for k, f in faces.items():
        if not alt[k - 1]:
            continue
        img2 = Image.open(alt[k - 1]).convert('RGB')
        diff = np.abs(np.asarray(img2, float) - np.asarray(f['img'], float)).max(2)
        changed = np.asarray(Image.fromarray(((diff > 30) * 255).astype(np.uint8)).filter(ImageFilter.MaxFilter(17))) > 0
        report[f'face{k}'].update(image=alt[k - 1], changed=round(float(changed.mean()), 4))
        f['img'] = img2
        if changed.mean() < 0.001:
            continue                                   # the same picture
        sky2, pred2 = look(img2)
        if sky2.mean() > 0.02:
            sky2 |= pred2 <= np.percentile(pred2[sky2], 99)
        use = ~changed & ~sky2 & np.isfinite(f['r'])
        x = pred2[use]; y = f['norm'][use] / f['r'][use]   # 1 / depth
        aa, bb = fit_inverse(x, y, rng)
        err = np.abs(f['norm'][use] / np.maximum(aa * x + bb, 1e-12) - f['r'][use]) / f['r'][use]
        inv = aa * pred2 + bb
        f['r'] = np.where((inv > 0) & ~sky2, f['norm'] / np.maximum(inv, 1e-12), np.inf)
        f['sky'] = sky2
        report[f'face{k}'].update(transfer_fit=[float(aa), float(bb)], transfer_median=round(float(np.median(err)), 4))
        print(f'face {k}: other picture, {changed.mean() * 100:.1f}% changed; its network depth fitted to the node\'s '
              f'on the rest: median {np.median(err) * 100:.1f}% off', flush=True)
    allr = np.concatenate([f['r'][::4, ::4].ravel() for f in faces.values()])
    r_near = float(np.percentile(allr, 0.5)); r_far = a.ratio * r_near

    def seam_steps():
        out = []
        for k in faces:
            for (v, u, k2, v2, u2) in pairs[k][::4]:
                r1, r2 = faces[k]['r'][v, u], faces[k2]['r'][v2, u2]
                if np.isfinite(r1) and np.isfinite(r2) and min(r1, r2) < r_far:
                    out.append(abs(r1 - r2) / min(r1, r2))
        out = np.array(out)
        return {'samples': int(len(out)), 'median': round(float(np.median(out)), 4) if len(out) else None,
                'p90': round(float(np.percentile(out, 90)), 4) if len(out) else None}
    if a.relief != 1.0:
        for k, f in faces.items():
            q = np.where(np.isfinite(f['r']), 1.0 / f['r'], 0.0)
            q2 = compress_relief(q, a.relief, sigma_px=12 * W / 640)
            f['r'] = np.where(q2 > 0, 1.0 / np.maximum(q2, 1e-12), np.inf)
        report['relief'] = a.relief
        print(f'fine relief scaled by {a.relief}', flush=True)
    before = seam_steps()
    feather(faces, W, H, a.band)
    after = seam_steps()
    report.update(node=a.node, node_spacing=spacing, r_near=r_near, r_near_spacings=r_near / spacing if spacing else None,
                  r_far=r_far, ratio=a.ratio, seams_fitted=before, seams=after, band=a.band)
    print((f'median node spacing {spacing:.3f}; r_near {r_near:.4f} ({r_near / spacing:.3f} of that)' if spacing else
           f'r_near {r_near:.4f} (scale of the measurements)') + f', r_far {r_far:.4f}; '
          f'seams as fitted: median step {before["median"]}, 90% within {before["p90"]}; '
          f'blended over {a.band} px: {after["median"]}, {after["p90"]}')
    tiles = []
    for k, f in faces.items():
        d = np.clip((r_far / f['r'] - 1) / (a.ratio - 1), 0, 1)
        g = Image.fromarray(np.round(d * 255).astype(np.uint8), 'L')
        name = names[k - 1] or f'face{k}'
        g.save(os.path.join(a.out, name + a.suffix))
        shown = np.asarray(f['img']).copy()
        mv, mu = f['marks']
        shown[mv, mu] = (255, 0, 0)                   # where something was measured
        tile = Image.new('RGB', (W * 2, H)); tile.paste(Image.fromarray(shown), (0, 0)); tile.paste(g.convert('RGB'), (W, 0))
        tiles.append(tile.resize((W, H // 2)))
    sheet = Image.new('RGB', (tiles[0].width * 2, tiles[0].height * 3))
    for i, tl in enumerate(tiles):
        sheet.paste(tl, ((i % 2) * tl.width, (i // 2) * tl.height))
    sheet.save(os.path.join(a.out, 'preview.jpg'), quality=85)
    with open(os.path.join(a.out, 'node_depth.json'), 'w') as fh:
        json.dump(report, fh, indent=1)


if __name__ == '__main__':
    main()
