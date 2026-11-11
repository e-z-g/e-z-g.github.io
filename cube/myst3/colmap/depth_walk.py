#!/usr/bin/env python3
"""
A depth video of a walk between two nodes, drawn in the layout of a generated walk, to guide the video model
(MiniMax H3's Fun ControlNet-Union, depth): geometry moves correctly across every cube edge or fisheye rim
because it is drawn, not generated.

    python depth_walk.py SCENE_DIR LAYOUT.json OUT.mp4 [--frames 124] [--fps 24] [--size WxH] [--step 2]

SCENE_DIR is a walk folder as the viewer's (scene.json; MA-<node>-<k>-depth.png): each depth pixel is a point
centre + matrix * dir(face, s, t) * r, r = r_far / (1 + (ratio - 1) d), as the viewer's walk meshes; depth 0
is sky. LAYOUT is walk_ends.py's layout.json (--net, --cross-hub or --dual-fisheye), whose axes are in the
walk's right, down, forward; the walk's direction comes from view.json beside it (look_node_frame). The
camera moves in a straight line from the first node to the second without turning. Each frame: both nodes'
points projected into the layout, the nearest kept per pixel, small holes closed by taking the nearest within
a few pixels, then inverse distance as brightness (near white, sky black), on one scale for the whole video.
--step takes every n-th depth pixel. Needs numpy, opencv-python, Pillow; ffmpeg.
"""
import argparse
import json
import os
import subprocess

import cv2
import numpy as np
from PIL import Image

DIRS = {1: lambda s, t: (2 * s - 1, 1 - 2 * t, -np.ones_like(s)),
        2: lambda s, t: (1 - 2 * s, -np.ones_like(s), 1 - 2 * t),
        3: lambda s, t: (1 - 2 * s, 1 - 2 * t, np.ones_like(s)),
        4: lambda s, t: (np.ones_like(s), 1 - 2 * t, 2 * s - 1),
        5: lambda s, t: (-np.ones_like(s), 1 - 2 * t, 1 - 2 * s),
        6: lambda s, t: (1 - 2 * s, np.ones_like(s), 2 * t - 1)}


