#!/usr/bin/env python3
r"""
One coloured mesh of a stretch of an age, fused from its nodes: each node's panorama given distances by MoGe,
placed by the joined model's cameras and scaled by its points, the six faces of every node joined into one
surface (Poisson reconstruction, Open3D) and coloured from the game's own pictures.

    python scene_mesh.py ROOT SPARSE_TXT OUT --nodes 4084 4089 [--near 20] [--stage moge,fuse]
        [--size 2048] [--voxel 0.02] [--far 12] [--triangles 1500000]

ROOT holds images\f<k>\MA-<node>.jpg (k as node_depth.py's faces: front, bottom, back, right, left, top);
SPARSE_TXT the joined model as text. The nodes are those given and the --near nearest to their middle.

  moge  For each node, its six faces drawn as one equirectangular panorama (--size wide) and MoGe-3's
        panorama inference run on it in ComfyUI (as moge_depth.py), the distances saved as
        OUT\moge\<node>_moge_depth.npy and the sky mask beside them. Needs a running ComfyUI.
  fuse  Each node's distances scaled to the model: the model's points that the node's faces saw, their
        distance from the node's centre against MoGe's in the same direction, median of the ratio
        (written to OUT\scales.json with how well they agree). Each face then becomes a depth image along
        its own axis (640 px, the picture's own pixels for colour) with the camera the model gives the
        node: face 1's rotation, the others turned from it as the cube's faces are. Sky and anything past
        --far times the median spacing between neighbouring nodes is left out. Every face of every node is
        turned into points, thinned to one a --voxel times that spacing, and one surface laid through all
        of them (Poisson, octree --depth) with the colours carried into its vertices; the surface is
        trimmed where it lies over 3 voxels from every point (where it closes over the sky or what no
        node saw), reduced to --triangles, and written as OUT\scene.ply
        and OUT\scene.glb (y up, the first node at the origin, one unit the median node spacing) with
        OUT\nodes.json (each node's centre in the same frame, for the viewer's start).

MoGe's shapes are each node's own guess; where nodes disagree the surface runs between them, so what many nodes
see is firmer than what one sees. Needs numpy, Pillow, opencv-python, open3d.
"""
import argparse
import json
import os
import time
import uuid

import cv2
import numpy as np
from PIL import Image

from moge_depth import api, dirs_to_equirect_px, equirect_dirs, face_axes, DIRS
from esrgan_dense_test import centre, read_model

F = np.diag([1.0, -1.0, -1.0])        # node frame (x right, y up, -z face 1) to face 1's camera (x right, y down, z ahead)


def pano(faces, W, H):
    d = equirect_dirs(W, H); N = faces[0].shape[0]
    out = np.zeros((H, W, 3), np.uint8); best = np.full((H, W), -np.inf)
    for k in range(1, 7):
        c, ds, dt = face_axes(k)
        z = d @ c; take = z > best
        with np.errstate(all='ignore'):
            p = d / z[..., None]
        s = 0.5 + (p - c) @ ds / (ds @ ds) / 2; t = 0.5 + (p - c) @ dt / (dt @ dt) / 2
        img = cv2.remap(faces[k - 1], (s * N - .5).astype(np.float32), (t * N - .5).astype(np.float32), cv2.INTER_CUBIC,
                        borderMode=cv2.BORDER_REPLICATE)
        out[take] = img[take]; best[take] = z[take]
    return out


def run_moge(server, comfy_input, pano_img, prefix, W):
    name = f'scene_{os.path.basename(prefix)}.png'
    Image.fromarray(pano_img).save(os.path.join(comfy_input, name))
    g = {'1': {'class_type': 'LoadImage', 'inputs': {'image': name}},
         '2': {'class_type': 'LoadMoGeModel', 'inputs': {'model_name': 'moge_3_vitg_fp16.safetensors'}},
         '3': {'class_type': 'MoGePanoramaInference', 'inputs': {'moge_model': ['2', 0], 'image': ['1', 0], 'resolution_level': 9,
                                                                 'split_resolution': 512, 'merge_resolution': W, 'batch_size': 4,
                                                                 'refine_steps': 3}},
         '4': {'class_type': 'SaveMoGeGeometry', 'inputs': {'moge_geometry': ['3', 0], 'path_prefix': prefix}}}
    r = api(server, '/prompt', {'prompt': g, 'client_id': uuid.uuid4().hex})
    if r.get('node_errors'):
        raise SystemExit('node errors: ' + json.dumps(r['node_errors'])[:2000])
    pid, t0 = r['prompt_id'], time.time()
    while True:
        h = api(server, f'/history/{pid}')
        if pid in h and h[pid].get('status', {}).get('completed'):
            return
        if pid in h and h[pid].get('status', {}).get('status_str') == 'error':
            raise SystemExit('ComfyUI error: ' + json.dumps(h[pid]['status'].get('messages'))[-2000:])
        if time.time() - t0 > 1800:
            raise SystemExit('timed out')
        time.sleep(3)


