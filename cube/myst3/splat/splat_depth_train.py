#!/usr/bin/env python3
r"""
A Gaussian splat trained with a depth loss: besides matching the pictures, every node face's rendered depth is
pulled toward the node's MoGe depth anchored to the dense cloud (colmap/scene_mesh.py --dense), so splats sit on
surfaces where the pictures alone leave them free (flat, plain or seen from one side). gsplat on the GPU.

    python splat_depth_train.py DATA MOGE_DIR MODEL_TXT OUT.ply [--steps 30000] [--depth-weight 0.1]
        [--depth-init 400000] [--far 10] [--eval]

DATA is a COLMAP text dataset as splat_dataset.py writes (images\, sparse\0\{cameras,images,points3D}.txt;
node faces named [againN_]f<k>_MA-<node>.jpg, movie frames anything else). MOGE_DIR holds scene_mesh.py's
<node>_anchored.npy (distances from the node in MODEL_TXT's units, an equirectangular panorama in the node's
frame: x right, y up, -z face 1) and <node>_moge_mask.npy (false on the sky). MODEL_TXT is the model the
anchoring was done in (its f1/MA-<node>.jpg cameras give each node's centre and turn); DATA's frame is fitted
to it by a similarity on the node centres both have, so the two need not share a frame.

Loss per picture: 0.8 L1 + 0.2 (1 - SSIM) on colour, plus --depth-weight times the mean |log rendered depth -
log MoGe depth| over a node face's pixels that MoGe gives a distance under --far node spacings and that the
render covers (alpha over 0.5). Movie frames and the sky have colour only. Splats grow and are pruned by
gsplat's DefaultStrategy. Starting points: DATA's points3D plus --depth-init points sampled from the node faces'
anchored depth, coloured from the faces. Writes OUT.ply in the usual 3DGS layout (x y z, normals, f_dc, f_rest,
opacity, scale, rot) and OUT.json with each node face's PSNR and median depth misfit at the end.

Needs torch with CUDA, gsplat (1.5), numpy, scipy, Pillow, opencv-python.
"""
import argparse
import json
import math
import os
import re
import sys
import time

import cv2
import numpy as np
import torch
import torch.nn.functional as Fn
from PIL import Image

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'colmap'))
from moge_depth import dirs_to_equirect_px  # noqa: E402

F = np.diag([1.0, -1.0, -1.0])
FACE = re.compile(r'(?:again\d+_)?f(\d)_MA-(\d+)\.(?:jpg|png)$')


def qvec2rot(q):
    w, x, y, z = q
    return np.array([[1 - 2 * y * y - 2 * z * z, 2 * x * y - 2 * w * z, 2 * x * z + 2 * w * y],
                     [2 * x * y + 2 * w * z, 1 - 2 * x * x - 2 * z * z, 2 * y * z - 2 * w * x],
                     [2 * x * z - 2 * w * y, 2 * y * z + 2 * w * x, 1 - 2 * x * x - 2 * y * y]])


def read_cameras(path):
    cams = {}
    for line in open(path):
        if line.startswith('#') or not line.strip():
            continue
        p = line.split(); cid, model, w, h = int(p[0]), p[1], int(p[2]), int(p[3]); v = list(map(float, p[4:]))
        if model == 'SIMPLE_PINHOLE' or model.startswith('SIMPLE_RADIAL'):
            fx = fy = v[0]; cx, cy = v[1], v[2]
        elif model == 'PINHOLE':
            fx, fy, cx, cy = v[:4]
        else:
            raise SystemExit(f'camera model {model} not handled')
        cams[cid] = (w, h, np.array([[fx, 0, cx], [0, fy, cy], [0, 0, 1]], float))
    return cams


def read_images(path, want=None):
    """name -> (R world to camera, t, camera id); only header lines (points2D lines skipped)."""
    out = {}
    with open(path) as f:
        for line in f:
            if line.startswith('#') or not line.strip():
                continue
            p = line.split()
            if len(p) >= 10 and (p[9].endswith('.jpg') or p[9].endswith('.png')):
                if want is None or want(p[9]):
                    out[p[9]] = (qvec2rot(list(map(float, p[1:5]))), np.array(list(map(float, p[5:8]))), int(p[8]))
                next(f, None)
    return out


