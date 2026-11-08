#!/usr/bin/env python3
"""
Put misplaced nodes back: each node's own dense points fitted onto the cloud of
a set of trusted nodes, by a similarity (shift, turn, scale about the node).

    python node_align.py DENSE TRUSTED OUT.json [--nodes MA-2001 ...] [--samples 8000]
        [--masks MASKS] [--starts 0.5,0.7,1,1.4,2] [--inlier 0.03]

DENSE is a dense workspace after fusion (sparse/images.bin, stereo/depth_maps,
fused.ply and fused.ply.vis); TRUSTED names the trusted nodes as for
ghost_points.py. The reference cloud is the fused points made by trusted nodes
alone. For every other node (or --nodes), points are sampled from its six
faces' geometric depth maps, and an ICP with scale moves them onto the
reference: X' = C + t + s Rot (X - C), with C the node's centre. Since a
similarity about any point keeps a node's depth maps consistent with its new
pose (only their depths change, by s), the node's pose becomes centre C + t,
turned by Rot, and its depth maps are multiplied by s; no stereo needs
running again.

ICP is started at each scale in --starts (a run of nodes misplaced together
is often off in scale: the joined model's steps in MAIS came out 2.7 times the
others'), with inliers closer than a share of the distance from the node that
falls from 0.2 to --inlier, and the start with the most final inliers wins.
Each node is then tested as ghost_points.py tests points: its points
projected into the trusted faces, the share they see past (a farther depth
or, with --masks, sky), before and after. Scale stays within 2x and the turn within
10 degrees (left free, the search shrank nodes to a tenth, which hides their
points from the trusted faces instead of fitting them). A move is kept only
when more points agree with the trusted faces, fewer are seen past, more are
inliers to the reference, and the scale is off its bound (shrinking alone
makes more points agree: a run already in place, shrunk to half, did). With --runs, each run of nodes named moves as one: one similarity about the
run's mean centre, so a run cannot hide its points by shrinking each node onto
itself, and runs already in place serve as a check that the search leaves
them be. Writes OUT.json: per node the old and new
centre, the turn in degrees, s, both inlier shares and both seen-past shares.
Needs numpy, Pillow, torch; ghost_points.py and its helpers beside it.
"""
import argparse
import json
import os
import re

import numpy as np

from depth_fill import read_colmap_array
from ghost_points import image_names_bin, read_ply, read_vis

NODE = re.compile(r'f(\d)/(.*)\.jpg')


def umeyama(P, Q, C):
    """s, Rot, t minimising |C + t + s Rot (P - C) - Q| (rows)."""
    mp, mq = P.mean(0), Q.mean(0)
    Pc, Qc = P - mp, Q - mq
    U, S, Vt = np.linalg.svd(Qc.T @ Pc / len(P))
    D = np.eye(3); D[2, 2] = np.sign(np.linalg.det(U @ Vt))
    Rot = U @ D @ Vt
    s = (S * np.diag(D)).sum() / (Pc ** 2).sum(1).mean()
    # Q = s Rot P + b; in the pivot form, t = b + s Rot C - C
    b = mq - s * Rot @ mp
    return s, Rot, b + s * Rot @ C - C


def rotvec(R):
    ang = np.arccos(np.clip((np.trace(R) - 1) / 2, -1, 1))
    if ang < 1e-9:
        return np.zeros(3)
    w = np.array([R[2, 1] - R[1, 2], R[0, 2] - R[2, 0], R[1, 0] - R[0, 1]]) / (2 * np.sin(ang))
    return w * ang


def rotmat(w):
    ang = np.linalg.norm(w)
    if ang < 1e-12:
        return np.eye(3)
    k = w / ang
    K = np.array([[0, -k[2], k[1]], [k[2], 0, -k[0]], [-k[1], k[0], 0]])
    return np.eye(3) + np.sin(ang) * K + (1 - np.cos(ang)) * K @ K


