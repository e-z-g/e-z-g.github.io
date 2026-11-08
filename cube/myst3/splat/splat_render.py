# Render a Gaussian splat (3DGS .ply, as Brush exports it) from COLMAP cameras, beside the real image.
#   py -3 splat_render.py SPLAT.ply DATASET OUT_DIR NAME [NAME ...] [--size 512]
# DATASET is the COLMAP text dataset the splat was trained on (sparse/0, images/). Front-to-back
# alpha compositing of each Gaussian's 2D footprint (EWA), spherical harmonics up to degree 3.
import argparse, os, re, sys
import numpy as np, torch
from PIL import Image
ap = argparse.ArgumentParser()
ap.add_argument('ply'); ap.add_argument('dataset'); ap.add_argument('out'); ap.add_argument('names', nargs='+')
ap.add_argument('--size', type=int, default=512); ap.add_argument('--chunk', type=int, default=400000)
ap.add_argument('--depth', action='store_true', help='also save each view\'s depth (where it becomes half covered, along the camera axis) as NAME_depth.npy, 0 where it never does')
a = ap.parse_args()
dev = 'cuda'

def read_ply(p):
    with open(p, 'rb') as f:
        head = b''
        while not head.endswith(b'end_header\n'):
            head += f.readline()
        n = int(re.search(rb'element vertex (\d+)', head).group(1))
        props = re.findall(rb'property float (\S+)', head)
        data = np.fromfile(f, dtype='<f4', count=n * len(props)).reshape(n, len(props))
    return {k.decode(): data[:, i] for i, k in enumerate(props)}

P = read_ply(a.ply)
N = len(P['x'])
X = torch.tensor(np.stack([P['x'], P['y'], P['z']], 1), device=dev)
S = torch.tensor(np.exp(np.stack([P['scale_0'], P['scale_1'], P['scale_2']], 1)), device=dev)
Q = torch.tensor(np.stack([P['rot_0'], P['rot_1'], P['rot_2'], P['rot_3']], 1), device=dev)
Q = Q / Q.norm(dim=1, keepdim=True)
O = torch.sigmoid(torch.tensor(P['opacity'], device=dev))
rest = sorted([k for k in P if k.startswith('f_rest_')], key=lambda k: int(k[7:]))
DC = torch.tensor(np.stack([P['f_dc_0'], P['f_dc_1'], P['f_dc_2']], 1), device=dev)
REST = torch.tensor(np.stack([P[k] for k in rest], 1), device=dev).reshape(N, 3, -1).transpose(1, 2) if rest else None
del P
print(N, 'splats;', 0 if REST is None else REST.shape[1], 'higher SH coefficients per colour')

def sh_colour(idx, d):
    C0 = 0.28209479177387814
    c = C0 * DC[idx]
    if REST is not None and REST.shape[1] >= 3:
        x, y, z = d[:, 0:1], d[:, 1:2], d[:, 2:3]
        R = REST[idx]
        C1 = 0.4886025119029199
        c = c - C1 * y * R[:, 0] + C1 * z * R[:, 1] - C1 * x * R[:, 2]
        if R.shape[1] >= 8:
            C2 = [1.0925484305920792, -1.0925484305920792, 0.31539156525252005, -1.0925484305920792, 0.5462742152960396]
            xx, yy, zz, xy, yz, xz = x * x, y * y, z * z, x * y, y * z, x * z
            c = c + C2[0] * xy * R[:, 3] + C2[1] * yz * R[:, 4] + C2[2] * (2 * zz - xx - yy) * R[:, 5] + C2[3] * xz * R[:, 6] + C2[4] * (xx - yy) * R[:, 7]
            if R.shape[1] >= 15:
                C3 = [-0.5900435899266435, 2.890611442640554, -0.4570457994644658, 0.3731763325901154, -0.4570457994644658, 1.445305721320277, -0.5900435899266435]
                c = c + C3[0] * y * (3 * xx - yy) * R[:, 8] + C3[1] * xy * z * R[:, 9] + C3[2] * y * (4 * zz - xx - yy) * R[:, 10] \
                      + C3[3] * z * (2 * zz - 3 * xx - 3 * yy) * R[:, 11] + C3[4] * x * (4 * zz - xx - yy) * R[:, 12] \
                      + C3[5] * z * (xx - yy) * R[:, 13] + C3[6] * x * (xx - 3 * yy) * R[:, 14]
    return (c + 0.5).clamp(0, 1)

