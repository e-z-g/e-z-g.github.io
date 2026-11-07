#!/usr/bin/env python3
"""
Every node's rotation and position in a Myst III room, solved from the links
between nodes, without assuming the nodes face the same way.

    python solve_nodes.py WORK [--features images_feat] [--out WORK/solve]

WORK is a folder laid out by prepare_colmap.py (images/f<face>/<ROOM>-<node>.jpg,
nodes.json). Writes OUT/relposes.json (one entry per linked pair) and
OUT/nodes_solved.json (each node's rotation and centre), and prints how the
result compares with the hotspot headings and the age map.

Why not COLMAP alone: its incremental mapper places only the well-lit nodes,
and its global mapper, which places nearly all, averages rotations from the
matches and lets a few bad cave links turn whole nodes by tens of degrees.
Here every linked pair is solved on its own, so a bad link stays one bad
measurement, and the averaging that follows down-weights it.

1. Relative pose per link. SIFT on the six faces of both nodes (on the
   brightened copies by default), matched across all 36 face pairs, turned into
   unit viewing directions through face_geometry.face_dir. The essential matrix
   comes from the eight-point algorithm on those directions in RANSAC (any
   direction works, so the six faces are one spherical camera), with the
   angular distance to the epipolar plane as the error; of its four
   decompositions, the one with the matched points in front of both nodes.
   No rotation is assumed: the rotation between the two nodes comes out of the
   pictures, and its angle is reported.
2. Rotations. Robust chordal averaging over the links (weights from the inlier
   counts, reweighted by each link's residual), node 1 fixed. Each node's
   rotation is then reported as a yaw, pitch and roll from node 1's: Myst III's
   cube nodes are thought level, but "forward" may differ from node to node.
3. Positions. Each link gives the direction from one node to the other, turned
   into the common frame with the solved rotations; the centres are the
   least-squares fit to those directions with every link's length at least 1
   (Zhuang et al.'s BATA form: alternate between solving centres for fixed
   lengths and lengths for fixed centres), reweighted against outlying links.
   Lengths come out in units of the shortest well-measured step; only ratios
   mean anything.

Needs numpy and opencv-python.
"""
import argparse
import json
import math
import os
import sys

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from face_geometry import FACES, face_dir  # noqa: E402

RNG = np.random.default_rng(0)


def features(folder, room, node, sift):
    dirs, descs = [], []
    for f in FACES:
        img = cv2.imread(os.path.join(folder, f'f{f}', f'{room}-{node:04d}.jpg'), cv2.IMREAD_GRAYSCALE)
        kps, d = sift.detectAndCompute(img, None)
        if d is None:
            continue
        n = img.shape[0]
        for k in kps:
            v = np.array(face_dir(f, k.pt[0] / n, k.pt[1] / n), float)
            dirs.append(v / np.linalg.norm(v))
        descs.append(d)
    return np.array(dirs), np.vstack(descs).astype(np.float32)


def match(d1, d2, ratio=0.8):
    m = cv2.BFMatcher(cv2.NORM_L2, crossCheck=False).knnMatch(d1, d2, k=2)
    return np.array([(a.queryIdx, a.trainIdx) for a, b in (p for p in m if len(p) == 2)
                     if a.distance < ratio * b.distance], int).reshape(-1, 2)


def eight_point(a, b):
    """E with b^T E a = 0 for unit directions a (node A) and b (node B)."""
    A = np.einsum('ni,nj->nij', b, a).reshape(len(a), 9)
    _, _, vt = np.linalg.svd(A)
    E = vt[-1].reshape(3, 3)
    U, S, Vt = np.linalg.svd(E)
    return U @ np.diag([1, 1, 0]) @ Vt


def epi_err(E, a, b):
    """Sine of the angle between each b and the epipolar plane of its a (and the converse), the larger."""
    Ea = a @ E.T
    Eb = b @ E
    num = np.abs(np.sum(b * Ea, axis=1))
    return np.maximum(num / np.maximum(np.linalg.norm(Ea, axis=1), 1e-12),
                      num / np.maximum(np.linalg.norm(Eb, axis=1), 1e-12))


