"""J'nanin's cliff walk (LEIS 1060 to 1067) by a multi-view depth network: MapAnything (Meta) or Depth Anything 3
(ByteDance Seed), given the faces of the nodes near the walk and the flyover frames that look at it, with the model's
camera poses and intrinsics. The points are drawn into the walk's polar layout (walk_ends.py --polar 20
--along-motion) at 1060, halfway and 1067. At the ends only the other views' points are drawn, so a picture that
matches the node's own says the depth is right; the last column is the end's own faces' depth.

    C:\\myst3_out\\mv3d\\env\\Scripts\\python.exe mv3d_cliff.py SPARSE_TXT IMAGES ENDS OUT --model ma|da3
        [--da3-name depth-anything/DA3-LARGE-1.1] [--no-poses] [--radius 6] [--fly-radius 35] [--fly-max 24] [--dry]

SPARSE_TXT is a COLMAP text model with the flyover in (video_jfly2's); ENDS holds ends_polar_first.png and
ends_polar_last.png. OUT gets sheet.jpg, points.npz (points within 40 of the walk) and log lines on stdout.
"""
import argparse, json, os, time
import numpy as np, cv2

A, B = 1060, 1067


def read_model(d):
    cams = {}
    for l in open(os.path.join(d, 'cameras.txt')):
        if l[0] == '#': continue
        p = l.split(); m, w, h = p[1], int(p[2]), int(p[3]); q = [float(x) for x in p[4:]]
        fx, fy, cx, cy = (q[0], q[0], q[1], q[2]) if m.startswith('SIMPLE') else q[:4]
        cams[int(p[0])] = (w, h, np.array([[fx, 0, cx], [0, fy, cy], [0, 0, 1]], np.float64))
    ims = {}
    with open(os.path.join(d, 'images.txt')) as f:
        pose = True
        for l in f:
            if l[0] == '#': continue
            if pose:
                p = l.split(); w, x, y, z = map(float, p[1:5]); t = np.array(p[5:8], float)
                R = np.array([[1-2*(y*y+z*z), 2*(x*y-w*z), 2*(x*z+w*y)], [2*(x*y+w*z), 1-2*(x*x+z*z), 2*(y*z-w*x)],
                              [2*(x*z-w*y), 2*(y*z+w*x), 1-2*(x*x+y*y)]])
                ims[p[9]] = (R, t, int(p[8]))
            pose = not pose
    return cams, ims


def centre(R, t): return -R.T @ t


def select(cams, ims, a):
    C = {n: centre(*ims[n][:2]) for n in ims}
    CA, CB = C[f'f1/LE-{A}.jpg'], C[f'f1/LE-{B}.jpg']; seg = CB - CA; L = np.linalg.norm(seg); mid = (CA + CB) / 2
    def segdist(p):
        s = np.clip((p - CA) @ seg / L / L, 0, 1); return np.linalg.norm(p - (CA + s * seg))
    nodes = sorted({n.split('/')[1] for n in ims if n.startswith('f1/') and segdist(C[n]) < a.radius} |
                   {f'LE-{A}.jpg', f'LE-{B}.jpg'})
    views = [f'f{k}/{n}' for n in nodes for k in a.faces if f'f{k}/{n}' in ims]
    fly = []
    for n in sorted(x for x in ims if x.startswith('jfly')):
        R, t, _ = ims[n]; d = mid - C[n]; dist = np.linalg.norm(d)
        if dist < a.fly_radius and R[2] @ d / dist > np.cos(np.radians(55)): fly.append(n)
    if len(fly) > a.fly_max: fly = [fly[i] for i in np.linspace(0, len(fly) - 1, a.fly_max).round().astype(int)]
    print(f'{len(nodes)} nodes within {a.radius} of the walk: ' + ' '.join(n[3:-4] for n in nodes))
    print(f'{len(views)} faces, {len(fly)} flyover frames: ' + ' '.join(n[-8:-4] for n in fly))
    return views + fly, CA, CB


def load(a, cams, ims, names):
    imgs, K, w2c = [], [], []
    for n in names:
        R, t, ci = ims[n]; w, h, k = cams[ci]
        im = cv2.cvtColor(cv2.imread(os.path.join(a.images, n.replace('/', os.sep))), cv2.COLOR_BGR2RGB)
        k = k.copy()
        if w != h:                                   # flyover frames: the middle square, so every view is square
            s = min(w, h); x0, y0 = (w - s) // 2, (h - s) // 2
            im = im[y0:y0 + s, x0:x0 + s]; k[0, 2] -= x0; k[1, 2] -= y0
        M = np.eye(4); M[:3, :3] = R; M[:3, 3] = t
        imgs.append(np.ascontiguousarray(im)); K.append(k); w2c.append(M)
    return imgs, np.array(K), np.array(w2c)


