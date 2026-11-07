#!/usr/bin/env python3
"""
Fill the gaps of a dense reconstruction with learned depth, scaled to COLMAP's.

    python depth_fill.py DENSE_DIR SPARSE_TXT OUT.ply [--model depth-anything/Depth-Anything-V2-Base-hf]
                         [--max-depth 15] [--stride 3] [--neighbours 8] [--report OUT.json]

DENSE_DIR is run_dense.ps1's workspace (images/ and stereo/depth_maps/, with
COLMAP's geometric depth map per face); SPARSE_TXT the sparse model as text, for
each face's pose.

For each face: Depth Anything V2 gives a relative inverse depth for every pixel
(it knows nothing of scale or offset). Where COLMAP's depth map has a value, the
two are fitted, 1/depth = a x network + b, by least squares with the worst fifth
dropped and refitted three times. Where COLMAP has no value, the fitted depth
is used, if it is nearer than --max-depth times the median spacing of the nodes
and no farther than the farthest 2% of COLMAP's depths on that face: beyond what
COLMAP measured the fit only extrapolates, and gives the sky a depth (the sky and
the far sea have no depth worth having; the node's own faces show them, see
viewer/). Those pixels, every --stride-th in each direction, are turned
into points with the face's colours. Faces with fewer than 500 COLMAP depths
cannot be scaled and are skipped.

Sky: a semantic segmentation network (--sky-model, SegFormer trained on ADE20K)
marks each face's sky. Sky pixels are never filled, COLMAP's depths there (on
textured clouds) are not used in the fit, and in the agreement test below a face
counts as seeing nothing near in its sky.

Agreement between nodes: a candidate point from one node is looked at from every
face of the --neighbours nearest other nodes. It is supported where such a face
sees something at the same depth in that direction (COLMAP's depth, or that
face's own fitted depth, within 10%), and contradicted where it would hide what
the face sees (nearer than 85% of it, including where the face sees nothing
near: sky, far sea). Kept: supported at least once, and contradicted no more
often than supported. Two networks' guesses from different nodes rarely agree
by chance, so this keeps what the views share and drops the sheets a single
guess puts across the sky.

The check: each face's fit is made on half of its COLMAP depths, chosen at random,
and judged on the other half: the median and 90th percentile of
|fitted - COLMAP| / COLMAP. These are printed per face and in total, and go to
--report. The fill can only be as good as that.

Writes OUT.ply (binary, x y z and red green blue, as COLMAP's fused.ply). Needs
numpy, Pillow, torch and transformers.
"""
import argparse
import json
import math
import os
import re
import sys

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from evaluate_model import qvec2rot  # noqa: E402


def read_colmap_array(path):
    with open(path, 'rb') as fh:
        w, h, c = (int(v) for v in fh.read(64).split(b'&')[:3])
        fh.seek(0)
        n = 0
        while n < 3:                                  # skip the 'w&h&c&' header
            if fh.read(1) == b'&':
                n += 1
        a = np.fromfile(fh, np.float32)
    return np.transpose(a.reshape((w, h, c), order='F'), (1, 0, 2)).squeeze()


def read_poses(txt_dir):
    out = {}
    lines = [l for l in open(os.path.join(txt_dir, 'images.txt')) if not l.startswith('#')]
    for l in lines[::2]:
        p = l.split()
        if len(p) >= 10:
            out[p[-1]] = (qvec2rot([float(v) for v in p[1:5]]), np.array([float(v) for v in p[5:8]]))
    return out


def fit_inverse(x, y, rng):
    """a, b with y ~ a x + b: least squares, dropping the worst fifth, three times."""
    keep = np.ones(len(x), bool)
    for _ in range(4):
        A = np.stack([x[keep], np.ones(keep.sum())], 1)
        a, b = np.linalg.lstsq(A, y[keep], rcond=None)[0]
        r = np.abs(a * x + b - y)
        keep = r <= np.percentile(r, 80)
    return a, b