def read_points(path):
    X, C = [], []
    for line in open(path):
        if line.startswith('#') or not line.strip():
            continue
        p = line.split(); X.append(list(map(float, p[1:4]))); C.append(list(map(float, p[4:7])))
    return np.array(X, np.float32).reshape(-1, 3), np.array(C, np.float32).reshape(-1, 3) / 255


def umeyama(src, dst):
    ms, md = src.mean(0), dst.mean(0); a, b = src - ms, dst - md
    U, S, Vt = np.linalg.svd(b.T @ a / len(src)); d = np.sign(np.linalg.det(U @ Vt))
    D = np.diag([1, 1, d]); R = U @ D @ Vt; s = np.trace(np.diag(S) @ D) / (a ** 2).sum(1).mean()
    return s, R, md - s * R @ ms


def ssim(x, y):
    """x, y: [1,3,H,W] in 0..1; Gaussian window 11, sigma 1.5."""
    g = torch.exp(-(torch.arange(11, device=x.device) - 5.0) ** 2 / (2 * 1.5 ** 2)); g = (g / g.sum())
    w = (g[:, None] * g[None, :]).expand(3, 1, 11, 11)
    mu_x = Fn.conv2d(x, w, padding=5, groups=3); mu_y = Fn.conv2d(y, w, padding=5, groups=3)
    sxx = Fn.conv2d(x * x, w, padding=5, groups=3) - mu_x ** 2; syy = Fn.conv2d(y * y, w, padding=5, groups=3) - mu_y ** 2
    sxy = Fn.conv2d(x * y, w, padding=5, groups=3) - mu_x * mu_y
    c1, c2 = 0.01 ** 2, 0.03 ** 2
    return (((2 * mu_x * mu_y + c1) * (2 * sxy + c2)) / ((mu_x ** 2 + mu_y ** 2 + c1) * (sxx + syy + c2))).mean()


