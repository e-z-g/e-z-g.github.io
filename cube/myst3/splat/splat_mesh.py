#!/usr/bin/env python3
r"""
A mesh from a Gaussian splat rather than from each node's MoGe depth: the splat was fitted to every picture
at once, so where the nodes' guesses disagree it holds one surface.

    python splat_mesh.py SPLAT.ply MESH_DIR OUT [--min-opacity 0.5] [--max-size 0.05] [--far 10]
        [--depth 11] [--triangles 1500000]

MESH_DIR is scene_mesh.py's OUT after splat_mesh_check.py (splat_to_viewer.npy, nodes.json, views.json,
scales.json). Splats under --min-opacity, larger than --max-size node spacings along their longest axis, or
farther than --far spacings from every node, are left out; each of the rest is a point with its flattest
axis as the normal, turned toward the nearest node. Poisson's surface through them (octree --depth) is
trimmed where it lies over 3 times the median gap between points from every point or is thinly supported,
small pieces dropped, reduced to --triangles, and written to OUT\scene.ply in the viewer frame, with
MESH_DIR's nodes.json, views.json and scales.json copied beside it for scene_attrs.py (--depth-from
MESH_DIR) and scene3d.html. Needs numpy, scipy, open3d.
"""
import argparse
import json
import os
import shutil

import numpy as np

from splat_mesh_check import read_splat


def quat_to_mat(q):
    w, x, y, z = (q / np.linalg.norm(q, axis=1, keepdims=True)).T
    return np.stack([np.stack([1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)], -1),
                     np.stack([2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)], -1),
                     np.stack([2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)], -1)], 1)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('splat'); ap.add_argument('mesh'); ap.add_argument('out')
    ap.add_argument('--min-opacity', type=float, default=0.5); ap.add_argument('--max-size', type=float, default=0.05)
    ap.add_argument('--far', type=float, default=10); ap.add_argument('--depth', type=int, default=11)
    ap.add_argument('--triangles', type=int, default=1500000)
    a = ap.parse_args()
    import open3d as o3d
    from scipy.spatial import cKDTree
    os.makedirs(a.out, exist_ok=True)
    M = np.load(os.path.join(a.mesh, 'splat_to_viewer.npy'))
    L = M[:3, :3]; k = np.cbrt(np.linalg.det(L)); Rot = L / k                  # similarity: scale k, rotation Rot
    sp = read_splat(a.splat)
    X = np.stack([sp['x'], sp['y'], sp['z']], 1).astype(np.float64) @ L.T + M[:3, 3]
    sc = np.exp(np.stack([sp['scale_0'], sp['scale_1'], sp['scale_2']], 1)) * k
    op = 1 / (1 + np.exp(-sp['opacity']))
    nodes = json.load(open(os.path.join(a.mesh, 'nodes.json'))); P = np.array(list(nodes.values()))
    dn, ni = cKDTree(P).query(X, workers=-1)
    keep = (op >= a.min_opacity) & (sc.max(1) < a.max_size) & (dn < a.far)
    print(f'{keep.sum()} of {len(X)} splats', flush=True)
    X, sc, ni = X[keep], sc[keep], ni[keep]
    Rq = quat_to_mat(np.stack([sp['rot_0'], sp['rot_1'], sp['rot_2'], sp['rot_3']], 1)[keep].astype(np.float64))
    Nrm = Rq[np.arange(len(X)), :, np.argmin(sc, 1)] @ Rot.T                    # the flattest axis, viewer frame
    flip = np.sum(Nrm * (P[ni] - X), 1) < 0; Nrm[flip] *= -1
    flatness = np.sort(sc, 1); flat = flatness[:, 0] < 0.5 * flatness[:, 1]
    print(f'{flat.mean() * 100:.0f}% of them flat (shortest axis under half the next)', flush=True)
    cloud = o3d.geometry.PointCloud(o3d.utility.Vector3dVector(X)); cloud.normals = o3d.utility.Vector3dVector(Nrm)
    gap = float(np.median(cKDTree(X).query(X, k=2, workers=-1)[0][:, 1]))
    print(f'median gap between points {gap:.4f} spacings', flush=True)
    mesh, dens = o3d.geometry.TriangleMesh.create_from_point_cloud_poisson(cloud, depth=a.depth, n_threads=-1)
    dens = np.asarray(dens); print(f'{len(mesh.triangles)} triangles', flush=True)
    d = np.asarray(o3d.geometry.PointCloud(mesh.vertices).compute_point_cloud_distance(cloud))
    mesh.remove_vertices_by_mask((d > max(3 * gap, 0.03)) | (dens < np.quantile(dens, 0.05)))
    tc, nc, _ = mesh.cluster_connected_triangles(); tc = np.asarray(tc); nc = np.asarray(nc)
    mesh.remove_triangles_by_mask(nc[tc] < 200); mesh.remove_unreferenced_vertices()
    print(f'{len(mesh.triangles)} triangles kept', flush=True)
    if len(mesh.triangles) > a.triangles:
        mesh = mesh.simplify_quadric_decimation(a.triangles)
    mesh.compute_vertex_normals()
    o3d.io.write_triangle_mesh(os.path.join(a.out, 'scene.ply'), mesh)
    for f in ('nodes.json', 'views.json', 'scales.json'):
        shutil.copy(os.path.join(a.mesh, f), os.path.join(a.out, f))
    print(f'{len(mesh.triangles)} triangles; {os.path.join(a.out, "scene.ply")}', flush=True)


if __name__ == '__main__':
    main()
