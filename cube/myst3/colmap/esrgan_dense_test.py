#!/usr/bin/env python3
r"""
Does upscaling the faces with Real-ESRGAN help dense reconstruction? Two dense runs on the same nodes, the
original 640 px faces and Real-ESRGAN x4plus upscales, from the same sparse model.

    python esrgan_dense_test.py ROOT SPARSE_TXT OUT --nodes 4084 4089 [--near 20] [--max-size 1280]
        [--esrgan RealESRGAN_x4plus.pth] [--run-dense run_dense.ps1]

ROOT holds images\f<k>\MA-<node>.jpg; SPARSE_TXT the joined model as text (cameras, images, points3D).
The nodes are the ones given and the --near nearest to their middle (by face 1's camera centre). The model is
cut to their faces (other images and the points no longer seen twice dropped) into OUT\sparse, and a copy
with every camera and keypoint scaled by 4 into OUT\sparse_x4. The faces are upscaled into OUT\images_x4 (same
names). run_dense.ps1 then runs on each: OUT\dense (originals, their own size) and OUT\dense_x4 (upscales,
patch_match_stereo capped at --max-size px). Writes OUT\report.json: images, points fused, seconds; and
OUT\view_<run>.png, each cloud drawn from the first node's centre as a 1024x512 equirectangular picture.
Needs numpy, Pillow, torch, spandrel; COLMAP (run_dense.ps1).
"""
import argparse
import json
import os
import subprocess
import time
import urllib.request

import numpy as np
from PIL import Image

ESRGAN_URL = 'https://github.com/xinntao/Real-ESRGAN/releases/download/v0.1.0/RealESRGAN_x4plus.pth'


def read_model(d):
    cams = {}
    for line in open(os.path.join(d, 'cameras.txt')):
        if line.startswith('#') or not line.strip():
            continue
        p = line.split(); cams[int(p[0])] = p
    imgs, lines = {}, open(os.path.join(d, 'images.txt')).read().splitlines()
    body = [l for l in lines if not l.startswith('#')]
    for i in range(0, len(body) - 1, 2):
        head, pts = body[i].split(), body[i + 1].split()
        if not head:
            continue
        imgs[int(head[0])] = (head, pts)
    return cams, imgs


def centre(head):
    qw, qx, qy, qz, tx, ty, tz = map(float, head[1:8])
    R = np.array([[1 - 2 * (qy * qy + qz * qz), 2 * (qx * qy - qz * qw), 2 * (qx * qz + qy * qw)],
                  [2 * (qx * qy + qz * qw), 1 - 2 * (qx * qx + qz * qz), 2 * (qy * qz - qx * qw)],
                  [2 * (qx * qz - qy * qw), 2 * (qy * qz + qx * qw), 1 - 2 * (qx * qx + qy * qy)]])
    return -R.T @ np.array([tx, ty, tz]), R


def write_cut(src, out, keep_ids, cams, imgs, scale):
    os.makedirs(out, exist_ok=True)
    used_cams = {int(imgs[i][0][8]) for i in keep_ids}
    with open(os.path.join(out, 'cameras.txt'), 'w') as f:
        for c in sorted(used_cams):
            p = list(cams[c])
            w, h = int(p[2]) * scale, int(p[3]) * scale
            params = [float(v) * scale for v in p[4:]]       # PINHOLE / SIMPLE_PINHOLE: f, c all scale
            f.write(' '.join([p[0], p[1], str(w), str(h)] + [repr(v) for v in params]) + '\n')
    # points seen at least twice among the kept images
    seen = {}
    for i in keep_ids:
        pts = imgs[i][1]
        for j in range(2, len(pts), 3):
            pid = int(pts[j])
            if pid >= 0:
                seen[pid] = seen.get(pid, 0) + 1
    keep_pts = {p for p, n in seen.items() if n >= 2}
    with open(os.path.join(out, 'images.txt'), 'w') as f:
        for i in sorted(keep_ids):
            head, pts = imgs[i]
            f.write(' '.join(head) + '\n')
            o = []
            for j in range(0, len(pts) - 2, 3):
                x, y, pid = float(pts[j]) * scale, float(pts[j + 1]) * scale, int(pts[j + 2])
                o += [repr(x), repr(y), str(pid if pid in keep_pts else -1)]
            f.write(' '.join(o) + '\n')
    with open(os.path.join(out, 'points3D.txt'), 'w') as f:
        for line in open(os.path.join(src, 'points3D.txt')):
            if line.startswith('#'):
                continue
            p = line.split()
            if not p or int(p[0]) not in keep_pts:
                continue
            track = p[8:]
            t = [track[k] + ' ' + track[k + 1] for k in range(0, len(track), 2) if int(track[k]) in keep_ids]
            f.write(' '.join(p[:8]) + ' ' + ' '.join(t) + '\n')
    return len(keep_pts)


def upscale(root, names, out, weights):
    import torch
    from spandrel import ModelLoader
    model = ModelLoader().load_from_file(weights).cuda().eval()
    for n, name in enumerate(names):
        dst = os.path.join(out, name)
        if os.path.exists(dst):
            continue
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        x = torch.from_numpy(np.asarray(Image.open(os.path.join(root, name)).convert('RGB'))).permute(2, 0, 1)[None].float().cuda() / 255
        with torch.no_grad():
            y = model(x)
        Image.fromarray((y[0].clamp(0, 1).permute(1, 2, 0).cpu().numpy() * 255 + .5).astype(np.uint8)).save(dst, quality=95)
        if n % 20 == 0:
            print(f'upscaled {n + 1}/{len(names)}', flush=True)


