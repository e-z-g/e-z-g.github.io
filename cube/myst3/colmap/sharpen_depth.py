#!/usr/bin/env python3
"""
Sharper depth for a site node: node_depth.py's measured depth, redrawn at a
higher resolution with outlines that follow the picture.

    python sharpen_depth.py SITE_DIR OUT_DIR [--names MAWWnodes-8 ... (six, node_depth's
        face order)] [--size 1280] [--input 1036] [--colour-suffix _seamless.webp]
        [--depth-suffix _measured-depth.png] [--out-suffix _sharp-depth.png]
        [--model depth-anything/Depth-Anything-V2-Large-hf] [--band 96]

Why. node_depth.py fits Depth Anything's prediction, made at the model's own
input size of 518 px, to measurements, at the 640 px of the captured faces. Its
outlines are rounder than the picture: on MAWW 101 the spire roof's eaves reach
some 10 px past the depth's outline, so in the two-layer version they stayed at
sky depth and were left behind in blocks when the roof moved. Run on the 4K
faces (the site's AI-upscaled `_seamless.webp`, reduced to --size) at an input
of 1036 px, Large's outlines follow the eaves.

How. For each face, the new prediction p is fitted to the measured depth: 1/z
= a p + b (z along the face's axis; the measured maps store 1/r in units of
the farthest kept distance, d = (r_far/r - 1)/19), by least squares with
Cauchy weights, over pixels away from the measured map's outlines (whose
place is the thing being corrected), with the measured sky held at 1/z = 0. So
the scale stays the measurement's and only the shape comes from the new
prediction. The six faces are then closed at their seams (node_depth.feather,
over --band px) and written in the measured maps' encoding, plus OUT_DIR/
<name>_sharp-colour.png, the picture the depth was predicted from.
Needs numpy, Pillow, opencv-python, torch, transformers; node_depth.py beside it.
"""
import argparse
import json
import os

import cv2
import numpy as np
from PIL import Image

from node_depth import edge_pairs, feather, follow_stereo

RATIO = 20.0


def predict(net, proc, img, size, inp):
    import torch
    x = proc(images=img, return_tensors='pt', size={'height': inp, 'width': inp},
             do_resize=True, keep_aspect_ratio=False)
    with torch.no_grad():
        p = net(**x.to(net.device)).predicted_depth
        p = torch.nn.functional.interpolate(p[:, None], size=(size, size), mode='bicubic', align_corners=False)
    return p[0, 0].cpu().numpy().astype(np.float64)


def seam_steps(qs, N):
    """Relative step in r_far / r across every seam where both sides have depth:
    median and 90th percentile, before any blending."""
    rel = []
    for (k, edge), e in edge_pairs(N, N).items():
        v, u, j, v2, u2 = e.T
        q1 = qs[k][v, u]; q2 = np.array([qs[jj][vv, uu] for jj, vv, uu in zip(j, v2, u2)])
        ok = (q1 > 0) & (q2 > 0)
        rel.append(np.abs(q1[ok] - q2[ok]) / ((q1[ok] + q2[ok]) / 2))
    rel = np.concatenate(rel)
    return float(np.median(rel) * 100), float(np.percentile(rel, 90) * 100)


def padded(imgs, k, N, pad):
    """Face k with pad px of its neighbours round it, as one picture."""
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'layers'))
    from build_layers import pad_lookup
    kk, row, col = pad_lookup(k, N, pad)
    stack = np.stack([np.asarray(imgs[i]) for i in range(1, 7)])
    return Image.fromarray(stack[kk - 1, row, col])


def fit(p, t, w, iters=8):
    """t = a p + b by least squares with Cauchy weights on the residual."""
    a, b = 1.0, 0.0
    ww = w.copy()
    for _ in range(iters):
        A = np.stack([p * np.sqrt(ww), np.sqrt(ww)], 1)
        (a, b), *_ = np.linalg.lstsq(A, t * np.sqrt(ww), rcond=None)
        r = a * p + b - t
        s = 1.4826 * np.median(np.abs(r[w > 0])) + 1e-9
        ww = w / (1 + (r / (2.385 * s)) ** 2)
    return a, b


LIGHTS = ('lamp', 'light', 'chandelier', 'sconce', 'lantern')