def front_count(R, t, a, b, min_parallax_deg=1.0):
    """How many matches lie in front of both nodes for x_B = R x_A + t, counting only
    matches whose two viewing directions differ by more than min_parallax_deg once
    turned into one frame. Distant points (sea, sky, the horizon) have almost no
    parallax, so the sign of their depth is noise; counted, they pull a clear
    answer towards a coin toss."""
    Ra = a @ R.T
    keep = np.sum(Ra * b, axis=1) < math.cos(math.radians(min_parallax_deg))
    Ra, bb = Ra[keep], b[keep]
    M = np.stack([Ra, -bb], axis=2)
    MtM = np.einsum('nki,nkj->nij', M, M)
    Mtt = np.einsum('nki,k->ni', M, -t)
    det = MtM[:, 0, 0] * MtM[:, 1, 1] - MtM[:, 0, 1] * MtM[:, 1, 0]
    det = np.where(np.abs(det) > 1e-12, det, np.inf)
    la = (MtM[:, 1, 1] * Mtt[:, 0] - MtM[:, 0, 1] * Mtt[:, 1]) / det
    lb = (MtM[:, 0, 0] * Mtt[:, 1] - MtM[:, 1, 0] * Mtt[:, 0]) / det
    return int(np.sum((la > 0) & (lb > 0))), int(keep.sum())


def decompose(E, a, b):
    """(R, t, count in front) with x_B = R x_A + t, t unit, picking the cheirality winner."""
    U, _, Vt = np.linalg.svd(E)
    if np.linalg.det(U) < 0:
        U = -U
    if np.linalg.det(Vt) < 0:
        Vt = -Vt
    W = np.array([[0, -1, 0], [1, 0, 0], [0, 0, 1]])
    best = None
    for R in (U @ W @ Vt, U @ W.T @ Vt):
        for t in (U[:, 2], -U[:, 2]):
            n, m = front_count(R, t, a, b)
            if best is None or n > best[2]:
                best = (R, t, n, m)
    return best


def relative_pose(a, b, iters=3000, thr_deg=0.3):
    if len(a) < 12:
        return None
    thr = math.sin(math.radians(thr_deg))
    best_inl, best_n = None, 0
    for _ in range(iters):
        s = RNG.choice(len(a), 8, replace=False)
        E = eight_point(a[s], b[s])
        inl = epi_err(E, a, b) < thr
        n = int(inl.sum())
        if n > best_n:
            best_inl, best_n = inl, n
    if best_n < 12:
        return None
    for _ in range(3):                              # refit on the inliers, then re-select
        E = eight_point(a[best_inl], b[best_inl])
        inl = epi_err(E, a, b) < thr
        if inl.sum() < 12:
            break
        best_inl = inl
    R, t, front, used = decompose(E, a[best_inl], b[best_inl])
    return R, t, int(best_inl.sum()), front / max(1, used)


def roty(theta):
    c, s_ = math.cos(theta), math.sin(theta)
    return np.array([[c, 0, s_], [0, 1, 0], [-s_, 0, c]])


