#!/usr/bin/env python3
"""
Place nodes again from the trusted model's points, with their turns held.

    python node_resect.py DATABASE TRUSTED_MODEL JOINED_TXT OUT.json [--nodes MA-2001 ...]
        [--max-angle 1.0] [--trials 2000]

DATABASE is the COLMAP database the models were made from (its keypoints and
verified matches), TRUSTED_MODEL a binary sparse model believed right (COLMAP's
own 62-node Amateria model, run1/sparse/0), JOINED_TXT the joined model as text,
whose turns are held (each node's heading checked on its hotspots) and whose
positions are in question.

The trusted model is brought into the joined model's frame by the similarity
that fits its node centres to the same nodes' there. For each other node (or
--nodes), every verified match between one of its faces and a trusted face
whose feature is a trusted 3D point X gives a line the node's centre C lies on:
X back along the feature's ray, whose direction is known because the turn is.
C is found by RANSAC over pairs of lines (a line agrees when the ray from C to
X is within --max-angle degrees of the feature's), then refined over the
agreeing lines, each weighted by 1/|X - C|^2 so that the error is an angle.
Only trusted points within --max-depth of the trusted camera that saw them
are used: scenery far off looks the same from everywhere near, so its lines
all pass through the trusted camera, and with them the first run put whole
runs of nodes exactly on MASS 35's centre. For the same reason a pair of lines
from one trusted node is not tried, and a centre needs agreeing lines from
--min-sources trusted nodes. The spread of C along its least-certain direction is reported: distant points
fix the bearing to them, not the distance, so a node that sees only far
scenery is placed weakly in one direction.

With --dense, a matched trusted feature with no sparse point takes its 3D
position from the trusted face's geometric depth map in that workspace (on the
joined model, whose trusted nodes are where the trusted model has them), so
that matches to everything the trusted nodes saw count, not only to the
trusted model's sparse points.

With --dense, the node's own depth at each agreeing feature is compared with
the distance from its new centre to the trusted point: the median ratio is the
factor its depth maps need (a run placed at the wrong size was given depths at
that size), so that they can be fused at the new place without stereo again.

Writes OUT.json: per node the old centre, the new one, the shift, the number of
lines and of agreeing ones, the spread and the depth scale. Needs numpy; evaluate_model.py
beside it.
"""
import argparse
import json
import os
import re
import sqlite3
import struct

import numpy as np

from evaluate_model import qvec2rot

NODE = re.compile(r'f(\d)/(.*)\.jpg')
PAIR = 2147483647


def read_images_bin(path):
    """name -> (R, t, xy (N,2), point3D ids (N,))"""
    out = {}
    with open(path, 'rb') as f:
        (n,) = struct.unpack('<Q', f.read(8))
        for _ in range(n):
            struct.unpack('<I', f.read(4))
            qt = struct.unpack('<7d', f.read(56)); f.read(4)
            name = b''
            while (c := f.read(1)) != b'\0':
                name += c
            (k,) = struct.unpack('<Q', f.read(8))
            raw = np.frombuffer(f.read(24 * k), dtype=np.dtype([('x', '<f8'), ('y', '<f8'), ('id', '<i8')]))
            out[name.decode()] = (qvec2rot(np.array(qt[:4])), np.array(qt[4:]),
                                  np.stack([raw['x'], raw['y']], 1), raw['id'])
    return out


def read_points_bin(path):
    pts = {}
    with open(path, 'rb') as f:
        (n,) = struct.unpack('<Q', f.read(8))
        for _ in range(n):
            pid, x, y, z = struct.unpack('<Q3d', f.read(32))
            f.read(3 + 8)
            (k,) = struct.unpack('<Q', f.read(8)); f.read(8 * k)
            pts[pid] = (x, y, z)
    return pts


def read_poses_txt(txt):
    poses = {}
    head = True
    for line in open(os.path.join(txt, 'images.txt')):
        if line.startswith('#'):
            continue
        if head:
            p = line.split()
            poses[p[9]] = (qvec2rot(np.array(p[1:5], float)), np.array(p[5:8], float))
        head = not head
    return poses


def similarity(X, Y):
    """s, R, b with Y ~ s R X + b."""
    mx, my = X.mean(0), Y.mean(0)
    U, S, Vt = np.linalg.svd((Y - my).T @ (X - mx))
    D = np.eye(3); D[2, 2] = np.sign(np.linalg.det(U @ Vt))
    R = U @ D @ Vt
    s = (S * np.diag(D)).sum() / ((X - mx) ** 2).sum()
    return s, R, my - s * R @ mx


