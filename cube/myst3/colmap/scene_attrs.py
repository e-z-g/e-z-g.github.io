#!/usr/bin/env python3
r"""
The material maps of every node's faces carried onto scene_mesh.py's mesh, for a viewer that lights it.

    python scene_attrs.py ROOT SPARSE_TXT MESH_DIR MAPS_DIR [--tolerance 0.06] [--stage attrs]

MESH_DIR is scene_mesh.py's OUT (scene.ply, scales.json, moge\); MAPS_DIR materials.py --nodes' output
(MA-<node>-<k>_albedo.png, _roughness.png, _metallic.png). The nodes are scales.json's. Each vertex is put
into every face of every node: where it falls inside the face and its distance along the face's axis agrees
with the face's own depth there (MoGe's, scaled as the mesh was) to --tolerance of it plus two voxels, the
face sees it, and the face's picture, albedo, roughness and metallic there are added in, weighted by how
squarely and how near the face sees it (cosine over distance). A vertex no face sees keeps the mesh's own
colour and mid values. Writes MESH_DIR\scene.bin and scene.json for the viewer: positions (float32, the
viewer's frame as scene.glb's), triangle indices (uint32), and per vertex the picture's colour, the albedo
(uint8 RGB each) and roughness and metallic (uint8 each). Also each node's six faces as one picture,
MESH_DIR\pictures\MA-<node>.jpg: three across and two down in face order (1 2 3 above, 4 5 6 below), each
face as in ROOT, for a viewer that projects them. Needs numpy, Pillow, opencv-python, open3d.
"""
import argparse
import json
import os

import cv2
import numpy as np
from PIL import Image

