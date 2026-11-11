#!/usr/bin/env python3
r"""
How far each vertex of scene_mesh.py's mesh lies from a Gaussian splat of the same place, for cutting the
mesh's surfaces that no splat backs up.

    python splat_mesh_check.py MESH_SPARSE_TXT MESH_DIR SPLAT.ply SPLAT_SPARSE_TXT [--min-opacity 0.3]

The splat was trained in its own dataset's frame (splat_local.py's, from a moved model); the two frames are
matched by the node centres both models have (face 1 of each node: f1/MA-<n>.jpg in the mesh's model,
f1_MA-<n>.jpg in the splat's), a similarity fitted by least squares (Umeyama), with each node's residual
printed, then refined by ICP of the splats' centres onto the mesh's vertices (--icp node spacings as the
farthest pairing; 0 for none), since the splat's model moved some nodes. Splats under --min-opacity, or larger than half a node spacing, are left out. Prints quantiles of
the distance from the mesh's vertices to the nearest splat centre (in node spacings) and writes
MESH_DIR\splat_dist.npy (per vertex) and MESH_DIR\splat_plan.png (from above: splats grey, vertices
coloured by distance, green near, red far). Needs numpy, scipy, Pillow, open3d.
"""
import argparse
import json
import os
import re
import sys

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'colmap'))
from esrgan_dense_test import centre, read_model

F = np.diag([1.0, -1.0, -1.0])


def read_splat(path):
    with open(path, 'rb') as f:
        head = b''
        while not head.endswith(b'end_header\n'):
            head += f.readline()
        n = int(re.search(rb'element vertex (\d+)', head).group(1))
        props = re.findall(rb'property float (\w+)', head)
        data = np.fromfile(f, dtype='<f4', count=n * len(props)).reshape(n, len(props))
    return {p.decode(): data[:, i] for i, p in enumerate(props)}


def node_centres(sparse, pat):
    _, imgs = read_model(sparse)
    out = {}
    for h, _ in imgs.values():
        m = re.fullmatch(pat, h[9])
        if m:
            out[m.group(1)] = centre(h)
    return out


def umeyama(src, dst):
    ms, md = src.mean(0), dst.mean(0); a, b = src - ms, dst - md
    U, S, Vt = np.linalg.svd(b.T @ a / len(src))
    d = np.sign(np.linalg.det(U @ Vt)); D = np.diag([1, 1, d])
    R = U @ D @ Vt; s = np.trace(np.diag(S) @ D) / (a ** 2).sum(1).mean()
    return s, R, md - s * R @ ms