def write_ply(path, means, scales, quats, opac, sh0, shN):
    n = len(means); nrest = shN.shape[1] * 3
    names = ['x', 'y', 'z', 'nx', 'ny', 'nz', 'f_dc_0', 'f_dc_1', 'f_dc_2'] + [f'f_rest_{i}' for i in range(nrest)] + \
            ['opacity', 'scale_0', 'scale_1', 'scale_2', 'rot_0', 'rot_1', 'rot_2', 'rot_3']
    rest = shN.transpose(0, 2, 1).reshape(n, -1)              # 3DGS order: channel-major
    data = np.concatenate([means, np.zeros((n, 3)), sh0.reshape(n, 3), rest, opac[:, None], scales, quats], 1).astype(np.float32)
    with open(path, 'wb') as f:
        f.write(('ply\nformat binary_little_endian 1.0\nelement vertex %d\n' % n).encode())
        for nm in names:
            f.write(f'property float {nm}\n'.encode())
        f.write(b'end_header\n'); f.write(data.tobytes())


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('data'); ap.add_argument('moge'); ap.add_argument('model'); ap.add_argument('out')
    ap.add_argument('--steps', type=int, default=30000); ap.add_argument('--depth-weight', type=float, default=0.1)
    ap.add_argument('--depth-init', type=int, default=400000); ap.add_argument('--far', type=float, default=10)
    ap.add_argument('--sh', type=int, default=3); ap.add_argument('--seed', type=int, default=0)
    ap.add_argument('--eval', action='store_true', help='only measure OUT.ply (no training)')
    a = ap.parse_args()
    torch.manual_seed(a.seed); np.random.seed(a.seed)
    dev = 'cuda'
    sp = os.path.join(a.data, 'sparse', '0')
    cams = read_cameras(os.path.join(sp, 'cameras.txt')); ims = read_images(os.path.join(sp, 'images.txt'))
    model = read_images(os.path.join(a.model, 'images.txt'), lambda nm: nm.startswith('f1/MA-'))
    centre = lambda R, t: -R.T @ t
    # node centres in both frames: DATA's f1 faces against MODEL's
    shared = {}
    for nm, (R, t, _) in ims.items():
        m = FACE.match(nm)
        if m and m.group(1) == '1' and not nm.startswith('again') and f'f1/MA-{m.group(2)}.jpg' in model:
            Rm, tm, _ = model[f'f1/MA-{m.group(2)}.jpg']; shared[m.group(2)] = (centre(R, t), centre(Rm, tm), R, Rm)
    nodes = sorted(shared)
    s, Rs, ts = umeyama(np.array([shared[n][1] for n in nodes]), np.array([shared[n][0] for n in nodes]))   # model -> data
    res = np.linalg.norm(np.array([s * Rs @ shared[n][1] + ts - shared[n][0] for n in nodes]), axis=1)
    P = np.array([shared[n][0] for n in nodes]); unit = float(np.median(np.sort(np.linalg.norm(P[:, None] - P[None], axis=2), 1)[:, 1]))
    print(f'{len(nodes)} nodes in both; model to data: scale {s:.4f}, residual median {np.median(res) / unit:.3f} spacings', flush=True)

    # the pictures, and for node faces the anchored depth along each pixel's ray
    views = []
    pano = {}
    for nm in sorted(ims):
        R, t, cid = ims[nm]; w, h, K = cams[cid]
        img = np.array(Image.open(os.path.join(a.data, 'images', nm)).convert('RGB'))
        assert img.shape[:2] == (h, w), (nm, img.shape)
        v = {'name': nm, 'R': R, 't': t, 'K': K, 'w': w, 'h': h, 'img': torch.from_numpy(img).to(dev), 'depth': None}
        m = FACE.match(nm)
        if m and m.group(2) in shared and os.path.exists(os.path.join(a.moge, m.group(2) + '_anchored.npy')):
            n = m.group(2)
            if n not in pano:
                D = np.load(os.path.join(a.moge, n + '_anchored.npy')).astype(np.float32)
                Mk = np.load(os.path.join(a.moge, n + '_moge_mask.npy'))
                Mk = cv2.resize((np.asarray(Mk) > 0.5).astype(np.uint8), (D.shape[1], D.shape[0]), interpolation=cv2.INTER_NEAREST) > 0
                pano[n] = (np.where(Mk & np.isfinite(D), D, 0).astype(np.float32))
            D = pano[n]; Hp, Wp = D.shape
            vv, uu = np.mgrid[0:h, 0:w].astype(np.float64)
            dc = np.stack([(uu + .5 - K[0, 2]) / K[0, 0], (vv + .5 - K[1, 2]) / K[1, 1], np.ones_like(uu)], -1)
            dw = dc @ R                                       # camera to data frame: R^T d
            dm = dw @ Rs                                      # data to model frame: Rs^T d
            Rm = shared[n][3]
            dn = dm @ Rm.T @ F; dn /= np.linalg.norm(dn, axis=-1, keepdims=True)   # node frame
            mx, my = dirs_to_equirect_px(dn, Wp, Hp)
            dist = cv2.remap(D, mx, my, cv2.INTER_NEAREST, borderMode=cv2.BORDER_WRAP) * s
            z = dist / np.linalg.norm(dc, axis=-1)
            z[(dist <= 0) | (dist > a.far * unit)] = 0
            v['depth'] = torch.from_numpy(z.astype(np.float32)).to(dev)
        views.append(v)
    nd = sum(v['depth'] is not None for v in views)
    print(f'{len(views)} pictures, {nd} with depth', flush=True)

    def viewmat(v):
        M = np.eye(4); M[:3, :3] = v['R']; M[:3, 3] = v['t']; return torch.tensor(M, dtype=torch.float32, device=dev)[None]

    from gsplat import rasterization
    from gsplat.strategy import DefaultStrategy
    cams_c = np.array([centre(v['R'], v['t']) for v in views])
    scene_scale = float(np.linalg.norm(cams_c - cams_c.mean(0), axis=1).max()) * 1.1

    if a.eval:
        from plyfile import PlyData
        el = PlyData.read(a.out)['vertex']; g = lambda k: np.asarray(el[k], np.float32)
        nrest = len([p.name for p in el.properties if p.name.startswith('f_rest_')])
        params = {'means': np.stack([g('x'), g('y'), g('z')], 1), 'scales': np.stack([g(f'scale_{i}') for i in range(3)], 1),
                  'quats': np.stack([g(f'rot_{i}') for i in range(4)], 1), 'opacities': g('opacity'),
                  'sh0': np.stack([g(f'f_dc_{i}') for i in range(3)], 1)[:, None],
                  'shN': np.stack([g(f'f_rest_{i}') for i in range(nrest)], 1).reshape(-1, 3, nrest // 3).transpose(0, 2, 1)}
        params = {k: torch.tensor(np.asarray(v, np.float32), device=dev) for k, v in params.items()}
    else:
        # starting points: DATA's cloud and samples of the anchored depth, coloured from the faces
        X0, C0 = read_points(os.path.join(sp, 'points3D.txt'))
        Xs, Cs = [], []
        dv = [v for v in views if v['depth'] is not None and not v['name'].startswith('again')]
        per = a.depth_init // max(len(dv), 1)
        for v in dv:
            z = v['depth'].cpu().numpy(); ok = np.argwhere(z > 0)
            if not len(ok):
                continue
            pick = ok[np.random.choice(len(ok), min(per, len(ok)), replace=False)]
            yy, xx = pick[:, 0], pick[:, 1]; K = v['K']
            pc = np.stack([(xx + .5 - K[0, 2]) / K[0, 0] * z[yy, xx], (yy + .5 - K[1, 2]) / K[1, 1] * z[yy, xx], z[yy, xx]], 1)
            Xs.append((pc - v['t']) @ v['R']); Cs.append(v['img'].cpu().numpy()[yy, xx] / 255.0)
        X = np.concatenate([X0] + Xs).astype(np.float32); Cc = np.concatenate([C0] + Cs).astype(np.float32)
        print(f'starting points: {len(X0)} from the cloud, {len(X) - len(X0)} from the depth', flush=True)
        from scipy.spatial import cKDTree
        dk, _ = cKDTree(X).query(X, k=4)
        d = np.sqrt((dk[:, 1:] ** 2).mean(1)).clip(1e-4 * unit, None)
        n0 = len(X); nsh = (a.sh + 1) ** 2
        sh0 = ((Cc - 0.5) / 0.28209479177387814)[:, None]
        params = {'means': X, 'scales': np.log(np.repeat(d[:, None], 3, 1)), 'quats': np.tile([1, 0, 0, 0], (n0, 1)).astype(np.float32),
                  'opacities': np.full(n0, math.log(0.1 / 0.9), np.float32), 'sh0': sh0.astype(np.float32),
                  'shN': np.zeros((n0, nsh - 1, 3), np.float32)}
        params = {k: torch.tensor(np.asarray(v, np.float32), device=dev) for k, v in params.items()}
    params = torch.nn.ParameterDict({k: torch.nn.Parameter(v) for k, v in params.items()})

    def render(v, deg):
        K = torch.tensor(v['K'], dtype=torch.float32, device=dev)[None]
        colors = torch.cat([params['sh0'], params['shN']], 1)
        out, alpha, info = rasterization(params['means'], params['quats'], torch.exp(params['scales']), torch.sigmoid(params['opacities']),
                                         colors, viewmat(v), K, v['w'], v['h'], sh_degree=deg, render_mode='RGB+ED',
                                         near_plane=0.01 * unit, far_plane=1e4 * unit, packed=False)
        return out[0], alpha[0, ..., 0], info

    def measure():
        rep = {}
        with torch.no_grad():
            for v in views:
                m = FACE.match(v['name'])
                if not m or v['name'].startswith('again'):
                    continue
                out, alpha, _ = render(v, a.sh)
                gt = v['img'].float() / 255
                mse = float(((out[..., :3].clamp(0, 1) - gt) ** 2).mean())
                e = {'psnr': -10 * math.log10(max(mse, 1e-10))}
                if v['depth'] is not None:
                    ok = (v['depth'] > 0) & (alpha > 0.5)
                    if ok.any():
                        e['depth_misfit'] = float(torch.median(torch.abs(torch.log(out[..., 3][ok].clamp_min(1e-6)) - torch.log(v['depth'][ok]))))
                    e['covered'] = float((alpha > 0.5).float().mean())
                rep[v['name']] = e
        return rep

    if not a.eval:
        lrs = {'means': 1.6e-4 * scene_scale, 'scales': 5e-3, 'quats': 1e-3, 'opacities': 5e-2, 'sh0': 2.5e-3, 'shN': 2.5e-3 / 20}
        opts = {k: torch.optim.Adam([{'params': params[k], 'lr': lr, 'name': k}], eps=1e-15) for k, lr in lrs.items()}
        sched = torch.optim.lr_scheduler.ExponentialLR(opts['means'], gamma=0.01 ** (1.0 / a.steps))
        strat = DefaultStrategy(refine_stop_iter=int(a.steps * 0.5), reset_every=3000, refine_every=100, verbose=False)
        strat.check_sanity(params, opts)
        state = strat.initialize_state(scene_scale=scene_scale)
        t0 = time.time(); run = {'l1': 0, 'dep': 0, 'n': 0}
        order = np.random.permutation(len(views)); oi = 0
        for step in range(a.steps):
            if oi >= len(order):
                order = np.random.permutation(len(views)); oi = 0
            v = views[order[oi]]; oi += 1
            deg = min(step // 1000, a.sh)
            out, alpha, info = render(v, deg)
            strat.step_pre_backward(params, opts, state, step, info)
            gt = v['img'].float() / 255
            rgb = out[..., :3]
            l1 = torch.abs(rgb - gt).mean()
            loss = 0.8 * l1 + 0.2 * (1 - ssim(rgb.permute(2, 0, 1)[None], gt.permute(2, 0, 1)[None]))
            if v['depth'] is not None and a.depth_weight > 0:
                ok = (v['depth'] > 0) & (alpha.detach() > 0.5)
                if ok.any():
                    dl = torch.abs(torch.log(out[..., 3][ok].clamp_min(1e-6)) - torch.log(v['depth'][ok])).mean()
                    loss = loss + a.depth_weight * dl; run['dep'] += float(dl)
            loss.backward()
            for o in opts.values():
                o.step(); o.zero_grad(set_to_none=True)
            sched.step()
            strat.step_post_backward(params, opts, state, step, info, packed=False)
            run['l1'] += float(l1); run['n'] += 1
            if (step + 1) % 1000 == 0:
                print(f'step {step + 1}: {len(params["means"])} splats, L1 {run["l1"] / run["n"]:.4f}, depth {run["dep"] / run["n"]:.4f}, '
                      f'{time.time() - t0:.0f} s', flush=True)
                run = {'l1': 0, 'dep': 0, 'n': 0}
        with torch.no_grad():
            write_ply(a.out, params['means'].cpu().numpy(), params['scales'].cpu().numpy(), Fn.normalize(params['quats'], dim=-1).cpu().numpy(),
                      params['opacities'].cpu().numpy(), params['sh0'].cpu().numpy(), params['shN'].cpu().numpy())
        print(f'{len(params["means"])} splats -> {a.out}', flush=True)
    rep = measure()
    ps = [e['psnr'] for e in rep.values()]; dm = [e['depth_misfit'] for e in rep.values() if 'depth_misfit' in e]
    cov = [e['covered'] for e in rep.values() if 'covered' in e]
    print(f'node faces: PSNR median {np.median(ps):.2f} dB, depth misfit median {np.median(dm) * 100:.1f}%, covered median {np.median(cov) * 100:.0f}%', flush=True)
    for k in ('f1_MA-4084.jpg', 'f5_MA-4084.jpg', 'f1_MA-4089.jpg'):
        if k in rep:
            print(k, json.dumps({x: round(y, 4) for x, y in rep[k].items()}), flush=True)
    json.dump({'scale_model_to_data': s, 'nodes': nodes, 'faces': rep}, open(os.path.splitext(a.out)[0] + '.json', 'w'), indent=1)


if __name__ == '__main__':
    main()