def closest_point(X, d, w=None):
    """The point nearest a set of lines X + l d (rows), weighted."""
    w = np.ones(len(X)) if w is None else w
    A = np.zeros((3, 3)); b = np.zeros(3)
    for Xi, di, wi in zip(X, d, w):
        P = np.eye(3) - np.outer(di, di)
        A += wi * P; b += wi * P @ Xi
    return np.linalg.lstsq(A, b, rcond=None)[0], A


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('database'); ap.add_argument('trusted_model'); ap.add_argument('joined_txt'); ap.add_argument('out')
    ap.add_argument('--nodes', nargs='*')
    ap.add_argument('--max-angle', type=float, default=1.0)
    ap.add_argument('--trials', type=int, default=2000)
    ap.add_argument('--max-depth', type=float, default=10.0,
                    help='only trusted points this near the trusted camera that saw them (joined units)')
    ap.add_argument('--min-sources', type=int, default=2)
    ap.add_argument('--dense', help='a dense workspace on the joined model: matched trusted features with no '
                    'sparse point take their 3D position from the trusted face\'s geometric depth map')
    a = ap.parse_args()
    dcache = {}

    def dense_xyz(name, xy, w, h):
        """World points (joined frame) of features xy of trusted face `name`, from its depth map; NaN where none."""
        if not a.dense:
            return np.full((len(xy), 3), np.nan)
        if name not in dcache:
            from depth_fill import read_colmap_array
            pth = os.path.join(a.dense, 'stereo', 'depth_maps', name + '.geometric.bin')
            dcache[name] = read_colmap_array(pth) if os.path.exists(pth) else None
        z = dcache[name]
        if z is None:
            return np.full((len(xy), 3), np.nan)
        H, Wd = z.shape
        u = np.clip((xy[:, 0] * Wd / w).astype(int), 0, Wd - 1); v = np.clip((xy[:, 1] * H / h).astype(int), 0, H - 1)
        zz = z[v, u].astype(np.float64)
        Xc = np.stack([(xy[:, 0] - w / 2) / (w / 2) * zz, (xy[:, 1] - h / 2) / (h / 2) * zz, zz], 1)
        R, t = jp[name]
        X = (Xc - t) @ R
        X[zz <= 0] = np.nan
        return X

    tr = read_images_bin(os.path.join(a.trusted_model, 'images.bin'))
    P3 = read_points_bin(os.path.join(a.trusted_model, 'points3D.bin'))
    jp = read_poses_txt(a.joined_txt)
    centre = lambda R, t: -R.T @ t
    common = [n for n in tr if n.startswith('f1/') and n in jp]
    s, Rs, b = similarity(np.array([centre(*tr[n][:2]) for n in common]), np.array([centre(*jp[n]) for n in common]))
    print(f'trusted model: {len(tr)} faces, {len(P3)} points; to the joined frame at scale {s:.4f} over {len(common)} nodes')
    to_j = lambda X: s * X @ Rs.T + b

    db = sqlite3.connect(a.database)
    ids = {name: iid for iid, name in db.execute('select image_id, name from images')}
    names = {v: k for k, v in ids.items()}
    W = {}
    for iid, cam in db.execute('select image_id, camera_id from images'):
        W[iid] = db.execute('select width, height from cameras where camera_id=?', (cam,)).fetchone()

    def keypoints(iid):
        rows, cols, data = db.execute('select rows, cols, data from keypoints where image_id=?', (iid,)).fetchone()
        return np.frombuffer(data, np.float32).reshape(rows, cols)[:, :2]

    trusted_ids = {ids[n] for n in tr if n in ids}
    tnodes = {NODE.fullmatch(n).group(2) for n in tr if NODE.fullmatch(n)}
    faces = {}
    for n in jp:
        m = NODE.fullmatch(n)
        if m:
            faces.setdefault(m.group(2), []).append(n)
    todo = a.nodes or sorted(n for n in faces if n not in tnodes)
    rng = np.random.default_rng(0)
    out = {}
    for node in todo:
        Xs, ds, rs, srcs = [], [], [], []
        for fname in faces[node]:
            if fname not in ids:
                continue
            i = ids[fname]
            kp = keypoints(i)
            w, h = W[i]
            R = jp[fname][0]
            for j in trusted_ids:
                lo, hi = min(i, j), max(i, j)
                row = db.execute('select rows, data from two_view_geometries where pair_id=?', (lo * PAIR + hi,)).fetchone()
                if not row or not row[0]:
                    continue
                mm = np.frombuffer(row[1], np.uint32).reshape(-1, 2)
                fi, fj = (mm[:, 0], mm[:, 1]) if i == lo else (mm[:, 1], mm[:, 0])
                pid = tr[names[j]][3][fj]
                sp = (pid >= 0) & np.array([p in P3 for p in pid])
                X = np.full((len(pid), 3), np.nan)
                if sp.any():
                    X[sp] = to_j(np.array([P3[p] for p in pid[sp]]))
                if a.dense and (~sp).any():
                    wj, hj = W[j]
                    X[~sp] = dense_xyz(names[j], keypoints(j)[fj[~sp]], wj, hj)
                Tj = centre(*jp[names[j]])
                ok = ~np.isnan(X[:, 0])
                ok[ok] &= np.linalg.norm(X[ok] - Tj, axis=1) < a.max_depth
                if not ok.any():
                    continue
                X = X[ok]
                xy = kp[fi[ok]]
                dc = np.stack([(xy[:, 0] - w / 2) / (w / 2), (xy[:, 1] - h / 2) / (h / 2), np.ones(len(xy))], 1)
                dw = dc @ R                                  # R^T d, as rows
                Xs.append(X); ds.append(dw / np.linalg.norm(dw, axis=1, keepdims=True))
                # the node's own depth there, as a distance along the ray (NaN where none)
                own = dense_xyz(fname, xy, w, h)
                rs.append(np.linalg.norm(own - centre(*jp[fname]), axis=1))
                srcs.append(np.full(len(X), hash(NODE.fullmatch(names[j]).group(2)) & 0x7fffffff))
        old = centre(*jp[faces[node][0]]) if faces[node] else None
        if not Xs:
            print(f'{node}: no matches to trusted points'); continue
        X = np.concatenate(Xs); d = np.concatenate(ds); rown = np.concatenate(rs); src = np.concatenate(srcs)
        # one line per 3D point: keep the first
        _, u = np.unique(np.round(X, 6), axis=0, return_index=True)
        X, d, rown, src = X[u], d[u], rown[u], src[u]
        cos_t = np.cos(np.radians(a.max_angle))

        def agree(C):
            v = X - C
            return (np.einsum('ij,ij->i', v, d) / np.linalg.norm(v, axis=1)) > cos_t

        best = (agree(old), old)
        if len(X) >= 2:
            for _ in range(a.trials):
                k = rng.choice(len(X), 2, replace=False)
                if src[k[0]] == src[k[1]]:
                    continue                             # two lines from one trusted node meet at that node
                C, _ = closest_point(X[k], d[k])
                m = agree(C)
                if len(set(src[m])) >= a.min_sources and m.sum() > best[0].sum():
                    best = (m, C)
        m, C = best
        A = None
        for _ in range(5):
            if m.sum() < 3:
                break
            wgt = 1 / np.maximum(np.linalg.norm(X[m] - C, axis=1), 1e-3) ** 2
            C, A = closest_point(X[m], d[m], wgt)
            m = agree(C)
        spread = None
        if A is not None:
            ev, evec = np.linalg.eigh(A)
            # angle error of 0.1 degree per line: spread ~ 1/sqrt(eigenvalue) radians-scale
            spread = float(np.radians(0.1) / np.sqrt(max(ev[0], 1e-12)))
        base = int(agree(old).sum())
        # The node's depth maps were made with it in the wrong place: the ratio
        # of the trusted distance to its own, over agreeing lines, is the
        # factor they need (1 for a node only shifted).
        good = m & np.isfinite(rown) & (rown > 0)
        dscale = float(np.median(np.linalg.norm(X[good] - C, axis=1) / rown[good])) if good.sum() >= 5 else None
        dspread = float(np.percentile(np.abs(np.log(np.linalg.norm(X[good] - C, axis=1) / rown[good]) - np.log(dscale)), 50)) if dscale else None
        out[node] = {'old': old.tolist(), 'new': C.tolist(), 'shift': float(np.linalg.norm(C - old)),
                     'lines': int(len(X)), 'sources': len(set(src[m])), 'agree_new': int(m.sum()), 'agree_old': base, 'spread': spread,
                     'depth_scale': dscale, 'depth_scale_mad_log': dspread, 'depth_scale_lines': int(good.sum())}
        print(f'{node}: {len(X)} lines from {len(set(src))} trusted nodes ({len(set(src[m]))} agreeing), agreeing {base} at the old centre, {m.sum()} at the new; '
              f'shift {np.linalg.norm(C - old):.2f}; spread {spread if spread is None else round(spread, 3)}; '
              f'depth scale {dscale if dscale is None else round(dscale, 3)} over {good.sum()}', flush=True)
    with open(a.out, 'w') as fh:
        json.dump({'scale_to_joined': s, 'nodes': out}, fh, indent=1)


if __name__ == '__main__':
    main()
