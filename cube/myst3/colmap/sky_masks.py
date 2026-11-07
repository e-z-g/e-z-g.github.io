#!/usr/bin/env python3
"""
Masks that keep sky and open water out of COLMAP's features.

    python sky_masks.py IMAGES LIST MASKS [--classes sky,sea,water] [--grow 6]
                        [--model nvidia/segformer-b2-finetuned-ade-512-512]

LIST names images relative to IMAGES (video_frames.py's list.txt). For each, SegFormer
(ADE20K) labels every pixel; the classes given are black in MASKS/<name>.png and
everything else white, which is what feature_extractor --ImageReader.mask_path
reads (features on black pixels are not extracted). The black is grown by --grow
pixels so cloud edges against a structure go too.

Why: a movie frame and a node face match well on the sky, which looks the same
from every point in the age, and on the sea that mirrors it. Such matches fix
which way a picture looks but not where it was taken; when the ride (MATO 24007)
was registered with them, eight nodes of five rooms were put within 0.15 node
spacings of one another. Prints the share of each image masked. Needs numpy,
Pillow, torch, transformers.
"""
import argparse
import os

import numpy as np
from PIL import Image, ImageFilter


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('images'); ap.add_argument('list'); ap.add_argument('masks')
    ap.add_argument('--classes', default='sky,sea,water')
    ap.add_argument('--grow', type=int, default=6)
    ap.add_argument('--model', default='nvidia/segformer-b2-finetuned-ade-512-512')
    ap.add_argument('--batch', type=int, default=16)
    a = ap.parse_args()
    import torch
    from transformers import SegformerForSemanticSegmentation, SegformerImageProcessor
    dev = 'cuda' if torch.cuda.is_available() else 'cpu'
    proc = SegformerImageProcessor.from_pretrained(a.model)
    seg = SegformerForSemanticSegmentation.from_pretrained(a.model).to(dev).eval()
    want = {c.strip() for c in a.classes.split(',')}
    ids = [int(k) for k, v in seg.config.id2label.items() if v in want]
    missing = want - {seg.config.id2label[i] for i in ids}
    if missing:
        raise SystemExit(f'not classes of {a.model}: {sorted(missing)}')
    names = [l.strip() for l in open(a.list) if l.strip()]
    shares = []
    for i in range(0, len(names), a.batch):
        chunk = names[i:i + a.batch]
        imgs = [Image.open(os.path.join(a.images, n)).convert('RGB') for n in chunk]
        with torch.no_grad():
            logits = seg(**proc(images=imgs, return_tensors='pt').to(dev)).logits
        for n, img, lg in zip(chunk, imgs, logits):
            lab = torch.nn.functional.interpolate(lg[None], size=img.size[::-1], mode='bilinear',
                                                  align_corners=False).argmax(1)[0].cpu().numpy()
            black = Image.fromarray((np.isin(lab, ids) * 255).astype(np.uint8))
            if a.grow:
                black = black.filter(ImageFilter.MaxFilter(2 * a.grow + 1))
            m = 255 - np.asarray(black)
            out = os.path.join(a.masks, n + '.png')
            os.makedirs(os.path.dirname(out), exist_ok=True)
            Image.fromarray(m.astype(np.uint8)).save(out)
            shares.append(float((m == 0).mean()))
        print(f'{min(i + a.batch, len(names))}/{len(names)}', end='\r', flush=True)
    s = np.array(shares)
    print(f'\n{len(s)} masks; masked share median {np.median(s) * 100:.1f}%, 10-90% {np.percentile(s, 10) * 100:.1f}-'
          f'{np.percentile(s, 90) * 100:.1f}%, {int((s > 0.95).sum())} over 95%')


if __name__ == '__main__':
    main()