def face_rot(k):
    """Node frame to face k's camera (x along s, y along t, z the face's axis)."""
    c, ds, dt = face_axes(k)
    return np.stack([ds / np.linalg.norm(ds), dt / np.linalg.norm(dt), c / np.linalg.norm(c)])


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('root'); ap.add_argument('sparse'); ap.add_argument('out')
    ap.add_argument('--nodes', nargs='+', required=True); ap.add_argument('--near', type=int, default=20)
    ap.add_argument('--stage', default='moge,fuse'); ap.add_argument('--size', type=int, default=2048)
    ap.add_argument('--voxel', type=float, default=0.02); ap.add_argument('--far', type=float, default=12)
    ap.add_argument('--triangles', type=int, default=1500000); ap.add_argument('--depth', type=int, default=11)
    ap.add_argument('--server', default=os.environ.get('COMFY_SERVER', 'http://127.0.0.1:8189'))
    ap.add_argument('--comfy-input', default=r'C:\ComfyUI\input')
    a = ap.parse_args()
    os.makedirs(os.path.join(a.out, 'moge'), exist_ok=True)
    cams, imgs = read_model(a.sparse)
    by_name = {h[9]: (i, h, pts) for i, (h, pts) in imgs.items()}
    face1 = {h[9].split('/')[1][3:-4]: centre(h) for h, _ in imgs.values() if h[9].startswith('f1/MA-')}
    mid = np.mean([face1[n][0] for n in a.nodes], axis=0)
    order = sorted(face1, key=lambda n: np.linalg.norm(face1[n][0] - mid))
    nodes = list(dict.fromkeys(a.nodes + order))[:len(a.nodes) + a.near]
    print(f'{len(nodes)} nodes: {" ".join(nodes)}', flush=True)
    W, H = a.size, a.size // 2
    load = lambda n, k: np.asarray(Image.open(os.path.join(a.root, 'images', f'f{k}', f'MA-{n}.jpg')).convert('RGB'))

    if 'moge' in a.stage:
        for n in nodes:
            prefix = os.path.join(a.out, 'moge', n)
            if os.path.exists(prefix + '_moge_depth.npy'):
                continue
            t0 = time.time()
            run_moge(a.server, a.comfy_input, pano([load(n, k) for k in range(1, 7)], W, H), prefix + '_moge', W)
            print(f'moge {n}: {time.time() - t0:.0f} s', flush=True)

    if 'fuse' not in a.stage:
        return
    import open3d as o3d
    C = {n: face1[n][0] for n in nodes}; R1 = {n: face1[n][1] for n in nodes}
    P = np.array([C[n] for n in nodes])
    dnn = np.sort(np.linalg.norm(P[:, None] - P[None], axis=2), axis=1)[:, 1]
    unit = float(np.median(dnn))
    # scale: the model's points each node's faces saw
    pts3d = {}
    for line in open(os.path.join(a.sparse, 'points3D.txt')):
        if line.startswith('#') or not line.strip():
            continue
        p = line.split(); pts3d[int(p[0])] = np.array(p[1:4], float)
    scales, report = {}, {}
    D, M = {}, {}
    for n in nodes:
        prefix = os.path.join(a.out, 'moge', n + '_moge')
        d = np.load(prefix + '_depth.npy').astype(np.float32)
        m = np.load(prefix + '_mask.npy') if os.path.exists(prefix + '_mask.npy') else np.isfinite(d)
        if d.shape != (H, W):
            d = cv2.resize(d, (W, H), interpolation=cv2.INTER_NEAREST); m = cv2.resize(m.astype(np.uint8), (W, H), interpolation=cv2.INTER_NEAREST) > 0
        D[n], M[n] = d, (np.asarray(m) > 0.5) & np.isfinite(d) & (d > 0)
        ids = set()
        for k in range(1, 7):
            e = by_name.get(f'f{k}/MA-{n}.jpg')
            if e:
                ids |= {int(x) for x in e[2][2::3] if int(x) >= 0}
        X = np.array([pts3d[i] for i in ids if i in pts3d])
        if len(X) < 10:
            print(f'node {n}: {len(X)} points, left out', flush=True); continue
        v = (X - C[n]) @ R1[n].T @ F                         # node frame (F is its own inverse)
        r = np.linalg.norm(v, axis=1); v /= r[:, None]
        mx, my = dirs_to_equirect_px(v, W, H)
        xi = np.clip(np.rint(mx).astype(int) % W, 0, W - 1); yi = np.clip(np.rint(my).astype(int), 0, H - 1)
        ok = M[n][yi, xi]
        ratio = r[ok] / D[n][yi, xi][ok]
        s = float(np.median(ratio))
        scales[n] = s
        report[n] = {'points': int(ok.sum()), 'scale': s, 'spread': float(np.median(np.abs(np.log(ratio / s))))}
        print(f'node {n}: scale {s:.4g} from {int(ok.sum())} points, typical misfit {report[n]["spread"] * 100:.0f}%', flush=True)
    json.dump({'unit': unit, 'nodes': report}, open(os.path.join(a.out, 'scales.json'), 'w'), indent=1)

    vox = a.voxel * unit
    N = 640
    intr = o3d.camera.PinholeCameraIntrinsic(N, N, N / 2, N / 2, N / 2 - .5, N / 2 - .5)
    t, s_ = np.mgrid[0:N, 0:N].astype(np.float64)
    cloud = o3d.geometry.PointCloud()
    for n in nodes:
        if n not in scales:
            continue
        for k in range(1, 7):
            v = np.stack(DIRS[k]((s_ + .5) / N, (t + .5) / N), -1)
            nv = np.linalg.norm(v, axis=-1)
            mx, my = dirs_to_equirect_px(v / nv[..., None], W, H)
            dist = cv2.remap(D[n], mx, my, cv2.INTER_NEAREST, borderMode=cv2.BORDER_WRAP) * scales[n]
            ok = cv2.remap(M[n].astype(np.uint8), mx, my, cv2.INTER_NEAREST, borderMode=cv2.BORDER_WRAP) > 0
            z = np.where(ok & (dist < a.far * unit), dist / nv, 0).astype(np.float32)
            Rk = face_rot(k) @ F @ R1[n]                      # world to face k's camera
            ext = np.eye(4); ext[:3, :3] = Rk; ext[:3, 3] = -Rk @ C[n]
            rgbd = o3d.geometry.RGBDImage.create_from_color_and_depth(
                o3d.geometry.Image(np.ascontiguousarray(load(n, k))), o3d.geometry.Image(z),
                depth_scale=1.0, depth_trunc=float(a.far * unit), convert_rgb_to_intensity=False)
            pc = o3d.geometry.PointCloud.create_from_rgbd_image(rgbd, intr, ext).voxel_down_sample(vox / 2)
            if not len(pc.points):
                continue
            # normals from the face's own points, turned toward the node that saw them
            pc.estimate_normals(o3d.geometry.KDTreeSearchParamHybrid(radius=4 * vox, max_nn=24))
            pc.orient_normals_towards_camera_location(C[n])
            cloud += pc
        cloud = cloud.voxel_down_sample(vox / 2)
        print(f'points from {n}: {len(cloud.points)} in all', flush=True)
    # Poisson's surface through every node's points (Open3D's TSDF volume gave no surface on this PC, even
    # for a flat test plane), then trimmed where it strays from them: what it closes over the sky and
    # where no node saw
    cloud = cloud.voxel_down_sample(vox)
    print(f'{len(cloud.points)} points for the surface', flush=True)
    mesh, dens = o3d.geometry.TriangleMesh.create_from_point_cloud_poisson(cloud, depth=a.depth, n_threads=-1)
    dens = np.asarray(dens)
    print(f'{len(mesh.triangles)} triangles', flush=True)
    vpc = o3d.geometry.PointCloud(mesh.vertices)
    gap = np.asarray(vpc.compute_point_cloud_distance(cloud))
    mesh.remove_vertices_by_mask((gap > 3 * vox) | (dens < np.quantile(dens, 0.02)))
    tri_c, n_c, _ = mesh.cluster_connected_triangles()
    tri_c = np.asarray(tri_c); n_c = np.asarray(n_c)
    mesh.remove_triangles_by_mask(n_c[tri_c] < 200); mesh.remove_unreferenced_vertices()
    print(f'{len(mesh.triangles)} triangles kept', flush=True)
    if len(mesh.triangles) > a.triangles:
        mesh = mesh.simplify_quadric_decimation(a.triangles)
    # the viewer's frame: first node at the origin, y up, one unit the node spacing
    n0 = nodes[0]
    T = np.eye(4); T[:3, :3] = F @ R1[n0] / unit; T[:3, 3] = -(F @ R1[n0] @ C[n0]) / unit
    mesh.transform(T)
    mesh.compute_vertex_normals()
    o3d.io.write_triangle_mesh(os.path.join(a.out, 'scene.ply'), mesh)
    o3d.io.write_triangle_mesh(os.path.join(a.out, 'scene.glb'), mesh)
    json.dump({n: (F @ R1[n0] @ (C[n] - C[n0]) / unit).tolist() for n in nodes},
              open(os.path.join(a.out, 'nodes.json'), 'w'), indent=1)
    print(f'{len(mesh.triangles)} triangles after; {os.path.join(a.out, "scene.glb")}', flush=True)


if __name__ == '__main__':
    main()
