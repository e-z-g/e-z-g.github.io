#!/usr/bin/env python3
"""
A site node's depth rendered from a mesh of the model: each pixel's ray cast
into the mesh, the first hit its distance.

    python mesh_depth.py MESH SPARSE_TXT OUT_DIR --node 4084 --names N1 ... N6
        --node-depth node_depth.json [--size 640] [--scale 1] [--dense DENSE]
        [--max-dist 0]

MESH is a triangle mesh in the model's frame (COLMAP's poisson_mesher or
delaunay_mesher output); SPARSE_TXT the text model with the node's faces
(images.txt, f<k>/MA-<node>.jpg); distances in it are --scale times the site
depth's. Each face is a 90-degree pinhole, --size px square. Writes
OUT_DIR/<name>_mesh-z.npy (depth along the face's axis in the site depth's
units, 0 where the ray hits nothing or beyond --max-dist), OUT_DIR/<name>
_mesh-depth.png in node_depth.py's encoding with --node-depth's r_far
(d = (r_far / r - 1) / 19, 0 where nothing), OUT_DIR/<name>_mesh-span.npy
(the angle, in radians, the hit triangle's longest edge spans from the node:
a big one is a surface the mesher made up between far-apart points), and a
report. With --dense (a
workspace with the node's geometric depth maps) each face is also compared
with COLMAP's stereo.

Why: the site's depth is Depth Anything's shape with one scale and offset per
face, and on MASS 84 it draws the rock wall as a slab per column and faces 3's
wall at half the distance the model has it. A mesh made from the dense cloud
is the cloud interpolated as a surface: rays stop at the nearest surface, so
nothing behind shows through, and it has no slabs the views do not.
Needs numpy, Pillow, open3d.
"""
import argparse
import json
import os
import sys

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from node_depth import qvec2rot  # noqa: E402
from depth_fill import read_colmap_array  # noqa: E402

RATIO = 20.0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('mesh'); ap.add_argument('sparse'); ap.add_argument('out')
    ap.add_argument('--node', required=True); ap.add_argument('--names', nargs=6, required=True)
    ap.add_argument('--node-depth', required=True)
    ap.add_argument('--size', type=int, default=640); ap.add_argument('--scale', type=float, default=1.0)
    ap.add_argument('--dense'); ap.add_argument('--max-dist', type=float, default=0.0)
    a = ap.parse_args()
    import open3d as o3d
    os.makedirs(a.out, exist_ok=True)
    r_far = json.load(open(a.node_depth))['r_far']
    mesh = o3d.io.read_triangle_mesh(a.mesh)
    print(f'{a.mesh}: {len(mesh.vertices)} vertices, {len(mesh.triangles)} triangles', flush=True)
    V = np.asarray(mesh.vertices); tri_np = np.asarray(mesh.triangles)
    scene = o3d.t.geometry.RaycastingScene()
    scene.add_triangles(o3d.t.geometry.TriangleMesh.from_legacy(mesh))
    want = {f'f{k}/MA-{a.node}.jpg': k for k in range(1, 7)}
    poses = {}
    with open(os.path.join(a.sparse, 'images.txt')) as fh:
        for line in fh:
            p = line.split()
            if len(p) >= 10 and p[9] in want:
                poses[want[p[9]]] = (qvec2rot(np.array(p[1:5], float)), np.array(p[5:8], float))
    N = a.size
    u = (np.arange(N) + .5) / N * 2 - 1
    xx, yy = np.meshgrid(u, u)
    norm = np.sqrt(1 + xx ** 2 + yy ** 2)
    report = {}
    for k, name in enumerate(a.names, 1):
        R, t = poses[k]
        C = -R.T @ t
        dirs_cam = np.stack([xx, yy, np.ones_like(xx)], -1)          # z = 1 on the face's axis
        dirs = dirs_cam.reshape(-1, 3) @ R                             # R^T d
        rays = np.concatenate([np.broadcast_to(C, dirs.shape), dirs], 1).astype(np.float32)
        res = scene.cast_rays(o3d.core.Tensor(rays))
        hit = res['t_hit'].numpy().reshape(N, N)                     # t along d, so z = t
        z = np.where(np.isfinite(hit), hit / a.scale, 0.0)
        # the angle the hit triangle's longest edge spans from here: a big
        # one is a surface the mesher made up between far-apart points
        prim = res['primitive_ids'].numpy().reshape(N, N)
        span = np.zeros((N, N), np.float32)
        m = np.isfinite(hit)
        if m.any():
            tri = tri_np[prim[m]]
            e = np.max(np.stack([np.linalg.norm(V[tri[:, i]] - V[tri[:, j]], axis=1)
                                 for i, j in ((0, 1), (1, 2), (2, 0))]), axis=0)
            span[m] = e / (hit[m] * norm[m])
        np.save(os.path.join(a.out, f'{name}_mesh-span.npy'), span)
        if a.max_dist > 0:
            z = np.where(z * norm > a.max_dist, 0.0, z)
        np.save(os.path.join(a.out, f'{name}_mesh-z.npy'), z.astype(np.float32))
        q = np.where(z > 0, r_far / np.maximum(z * norm, 1e-9), 0.0)
        d8 = (np.rint(np.clip((q - 1) / (RATIO - 1), 0, 1) * 255) * (q > 0)).astype(np.uint8)
        Image.fromarray(d8).save(os.path.join(a.out, f'{name}_mesh-depth.png'))
        rec = {'hit': float(np.mean(z > 0))}
        if a.dense:
            dm = os.path.join(a.dense, 'stereo', 'depth_maps', f'f{k}', f'MA-{a.node}.jpg.geometric.bin')
            if os.path.exists(dm):
                zs = read_colmap_array(dm).astype(float) / a.scale
                if zs.shape != z.shape:
                    zs = np.asarray(Image.fromarray(zs.astype(np.float32)).resize((N, N), Image.NEAREST))
                both = (zs > 0) & (z > 0)
                if both.sum() > 100:
                    rel = np.abs(z[both] - zs[both]) / zs[both]
                    rec.update(stereo_median=float(np.median(rel)), stereo_p90=float(np.percentile(rel, 90)),
                               stereo_n=int(both.sum()))
        report[name] = rec
        print(f'{name}: {rec["hit"] * 100:.1f}% of rays hit' + (f'; against the stereo median {rec["stereo_median"] * 100:.1f}%, '
              f'90% {rec["stereo_p90"] * 100:.1f}%' if 'stereo_median' in rec else ''), flush=True)
    with open(os.path.join(a.out, 'mesh_depth.json'), 'w') as fh:
        json.dump({'mesh': a.mesh, 'r_far': r_far, 'scale': a.scale, 'faces': report}, fh, indent=1)


if __name__ == '__main__':
    main()
