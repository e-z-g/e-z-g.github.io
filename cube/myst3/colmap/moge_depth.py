#!/usr/bin/env python3
r"""
A node's depth faces made again by MoGe from the whole panorama at once, fitted to its measured depth.

    python moge_depth.py IN_DIR OUT_DIR NAME1 ... NAME6 [--colour-suffix _orig.jpg]
        [--depth-suffix _measured-depth.png] [--model moge_3_vitg_fp16.safetensors] [--size 2048]
        [--face-size N] [--server $COMFY_SERVER] [--comfy-input C:\ComfyUI\input]

IN_DIR holds the node's six faces (NAME<k><colour-suffix>, 640 px, node_depth.py's order: front, bottom,
back, right, left, top) and its current depth (NAME<k><depth-suffix>: 8-bit, 1 + 19 d/255 inverse distance,
0 sky). The faces are drawn as one equirectangular panorama (--size x --size/2); ComfyUI's
MoGePanoramaInference (12 views merged into one distance map, MoGe-3's refinement) gives its distances,
saved raw by the SaveMoGeGeometry node. The distances go back onto the six faces, and their inverse is
scaled by one number so it matches the current depth over the pixels both call solid (median of the
ratio): the measured scale is kept, MoGe gives the shape. Writes OUT_DIR/NAME<k>_moge-depth.png (same
encoding; MoGe's sky and anything beyond the farthest current depth are 0), NAME<k>_moge-normal.png (the
surface normals from the distances, in the face's own camera axes, OpenGL convention: red right, green up,
blue toward the viewer) and the panorama, its distance map and a report. With --face-size the faces written
are that size (the panorama's 2048 px give 512 px a face; 4096 give 1024), the distances taken from the
panorama's nearest pixel so that no pixel mixes a near edge with what is behind it, and the colour faces are
written beside them at that size (NAME<k>_moge-colour.png, Lanczos), for build_layers.py. Needs numpy, Pillow,
opencv-python; a running ComfyUI with the MoGe model and custom_nodes/save_moge.
"""
import argparse
import json
import os
import time
import urllib.request
import uuid

import cv2
import numpy as np
from PIL import Image

DIRS = {1: lambda s, t: (2 * s - 1, 1 - 2 * t, -np.ones_like(s)),
        2: lambda s, t: (1 - 2 * s, -np.ones_like(s), 1 - 2 * t),
        3: lambda s, t: (1 - 2 * s, 1 - 2 * t, np.ones_like(s)),
        4: lambda s, t: (np.ones_like(s), 1 - 2 * t, 2 * s - 1),
        5: lambda s, t: (-np.ones_like(s), 1 - 2 * t, 1 - 2 * s),
        6: lambda s, t: (1 - 2 * s, np.ones_like(s), 2 * t - 1)}


def api(server, path, data=None):
    req = urllib.request.Request(server + path, data=json.dumps(data).encode() if data is not None else None,
                                 headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read())


def face_axes(k):
    c = np.array(DIRS[k](np.array(0.5), np.array(0.5)), float)
    ds = np.array(DIRS[k](np.array(1.0), np.array(0.5)), float) - c        # half of d/ds
    dt = np.array(DIRS[k](np.array(0.5), np.array(1.0)), float) - c
    return c, ds, dt


def face_dirs(k, N):
    t, s = np.mgrid[0:N, 0:N].astype(np.float64)
    v = np.stack(DIRS[k]((s + .5) / N, (t + .5) / N), -1)
    return v / np.linalg.norm(v, axis=-1, keepdims=True)


def equirect_dirs(W, H):
    v, u = np.mgrid[0:H, 0:W].astype(np.float64)
    lon = ((u + .5) / W * 2 - 1) * np.pi; lat = (0.5 - (v + .5) / H) * np.pi
    return np.stack([np.sin(lon) * np.cos(lat), np.sin(lat), -np.cos(lon) * np.cos(lat)], -1)   # node frame: y up, -z face 1