def write_ply(path, xyz, rgb):
    with open(path, 'wb') as fh:
        fh.write((f'ply\nformat binary_little_endian 1.0\nelement vertex {len(xyz)}\n'
                  'property float x\nproperty float y\nproperty float z\n'
                  'property uchar red\nproperty uchar green\nproperty uchar blue\nend_header\n').encode())
        rec = np.zeros(len(xyz), dtype=[('x', '<f4'), ('y', '<f4'), ('z', '<f4'),
                                        ('red', 'u1'), ('green', 'u1'), ('blue', 'u1')])
        rec['x'], rec['y'], rec['z'] = xyz[:, 0], xyz[:, 1], xyz[:, 2]
        rec['red'], rec['green'], rec['blue'] = rgb[:, 0], rgb[:, 1], rgb[:, 2]
        fh.write(rec.tobytes())


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('dense'); ap.add_argument('sparse_txt'); ap.add_argument('out')
    ap.add_argument('--model', default='depth-anything/Depth-Anything-V2-Base-hf')
    ap.add_argument('--max-depth', type=float, default=15.0, help='in median node spacings')
    ap.add_argument('--stride', type=int, default=3)
    ap.add_argument('--report')
    ap.add_argument('--neighbours', type=int, default=8)
    ap.add_argument('--sky-model', default='nvidia/segformer-b2-finetuned-ade-512-512',
                    help="a semantic segmentation model with a 'sky' class; '' to not look for sky")
    a = ap.parse_args()

    import torch
    from transformers import AutoImageProcessor, AutoModelForDepthEstimation
    dev = 'cuda' if torch.cuda.is_available() else 'cpu'
    proc = AutoImageProcessor.from_pretrained(a.model)
    net = AutoModelForDepthEstimation.from_pretrained(a.model).to(dev).eval()

    seg = seg_proc = sky_id = None
    if a.sky_model:
        from transformers import SegformerForSemanticSegmentation, SegformerImageProcessor
        seg_proc = SegformerImageProcessor.from_pretrained(a.sky_model)
        seg = SegformerForSemanticSegmentation.from_pretrained(a.sky_model).to(dev).eval()
        sky_id = next(int(k) for k, v in seg.config.id2label.items() if v == 'sky')

    def sky_mask(img):
        with torch.no_grad():
            logits = seg(**seg_proc(images=img, return_tensors='pt').to(dev)).logits
            lab = torch.nn.functional.interpolate(logits, size=img.size[::-1], mode='bilinear',
                                                  align_corners=False).argmax(1)[0].cpu().numpy()
        return lab == sky_id

    poses = read_poses(a.sparse_txt)
    centres = {}
    for name, (R, t) in poses.items():
        if name.startswith('f1/'):
            centres[int(re.search(r'-(\d+)\.jpg$', name).group(1))] = -R.T @ t
    step = float(np.median([min(np.linalg.norm(c - d) for m, d in centres.items() if m != n)
                            for n, c in centres.items()]))
    rng = np.random.default_rng(0)
    report, all_err = {}, []
    obs, cands, node_of = {}, {}, {}
    SUB = 4                                          # observed-depth maps kept at a quarter size
    for name in sorted(poses):
        node = int(re.search(r'-(\d+)\.jpg$', name).group(1))
        node_of[name] = node
        dpath = os.path.join(a.dense, 'stereo', 'depth_maps', name + '.geometric.bin')
        if not os.path.exists(dpath):
            continue
        D = read_colmap_array(dpath)
        img = Image.open(os.path.join(a.dense, 'images', name)).convert('RGB')
        W, H = img.size
        sky = sky_mask(img) if seg is not None else np.zeros((H, W), bool)
        valid = (D > 0) & ~sky                        # COLMAP's depths on clouds are not geometry
        if valid.sum() < 500:                         # cannot be scaled: what it sees is unknown, but sky
            report[name] = {'colmap_pixels': int(valid.sum()), 'sky': float(sky.mean()), 'skipped': True}
            obs[name] = np.where(valid, D, np.where(sky, np.inf, np.nan))[::SUB, ::SUB]
            continue
        with torch.no_grad():
            inp = proc(images=img, return_tensors='pt').to(dev)
            pred = net(**inp).predicted_depth
            pred = torch.nn.functional.interpolate(pred[:, None], size=(H, W), mode='bicubic',
                                                   align_corners=False)[0, 0].float().cpu().numpy()
        x, y = pred[valid], 1.0 / D[valid]
        half = rng.random(len(x)) < 0.5
        aa, bb = fit_inverse(x[half], y[half], rng)
        test = 1.0 / np.maximum(aa * x[~half] + bb, 1e-9)
        err = np.abs(test - D[valid][~half]) / D[valid][~half]
        all_err.append(err)
        aa, bb = fit_inverse(x, y, rng)               # the fill uses every COLMAP depth
        inv = aa * pred + bb
        Df = np.where(inv > 0, 1.0 / np.maximum(inv, 1e-9), np.inf)
        eligible = np.isfinite(Df) & (Df < a.max_depth * step) & ~sky
        eligible &= pred >= np.percentile(x, 2)      # no farther than COLMAP measured on this face:
                                                     # beyond it (sky, far sea) the fit only extrapolates
        # what this face sees: COLMAP's depth, else its own fill, else nothing near (inf)
        obs[name] = np.where(valid, D, np.where(eligible, Df, np.inf))[::SUB, ::SUB]
        fill = (~valid) & eligible
        sub = np.zeros_like(fill)
        sub[::a.stride, ::a.stride] = True
        fill &= sub
        v, u = np.nonzero(fill)
        z = Df[v, u]
        cam = np.stack([(u + 0.5 - W / 2) / (W / 2) * z, (v + 0.5 - H / 2) / (H / 2) * z, z], 1)
        R, t = poses[name]
        cands[name] = ((cam - t) @ R, np.asarray(img)[v, u])   # R^T (X_cam - t)
        report[name] = {'colmap_pixels': int(valid.sum()), 'sky': float(sky.mean()), 'candidates': int(len(z)),
                        'check_median': float(np.median(err)), 'check_p90': float(np.percentile(err, 90))}
        print(f'{name}: sky {sky.mean() * 100:5.1f}%, COLMAP {valid.mean() * 100:5.1f}% of pixels; fit checked on held-out half: '
              f'median {np.median(err) * 100:5.1f}%, 90% within {np.percentile(err, 90) * 100:5.1f}%; '
              f'{len(z)} candidates', flush=True)

    # agreement between nodes: each candidate seen from the faces of the nearest other nodes
    near = {n: sorted((m for m in centres if m != n), key=lambda m: np.linalg.norm(centres[m] - centres[n]))[:a.neighbours]
            for n in centres}
    faces_of = {}
    for name in obs:
        faces_of.setdefault(node_of[name], []).append(name)
    pts, cols = [], []
    for name, (P, C) in cands.items():
        sup = np.zeros(len(P), int); con = np.zeros(len(P), int)
        for m in near[node_of[name]]:
            for other in faces_of.get(m, []):
                R, t = poses[other]
                O = obs[other]
                h, w = O.shape
                Xc = P @ R.T + t
                z = Xc[:, 2]
                ok = z > 1e-6
                u = np.full(len(P), -1); v = np.full(len(P), -1)
                u[ok] = np.floor((Xc[ok, 0] / z[ok] + 1) * w / 2).astype(int)
                v[ok] = np.floor((Xc[ok, 1] / z[ok] + 1) * h / 2).astype(int)
                ins = ok & (u >= 0) & (u < w) & (v >= 0) & (v < h)
                o = np.full(len(P), np.nan)
                o[ins] = O[v[ins], u[ins]]
                known = ins & ~np.isnan(o)
                fin = known & np.isfinite(o)
                sup[fin] += (np.abs(z[fin] - o[fin]) < 0.1 * o[fin])
                con[known] += z[known] < 0.85 * o[known]          # it would hide what that face sees
        keep = (sup >= 1) & (con <= sup)
        pts.append(P[keep]); cols.append(C[keep])
        report[name].update({'kept': int(keep.sum())})
    total_c = sum(len(P) for P, _ in cands.values())
    total_k = sum(len(p) for p in pts)
    print(f'candidates {total_c}; kept {total_k} ({total_k / max(1, total_c) * 100:.0f}%): seen at the same depth '
          f'(within 10%) by at least one of the {a.neighbours} nearest nodes, and contradicted by no more than support')
    e = np.concatenate(all_err)
    print(f'all faces: held-out error median {np.median(e) * 100:.1f}%, 90% within {np.percentile(e, 90) * 100:.1f}%')
    xyz, rgb = np.concatenate(pts), np.concatenate(cols)
    write_ply(a.out, xyz, rgb)
    print(f'{len(xyz)} fill points written to {a.out}')
    if a.report:
        json.dump({'step': step, 'max_depth_steps': a.max_depth, 'faces': report,
                   'held_out_median': float(np.median(e)), 'held_out_p90': float(np.percentile(e, 90))},
                  open(a.report, 'w'), indent=0)


if __name__ == '__main__':
    main()