from esrgan_dense_test import centre, read_model
from moge_depth import DIRS, dirs_to_equirect_px
from scene_mesh import F, face_rot


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('root'); ap.add_argument('sparse'); ap.add_argument('mesh'); ap.add_argument('maps')
    ap.add_argument('--tolerance', type=float, default=0.06); ap.add_argument('--voxel', type=float, default=0.02)
    ap.add_argument('--size', type=int, default=2048)
    ap.add_argument('--depth-from', help="where the nodes' moge\\ depth is, when MESH_DIR is not scene_mesh.py's own (splat_mesh.py's)")
    a = ap.parse_args()
    import open3d as o3d
    sc = json.load(open(os.path.join(a.mesh, 'scales.json')))
    unit = sc['unit']; nodes = list(json.load(open(os.path.join(a.mesh, 'nodes.json'))).keys())
    _, imgs = read_model(a.sparse)
    face1 = {h[9].split('/')[1][3:-4]: centre(h) for h, _ in imgs.values() if h[9].startswith('f1/MA-')}
    m = o3d.io.read_triangle_mesh(os.path.join(a.mesh, 'scene.ply'))
    V = np.asarray(m.vertices).astype(np.float64); T = np.asarray(m.triangles).astype(np.uint32)
    m.compute_vertex_normals(); Nrm = np.asarray(m.vertex_normals)
    base = (np.asarray(m.vertex_colors) * 255).astype(np.float64) if m.has_vertex_colors() else np.full((len(V), 3), 128.0)
    # the mesh is in the viewer's frame; back to the model's
    n0 = nodes[0]; C0, R0 = face1[n0]
    A = F @ R0 / unit                                         # model to viewer: v = A (p - C0)
    Pw = V @ np.linalg.inv(A).T + C0
    Nw = Nrm @ np.linalg.inv(A).T; Nw /= np.linalg.norm(Nw, axis=1, keepdims=True) + 1e-12
    W, H = a.size, a.size // 2
    acc = np.zeros((len(V), 8)); wsum = np.zeros(len(V))
    N = 640
    t_, s_ = np.mgrid[0:N, 0:N].astype(np.float64)
    for n in nodes:
        if n not in sc['nodes']:
            continue
        C, R1 = face1[n]; s = sc['nodes'][n]['scale']
        mdir = os.path.join(a.depth_from or a.mesh, 'moge')
        pre = os.path.join(mdir, n + '_moge')
        D = np.load(pre + '_depth.npy').astype(np.float32)
        anch = os.path.join(mdir, n + '_anchored.npy')
        if os.path.exists(anch):                              # scene_mesh.py --dense: already in the model's units
            D = cv2.resize(np.load(anch), (D.shape[1], D.shape[0]), interpolation=cv2.INTER_NEAREST); s = 1.0
        Mk = (np.load(pre + '_mask.npy') > 0.5) if os.path.exists(pre + '_mask.npy') else np.isfinite(D)
        if D.shape != (H, W):
            D = cv2.resize(D, (W, H), interpolation=cv2.INTER_NEAREST); Mk = cv2.resize(Mk.astype(np.uint8), (W, H), interpolation=cv2.INTER_NEAREST) > 0
        seen = 0
        for k in range(1, 7):
            v = np.stack(DIRS[k]((s_ + .5) / N, (t_ + .5) / N), -1); nv = np.linalg.norm(v, axis=-1)
            mx, my = dirs_to_equirect_px(v / nv[..., None], W, H)
            z_map = cv2.remap(D, mx, my, cv2.INTER_NEAREST, borderMode=cv2.BORDER_WRAP) * s / nv
            ok_map = cv2.remap(Mk.astype(np.uint8), mx, my, cv2.INTER_NEAREST, borderMode=cv2.BORDER_WRAP) > 0
            Rk = face_rot(k) @ F @ R1
            pc = (Pw - C) @ Rk.T
            z = pc[:, 2]
            front = z > 1e-6
            u = np.where(front, pc[:, 0] / np.maximum(z, 1e-6) * N / 2 + N / 2 - .5, -1)
            w_ = np.where(front, pc[:, 1] / np.maximum(z, 1e-6) * N / 2 + N / 2 - .5, -1)
            ui = np.rint(u).astype(int); vi = np.rint(w_).astype(int)
            inside = front & (ui >= 0) & (ui < N) & (vi >= 0) & (vi < N)
            idx = np.nonzero(inside)[0]
            zm = z_map[vi[idx], ui[idx]]; okm = ok_map[vi[idx], ui[idx]]
            vis = okm & (np.abs(z[idx] - zm) < a.tolerance * zm + 2 * a.voxel * unit)
            idx = idx[vis]
            if not len(idx):
                continue
            ray = (Pw[idx] - C); dist = np.linalg.norm(ray, axis=1); ray /= dist[:, None]
            cos = np.abs(np.sum(ray * Nw[idx], axis=1))
            wt = np.maximum(cos, 0.05) / (dist / unit)
            yy, xx = vi[idx], ui[idx]
            pic = np.asarray(Image.open(os.path.join(a.root, 'images', f'f{k}', f'MA-{n}.jpg')).convert('RGB'), np.float64)
            vals = [pic[yy, xx]]
            for key, ch in (('albedo', 3), ('roughness', 1), ('metallic', 1)):
                f = os.path.join(a.maps, f'MA-{n}-{k}_{key}.png')
                if os.path.exists(f):
                    im = np.asarray(Image.open(f).convert('RGB').resize((N, N)), np.float64)
                    vals.append(im[yy, xx] if ch == 3 else im[yy, xx, :1])
                else:
                    vals.append(np.full((len(idx), ch), np.nan))
            vals = np.concatenate(vals, 1)
            good = ~np.isnan(vals).any(1)
            np.add.at(acc, idx[good], vals[good] * wt[good, None]); np.add.at(wsum, idx[good], wt[good])
            seen += len(idx)
        print(f'node {n}: {seen} vertex sightings', flush=True)
        faces = [Image.open(os.path.join(a.root, 'images', f'f{k}', f'MA-{n}.jpg')).convert('RGB') for k in range(1, 7)]
        fs = faces[0].size[0]; atlas = Image.new('RGB', (3 * fs, 2 * fs))
        for k, im in enumerate(faces):
            atlas.paste(im, (k % 3 * fs, k // 3 * fs))
        os.makedirs(os.path.join(a.mesh, 'pictures'), exist_ok=True)
        atlas.save(os.path.join(a.mesh, 'pictures', f'MA-{n}.jpg'), quality=92)
    have = wsum > 0
    out = np.empty((len(V), 8))
    out[have] = acc[have] / wsum[have, None]
    out[~have, :3] = base[~have]; out[~have, 3:6] = base[~have]; out[~have, 6:] = 128
    print(f'{have.mean() * 100:.1f}% of {len(V)} vertices seen by a face', flush=True)
    q = np.clip(np.rint(out), 0, 255).astype(np.uint8)
    parts = [('position', V.astype(np.float32)), ('index', T), ('color', q[:, 0:3].copy()), ('albedo', q[:, 3:6].copy()),
             ('roughMetal', q[:, 6:8].copy())]
    head, off = {'vertices': len(V), 'triangles': len(T), 'parts': {}}, 0
    with open(os.path.join(a.mesh, 'scene.bin'), 'wb') as f:
        for name, arr in parts:
            b = np.ascontiguousarray(arr).tobytes()
            head['parts'][name] = {'offset': off, 'bytes': len(b), 'type': str(arr.dtype), 'size': arr.shape[1]}
            f.write(b); off += len(b)
            pad = (-off) % 4; f.write(b'\0' * pad); off += pad
    json.dump(head, open(os.path.join(a.mesh, 'scene.json'), 'w'), indent=1)
    print(os.path.join(a.mesh, 'scene.bin'), off, 'bytes', flush=True)


if __name__ == '__main__':
    main()