def dirs_to_equirect_px(d, W, H):
    lon = np.arctan2(d[..., 0], -d[..., 2]); lat = np.arcsin(np.clip(d[..., 1], -1, 1))
    return ((lon / np.pi + 1) / 2 * W - .5).astype(np.float32), ((0.5 - lat / np.pi) * H - .5).astype(np.float32)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('inp'); ap.add_argument('out'); ap.add_argument('names', nargs=6)
    ap.add_argument('--colour-suffix', default='_orig.jpg'); ap.add_argument('--depth-suffix', default='_measured-depth.png')
    ap.add_argument('--model', default='moge_3_vitg_fp16.safetensors'); ap.add_argument('--size', type=int, default=2048)
    ap.add_argument('--refine', type=int, default=3); ap.add_argument('--face-size', type=int)
    ap.add_argument('--server', default=os.environ.get('COMFY_SERVER', 'http://127.0.0.1:8189'))
    ap.add_argument('--comfy-input', default=r'C:\ComfyUI\input')
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    faces = [np.asarray(Image.open(os.path.join(a.inp, n + a.colour_suffix)).convert('RGB')) for n in a.names]
    N = faces[0].shape[0]
    W, H = a.size, a.size // 2
    # 1. the panorama: each direction from the face it is most along
    d = equirect_dirs(W, H)
    pano = np.zeros((H, W, 3), np.uint8); best = np.full((H, W), -np.inf)
    for k in range(1, 7):
        c, ds, dt = face_axes(k)
        z = d @ c
        take = z > best
        with np.errstate(all='ignore'):
            p = d / z[..., None]
        s = 0.5 + (p - c) @ ds / (ds @ ds) / 2; t = 0.5 + (p - c) @ dt / (dt @ dt) / 2
        img = cv2.remap(faces[k - 1], (s * N - .5).astype(np.float32), (t * N - .5).astype(np.float32), cv2.INTER_CUBIC,
                        borderMode=cv2.BORDER_REPLICATE)
        pano[take] = img[take]; best[take] = z[take]
    stem = a.names[0]
    pano_name = f'moge_{stem}_pano.png'
    Image.fromarray(pano).save(os.path.join(a.out, pano_name)); Image.fromarray(pano).save(os.path.join(a.comfy_input, pano_name))
    # 2. MoGe on the panorama
    prefix = os.path.join(a.out, f'{stem}_moge')
    g = {'1': {'class_type': 'LoadImage', 'inputs': {'image': pano_name}},
         '2': {'class_type': 'LoadMoGeModel', 'inputs': {'model_name': a.model}},
         '3': {'class_type': 'MoGePanoramaInference', 'inputs': {'moge_model': ['2', 0], 'image': ['1', 0], 'resolution_level': 9,
                                                                 'split_resolution': 512, 'merge_resolution': W, 'batch_size': 4,
                                                                 'refine_steps': a.refine}},
         '4': {'class_type': 'SaveMoGeGeometry', 'inputs': {'moge_geometry': ['3', 0], 'path_prefix': prefix}}}
    r = api(a.server, '/prompt', {'prompt': g, 'client_id': uuid.uuid4().hex})
    if r.get('node_errors'):
        raise SystemExit('node errors: ' + json.dumps(r['node_errors'])[:2000])
    pid, t0 = r['prompt_id'], time.time()
    while True:
        h = api(a.server, f'/history/{pid}')
        if pid in h and h[pid].get('status', {}).get('completed'):
            break
        if pid in h and h[pid].get('status', {}).get('status_str') == 'error':
            raise SystemExit('ComfyUI error: ' + json.dumps(h[pid]['status'].get('messages'))[-2000:])
        if time.time() - t0 > 3600:
            raise SystemExit('timed out')
        time.sleep(5)
    D = np.load(prefix + '_depth.npy').astype(np.float64)                     # distance, (H, W)
    M = np.load(prefix + '_mask.npy') if os.path.exists(prefix + '_mask.npy') else np.ones_like(D, bool)
    if D.shape != (H, W):
        D = cv2.resize(D, (W, H), interpolation=cv2.INTER_LINEAR); M = cv2.resize(M.astype(np.uint8), (W, H)) > 0
    # 3. back onto the faces; one scale to the current depth
    old_q, new_iq, keep, rs = [], [], [], []
    FN = a.face_size or N
    interp = cv2.INTER_NEAREST if a.face_size else cv2.INTER_LINEAR
    for k in range(1, 7):
        fd = face_dirs(k, FN); mx, my = dirs_to_equirect_px(fd, W, H)
        r = cv2.remap(D.astype(np.float32), mx, my, interp, borderMode=cv2.BORDER_WRAP)
        m = cv2.remap(M.astype(np.uint8), mx, my, cv2.INTER_NEAREST, borderMode=cv2.BORDER_WRAP) > 0
        od = np.asarray(Image.open(os.path.join(a.inp, a.names[k - 1] + a.depth_suffix)).convert('L')).astype(np.float64)
        if od.shape[0] != FN:
            od = cv2.resize(od, (FN, FN), interpolation=cv2.INTER_NEAREST)
        if a.face_size:
            Image.fromarray(faces[k - 1]).resize((FN, FN), Image.LANCZOS).save(os.path.join(a.out, f'{a.names[k - 1]}_moge-colour.png'))
        rs.append((r, m, od, fd))
        ok = m & (od > 0) & (r > 0)
        old_q.append(1 + 19 * od[ok] / 255); new_iq.append(1 / r[ok])
    scale = float(np.median(np.concatenate(old_q) / np.concatenate(new_iq)))
    report = {'node': stem, 'scale': scale, 'faces': []}
    for k, (r, m, od, fd) in enumerate(rs, 1):
        q = scale / np.maximum(r, 1e-6)
        dn = np.where(m, np.clip((q - 1) / 19, 0, 1) * 255, 0)
        dn = np.where(q < 1, 0, dn)
        Image.fromarray(np.rint(dn).astype(np.uint8)).save(os.path.join(a.out, f'{a.names[k - 1]}_moge-depth.png'))
        # normals from the face's points (central differences), in the face camera's axes
        P = fd * r[..., None]
        dx = np.gradient(P, axis=1); dy = np.gradient(P, axis=0)
        n = np.cross(dy, dx); n /= np.linalg.norm(n, axis=-1, keepdims=True) + 1e-9
        c, ds, dt = face_axes(k)
        X = ds / np.linalg.norm(ds); Y = -dt / np.linalg.norm(dt); Z = -c / np.linalg.norm(c)   # right, up, toward the viewer
        nc = np.stack([n @ X, n @ Y, n @ Z], -1)
        nc = np.where((nc[..., 2:3] < 0), -nc, nc)                              # facing the viewer
        Image.fromarray(np.clip((nc * 0.5 + 0.5) * 255, 0, 255).astype(np.uint8)).save(os.path.join(a.out, f'{a.names[k - 1]}_moge-normal.png'))
        ok = m & (od > 0)
        corr = float(np.corrcoef(od[ok], dn[ok])[0, 1]) if ok.sum() > 100 else None
        report['faces'].append({'face': a.names[k - 1], 'solid_both': int(ok.sum()), 'agreement_r': corr,
                                'sky_now': float((dn == 0).mean()), 'sky_before': float((od == 0).mean())})
    json.dump(report, open(os.path.join(a.out, f'{stem}_moge_report.json'), 'w'), indent=1)
    print(json.dumps(report), flush=True)


if __name__ == '__main__':
    main()
