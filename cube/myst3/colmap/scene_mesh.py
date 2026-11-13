#!/usr/bin/env python3
r"""
One coloured mesh of a stretch of an age, fused from its nodes: each node's panorama given distances by MoGe,
placed by the joined model's cameras and scaled by its points, the six faces of every node joined into one
surface (Poisson reconstruction, Open3D) and coloured from the game's own pictures.

    python scene_mesh.py ROOT SPARSE_TXT OUT --nodes 4084 4089 [--near 20] [--exclude N ...] [--stage moge,fuse]
        [--size 2048] [--voxel 0.02] [--far 12] [--confirm-beyond 3] [--triangles 1500000] [--tile 12]

ROOT holds images\f<k>\<PREFIX>-<node>.jpg (PREFIX --prefix: MA for Amateria, LE for J'nanin) (k as node_depth.py's faces: front, bottom, back, right, left, top);
SPARSE_TXT the joined model as text. The nodes are those given and the --near nearest to their middle, less
--exclude (nodes the model still has in the wrong place).

  moge  For each node, its six faces drawn as one equirectangular panorama (--size wide) and MoGe-3's
        panorama inference run on it in ComfyUI (as moge_depth.py), the distances saved as
        OUT\moge\<node>_moge_depth.npy and the sky mask beside them. Needs a running ComfyUI.
  fuse  Each node's distances scaled to the model: the model's points that the node's faces saw, their
        distance from the node's centre against MoGe's in the same direction, median of the ratio
        (written to OUT\scales.json with how well they agree). With --dense, each node's distances are then
        anchored to that cloud: the log of its distance over MoGe's, seen from the node, smoothed over the
        sphere (--anchor-sigma degrees) and applied, so MoGe is pulled onto what was measured and carried
        smoothly across the cloud's holes (OUT\moge\<node>_anchored.npy). Each face then becomes a depth image along
        its own axis (640 px, the picture's own pixels for colour) with the camera the model gives the
        node: face 1's rotation, the others turned from it as the cube's faces are. Sky and anything past
        --far times the median spacing between neighbouring nodes is left out. Every face of every node is
        turned into points; a point is dropped where more of the other nodes within --check-range spacings
        look past it to something farther than see something there (by --tolerance): a copy of a surface
        put in the wrong place by one node lies in the open space of the others. A point more than
        --confirm-beyond spacings from its own node is also dropped unless at least one other node sees
        something there: far surfaces one node sees at a grazing angle are where its guess is worst, and
        nothing else would contradict them (from outside they stood out as shards). With --splat-centres
        (splat/splat_mesh_check.py's splat_centres.npy: a Gaussian splat's centres in the viewer frame
        below), a point is also dropped unless a splat centre lies within --splat-radius spacings: the
        splat was fitted to every picture at once, so what MoGe alone put somewhere has no splat there (and
        what the splat does not cover is left out). The rest are thinned to
        one a --voxel times that spacing, and one surface laid through all
        of them (Poisson, octree --depth) with the colours carried into its vertices; the surface is
        trimmed where it lies over 3 voxels from every point (where it closes over the sky or what no
        node saw), reduced to --triangles, and written as OUT\scene.ply. With --tile, for a whole age,
        the surface is laid tile by tile (squares --tile spacings across in the viewer frame's x and z,
        each with --tile-margin round it, keeping the triangles whose middle is in the square), since
        Poisson's octree spans all its points and one over an age is as coarse as the age is wide; the
        --triangles are shared by the tiles' points. A node the model gives too few points to scale
        by is scaled by the --dense cloud alone, and with --dense every node's scale is first set by
        the dense cloud (the model's points no longer fit nodes it moved later). Written
        and OUT\scene.glb (y up, the first node at the origin, one unit the median node spacing) with
        OUT\nodes.json (each node's centre in the same frame, for the viewer's start) and OUT\views.json
        (each node's centre and the rotation from that frame to the node's own, x right, y up, -z face 1,
        row by row, for a viewer that projects the node's pictures onto the mesh).

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
    ap.add_argument('--exclude', nargs='*', default=[], help='nodes left out (still misplaced in the model)')
    ap.add_argument('--stage', default='moge,fuse'); ap.add_argument('--size', type=int, default=2048)
    ap.add_argument('--voxel', type=float, default=0.02); ap.add_argument('--far', type=float, default=12)
    ap.add_argument('--triangles', type=int, default=1500000); ap.add_argument('--depth', type=int, default=11)
    ap.add_argument('--dense', help="a dense cloud in the model's frame (run_dense.ps1's fused.ply) to anchor each node's depth to")
    ap.add_argument('--anchor-sigma', type=float, default=8.0)
    ap.add_argument('--tolerance', type=float, default=0.06); ap.add_argument('--check-range', type=float, default=6.0)
    ap.add_argument('--confirm-beyond', type=float, default=3.0)
    ap.add_argument('--splat-centres'); ap.add_argument('--splat-radius', type=float, default=0.2)
    ap.add_argument('--tile', type=float, default=0, help='surface laid in square tiles this many spacings across (0: one surface)')
    ap.add_argument('--tile-margin', type=float, default=1.0)
    ap.add_argument('--moge-nodes', nargs='*', help='the moge stage on these nodes instead (any node with faces in ROOT, in the model or not)')
    ap.add_argument('--server', default=os.environ.get('COMFY_SERVER', 'http://127.0.0.1:8189'))
    ap.add_argument('--comfy-input', default=r'C:\ComfyUI\input')
    ap.add_argument('--prefix', default='MA', help="the faces' and pictures' file prefix: MA (Amateria), LE (J'nanin)")
    a = ap.parse_args()
    os.makedirs(os.path.join(a.out, 'moge'), exist_ok=True)
    cams, imgs = read_model(a.sparse)
    by_name = {h[9]: (i, h, pts) for i, (h, pts) in imgs.items()}
    face1 = {h[9].split('/')[1][3:-4]: centre(h) for h, _ in imgs.values() if h[9].startswith(f'f1/{a.prefix}-')}
    mid = np.mean([face1[n][0] for n in a.nodes], axis=0)
    order = [n for n in sorted(face1, key=lambda n: np.linalg.norm(face1[n][0] - mid)) if n not in a.exclude]
    nodes = list(dict.fromkeys(a.nodes + order))[:len(a.nodes) + a.near]
    print(f'{len(nodes)} nodes: {" ".join(nodes)}', flush=True)
    W, H = a.size, a.size // 2
    load = lambda n, k: np.asarray(Image.open(os.path.join(a.root, 'images', f'f{k}', f'{a.prefix}-{n}.jpg')).convert('RGB'))

    if 'moge' in a.stage:
        for n in a.moge_nodes or nodes:
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
            e = by_name.get(f'f{k}/{a.prefix}-{n}.jpg')
            if e:
                ids |= {int(x) for x in e[2][2::3] if int(x) >= 0}
        X = np.array([pts3d[i] for i in ids if i in pts3d])
        if len(X) < 10:
            if a.dense:
                scales[n] = 1.0; report[n] = {'points': 0, 'scale': 1.0, 'spread': None}
                print(f'node {n}: {len(X)} points, scaled by the dense cloud alone', flush=True)
            else:
                print(f'node {n}: {len(X)} points, left out', flush=True)
            continue
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
    # A node the model moved after its points were made (node_align.py --runs, apply_moves.py) no longer fits
    # those points; with --dense its scale is first set by the dense cloud itself (median over the panorama's
    # cells of the dense distance over MoGe's), so the anchoring below starts within its reach.
    # Anchored to the dense cloud: one scale leaves each node's own shape errors (the nodes put the same
    # walls up to half a node spacing apart, and far things too near), so the log of the dense cloud's
    # distance over MoGe's, seen from the node (nearest dense point per cell of a 512 x 256 panorama), is
    # smoothed over the sphere (normalised Gaussian, --anchor-sigma degrees) and multiplies MoGe's
    # distances: pulled onto the measurement where there is one, carried smoothly across its holes.
    if a.dense:
        dense = np.asarray(o3d.io.read_point_cloud(a.dense).voxel_down_sample(0.005 * unit).points)
        Wl, Hl = 512, 256
        sig = a.anchor_sigma / 180 * Hl
        def blur_sphere(x):
            pad = int(3 * sig) + 1
            xp = np.pad(x, ((pad, pad), (0, 0)), mode='reflect'); xp = np.pad(xp, ((0, 0), (pad, pad)), mode='wrap')
            return cv2.GaussianBlur(xp, (0, 0), sig)[pad:-pad, pad:-pad]
        for n in list(scales):
            v = (dense - C[n]) @ R1[n].T @ F; r = np.linalg.norm(v, axis=1)
            near = r < a.far * unit
            u = v[near] / r[near, None]; r = r[near]
            mx, my = dirs_to_equirect_px(u, Wl, Hl)
            xi = np.rint(mx).astype(int) % Wl; yi = np.clip(np.rint(my).astype(int), 0, Hl - 1)
            zb = np.full((Hl, Wl), np.inf, np.float32); np.minimum.at(zb, (yi, xi), r.astype(np.float32))
            Dl = cv2.resize(D[n], (Wl, Hl), interpolation=cv2.INTER_NEAREST) * scales[n]
            Ml = cv2.resize(M[n].astype(np.uint8), (Wl, Hl), interpolation=cv2.INTER_NEAREST) > 0
            with np.errstate(all='ignore'):
                lr = np.log(zb / Dl)
            ok0 = Ml & np.isfinite(lr)
            if ok0.sum() > 200:
                g = float(np.median(lr[ok0])); scales[n] *= np.exp(g); Dl = Dl * np.exp(g); lr = lr - g
                report[n]['dense_scale'] = float(np.exp(g))
            ok = Ml & np.isfinite(lr) & (np.abs(lr) < np.log(1.8))
            w = ok.astype(np.float32); lr = np.where(ok, lr, 0).astype(np.float32)
            field = blur_sphere(w * lr) / (blur_sphere(w) + 0.02)
            after = np.abs(lr - field)[ok]
            report[n].update({'anchor_cells': int(ok.sum()), 'dense_misfit_before': float(np.median(np.abs(lr[ok]))) if ok.any() else None,
                              'dense_misfit_after': float(np.median(after)) if ok.any() else None})
            D[n] = (D[n] * scales[n] * np.exp(cv2.resize(field, (W, H), interpolation=cv2.INTER_LINEAR))).astype(np.float32)
            scales[n] = 1.0
            np.save(os.path.join(a.out, 'moge', n + '_anchored.npy'), D[n])
            if not ok.any():
                print(f'node {n}: nothing of the dense cloud to anchor to', flush=True); continue
            print(f'node {n}: anchored on {int(ok.sum())} cells (scale x{report[n].get("dense_scale", 1):.3f} first), misfit to the dense cloud '
                  f'{report[n]["dense_misfit_before"] * 100:.0f}% -> {report[n]["dense_misfit_after"] * 100:.0f}%', flush=True)
    json.dump({'unit': unit, 'anchored': bool(a.dense), 'nodes': report}, open(os.path.join(a.out, 'scales.json'), 'w'), indent=1)
    # each node's distances at 1024 x 512 for the see-through test, the largest of each 3 x 3 (lenient at edges)
    Wf, Hf = 1024, 512
    Df = {n: cv2.dilate(cv2.resize(D[n] * scales[n], (Wf, Hf), interpolation=cv2.INTER_NEAREST), np.ones((3, 3), np.uint8)) for n in scales}
    Mf = {n: cv2.resize(M[n].astype(np.uint8), (Wf, Hf), interpolation=cv2.INTER_NEAREST) > 0 for n in scales}

    def see_through(n, X):
        """How many other nodes look past each point X to something farther (it lies in their open
        space: a misplaced copy), and how many see something there."""
        bad = np.zeros(len(X), int); good = np.zeros(len(X), int)
        for m in scales:
            if m == n or np.linalg.norm(C[m] - C[n]) > a.check_range * unit:
                continue
            v = (X - C[m]) @ R1[m].T @ F; r = np.linalg.norm(v, axis=1)
            mx, my = dirs_to_equirect_px(v / r[:, None], Wf, Hf)
            xi = np.rint(mx).astype(int) % Wf; yi = np.clip(np.rint(my).astype(int), 0, Hf - 1)
            dm = Df[m][yi, xi]; sky = ~Mf[m][yi, xi]
            bad += (sky & (r < 3 * unit)) | (~sky & (r < dm * (1 - a.tolerance)))
            good += ~sky & (np.abs(r - dm) < a.tolerance * dm)
        return bad, good

    vox = a.voxel * unit
    n0 = nodes[0]
    T = np.eye(4); T[:3, :3] = F @ R1[n0] / unit; T[:3, 3] = -(F @ R1[n0] @ C[n0]) / unit    # model to viewer frame
    splat_tree = None
    if a.splat_centres:
        from scipy.spatial import cKDTree
        splat_tree = cKDTree(np.load(a.splat_centres).astype(np.float64))
    N = 640
    intr = o3d.camera.PinholeCameraIntrinsic(N, N, N / 2, N / 2, N / 2 - .5, N / 2 - .5)
    t, s_ = np.mgrid[0:N, 0:N].astype(np.float64)
    parts = []
    kept, dropped = {}, {}
    for n in nodes:
        if n not in scales:
            continue
        cloud = o3d.geometry.PointCloud()
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
            # kept unless more other nodes see through it than see it, and when far from the node only if
            # another node sees it too
            X = np.asarray(pc.points)
            bad, good = see_through(n, X)
            far_off = np.linalg.norm(X - C[n], axis=1) > a.confirm_beyond * unit
            ok = (bad <= good) & (~far_off | (good >= 1))
            if splat_tree is not None:
                ds, _ = splat_tree.query(X @ T[:3, :3].T + T[:3, 3], distance_upper_bound=a.splat_radius, workers=-1)
                ok &= np.isfinite(ds)
            keep = np.nonzero(ok)[0]
            dropped[n] = dropped.get(n, 0) + len(pc.points) - len(keep); kept[n] = kept.get(n, 0) + len(keep)
            cloud += pc.select_by_index(keep)
        parts.append(cloud.voxel_down_sample(vox / 2))
        print(f'points from {n}: {kept[n]} kept, {dropped[n]} dropped', flush=True)
    # Poisson's surface through every node's points (Open3D's TSDF volume gave no surface on this PC, even
    # for a flat test plane), then trimmed where it strays from them: what it closes over the sky and
    # where no node saw
    cloud = o3d.geometry.PointCloud()
    for c in parts:
        cloud += c
    del parts
    cloud = cloud.voxel_down_sample(vox)
    print(f'{len(cloud.points)} points for the surface', flush=True)

    def surface(pc, budget, keep_tri=None):
        m, dens = o3d.geometry.TriangleMesh.create_from_point_cloud_poisson(pc, depth=a.depth, n_threads=-1)
        dens = np.asarray(dens); nt = len(m.triangles)
        gap = np.asarray(o3d.geometry.PointCloud(m.vertices).compute_point_cloud_distance(pc))
        m.remove_vertices_by_mask((gap > 3 * vox) | (dens < np.quantile(dens, 0.02)))
        if keep_tri is not None:
            m.remove_triangles_by_mask(~keep_tri(np.asarray(m.vertices)[np.asarray(m.triangles)].mean(1)))
            m.remove_unreferenced_vertices()
        if not len(m.triangles):
            return m, nt
        tri_c, n_c, _ = m.cluster_connected_triangles()
        tri_c = np.asarray(tri_c); n_c = np.asarray(n_c)
        m.remove_triangles_by_mask(n_c[tri_c] < 200); m.remove_unreferenced_vertices()
        if len(m.triangles) > budget:
            m = m.simplify_quadric_decimation(int(budget))
        return m, nt

    if not a.tile:
        mesh, nt = surface(cloud, a.triangles)
        print(f'{nt} triangles, {len(mesh.triangles)} kept', flush=True)
    else:
        # in tiles: Poisson's octree spans its points' box, so one surface over a whole age is as coarse as the
        # age is wide. Each tile is surfaced with --tile-margin around it and keeps the triangles whose middle
        # lies in it; the triangle budget is shared by the tiles' points.
        Pv = np.asarray(cloud.points) @ T[:3, :3].T + T[:3, 3]
        L, mg = a.tile, a.tile_margin
        ij = np.floor(Pv[:, [0, 2]] / L).astype(int)
        cells, counts = np.unique(ij, axis=0, return_counts=True)
        mesh = o3d.geometry.TriangleMesh()
        for (ci, cj), cnt in zip(cells, counts):
            if cnt < 2000:
                continue
            lo = np.array([ci, cj]) * L; hi = lo + L
            sel = np.all((Pv[:, [0, 2]] >= lo - mg) & (Pv[:, [0, 2]] < hi + mg), axis=1)
            def inside(X, lo=lo, hi=hi):
                Y = X @ T[:3, :3].T + T[:3, 3]
                return np.all((Y[:, [0, 2]] >= lo) & (Y[:, [0, 2]] < hi), axis=1)
            m, nt = surface(cloud.select_by_index(np.nonzero(sel)[0]), a.triangles * cnt / len(Pv), inside)
            print(f'tile {ci},{cj}: {cnt} points, {nt} triangles, {len(m.triangles)} kept', flush=True)
            mesh += m
    # the viewer's frame: first node at the origin, y up, one unit the node spacing
    mesh.transform(T)
    mesh.compute_vertex_normals()
    o3d.io.write_triangle_mesh(os.path.join(a.out, 'scene.ply'), mesh)
    o3d.io.write_triangle_mesh(os.path.join(a.out, 'scene.glb'), mesh)
    json.dump({n: (F @ R1[n0] @ (C[n] - C[n0]) / unit).tolist() for n in nodes},
              open(os.path.join(a.out, 'nodes.json'), 'w'), indent=1)
    # viewer frame to node n's frame: F R1[n] R1[n0]^T F (both frames have the same scale)
    json.dump({n: {'pos': (F @ R1[n0] @ (C[n] - C[n0]) / unit).tolist(), 'rot': (F @ R1[n] @ R1[n0].T @ F).tolist()} for n in nodes},
              open(os.path.join(a.out, 'views.json'), 'w'), indent=1)
    print(f'{len(mesh.triangles)} triangles after; {os.path.join(a.out, "scene.glb")}', flush=True)


if __name__ == '__main__':
    main()