def search(f, x0, rng, steps=(0.6, 0.6, 0.6, 0.15, 0.04, 0.04, 0.04), rounds=6, tries=60):
    """Maximise f by random steps round the best so far, halving them each round."""
    x, fx = np.array(x0, float), f(x0)
    st = np.array(steps, float)
    for _ in range(rounds):
        for _ in range(tries):
            y = x + rng.normal(size=len(x)) * st
            fy = f(y)
            if fy > fx:
                x, fx = y, fy
        st /= 2
    return x, fx


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('dense'); ap.add_argument('trusted'); ap.add_argument('out')
    ap.add_argument('--nodes', nargs='*')
    ap.add_argument('--runs', nargs='*', help='NAME=NODE,NODE,...: nodes moved together by one similarity')
    ap.add_argument('--samples', type=int, default=8000)
    ap.add_argument('--masks'); ap.add_argument('--sky-margin', type=int, default=8)
    ap.add_argument('--starts', default='0.5,0.7,1,1.4,2')
    ap.add_argument('--inlier', type=float, default=0.03)
    ap.add_argument('--iters', type=int, default=40)
    ap.add_argument('--voxel', type=float, default=0.03)
    a = ap.parse_args()
    import torch
    dev = 'cuda' if torch.cuda.is_available() else 'cpu'

    poses = {}
    order, _ = image_names_bin(os.path.join(a.dense, 'sparse', 'images.bin'), poses)
    trusted = set()
    for line in open(a.trusted):
        for tok in line.split():
            m = NODE.fullmatch(tok) or re.fullmatch(r'([A-Z]+-\d+)', tok)
            if m:
                trusted.add(m.groups()[-1])
    faces = {}
    for nm in poses:
        m = NODE.fullmatch(nm)
        if m:
            faces.setdefault(m.group(2), {})[int(m.group(1))] = nm
    centre = {n: -poses[f[1]][0].T @ poses[f[1]][1] for n, f in faces.items() if 1 in f}

    # The reference: fused points whose every source image is a trusted node's.
    pts = read_ply(os.path.join(a.dense, 'fused.ply'))
    vis = read_vis(os.path.join(a.dense, 'fused.ply.vis'))
    tr_idx = np.array([bool((m := NODE.fullmatch(nm))) and m.group(2) in trusted for nm in order])
    keep = np.array([len(v) > 0 and tr_idx[v].all() for v in vis])
    ref = np.stack([pts['x'], pts['y'], pts['z']], 1)[keep].astype(np.float64)
    _, u = np.unique(np.floor(ref / a.voxel).astype(np.int64), axis=0, return_index=True)
    ref = ref[u]
    print(f'reference: {len(ref)} points from trusted nodes alone ({keep.sum()} before thinning)')
    R_t = torch.tensor(ref, dtype=torch.float32, device=dev)

    def nearest(Q):
        Qt = torch.tensor(Q, dtype=torch.float32, device=dev)
        d = torch.empty(len(Q), device=dev); j = torch.empty(len(Q), dtype=torch.long, device=dev)
        for k in range(0, len(Q), 512):
            dd = torch.cdist(Qt[k:k + 512], R_t)
            v, i = dd.min(1); d[k:k + 512] = v; j[k:k + 512] = i
        return d.cpu().numpy(), ref[j.cpu().numpy()]

    dcache, scache = {}, {}

    def dmap(name):
        if name not in dcache:
            p = os.path.join(a.dense, 'stereo', 'depth_maps', name + '.geometric.bin')
            dcache[name] = read_colmap_array(p) if os.path.exists(p) else None
        return dcache[name]

    def skymap(name, shape):
        if not a.masks:
            return None
        if name not in scache:
            p = os.path.join(a.masks, name + '.png')
            if not os.path.exists(p):
                scache[name] = None
            else:
                from PIL import Image, ImageFilter
                m = Image.open(p).convert('L')
                if a.sky_margin:
                    m = m.filter(ImageFilter.MaxFilter(2 * a.sky_margin + 1))
                scache[name] = np.asarray(m.resize((shape[1], shape[0]), Image.NEAREST)) < 128
        return scache[name]

    tfaces = [nm for n in trusted if n in faces for nm in faces[n].values()]

    def seen_past(X, tol=0.1):
        agree = against = 0
        for name in tfaces:
            z = dmap(name)
            if z is None:
                continue
            H, W = z.shape
            R, t = poses[name]
            Y = X @ R.T + t
            ok = Y[:, 2] > 1e-6
            x = Y[:, 0] / np.where(ok, Y[:, 2], 1); y = Y[:, 1] / np.where(ok, Y[:, 2], 1)
            ok &= (np.abs(x) < 1) & (np.abs(y) < 1)
            if not ok.any():
                continue
            px = np.clip(((x + 1) * W / 2).astype(int), 0, W - 1); py = np.clip(((y + 1) * H / 2).astype(int), 0, H - 1)
            zn = np.where(ok, z[py, px], 0)
            has = ok & (zn > 0)
            rel = (zn[has] - Y[has, 2]) / Y[has, 2]
            agree += int((np.abs(rel) <= tol).sum()); against += int((rel > tol).sum())
            sm = skymap(name, z.shape)
            if sm is not None:
                against += int((ok & (zn <= 0) & sm[py, px]).sum())
        return against / max(1, agree + against), agree

    # Trusted faces on the GPU, for the search: depths and sky at a fixed size.
    G = 384
    TD, TS, TR, TT = [], [], [], []
    from PIL import Image
    for name in tfaces:
        z = dmap(name)
        if z is None:
            continue
        zi = np.asarray(Image.fromarray(z.astype(np.float32)).resize((G, G), Image.NEAREST))
        sm = skymap(name, z.shape)
        TD.append(zi); TS.append(np.zeros((G, G), bool) if sm is None else
                                 np.asarray(Image.fromarray(sm).resize((G, G), Image.NEAREST)))
        TR.append(poses[name][0]); TT.append(poses[name][1])
    TD = torch.tensor(np.stack(TD), device=dev); TS = torch.tensor(np.stack(TS), device=dev)
    TR = torch.tensor(np.stack(TR), dtype=torch.float32, device=dev); TT = torch.tensor(np.stack(TT), dtype=torch.float32, device=dev)
    fidx = torch.arange(len(TD), device=dev)[:, None]
    print(f'{len(TD)} trusted faces on {dev}')

    def vis_score(Pt, C, x):
        """Agreeing views minus twice the views that see past (or sky), per point."""
        if abs(x[3]) > np.log(2) or np.linalg.norm(x[4:]) > np.radians(10):
            return -1e9                                  # nodes keep their size within 2x and turn within 10 degrees
        t, s, Rot = x[:3], float(np.exp(x[3])), rotmat(x[4:])
        M = torch.tensor(s * Rot, dtype=torch.float32, device=dev)
        X = Pt @ M.T + torch.tensor(C + t, dtype=torch.float32, device=dev)
        Y = torch.einsum('fij,nj->fni', TR, X) + TT[:, None, :]
        zc = Y[..., 2]
        ok = zc > 1e-6
        zs = torch.where(ok, zc, torch.ones_like(zc))
        u, v = Y[..., 0] / zs, Y[..., 1] / zs
        ok &= (u.abs() < 1) & (v.abs() < 1)
        px = ((u + 1) * G / 2).long().clamp(0, G - 1); py = ((v + 1) * G / 2).long().clamp(0, G - 1)
        zn = TD[fidx, py, px]
        has = ok & (zn > 0)
        r = torch.log(torch.where(has, zn, torch.ones_like(zn)) / zs)
        agree = (has & (r.abs() <= 0.1)).sum()
        past = (has & (r > 0.1)).sum() + (ok & (zn <= 0) & TS[fidx, py, px]).sum()
        return float(agree - 2 * past) / len(Pt)

    rng = np.random.default_rng(0)
    starts = [float(v) for v in a.starts.split(',')]
    if a.runs:
        groups = [(r.split('=')[0], [m for m in r.split('=')[1].split(',') if m in centre]) for r in a.runs]
    else:
        groups = [(n, [n]) for n in (a.nodes or sorted(n for n in centre if n not in trusted))]
    out = {}
    for n, members in groups:
        C = np.mean([centre[m] for m in members], 0)
        P, own = [], []
        for k, name in [(k, nm) for m in members for k, nm in faces[m].items()]:
            z = dmap(name)
            if z is None:
                continue
            H, W = z.shape
            v, u = np.nonzero(z > 0)
            if not len(v):
                continue
            i = rng.choice(len(v), min(a.samples // 6, len(v)), replace=False)
            v, u, zz = v[i], u[i], z[v[i], u[i]]
            Xc = np.stack([(u + 0.5 - W / 2) / (W / 2) * zz, (v + 0.5 - H / 2) / (H / 2) * zz, zz], 1)
            R, t = poses[name]
            P.append((Xc - t) @ R); own.append(np.linalg.norm(Xc, axis=1))
        if not P:
            continue
        P = np.concatenate(P)
        rng_d = np.concatenate(own)

        def inliers(s, Rot, t, tau):
            Q = C + t + s * (P - C) @ Rot.T
            d, nn = nearest(Q)
            return d < tau * s * rng_d, Q, nn

        base = inliers(1.0, np.eye(3), np.zeros(3), a.inlier)[0].mean()
        best = None
        for s0 in starts:
            s, Rot, t = s0, np.eye(3), np.zeros(3)
            for it in range(a.iters):
                tau = max(a.inlier, 0.2 * (1 - it / (0.6 * a.iters)))
                m, Q, nn = inliers(s, Rot, t, tau)
                if m.sum() < 30:
                    break
                ds, dR, dt = umeyama(Q[m], nn[m], C + t)
                # compose: X'' = (C+t) + dt + ds dR (X' - (C+t))
                Rot = dR @ Rot; t = t + dt; s = s * ds
            fin = inliers(s, Rot, t, a.inlier)[0].mean()
            if best is None or fin > best[0]:
                best = (fin, s, Rot, t, s0)
        fin, s, Rot, t, s0 = best
        # Then the trusted faces' own test, searched from the ICP result and
        # from plain scales: ICP needs the reference to cover what the node
        # sees, and it often covers little.
        if abs(np.log(s)) > np.log(2) or np.degrees(np.arccos(np.clip((np.trace(Rot) - 1) / 2, -1, 1))) > 10:
            s, Rot, t = 1.0, np.eye(3), np.zeros(3)
        cands = [(s, Rot, t)] + [(sc, np.eye(3), np.zeros(3)) for sc in (1.0,) + tuple(starts) if abs(np.log(sc)) <= np.log(2)]
        vbest = None
        Pt = torch.tensor(P - C, dtype=torch.float32, device=dev)
        for s1, R1, t1 in cands:
            x0 = np.concatenate([t1, [np.log(s1)], rotvec(R1)])
            x, f = search(lambda x: vis_score(Pt, C, x), x0, rng)
            if vbest is None or f > vbest[1]:
                vbest = (x, f)
        x = vbest[0]
        t, s, Rot = x[:3], float(np.exp(x[3])), rotmat(x[4:])
        fin = inliers(s, Rot, t, a.inlier)[0].mean()
        ang = float(np.degrees(np.arccos(np.clip((np.trace(Rot) - 1) / 2, -1, 1))))
        before, nb = seen_past(P)
        after, na = seen_past(C + t + s * (P - C) @ Rot.T)
        # More agreeing views alone is not enough: shrinking a run towards its
        # centre makes more of its points land in front of what others saw.
        # The control run MACA14,15,38, already in place, did exactly that
        # (agreeing x4, scale at the 0.5 bound, inliers 6% -> 2%). So the
        # inliers must rise too and the scale must stay off its bound.
        keepit = na > nb and after < before and fin > base and abs(np.log(s)) < 0.95 * np.log(2)
        out[n] = {'members': members,
                  'new_centres': {m: (C + t + s * Rot @ (centre[m] - C)).tolist() for m in members},
                  'centre': C.tolist(), 'new_centre': (C + t).tolist(), 'shift': float(np.linalg.norm(t)),
                  'turn_deg': ang, 'scale': float(s), 'rot': Rot.tolist(), 'start': s0,
                  'inliers_before': float(base), 'inliers_after': float(fin),
                  'seen_past_before': before, 'seen_past_after': after, 'agreeing': [nb, na], 'kept': bool(keepit),
                  'trusted': all(m in trusted for m in members)}
        print(f'{n} ({len(members)} nodes): agreeing {nb} -> {na}, inliers {base * 100:4.1f}% -> {fin * 100:4.1f}%  seen past {before * 100:4.1f}% -> {after * 100:4.1f}%  '
              f'shift {np.linalg.norm(t):.2f} turn {ang:.1f} deg scale {s:.3f} (start {s0})  {"MOVE" if keepit else "keep"}', flush=True)
    with open(a.out, 'w') as fh:
        json.dump(out, fh, indent=1)


if __name__ == '__main__':
    main()