def umeyama(src, dst):
    ms, md = src.mean(0), dst.mean(0); s0, d0 = src - ms, dst - md
    U, S, Vt = np.linalg.svd(d0.T @ s0 / len(src)); D = np.eye(3)
    if np.linalg.det(U @ Vt) < 0: D[2, 2] = -1
    R = U @ D @ Vt; sc = np.trace(np.diag(S) @ D) / s0.var(0).sum()
    return sc, R, md - sc * R @ ms


def run_ma(a, imgs, K, w2c):
    import torch
    from mapanything.models import MapAnything
    from mapanything.utils.image import preprocess_inputs
    dev = 'cuda'
    model = MapAnything.from_pretrained(a.ma_name).to(dev)
    enc = model._encode_n_views                      # the encoder takes every view in one pass: 8 at a time instead
    def enc_chunked(views, n=8):
        F, Rg = [], []
        for i in range(0, len(views), n):
            f, r = enc(views[i:i + n]); F += list(f); Rg = None if r is None else (Rg or []) + list(r)
        return tuple(F), (None if Rg is None else tuple(Rg))
    model._encode_n_views = enc_chunked
    views = []
    for im, k, M in zip(imgs, K, w2c):
        v = {'img': torch.from_numpy(im), 'intrinsics': torch.from_numpy(k).float()}
        if not a.no_poses:
            v['camera_poses'] = torch.from_numpy(np.linalg.inv(M)).float(); v['is_metric_scale'] = torch.tensor([False])
        views.append(v)
    pv = preprocess_inputs(views, resize_mode='square', size=518)
    with torch.no_grad():
        out = model.infer(pv, memory_efficient_inference=True, minibatch_size=a.minibatch, use_amp=True, amp_dtype='bf16', apply_mask=True,
                          mask_edges=True, apply_confidence_mask=False)
    P, Cf, Col, cam = [], [], [], []
    for o in out:
        P.append(o['pts3d'][0].float().cpu().numpy()); Cf.append(o['conf'][0].float().cpu().numpy())
        c = o['img_no_norm'][0].float().cpu().numpy(); Col.append((c * 255 if c.max() <= 1.5 else c).clip(0, 255).astype(np.uint8))
        cam.append(o['camera_poses'][0].float().cpu().numpy()[:3, 3])
        if 'mask' in o: P[-1][~o['mask'][0, ..., 0].cpu().numpy().astype(bool)] = np.nan
    return np.array(P), np.array(Cf), np.array(Col), np.array(cam)


def run_da3(a, imgs, K, w2c):
    import torch
    from depth_anything_3.api import DepthAnything3
    model = DepthAnything3.from_pretrained(a.da3_name).to('cuda')
    kw = {} if a.no_poses else dict(extrinsics=w2c.astype(np.float32), intrinsics=K.astype(np.float32))
    with torch.no_grad():
        p = model.inference(imgs, process_res=a.res, **kw)
    D, Kp, E = p.depth, p.intrinsics, p.extrinsics
    N, h, w = D.shape
    u, v = np.meshgrid(np.arange(w) + .5, np.arange(h) + .5)
    pix = np.stack([u, v, np.ones_like(u)], -1)
    P, cam = [], []
    for i in range(N):
        Xc = (pix @ np.linalg.inv(Kp[i]).T) * D[i][..., None]
        R, t = E[i][:3, :3], E[i][:3, 3]
        P.append((Xc - t) @ R); cam.append(-R.T @ t)
    conf = p.conf if p.conf is not None else np.ones_like(D)
    return np.array(P, np.float32), conf, p.processed_images, np.array(cam)