def quat_rot(q):
    w, x, y, z = q.unbind(1)
    return torch.stack([1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y),
                        2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x),
                        2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)], 1).reshape(-1, 3, 3)

def qrot(qw, qx, qy, qz):
    return quat_rot(torch.tensor([[qw, qx, qy, qz]], dtype=torch.float32, device=dev))[0]

cams = {}
for l in open(os.path.join(a.dataset, 'sparse', '0', 'cameras.txt')):
    if l.startswith('#') or not l.strip(): continue
    p = l.split(); cams[int(p[0])] = (p[1], int(p[2]), int(p[3]), [float(v) for v in p[4:]])
imgs = {}
for l in open(os.path.join(a.dataset, 'sparse', '0', 'images.txt')):
    p = l.split()
    if len(p) >= 10 and not l.startswith('#'):
        imgs[p[9]] = ([float(v) for v in p[1:8]], int(p[8]))

def render(name):
    (qw, qx, qy, qz, tx, ty, tz), cid = imgs[name]
    model, W, H, prm = cams[cid]
    fx = fy = prm[0]; cx, cy = (prm[1], prm[2]) if model == 'SIMPLE_PINHOLE' else (prm[2], prm[3])
    if model == 'PINHOLE': fx, fy = prm[0], prm[1]
    k = a.size / max(W, H); W2, H2 = round(W * k), round(H * k)
    fx, fy, cx, cy = fx * k, fy * k, cx * k, cy * k
    R = qrot(qw, qx, qy, qz); t = torch.tensor([tx, ty, tz], device=dev)
    C = -R.T @ t
    img = torch.zeros(H2 * W2, 3, device=dev)
    # all pairs (gaussian, pixel) in view, then composite per pixel by depth
    keys, alphas, cols = [], [], []
    for s0 in range(0, N, a.chunk):
        sl = slice(s0, s0 + a.chunk)
        Y = X[sl] @ R.T + t
        z = Y[:, 2]
        u = fx * Y[:, 0] / z + cx; v = fy * Y[:, 1] / z + cy
        ok = (z > 0.05) & (u > -50) & (u < W2 + 50) & (v > -50) & (v < H2 + 50)
        idx = torch.nonzero(ok).squeeze(1)
        if not len(idx): continue
        Yk, zk, uk, vk = Y[idx], z[idx], u[idx], v[idx]
        gi = idx + s0
        M = quat_rot(Q[gi]) * S[gi][:, None, :]
        Sig = M @ M.transpose(1, 2)
        J = torch.zeros(len(idx), 2, 3, device=dev)
        J[:, 0, 0] = fx / zk; J[:, 0, 2] = -fx * Yk[:, 0] / zk ** 2
        J[:, 1, 1] = fy / zk; J[:, 1, 2] = -fy * Yk[:, 1] / zk ** 2
        T = J @ R
        S2 = T @ Sig @ T.transpose(1, 2) + 0.3 * torch.eye(2, device=dev)
        det = S2[:, 0, 0] * S2[:, 1, 1] - S2[:, 0, 1] ** 2
        inv = torch.stack([S2[:, 1, 1], -S2[:, 0, 1], S2[:, 0, 0]], 1) / det[:, None]
        lam = 0.5 * (S2[:, 0, 0] + S2[:, 1, 1]) + torch.sqrt((0.25 * (S2[:, 0, 0] - S2[:, 1, 1]) ** 2 + S2[:, 0, 1] ** 2).clamp(min=0))
        rad = torch.ceil(3 * torch.sqrt(lam)).clamp(max=40).long()
        d = X[gi] - C; d = d / d.norm(dim=1, keepdim=True)
        col = sh_colour(gi, d)
        for r in (1, 2, 4, 8, 16, 24, 40):          # footprints in size groups, so each group is one tensor
            sel = torch.nonzero((rad <= r) & (rad > {1: 0, 2: 1, 4: 2, 8: 4, 16: 8, 24: 16, 40: 24}[r])).squeeze(1)
            if not len(sel): continue
            off = torch.arange(-r, r + 1, device=dev)
            oy, ox = torch.meshgrid(off, off, indexing='ij'); ox = ox.reshape(-1); oy = oy.reshape(-1)
            for s1 in range(0, len(sel), max(1, 4000000 // len(ox))):
                ss = sel[s1:s1 + max(1, 4000000 // len(ox))]
                px = torch.floor(uk[ss])[:, None] + ox[None]; py = torch.floor(vk[ss])[:, None] + oy[None]
                dx = px + 0.5 - uk[ss][:, None]; dy = py + 0.5 - vk[ss][:, None]
                iv = inv[ss]
                pw = iv[:, 0:1] * dx * dx + 2 * iv[:, 1:2] * dx * dy + iv[:, 2:3] * dy * dy
                al = (O[gi[ss]][:, None] * torch.exp(-0.5 * pw)).clamp(max=0.99)
                m = (al > 1 / 255) & (px >= 0) & (px < W2) & (py >= 0) & (py < H2)
                pix = (py * W2 + px)[m].long()
                keys.append(torch.stack([pix.float(), zk[ss][:, None].expand_as(px)[m]], 1))
                alphas.append(al[m]); cols.append(col[ss][:, None, :].expand(-1, len(ox), -1)[m])
    K = torch.cat(keys); A = torch.cat(alphas); Cc = torch.cat(cols)
    o1 = torch.argsort(K[:, 1]); K, A, Cc = K[o1], A[o1], Cc[o1]          # by depth, then stably by pixel
    o2 = torch.argsort(K[:, 0], stable=True); pix = K[o2, 0].long(); A = A[o2]; Cc = Cc[o2]
    # in double: the running sum over every sample of a view reaches millions, where single
    # precision loses the per-pixel differences (at 1280 px everything past a third of the rows)
    lg = torch.log1p(-A).double()
    cum = torch.cumsum(lg, 0)
    start = torch.ones_like(pix, dtype=torch.bool); start[1:] = pix[1:] != pix[:-1]
    first = torch.cummax(torch.where(start, torch.arange(len(pix), device=dev), torch.zeros_like(pix)), 0).values
    before = cum - lg - (cum[first] - lg[first])                            # log transmittance in front of each
    w = A * torch.exp(before).float()
    img.index_add_(0, pix, w[:, None] * Cc)
    if a.depth:
        zs = K[o2, 1]
        cross = (before > np.log(0.5)) & (before + lg <= np.log(0.5))   # where the view becomes half covered
        dep = torch.zeros(H2 * W2, device=dev)
        dep[pix[cross]] = zs[cross]
    out = (img.reshape(H2, W2, 3).clamp(0, 1) * 255).byte().cpu().numpy()
    real = Image.open(os.path.join(a.dataset, 'images', name)).convert('RGB').resize((W2, H2), Image.LANCZOS)
    both = Image.new('RGB', (W2 * 2 + 8, H2), 'black'); both.paste(real, (0, 0)); both.paste(Image.fromarray(out), (W2 + 8, 0))
    fn = os.path.join(a.out, name.replace('/', '_').replace('.jpg', '.png'))
    both.save(fn)
    if a.depth:
        np.save(fn[:-4] + '_depth.npy', dep.reshape(H2, W2).cpu().numpy())
    r = np.asarray(real, float); o = out.astype(float)
    psnr = 10 * np.log10(255 ** 2 / ((r - o) ** 2).mean())
    print(f'{name}: {len(pix)} footprint samples, PSNR {psnr:.1f} dB -> {fn}', flush=True)

os.makedirs(a.out, exist_ok=True)
for nm in a.names:
    render(nm)