def node_points(scene_dir, n, step):
    pts = []
    M = np.array(n['matrix'], float); C = np.array(n['centre'], float)
    for k in range(1, 7):
        d = np.asarray(Image.open(os.path.join(scene_dir, f"MA-{n['node']}-{k}-depth.png")).convert('L'), np.float32)[::step, ::step] / 255
        N = d.shape[0]
        t, s = np.mgrid[0:N, 0:N].astype(np.float32)
        s = (s + .5) / N; t = (t + .5) / N
        v = np.stack(DIRS[k](s, t), -1); v /= np.linalg.norm(v, axis=-1, keepdims=True)
        r = n['r_far'] / (1 + (n['ratio'] - 1) * d)
        ok = d > 0.5 / 255                                   # depth 0 is sky: left out, drawn black
        pts.append(C + (v[ok] * r[ok][:, None]) @ M.T)
    return np.concatenate(pts)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('scene'); ap.add_argument('layout'); ap.add_argument('out')
    ap.add_argument('--frames', type=int, default=124); ap.add_argument('--fps', type=float, default=24)
    ap.add_argument('--size'); ap.add_argument('--step', type=int, default=2)
    a = ap.parse_args()
    scn = json.load(open(os.path.join(a.scene, 'scene.json')))
    L = json.load(open(a.layout))
    view = json.load(open(os.path.join(os.path.dirname(a.layout), 'view.json')))
    W, H = (int(x) for x in a.size.split('x')) if a.size else L['size']
    if 'size' not in L:                                   # an older layout.json: cells on a plain grid
        L['size'] = [W, H]; cw, ch = W / L.get('cols', 4), H / L.get('rows', 3)
        for c in L['cells']:
            c['rect'] = [c['col'] * cw, c['row'] * ch, cw, ch]
    sx, sy = W / L['size'][0], H / L['size'][1]
    # the walk's frame in the first node's frame (y up), as walk_ends.py builds it in the model's
    up = np.array([0.0, 1.0, 0.0])
    fwd = np.array(view['look_node_frame'], float); fwd -= up * (fwd @ up); fwd /= np.linalg.norm(fwd)
    right = np.cross(fwd, up); right /= np.linalg.norm(right)
    down = np.cross(fwd, right); down /= np.linalg.norm(down)
    B = np.stack([right, down, fwd])                         # walk frame from node frame: w = B @ p
    P = np.concatenate([node_points(a.scene, n, a.step) for n in scn['nodes'][:2]])
    C0, C1 = (np.array(n['centre'], float) for n in scn['nodes'][:2])
    print(f'{len(P)} points; {W}x{H}, {a.frames} frames', flush=True)

    if L.get('net') == 'dual-fisheye':
        half = np.radians(L['fov']) / 2
        views = [(np.array(e['axes'], float), e['rect']) for e in L['eyes']]
    else:
        views = [(np.array(c['axes'], float), c['rect']) for c in L['cells']]
    near = min(n['r_far'] / n['ratio'] for n in scn['nodes'][:2])  # the nearest a node's depth reaches
    frames = []
    for i in range(a.frames):
        u = i / (a.frames - 1)
        cam = (1 - u) * C0 + u * C1
        w = (P - cam) @ B.T                                  # walk frame
        dist = np.linalg.norm(w, axis=1); dvec = w / dist[:, None]
        zbuf = np.full((H, W), np.inf, np.float32)
        best = np.full(len(P), -np.inf)
        which = np.full(len(P), -1)
        for j, (A, rect) in enumerate(views):
            z = dvec @ A[2]
            take = z > best
            best[take] = z[take]; which[take] = j
        for j, (A, rect) in enumerate(views):
            m = which == j
            if not m.any():
                continue
            dv = dvec[m]
            x, y, z = dv @ A[0], dv @ A[1], dv @ A[2]
            if L.get('net') == 'dual-fisheye':
                th = np.arccos(np.clip(z, -1, 1)); ph = np.arctan2(y, x)
                fx = 0.5 + 0.5 * th / half * np.cos(ph); fy = 0.5 + 0.5 * th / half * np.sin(ph)
                keep = th <= half
            else:
                fx = (x / z + 1) / 2; fy = (y / z + 1) / 2
                keep = (z > 0) & (fx >= 0) & (fx < 1) & (fy >= 0) & (fy < 1)
            rx, ry, rw, rh = rect
            px = ((rx + fx * rw) * sx).astype(int); py = ((ry + fy * rh) * sy).astype(int)
            keep &= (px >= 0) & (px < W) & (py >= 0) & (py < H)
            np.minimum.at(zbuf, (py[keep], px[keep]), dist[m][keep].astype(np.float32))
        inv = np.where(np.isfinite(zbuf), near / zbuf, 0).astype(np.float32)
        inv = np.maximum(inv, cv2.dilate(inv, np.ones((3, 3), np.uint8)) * (inv == 0))   # pinholes from the nearest
        inv = np.maximum(inv, cv2.dilate(inv, np.ones((5, 5), np.uint8)) * (inv == 0))
        frames.append(np.clip(np.sqrt(np.clip(inv, 0, 1)) * 255, 0, 255).astype(np.uint8))
        if i % 20 == 0:
            print(f'frame {i}', flush=True)
    # outside the layout's cells or circles: black, as in the picture
    mask = np.zeros((H, W), np.uint8)
    for A, (rx, ry, rw, rh) in views:
        x0, y0, x1, y1 = int(rx * sx), int(ry * sy), int((rx + rw) * sx), int((ry + rh) * sy)
        if L.get('net') == 'dual-fisheye':
            cv2.circle(mask, ((x0 + x1) // 2, (y0 + y1) // 2), (x1 - x0) // 2, 255, -1)
        else:
            mask[y0:y1, x0:x1] = 255
    p = subprocess.Popen(['ffmpeg', '-v', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'gray', '-s', f'{W}x{H}', '-r', str(a.fps),
                          '-i', '-', '-c:v', 'libx264', '-crf', '12', '-pix_fmt', 'yuv420p', a.out], stdin=subprocess.PIPE)
    for f in frames:
        p.stdin.write(np.where(mask > 0, f, 0).astype(np.uint8).tobytes())
    p.stdin.close(); p.wait()
    print(a.out, flush=True)


if __name__ == '__main__':
    main()
