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

from node_depth import feather

RATIO = 20.0


def predict(net, proc, img, size, inp):
    import torch
    x = proc(images=img, return_tensors='pt', size={'height': inp, 'width': inp},
             do_resize=True, keep_aspect_ratio=False)
    with torch.no_grad():
        p = net(**x.to(net.device)).predicted_depth
        p = torch.nn.functional.interpolate(p[:, None], size=(size, size), mode='bicubic', align_corners=False)
    return p[0, 0].cpu().numpy().astype(np.float64)


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
    SegFormer (ADE20K) finds lamps, lights, chandeliers and sconces; each
    piece takes the nearer end (90th percentile of r_far / r) of the solid
    things in a ring round it, where that is nearer than its own."""
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
    lamp = cv2.dilate(lamp.astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
    n, comp = cv2.connectedComponents(lamp.astype(np.uint8), connectivity=8)
    out, filled = q.copy(), 0
    for c in range(1, n):
        m = comp == c
        ring = (cv2.dilate(m.astype(np.uint8), np.ones((31, 31), np.uint8)) > 0) & ~m & (q >= 1)
        if ring.sum() < 20:
            continue
        qf = np.percentile(q[ring], 90)
        upd = m & (out < qf)
        out[upd] = qf; filled += int(upd.sum())
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
    for k, name in enumerate(a.names, 1):
        img = Image.open(os.path.join(a.site, name + a.colour_suffix)).convert('RGB').resize((N, N), Image.LANCZOS)
        img.save(os.path.join(a.out, name + '_sharp-colour.png'))
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
        qn, lit = light_fill(img, qn, seg, seg_proc)
        if lit:
            print(f'{name}: {lit} px of lamps and lights set to the depth round them')
            report.setdefault(name, {})['lights_filled_px'] = lit
        faces[k] = {'r': np.where(qn >= 1, 1.0 / np.maximum(qn, 1e-12), np.inf)}
    feather(faces, N, N, a.band)
    for k, name in enumerate(a.names, 1):
        qn = np.where(np.isfinite(faces[k]['r']), 1.0 / faces[k]['r'], 0.0)
        d = np.clip((qn - 1) / (RATIO - 1), 0, 1)
        Image.fromarray(np.rint(d * 255).astype(np.uint8)).save(os.path.join(a.out, name + a.out_suffix))
    with open(os.path.join(a.out, 'sharpen_depth.json'), 'w') as fh:
        json.dump({'model': a.model, 'input': a.input, 'size': N, 'faces': report}, fh, indent=1)


if __name__ == '__main__':
    main()
