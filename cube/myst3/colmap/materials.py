#!/usr/bin/env python3
r"""
Material maps for a node's six faces by Marigold's intrinsic image models (diffusers): from each picture, the
colour without its lighting (albedo), roughness and metallic (marigold-iid-appearance-v1-1), and the shading
and the residual the lighting model splits off (marigold-iid-lighting-v1-1).

    python materials.py IN_DIR OUT_DIR NAME1 ... NAME6 [--colour-suffix _orig.jpg] [--ensemble 4] [--steps 4]
    python materials.py ROOT OUT_DIR --nodes 4084 4089 ... [--ensemble 4] [--steps 4]

Writes OUT_DIR/NAME<k>_albedo.png, _roughness.png, _metallic.png, _shading.png, _residual.png, and
OUT_DIR/sheet.jpg (each face's picture and maps in a row). With --nodes, the faces are ROOT\images\f<k>\<PREFIX>-<node>.jpg
(the joined model's) and the maps OUT_DIR/<PREFIX>-<node>-<k>_<map>.png (PREFIX --prefix, default MA), every node's faces done with each model
loaded once, no sheet; faces already done are skipped. The game's pictures have their lighting baked in,
so these are the models' estimates, not data the game holds. Needs torch, diffusers, Pillow, numpy.
"""
import argparse
import os

import numpy as np
import torch
from PIL import Image


def to_img(a):
    a = np.asarray(a, np.float32)
    if a.ndim == 3 and a.shape[0] in (1, 3) and a.shape[-1] not in (1, 3):
        a = a.transpose(1, 2, 0)
    a = np.clip(a, 0, 1)
    if a.ndim == 3 and a.shape[-1] == 1:
        a = a[..., 0]
    return Image.fromarray((a * 255 + .5).astype(np.uint8))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('inp'); ap.add_argument('out'); ap.add_argument('names', nargs='*')
    ap.add_argument('--nodes', nargs='+')
    ap.add_argument('--colour-suffix', default='_orig.jpg')
    ap.add_argument('--ensemble', type=int, default=4); ap.add_argument('--steps', type=int, default=4)
    ap.add_argument('--prefix', default='MA', help="the faces' file prefix with --nodes: MA (Amateria), LE (J'nanin)")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    from diffusers import MarigoldIntrinsicsPipeline
    if a.nodes:
        jobs = [(os.path.join(a.inp, 'images', f'f{k}', f'{a.prefix}-{n}.jpg'), f'{a.prefix}-{n}-{k}') for n in a.nodes for k in range(1, 7)]
        for repo, wanted in (('prs-eth/marigold-iid-appearance-v1-1', ('albedo', 'roughness', 'metallic')),
                             ('prs-eth/marigold-iid-lighting-v1-1', ('shading', 'residual'))):
            todo = [(f, n) for f, n in jobs if not os.path.exists(os.path.join(a.out, f'{n}_{wanted[-1]}.png'))]
            if not todo:
                continue
            pipe = MarigoldIntrinsicsPipeline.from_pretrained(repo, variant='fp16', torch_dtype=torch.float16).to('cuda')
            for i, (f, n) in enumerate(todo):
                pic = Image.open(f).convert('RGB')
                out = pipe(pic, ensemble_size=a.ensemble, num_inference_steps=a.steps)
                v = pipe.image_processor.visualize_intrinsics(out.prediction, pipe.target_properties)[0]
                for key in wanted:
                    found = [k for k in v if k.startswith(key)]
                    if found:
                        v[found[0]].resize(pic.size).save(os.path.join(a.out, f'{n}_{key}.png'))
                print(f'{repo.split("/")[-1]} {i + 1}/{len(todo)} {n}', flush=True)
            del pipe; torch.cuda.empty_cache()
        return
    rows = []
    pics = [Image.open(os.path.join(a.inp, n + a.colour_suffix)).convert('RGB') for n in a.names]
    maps = {n: {} for n in a.names}
    for repo, wanted in (('prs-eth/marigold-iid-appearance-v1-1', ('albedo', 'roughness', 'metallic')),
                         ('prs-eth/marigold-iid-lighting-v1-1', ('shading', 'residual'))):
        pipe = MarigoldIntrinsicsPipeline.from_pretrained(repo, variant='fp16', torch_dtype=torch.float16).to('cuda')
        for n, pic in zip(a.names, pics):
            out = pipe(pic, ensemble_size=a.ensemble, num_inference_steps=a.steps)
            vis = pipe.image_processor.visualize_intrinsics(out.prediction, pipe.target_properties)
            # one dict per image: target name -> PIL image
            v = vis[0]
            for key in wanted:
                found = [k for k in v if k.startswith(key)]
                if found:
                    img = v[found[0]].resize(pic.size)
                    img.save(os.path.join(a.out, f'{n}_{key}.png')); maps[n][key] = img
            print(repo.split('/')[-1], n, 'done', flush=True)
        del pipe; torch.cuda.empty_cache()
    S = 256
    for n, pic in zip(a.names, pics):
        tiles = [pic.resize((S, S))] + [maps[n][k].convert('RGB').resize((S, S)) for k in ('albedo', 'roughness', 'metallic', 'shading', 'residual') if k in maps[n]]
        row = Image.new('RGB', (S * 6, S)); [row.paste(t, (i * S, 0)) for i, t in enumerate(tiles)]
        rows.append(row)
    sheet = Image.new('RGB', (S * 6, S * len(rows))); [sheet.paste(r, (0, i * S)) for i, r in enumerate(rows)]
    sheet.save(os.path.join(a.out, 'sheet.jpg'), quality=88)
    print(os.path.join(a.out, 'sheet.jpg'), flush=True)


if __name__ == '__main__':
    main()