def write_depth(a, names, P, cam, fit, r_near=0.4, r_far=40.0, N=640):
    """The two ends' faces' depth in node_depth.py's form (DIR/LE<n>/face<k>_measured-depth.png, node_depth.json), for
    walk_ends.py --mid-depth: grey g codes the distance along the ray, r = r_far / (1 + g (ratio - 1)); 0 is sky or
    nothing (beyond r_far, or masked)."""
    ratio = r_far / r_near
    for n in (A, B):
        d = os.path.join(a.depth_out, f'LE{n}'); os.makedirs(d, exist_ok=True); rep = {}
        for k in range(1, 7):
            nm = f'f{k}/LE-{n}.jpg'
            if nm not in names: continue
            i = names.index(nm); Pi, ci = P[i].astype(np.float64), cam[i].astype(np.float64)
            if fit:
                sc, R, tr = fit; Pi = Pi @ R.T * sc + tr; ci = ci @ R.T * sc + tr
            r = np.linalg.norm(Pi - ci, axis=-1)
            with np.errstate(all='ignore'):
                g = (r_far / r - 1) / (ratio - 1)
            sky = ~np.isfinite(g) | (r > r_far)
            g = np.where(sky, 0, np.clip(g, 0.03, 1))
            img = cv2.resize((g * 255).round().astype(np.uint8), (N, N), interpolation=cv2.INTER_NEAREST)
            cv2.imwrite(os.path.join(d, f'face{k}_measured-depth.png'), img)
            rep[f'face{k}'] = {'image': nm, 'sky': float(sky.mean()), 'median_r': float(np.nanmedian(np.where(sky, np.nan, r)))}
        rep.update(node=str(n), r_near=r_near, r_far=r_far, ratio=ratio, source=f'mv3d_cliff.py --model {a.model}')
        json.dump(rep, open(os.path.join(d, 'node_depth.json'), 'w'), indent=1)
        print(f'depth for {n}: ' + ' '.join(f"f{k[-1]} sky {v['sky']:.2f}" for k, v in rep.items() if k.startswith('face')))