def read_ply_points(path):
    with open(path, 'rb') as f:
        header = b''
        while True:                                       # the header ends at end_header, whatever the line ending
            line = f.readline()
            if not line:
                raise ValueError(f'{path}: no end_header')
            header += line
            if line.strip() == b'end_header':
                break
        h = header.decode(errors='ignore')
        n = int([l for l in h.splitlines() if l.startswith('element vertex')][0].split()[-1])
        props = [l.split() for l in h.splitlines() if l.startswith('property')]
        dt = np.dtype([(p[-1], {'float': '<f4', 'double': '<f8', 'uchar': 'u1', 'int': '<i4'}[p[1]]) for p in props])
        v = np.frombuffer(f.read(n * dt.itemsize), dt, n)
    return np.stack([v['x'], v['y'], v['z']], 1).astype(np.float64), np.stack([v['red'], v['green'], v['blue']], 1)


def view(ply, C, R, out):
    """The cloud from C as a 1024x512 equirectangular picture in face 1's camera axes (nearest point wins)."""
    P, col = read_ply_points(ply)
    d = (P - C) @ R.T                                         # face 1's camera axes: x right, y down, z ahead
    r = np.linalg.norm(d, axis=1)
    lon = np.arctan2(d[:, 0], d[:, 2]); lat = np.arcsin(np.clip(-d[:, 1] / r, -1, 1))
    W, H = 1024, 512
    u = ((lon / np.pi + 1) / 2 * W).astype(int) % W; v = np.clip(((0.5 - lat / np.pi) * H).astype(int), 0, H - 1)
    order = np.argsort(-r)                                    # far first, near overwrite
    img = np.zeros((H, W, 3), np.uint8); img[v[order], u[order]] = col[order]
    Image.fromarray(img).save(out)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('root'); ap.add_argument('sparse'); ap.add_argument('out')
    ap.add_argument('--nodes', nargs='+', required=True); ap.add_argument('--near', type=int, default=20)
    ap.add_argument('--max-size', type=int, default=1280)
    ap.add_argument('--esrgan', default=r'C:\myst3_out\film\RealESRGAN_x4plus.pth')
    ap.add_argument('--run-dense', default=r'C:\myst3_out\colmap\run_dense.ps1')
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    cams, imgs = read_model(a.sparse)
    face1 = {h[9].split('/')[1][3:-4]: (centre(h)[0], centre(h)[1]) for h, _ in imgs.values() if h[9].startswith('f1/MA-')}
    mid = np.mean([face1[n][0] for n in a.nodes], axis=0)
    order = sorted(face1, key=lambda n: np.linalg.norm(face1[n][0] - mid))
    nodes = list(dict.fromkeys(a.nodes + order))[:len(a.nodes) + a.near]
    keep = [i for i, (h, _) in imgs.items() if h[9].startswith('f') and h[9].split('/')[1][3:-4] in nodes and '/MA-' in h[9]]
    names = [imgs[i][0][9] for i in keep]
    print(f'{len(nodes)} nodes, {len(keep)} faces: {" ".join(sorted(nodes))}', flush=True)
    n1 = write_cut(a.sparse, os.path.join(a.out, 'sparse'), set(keep), cams, imgs, 1)
    write_cut(a.sparse, os.path.join(a.out, 'sparse_x4'), set(keep), cams, imgs, 4)
    print(f'model cut: {n1} points seen twice or more', flush=True)
    if not os.path.exists(a.esrgan):
        urllib.request.urlretrieve(ESRGAN_URL, a.esrgan)
    t0 = time.time()
    upscale(os.path.join(a.root, 'images'), names, os.path.join(a.out, 'images_x4'), a.esrgan)
    report = {'nodes': nodes, 'faces': len(keep), 'upscale_s': round(time.time() - t0)}
    # the baseline reads the originals; a folder of links keeps the image paths the same as the model's
    runs = (('dense', os.path.join(a.root, 'images'), 'sparse', None), ('dense_x4', os.path.join(a.out, 'images_x4'), 'sparse_x4', a.max_size))
    for run, images, sparse, mx in runs:
        t0 = time.time()
        done = os.path.exists(os.path.join(a.out, run, 'fused.ply'))   # a run already done is not repeated
        cmd = ['powershell', '-ExecutionPolicy', 'Bypass', '-File', a.run_dense, '-Images', images,
               '-Sparse', os.path.join(a.out, sparse), '-Out', os.path.join(a.out, run)]
        if mx:
            cmd += ['-MaxImageSize', str(mx)]
        print(f'== {run}' + (' (done before)' if done else ''), flush=True)
        if not done:
            subprocess.run(cmd, check=False)
        ply = os.path.join(a.out, run, 'fused.ply')
        n = None
        if os.path.exists(ply):
            n = int([l for l in open(ply, 'rb').read(400).decode(errors='ignore').splitlines() if l.startswith('element vertex')][0].split()[-1])
            C, R = face1[a.nodes[0]]
            view(ply, C, R, os.path.join(a.out, f'view_{run}.png'))
        report[run] = {'points': n, 'seconds': round(time.time() - t0)}
        print(run, report[run], flush=True)
        json.dump(report, open(os.path.join(a.out, 'report.json'), 'w'), indent=1)


if __name__ == '__main__':
    main()