def relative_pose_upright(a, b, step_deg=0.5, pairs=300, thr_deg=0.3):
    """As relative_pose, but with both nodes level: R is a turn about the vertical alone.
    For each turn on a 0.5-degree grid, t must satisfy t . (R a x b) = 0 for every match;
    two matches give a candidate t, and the turn and t with the most matches within
    thr_deg of their epipolar plane win. Three unknowns instead of five, which is what
    lets links with a dozen good matches be measured at all."""
    if len(a) < 6:
        return None
    thr = math.sin(math.radians(thr_deg))
    i = RNG.integers(0, len(a), pairs); j = RNG.integers(0, len(a), pairs)
    best = (0, None, None, None)
    for th in np.radians(np.arange(0, 360, step_deg)):
        R = roty(th)
        n = np.cross(a @ R.T, b)
        nn = np.linalg.norm(n, axis=1)
        ok = nn > 1e-6
        n = n / np.where(ok, nn, 1)[:, None]
        T = np.cross(n[i], n[j])
        tn = np.linalg.norm(T, axis=1)
        T = T[tn > 1e-6] / tn[tn > 1e-6, None]
        if not len(T):
            continue
        counts = ((np.abs(n @ T.T) < thr) & ok[:, None]).sum(0)
        k = int(np.argmax(counts))
        if counts[k] > best[0]:
            best = (int(counts[k]), th, T[k], np.abs(n @ T[k]) < thr)
    nin, th, t, inl = best
    if nin < 6:
        return None
    # A level turn th with travel t fits the matches exactly as well as th + 180 with t
    # reflected (the essential matrix's twisted pair), so the count cannot choose between
    # them; the points-in-front test can. Try both and keep the one with more in front.
    out = None
    for th2 in (th, th + math.pi):
        R = roty(th2)
        n = np.cross(a[inl] @ R.T, b[inl])
        t2 = np.linalg.svd(n)[2][-1]                # refit t on the inliers
        for sg in (1, -1):
            front, used = front_count(R, sg * t2, a[inl], b[inl])
            if out is None or front > out[3]:
                out = (R, sg * t2, nin, front, used)
    R, t, nin, front, used = out
    return R, t, nin, front / max(1, used)


def rot_angle(R):
    return math.degrees(math.acos(max(-1.0, min(1.0, (np.trace(R) - 1) / 2))))


def project_so3(M):
    U, _, Vt = np.linalg.svd(M)
    R = U @ Vt
    if np.linalg.det(R) < 0:
        R = U @ np.diag([1, 1, -1]) @ Vt
    return R