def splat(P, Col, CA, Rc, apart, T, W, H):
    q = (P - CA) @ Rc.T
    along, out = q[:, 2] - T * apart, np.hypot(q[:, 0], q[:, 1])
    phi = np.arctan2(q[:, 0], -q[:, 1]); th = np.arctan2(out, along); dist = np.hypot(out, along)
    u = ((phi / (np.pi + np.radians(20)) + 1) / 2 * W).astype(int); v = (th / np.pi * H).astype(int)
    k = (u >= 0) & (u < W) & (v >= 0) & (v < H) & (dist > 0.05)
    idx = (v * W + u)[k]; d = dist[k]; c = Col[k]
    o = np.argsort(d); idx, d, c = idx[o], d[o], c[o]
    idx, first = np.unique(idx, return_index=True)
    img = np.zeros((H * W, 3), np.uint8); dep = np.full(H * W, np.nan, np.float32)
    img[idx] = c[first]; dep[idx] = d[first]
    img, dep = img.reshape(H, W, 3), dep.reshape(H, W)
    for _ in range(2):                                   # close one-pixel holes
        hole = np.isnan(dep); g = cv2.dilate(img, np.ones((3, 3), np.uint8))
        gd = cv2.erode(np.nan_to_num(dep, nan=1e9), np.ones((3, 3), np.uint8))
        img[hole] = g[hole]; dep[hole] = np.where(gd[hole] < 1e8, gd[hole], np.nan)
    lg = np.clip((np.log(np.nan_to_num(dep, nan=1e9)) - np.log(0.5)) / (np.log(40) - np.log(0.5)), 0, 1)
    dc = cv2.applyColorMap((255 - lg * 255).astype(np.uint8), cv2.COLORMAP_TURBO); dc[np.isnan(dep)] = 0
    return cv2.cvtColor(img, cv2.COLOR_RGB2BGR), dc


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('sparse'); ap.add_argument('images'); ap.add_argument('ends'); ap.add_argument('out')
    ap.add_argument('--model', choices=['ma', 'da3'], default='ma')
    ap.add_argument('--ma-name', default='facebook/map-anything')
    ap.add_argument('--da3-name', default='depth-anything/DA3-LARGE-1.1'); ap.add_argument('--res', type=int, default=504)
    ap.add_argument('--no-poses', action='store_true', help='images and intrinsics only; fitted to the model afterwards')
    ap.add_argument('--radius', type=float, default=6); ap.add_argument('--fly-radius', type=float, default=35)
    ap.add_argument('--fly-max', type=int, default=24); ap.add_argument('--stride', type=int, default=2)
    ap.add_argument('--gpu-frac', type=float, default=0, help='cap on the share of GPU memory (beside another GPU job)')
    ap.add_argument('--minibatch', type=int, default=1, help="MapAnything's minibatch_size (1: least GPU memory)")
    ap.add_argument('--faces', type=int, nargs='*', default=[1, 2, 3, 4, 5, 6], help='which faces: 1 front, 2 bottom, 3 back, 4 right, 5 left, 6 top')
    ap.add_argument('--depth-out', help="write the two ends' depth here in node_depth.py's form (walk_ends.py --mid-depth)")
    ap.add_argument('--dry', action='store_true')
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    cams, ims = read_model(a.sparse)
    names, CA, CB = select(cams, ims, a)
    if a.dry: return
    imgs, K, w2c = load(a, cams, ims, names)
    if a.gpu_frac:
        import torch; torch.cuda.set_per_process_memory_fraction(a.gpu_frac)
    t0 = time.time()
    P, Cf, Col, cam = (run_ma if a.model == 'ma' else run_da3)(a, imgs, K, w2c)
    import torch; print(f'{a.model}: {len(names)} views, {time.time() - t0:.0f} s, GPU peak {torch.cuda.max_memory_allocated() / 2**30:.1f} GB')
    C_in = np.array([centre(M[:3, :3], M[:3, 3]) for M in w2c])
    sc, R, tr = umeyama(cam, C_in)
    print(f'cameras against the model: before a fit median {np.median(np.linalg.norm(cam - C_in, axis=1)):.3f}; '
          f'fit scale {sc:.3f}, after median {np.median(np.linalg.norm(cam @ R.T * sc + tr - C_in, axis=1)):.3f}')
    fit = a.no_poses or np.median(np.linalg.norm(cam - C_in, axis=1)) > 0.05
    if a.depth_out:
        write_depth(a, names, P, cam, (sc, R, tr) if fit else None)
    P = P[:, ::a.stride, ::a.stride]; Cf = Cf[:, ::a.stride, ::a.stride]; Col = Col[:, ::a.stride, ::a.stride]
    view = np.broadcast_to(np.arange(len(names))[:, None, None], P.shape[:3])
    P, Cf, Col, view = P.reshape(-1, 3), Cf.reshape(-1), Col.reshape(-1, 3), view.reshape(-1)
    ok = np.isfinite(P).all(1) & (Cf >= np.nanpercentile(Cf, 20))
    P, Cf, Col, view = P[ok], Cf[ok], Col[ok], view[ok]
    if fit: P = P @ R.T * sc + tr
    RA = w2c[names.index(f'f1/LE-{A}.jpg')][:3, :3]
    apart = np.linalg.norm(CB - CA); fwd = (CB - CA) / apart; up = -RA[1]
    right = np.cross(fwd, up); right /= np.linalg.norm(right); down = np.cross(fwd, right); Rc = np.stack([right, down, fwd])
    q = (P - CA) @ Rc.T; out = np.hypot(q[:, 0], q[:, 1])
    near = np.hypot(out, q[:, 2] - apart / 2) < 40
    np.savez_compressed(os.path.join(a.out, 'points.npz'), xyz=P[near].astype(np.float32), rgb=Col[near],
                        conf=Cf[near].astype(np.float16), view=view[near].astype(np.int16), names=np.array(names))
    bridge = (out < 3) & (q[:, 2] > .5 * apart) & (q[:, 2] < .9 * apart)
    isA = np.array([n.endswith(f'LE-{A}.jpg') for n in names])[view]; isB = np.array([n.endswith(f'LE-{B}.jpg') for n in names])[view]
    print(f'{len(P)} points; {near.sum()} within 40 of the walk; within 3 of the line on the bridge\'s stretch: '
          f'{bridge.sum()} ({(bridge & ~isA & ~isB).sum()} not from the two ends)')
    W, H = 960, 480
    rows = []
    for T, nm, mine in ((0, 'first', isA), (.5, None, None), (1, 'last', isB)):
        pic = cv2.resize(cv2.imread(os.path.join(a.ends, f'ends_polar_{nm}.png')), (W, H), interpolation=cv2.INTER_AREA) if nm else np.zeros((H, W, 3), np.uint8)
        sel = ~mine if mine is not None else np.ones(len(P), bool)
        col, dep = splat(P[sel], Col[sel], CA, Rc, apart, T, W, H)
        owndep = splat(P[mine], Col[mine], CA, Rc, apart, T, W, H)[1] if mine is not None else np.zeros_like(pic)
        r = np.hstack([pic, col, dep, owndep])
        lab = {0: f'{A}', .5: 'halfway', 1: f'{B}'}[T]
        for j, s in enumerate([f'{lab}: node picture' if nm else 'halfway', 'from the other views', 'their distance', 'own faces\' distance' if nm else '']):
            cv2.putText(r, s, (10 + j * W, 28), cv2.FONT_HERSHEY_SIMPLEX, .8, (255, 255, 255), 2)
        rows.append(r)
    cv2.imwrite(os.path.join(a.out, 'sheet.jpg'), np.vstack(rows), [cv2.IMWRITE_JPEG_QUALITY, 85])
    print('wrote', os.path.join(a.out, 'sheet.jpg'))


if __name__ == '__main__':
    main()