def splat_in_mesh_frame(mesh_sparse, mesh_dir, splat_ply, splat_sparse, min_opacity):
    """The splat's centres in the mesh's viewer frame (scene.ply's), and the fit's report."""
    nodes = list(json.load(open(os.path.join(mesh_dir, 'nodes.json'))))
    unit = json.load(open(os.path.join(mesh_dir, 'scales.json')))['unit']
    A = node_centres(mesh_sparse, r'f1/MA-(\d+)\.jpg')
    B = node_centres(splat_sparse, r'f1_MA-(\d+)\.jpg')
    both = [n for n in A if n in B]
    s, R, t = umeyama(np.array([B[n][0] for n in both]), np.array([A[n][0] for n in both]))
    res = {n: float(np.linalg.norm(s * R @ B[n][0] + t - A[n][0]) / unit) for n in both}
    sp = read_splat(splat_ply)
    X = np.stack([sp['x'], sp['y'], sp['z']], 1).astype(np.float64)
    op = 1 / (1 + np.exp(-sp['opacity']))
    size = np.exp(np.stack([sp['scale_0'], sp['scale_1'], sp['scale_2']], 1)).max(1) * s
    keep = (op >= min_opacity) & (size < 0.5 * unit)
    Xm = (X[keep] * s) @ R.T + t                              # the mesh's model frame
    n0 = nodes[0]; C0, R0 = A[n0][0], A[n0][1]
    V = (Xm - C0) @ (F @ R0).T / unit                         # its viewer frame
    return V, {'nodes_matched': len(both), 'scale': float(s), 'residual_spacings': res,
               'splats': int(len(X)), 'kept': int(keep.sum()), 'mesh_nodes_in_splat': [n for n in nodes if n in B]}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('mesh_sparse'); ap.add_argument('mesh'); ap.add_argument('splat'); ap.add_argument('splat_sparse')
    ap.add_argument('--min-opacity', type=float, default=0.3); ap.add_argument('--icp', type=float, default=0.3)
    a = ap.parse_args()
    import open3d as o3d
    from scipy.spatial import cKDTree
    S, rep = splat_in_mesh_frame(a.mesh_sparse, a.mesh, a.splat, a.splat_sparse, a.min_opacity)
    r = rep['residual_spacings']
    print(f"{rep['nodes_matched']} nodes matched, scale {rep['scale']:.4f}; residual median {np.median(list(r.values())):.3f}, "
          f"worst {max(r.values()):.3f} spacings ({max(r, key=r.get)}); {rep['kept']} of {rep['splats']} splats kept", flush=True)
    print('mesh nodes the splat has:', ' '.join(rep['mesh_nodes_in_splat']), flush=True)
    V = np.asarray(o3d.io.read_triangle_mesh(os.path.join(a.mesh, 'scene.ply')).vertices)
    if a.icp > 0:
        src = o3d.geometry.PointCloud(o3d.utility.Vector3dVector(S)); dst = o3d.geometry.PointCloud(o3d.utility.Vector3dVector(V))
        for dmax in (a.icp, a.icp / 2, a.icp / 4):
            r = o3d.pipelines.registration.registration_icp(src, dst, dmax, np.eye(4),
                o3d.pipelines.registration.TransformationEstimationPointToPoint(True),
                o3d.pipelines.registration.ICPConvergenceCriteria(max_iteration=60))
            src.transform(r.transformation)
            print(f'ICP within {dmax:.3f}: fitness {r.fitness:.3f}, rms {r.inlier_rmse:.4f}', flush=True)
        S = np.asarray(src.points)
        np.save(os.path.join(a.mesh, 'splat_centres.npy'), S.astype(np.float32))
    d, _ = cKDTree(S).query(V, workers=-1)
    np.save(os.path.join(a.mesh, 'splat_dist.npy'), d.astype(np.float32))
    q = np.quantile(d, [.1, .25, .5, .75, .9, .95, .99])
    print('vertex to nearest splat, spacings: ' + ' '.join(f'{p}%:{v:.3f}' for p, v in zip((10, 25, 50, 75, 90, 95, 99), q)), flush=True)
    for rr in (0.02, 0.05, 0.1, 0.2, 0.4):
        print(f'  beyond {rr}: {np.mean(d > rr) * 100:.1f}% of vertices', flush=True)
    # plan from above (viewer frame: y up; x across, z down the picture)
    lo = np.quantile(V[:, [0, 2]], 0.005, axis=0) - 1; hi = np.quantile(V[:, [0, 2]], 0.995, axis=0) + 1
    Wp = 1400; k = Wp / (hi[0] - lo[0]); Hp = int((hi[1] - lo[1]) * k)
    img = np.zeros((Hp, Wp, 3), np.uint8)
    def px(P):
        x = ((P[:, 0] - lo[0]) * k).astype(int); y = ((P[:, 2] - lo[1]) * k).astype(int)
        ok = (x >= 0) & (x < Wp) & (y >= 0) & (y < Hp); return x[ok], y[ok], ok
    x, y, _ = px(S); img[y, x] = (90, 90, 90)
    x, y, ok = px(V); t = np.clip(d[ok] / 0.3, 0, 1)
    img[y, x] = np.stack([255 * t, 255 * (1 - t), 40 + 0 * t], 1).astype(np.uint8)
    Image.fromarray(img).save(os.path.join(a.mesh, 'splat_plan.png'))


if __name__ == '__main__':
    main()