def ypr(R):
    """Yaw (as a heading change: + turns right), pitch and roll of node frame R relative to the reference.
    R maps reference-frame directions into this node's frame; in the cube frame x right, y up, z back."""
    Rt = R.T                                         # this node's axes in the reference frame
    fwd = Rt @ np.array([0, 0, -1.0])                # this node's front, in reference coordinates
    up = Rt @ np.array([0, 1.0, 0])
    # heading of a direction d in the reference frame: atan2(-dx, dz); front itself is heading 180
    yaw = (math.degrees(math.atan2(-fwd[0], fwd[2])) - 180 + 180) % 360 - 180
    pitch = math.degrees(math.asin(max(-1, min(1, fwd[1]))))
    tilt = math.degrees(math.acos(max(-1, min(1, up[1]))))
    return yaw, pitch, tilt


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('work')
    ap.add_argument('--features', default='images_feat')
    ap.add_argument('--out')
    ap.add_argument('--min-inliers', type=int, default=20)
    ap.add_argument('--min-front', type=float, default=0.8,
                    help='drop links where fewer of the matched points lie in front of both nodes: '
                         'their direction, even its sign, is not settled')
    ap.add_argument('--compare', action='append', default=[],
                    help="a COLMAP model as text (sparse_txt/<n>) to compare the solved centres with; repeatable")
    ap.add_argument('--nodes', help='only these nodes, e.g. 1-27 or 1-20,25')
    ap.add_argument('--same-rotation', action='store_true',
                    help='hold every node to one rotation and solve only the direction of each step '
                         '(heading_check.solve_t); for parts where the turn has been measured to be zero')
    ap.add_argument('--upright', action='store_true',
                    help='nodes level: each node a yaw alone, each link a turn about the vertical')
    a = ap.parse_args()
    out = a.out or os.path.join(a.work, 'solve_same' if a.same_rotation else 'solve_upright' if a.upright else 'solve')
    os.makedirs(out, exist_ok=True)
    meta = json.load(open(os.path.join(a.work, 'nodes.json')))
    room, nodes = meta['room'], meta['nodes']
    if a.nodes:
        keep = set()
        for part in a.nodes.split(','):
            lo, _, hi = part.partition('-')
            keep |= set(range(int(lo), int(hi or lo) + 1))
        nodes = [n for n in nodes if n in keep]
        meta['links'] = [l for l in meta['links'] if l[0] in keep and l[1] in keep]
        meta['links_used'] = [l for l in meta['links_used'] if l['from'] in keep]
    folder = os.path.join(a.work, a.features)

    # 1. relative poses
    rel_path = os.path.join(out, 'relposes.json')
    if os.path.exists(rel_path):
        rel = {tuple(map(int, k.split('-'))): v for k, v in json.load(open(rel_path)).items()}
        print(f'relative poses read from {rel_path}')
    else:
        sift = cv2.SIFT_create(nfeatures=5000, contrastThreshold=0.01)
        feats = {}
        rel = {}
        for x, y in meta['links']:
            for n in (x, y):
                if n not in feats:
                    feats[n] = features(folder, room, n, sift)
            (da, fa), (db, fb) = feats[x], feats[y]
            m = match(fa, fb)
            if a.same_rotation:
                from heading_check import solve_t
                r = solve_t(da[m[:, 0]], db[m[:, 1]]) if len(m) >= 8 else None
                if r is not None:                    # solve_t gives B's centre seen from A, x_B = x_A + t
                    c, ninl, _, front = r
                    r = (np.eye(3), -c, ninl, front)
            else:
                fn = relative_pose_upright if a.upright else relative_pose
                r = fn(da[m[:, 0]], db[m[:, 1]]) if len(m) else None
            if r is None:
                rel[(x, y)] = {'matches': int(len(m)), 'inliers': 0}
                print(f'  {x:3d}-{y:3d}: {len(m):5d} matches, no pose')
                continue
            R, t, ninl, front = r
            rel[(x, y)] = {'matches': int(len(m)), 'inliers': ninl, 'front': round(front, 3),
                           'R': R.tolist(), 't': t.tolist()}
            print(f'  {x:3d}-{y:3d}: {len(m):5d} matches, {ninl:5d} inliers, in front {front:.2f}, '
                  f'rotation between them {rot_angle(R):5.1f} deg')
        json.dump({f'{x}-{y}': v for (x, y), v in rel.items()}, open(rel_path, 'w'), indent=0)

    wanted = {tuple(l) for l in meta['links']}
    good = {k: v for k, v in rel.items() if v['inliers'] >= a.min_inliers and k in wanted
            and v.get('front', 1) >= a.min_front}
    print(f'{len(good)} of {len(wanted)} links with at least {a.min_inliers} inliers and {a.min_front} in front; '
          f'dropped: {sorted(k for k in wanted if k not in good)}')

    # 2. rotations: R_n maps the common frame into node n's frame; link (x, y) says R_y = R_xy R_x
    Rs = {nodes[0]: np.eye(3)} if nodes[0] in nodes else {}
    order = sorted(good, key=lambda k: -good[k]['inliers'])
    changed = True
    while changed:                                   # spanning tree from the strongest links
        changed = False
        for x, y in order:
            Rxy = np.array(good[(x, y)]['R'])
            if x in Rs and y not in Rs:
                Rs[y] = Rxy @ Rs[x]; changed = True
            elif y in Rs and x not in Rs:
                Rs[x] = Rxy.T @ Rs[y]; changed = True
    w = {k: float(v['inliers']) for k, v in good.items()}
    for it in range(30):
        resid = {}
        for (x, y), v in good.items():
            if x in Rs and y in Rs:
                resid[(x, y)] = rot_angle(np.array(v['R']) @ Rs[x] @ Rs[y].T)
        for n in Rs:
            if n == nodes[0]:
                continue
            M = np.zeros((3, 3))
            for (x, y), v in good.items():
                if (x, y) not in resid:
                    continue
                k = w[(x, y)] / (1 + (resid[(x, y)] / 3.0) ** 2)    # Cauchy, 3 deg scale
                Rxy = np.array(v['R'])
                if y == n:
                    M += k * (Rxy @ Rs[x])
                elif x == n:
                    M += k * (Rxy.T @ Rs[y])
            if M.any():
                if a.upright:                        # keep it a turn about the vertical
                    Rs[n] = roty(math.atan2(M[0, 2] - M[2, 0], M[0, 0] + M[2, 2]))
                else:
                    Rs[n] = project_so3(M)
    resid = {k: rot_angle(np.array(v['R']) @ Rs[k[0]] @ Rs[k[1]].T) for k, v in good.items() if k[0] in Rs and k[1] in Rs}

    # 3. positions: c_y - c_x = s * u, u = R_x^T (direction from x to y in x's frame)
    #    with x_B = R x_A + t, B's centre in A's frame is -R^T t
    placed = sorted(Rs)
    idx = {n: i for i, n in enumerate(placed)}
    links = []
    for (x, y), v in good.items():
        if x not in Rs or y not in Rs:
            continue                                 # outside the part joined to the first node
        R, t = np.array(v['R']), np.array(v['t'])
        c = -R.T @ t
        links.append((x, y, Rs[x].T @ (c / np.linalg.norm(c)), w[(x, y)]))
    s = np.ones(len(links))
    lw = np.array([l[3] for l in links])
    C = np.zeros((len(placed), 3))
    for it in range(200):
        rows, rhs, ws = [], [], []
        A = np.zeros((3 * len(links) + 3, 3 * len(placed)))
        bvec = np.zeros(3 * len(links) + 3)
        for k, (x, y, u, _) in enumerate(links):
            for d in range(3):
                A[3 * k + d, 3 * idx[y] + d] = 1
                A[3 * k + d, 3 * idx[x] + d] = -1
                bvec[3 * k + d] = s[k] * u[d]
        for d in range(3):                           # gauge: the first node at the origin
            A[3 * len(links) + d, d] = 1
        W = np.repeat(np.append(lw, 1e3), 3)
        sol = np.linalg.lstsq(A * np.sqrt(W)[:, None], bvec * np.sqrt(W), rcond=None)[0]
        C = sol.reshape(-1, 3)
        res = []
        for k, (x, y, u, w0) in enumerate(links):
            dvec = C[idx[y]] - C[idx[x]]
            s[k] = max(1.0, float(dvec @ u))
            res.append(np.linalg.norm(dvec - s[k] * u) / s[k])
        res = np.array(res)
        lw = np.array([l[3] for l in links]) / (1 + (res / 0.1) ** 2)
    ang_res = {}
    for k, (x, y, u, _) in enumerate(links):
        dvec = C[idx[y]] - C[idx[x]]
        ang_res[(x, y)] = math.degrees(math.acos(max(-1, min(1, dvec @ u / np.linalg.norm(dvec)))))

    # report
    print('\nnode rotations relative to node %d (yaw: + turns right; tilt: of the up axis):' % nodes[0])
    turned = []
    for n in placed:
        yv, pv, tv = ypr(Rs[n])
        if abs(yv) > 5 or tv > 3:
            turned.append(n)
        print(f'  {n:3d}: yaw {yv:+7.2f}  pitch {pv:+6.2f}  tilt {tv:5.2f}')
    print(f'nodes turned by more than 5 deg or tilted more than 3: {turned or "none"}')
    print(f'not placed: {[n for n in nodes if n not in Rs] or "none"}')
    r = sorted(resid.values())
    print(f'rotation residuals over {len(r)} links: median {r[len(r) // 2]:.2f} deg, max {r[-1]:.2f} '
          f'({max(resid, key=resid.get)})')
    big = sorted(((v, k) for k, v in ang_res.items() if v > 5), reverse=True)
    if big:
        print('links whose measured direction the solve does not follow (over 5 deg): ' +
              ', '.join(f'{x}-{y} {v:.0f}' for v, (x, y) in big))
    r = sorted(ang_res.values())
    print(f'direction residuals: median {r[len(r) // 2]:.2f} deg, max {r[-1]:.2f} ({max(ang_res, key=ang_res.get)})')

    # hotspot check, in each node's own frame
    errs = []
    for l in meta['links_used']:
        x = l['from']; y = l['to'] - 100 if 100 <= l['to'] < 1000 else l['to']
        if x in idx and y in idx and x != y:
            dvec = Rs[x] @ (C[idx[y]] - C[idx[x]])
            h = math.degrees(math.atan2(-dvec[0], dvec[2])) % 360
            errs.append(abs((h - l['heading'] + 180) % 360 - 180))
    e = sorted(errs)
    print(f'hotspot headings vs solved directions, in each node\'s own frame: {len(e)} hotspots, '
          f'median {e[len(e) // 2]:.1f} deg, 90% within {e[int(len(e) * 0.9)]:.1f}, worst {e[-1]:.1f}')

    # age map, horizontal, in node 1's frame (map step for heading h is (sin h, cos h))
    pos = meta['age_map_positions_steps']
    common = [n for n in placed if pos.get(str(n))]
    P = np.array([[-C[idx[n]][0], C[idx[n]][2]] for n in common])
    Q = np.array([pos[str(n)] for n in common])
    P0, Q0 = P - P.mean(0), Q - Q.mean(0)
    U, S, Vt = np.linalg.svd(P0.T @ Q0)
    D = np.diag([1, np.sign(np.linalg.det(U @ Vt))])
    R2 = (U @ D @ Vt).T
    sc = (S * np.diag(D)).sum() / (P0 ** 2).sum()
    res = np.linalg.norm((sc * (R2 @ P0.T)).T + Q.mean(0) - Q, axis=1)
    rr = sorted(res)
    print(f'age map: {len(common)} nodes, turn {math.degrees(math.atan2(R2[1, 0], R2[0, 0])):+.1f} deg, '
          f'residual median {rr[len(rr) // 2]:.2f} steps, max {rr[-1]:.2f} (node {common[int(np.argmax(res))]})')

    # COLMAP models: the solved centres against the model's, after the best similarity
    from evaluate_model import read_frames
    step = float(np.median([np.linalg.norm(C[idx[y]] - C[idx[x]]) for x, y, _, _ in links]))
    for path in a.compare:
        fr = read_frames(path)
        com = [n for n in placed if n in fr]
        if len(com) < 3:
            print(f'{path}: only {len(com)} nodes in common')
            continue
        X = np.array([fr[n][1] for n in com]); Y = np.array([C[idx[n]] for n in com])
        Xm, Ym = X.mean(0), Y.mean(0)
        U, S, Vt = np.linalg.svd((X - Xm).T @ (Y - Ym))
        D = np.diag([1, 1, np.sign(np.linalg.det(U @ Vt))])
        Rsim = (U @ D @ Vt).T
        sc = (S * np.diag(D)).sum() / ((X - Xm) ** 2).sum()
        diff = ((sc * (Rsim @ (X - Xm).T)).T + Ym - Y) / step
        res = np.linalg.norm(diff, axis=1)
        rr = sorted(res)
        hz = sorted(np.linalg.norm(diff[:, [0, 2]], axis=1)); vt = sorted(np.abs(diff[:, 1]))
        print(f'   horizontal: median {hz[len(hz) // 2]:.3f}, max {hz[-1]:.3f}; vertical: median '
              f'{vt[len(vt) // 2]:.3f}, max {vt[-1]:.3f}')
        print(f'against {path}: {len(com)} nodes, centres differ by median {rr[len(rr) // 2]:.3f} '
              f'and at most {rr[-1]:.3f} median steps (node {com[int(np.argmax(res))]})')

    json.dump({'room': room, 'reference_node': nodes[0],
               'note': 'node_from_ref maps directions in the reference node frame into this node\'s cube frame; '
                       'centre is in the reference frame, units of the shortest well-measured link',
               'nodes': {str(n): {'node_from_ref': Rs[n].tolist(), 'centre': C[idx[n]].tolist(),
                                  'yaw_pitch_tilt_deg': list(ypr(Rs[n]))} for n in placed},
               'not_placed': [n for n in nodes if n not in Rs],
               'link_rotation_residual_deg': {f'{x}-{y}': v for (x, y), v in resid.items()},
               'link_direction_residual_deg': {f'{x}-{y}': v for (x, y), v in ang_res.items()}},
              open(os.path.join(out, 'nodes_solved.json'), 'w'), indent=1)


if __name__ == '__main__':
    main()