def light_fill(img, q, seg, seg_proc):
    """Lamps and lights at the depth of what they hang from. Depth Anything
    reads a glowing glass as far off, as light sources often are, so MASS 84's
    lantern stayed with the sky while its dark cap moved with the post.
    SegFormer (ADE20K) finds lamps, lights, chandeliers and sconces; within
    each under 4% of the face, pixels as bright as its glow (over 0.8 of its
    99th percentile of lightness) whose r_far / r is under 0.6 of the light's
    nearer part (its 90th percentile) take that value.

    On MASS 84 itself it did harm: SegFormer called the far post's blue flame
    a light, the piece took in the rails crossing it, and 2,148 px of the
    flame were pulled forward to the rails' depth, so as the eye moved the
    flame slid off its post; and the lamp glass was not among the pixels
    filled. That node is built with --no-lights and build_layers.py --light."""
    import cv2
    import torch
    ids = [int(i) for i, l in seg.config.id2label.items() if any(w in l for w in LIGHTS)]
    with torch.no_grad():
        x = seg_proc(images=img, return_tensors='pt').to(seg.device)
        lab = torch.nn.functional.interpolate(seg(**x).logits, size=q.shape, mode='bilinear',
                                              align_corners=False).argmax(1)[0].cpu().numpy()
    lamp = np.isin(lab, ids)
    if not lamp.any():
        return q, 0
    n, comp = cv2.connectedComponents(lamp.astype(np.uint8), connectivity=8)
    rgb = np.asarray(img.convert('RGB'), dtype=np.float32)
    lum = 0.299 * rgb[..., 0] + 0.587 * rgb[..., 1] + 0.114 * rgb[..., 2]
    out, filled = q.copy(), 0
    for c in range(1, n):
        m = comp == c
        # Lamps are small: a large lit area (J'nanin's hut, whose windows and
        # roof glow) is left alone, and the light's own pixels are used as
        # SegFormer gives them, since grown by a few px they took in the cliff
        # beside the roof and pulled it forward in white specks.
        if m.sum() < 20 or m.sum() > 0.04 * m.size:
            continue
        # Within the light itself: pixels reading far behind its nearer part
        # (MASS 84's lantern: the cap at r_far/r 2.7, a quarter of the glowing
        # glass at 1, the sky) take that part's depth. Compared with a ring
        # round it instead, the lantern hung against the sky passed for
        # nothing wrong, and J'nanin's lit windows were pulled forward.
        qn = np.percentile(q[m], 90)
        # and only the glow: SegFormer's streetlight is the whole post, and
        # the sky between it and the rails reads far too (pulled forward, it
        # broke MASS 84's overhead rails into dashes); the glass is the
        # brightest thing in the piece.
        upd = m & (q < 0.6 * qn) & (lum > 0.8 * np.percentile(lum[m], 99))
        out[upd] = qn; filled += int(upd.sum())
    return out, filled


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('site'); ap.add_argument('out')
    ap.add_argument('--names', nargs=6, default=[f'MAWWnodes-{n}' for n in range(8, 14)])
    ap.add_argument('--size', type=int, default=1280); ap.add_argument('--input', type=int, default=1036)
    ap.add_argument('--colour-suffix', default='_seamless.webp')
    ap.add_argument('--depth-suffix', default='_measured-depth.png')
    ap.add_argument('--out-suffix', default='_sharp-depth.png')
    ap.add_argument('--model', default='depth-anything/Depth-Anything-V2-Large-hf')
    ap.add_argument('--band', type=int, default=96)
    ap.add_argument('--seg-model', default='nvidia/segformer-b2-finetuned-ade-512-512')
    ap.add_argument('--follow-measured', type=float, default=0.0,
                    help='after the fit, hold the new depth to the measured one away from its outlines with this '
                         "weight (node_depth.follow_stereo; 0: off): the fit's one scale and offset leaves the "
                         "network's own slabs, which the measured depth no longer has once node_depth.py "
                         '--follow-stereo has taken them out')
    ap.add_argument('--no-lights', action='store_true',
                    help="leave out light_fill (on MASS 84 it pulled the far post's blue flame forward to the rails crossing it; "
                         "build_layers.py --light places that node's lamp glass instead)")
    ap.add_argument('--pad', type=float, default=0.0,
                    help='predict each face padded with this share of its size from its neighbours, then crop '
                         '(0: each face alone, as the site builds were made)')
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    import torch
    from transformers import AutoImageProcessor, AutoModelForDepthEstimation
    proc = AutoImageProcessor.from_pretrained(a.model)
    net = AutoModelForDepthEstimation.from_pretrained(a.model).to('cuda' if torch.cuda.is_available() else 'cpu').eval()
    from transformers import SegformerForSemanticSegmentation, SegformerImageProcessor
    seg_proc = SegformerImageProcessor.from_pretrained(a.seg_model)
    seg = SegformerForSemanticSegmentation.from_pretrained(a.seg_model).to(net.device).eval()
    N = a.size
    u = (np.arange(N) + 0.5) / N
    s, t = np.meshgrid(u, u)
    ray = np.sqrt(1 + (2 * s - 1) ** 2 + (1 - 2 * t) ** 2)     # r / z on a 90-degree face
    faces, report = {}, {}
    imgs = {k: Image.open(os.path.join(a.site, name + a.colour_suffix)).convert('RGB').resize((N, N), Image.LANCZOS)
            for k, name in enumerate(a.names, 1)}
    PADPX = int(round(a.pad * N))
    for k, name in enumerate(a.names, 1):
        img = imgs[k]
        img.save(os.path.join(a.out, name + '_sharp-colour.png'))
        if PADPX:
            # Depth Anything sees across the seams, so the six predictions agree
            # there instead of each guessing what lies past its own edge.
            big = N + 2 * PADPX
            inp = int(round(a.input * big / N / 14)) * 14
            p = predict(net, proc, padded(imgs, k, N, PADPX), big, inp)[PADPX:PADPX + N, PADPX:PADPX + N]
        else:
            p = predict(net, proc, img, N, a.input)
        d8 = np.asarray(Image.open(os.path.join(a.site, name + a.depth_suffix)).convert('L'))
        dm = cv2.resize(d8.astype(np.float32), (N, N), interpolation=cv2.INTER_LINEAR) / 255
        sky = cv2.resize((d8 == 0).astype(np.uint8), (N, N), interpolation=cv2.INTER_NEAREST) > 0
        q = 1 + (RATIO - 1) * dm                                 # r_far / r
        # Away from the measured outlines: not within 12 px of a steep place or of the sky.
        g = np.hypot(*np.gradient(q))
        edge = cv2.dilate(((g > 0.15) | sky).astype(np.uint8), np.ones((25, 25), np.uint8)) > 0
        solid = ~edge
        skyc = cv2.erode(sky.astype(np.uint8), np.ones((25, 25), np.uint8)) > 0
        step = 3                                                  # every third pixel is plenty
        sel = np.zeros((N, N), bool); sel[::step, ::step] = True
        m1 = sel & solid; m2 = sel & skyc
        P = np.concatenate([p[m1], p[m2]])
        T = np.concatenate([(q * ray)[m1], np.zeros(m2.sum())])      # 1/z, in units of 1/r_far
        W = np.concatenate([np.ones(m1.sum()), np.full(m2.sum(), 0.2 * max(1, m1.sum()) / max(1, m2.sum()))])
        if m1.sum() < 100:                                       # a face of sky
            qn = np.zeros((N, N))
            report[name] = {'sky_only': True}
        else:
            A, B = fit(P, T, W)
            qn = (A * p + B) / ray
            rel = np.abs(qn[m1] - q[m1]) / q[m1]
            report[name] = {'a': float(A), 'b': float(B), 'points': int(m1.sum()),
                            'vs_measured_median_pct': float(np.median(rel) * 100),
                            'vs_measured_p90_pct': float(np.percentile(rel, 90) * 100)}
            print(f'{name}: 1/z = {A:.4g} p + {B:.4g} over {m1.sum()} px; against the measured depth '
                  f'median {np.median(rel) * 100:.1f}%, 90% within {np.percentile(rel, 90) * 100:.1f}%')
        if a.follow_measured > 0 and m1.sum() >= 100:
            okn = (qn > 1e-6) & ~skyc
            hasn = solid & (q > 0) & okn
            qn2, _ = follow_stereo(qn, q, okn, hasn, lam=a.follow_measured)
            rel0 = np.abs(qn[hasn] - q[hasn]) / q[hasn]; rel1 = np.abs(qn2[hasn] - q[hasn]) / q[hasn]
            print(f'{name}: held to the measured depth over {hasn.sum()} px: off by median {np.median(rel0) * 100:.1f}%, '
                  f'90% {np.percentile(rel0, 90) * 100:.1f}% before; {np.median(rel1) * 100:.1f}%, '
                  f'{np.percentile(rel1, 90) * 100:.1f}% after')
            report[name]['follow_measured'] = {'median_before': float(np.median(rel0)), 'median_after': float(np.median(rel1))}
            qn = np.where(okn, qn2, qn)
        qn, lit = (qn, 0) if a.no_lights else light_fill(img, qn, seg, seg_proc)
        if lit:
            print(f'{name}: {lit} px of lamps and lights set to the depth round them')
            report.setdefault(name, {})['lights_filled_px'] = lit
        faces[k] = {'r': np.where(qn >= 1, 1.0 / np.maximum(qn, 1e-12), np.inf)}
    qs = {k: np.where(np.isfinite(f['r']), 1.0 / f['r'], 0.0) for k, f in faces.items()}
    med, p90 = seam_steps(qs, N)
    print(f'seams before blending: median step {med:.1f}%, 90% within {p90:.1f}% (pad {a.pad})')
    report['seams_before_blending'] = {'median_pct': med, 'p90_pct': p90, 'pad': a.pad}
    feather(faces, N, N, a.band)
    for k, name in enumerate(a.names, 1):
        qn = np.where(np.isfinite(faces[k]['r']), 1.0 / faces[k]['r'], 0.0)
        d = np.clip((qn - 1) / (RATIO - 1), 0, 1)
        Image.fromarray(np.rint(d * 255).astype(np.uint8)).save(os.path.join(a.out, name + a.out_suffix))
    with open(os.path.join(a.out, 'sharpen_depth.json'), 'w') as fh:
        json.dump({'model': a.model, 'input': a.input, 'size': N, 'faces': report}, fh, indent=1)


if __name__ == '__main__':
    main()
