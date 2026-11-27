#!/usr/bin/env python3
r"""
The standard equirectangular layout for a walk's first pass (straight ahead in the centre, straight behind at the left
and right edges, the horizon across the middle, up at the top), the layout rehan-fal/minimax-h3-360-equirect-lora was
trained on (the maintainer, 26 November 2026: try the 360 LoRA); the picture may be wider than 2:1 (the LoRA renders
21:9 and is squeezed to 2:1 after: here the longitude simply spans the whole width).

    python eqr_walk.py ends FACES_A FACES_B OUT --heading H [--pitch 0] [--size 2912x1280]
    python eqr_walk.py todual FRAMES_DIR OUT_DIR [--size 2560x1280] [--dual 180] [--fill-square] [--squash 0.35]

ends: first.png and last.png from the two nodes' cube faces facing game heading H (as walk_ends_heading.py).
todual: each frame redrawn as the two-fisheye layout (draw_dual_fisheye's: front left, back right), the left and right
edges wrapping round. Writes OUT_DIR/0000.png ... Needs numpy, opencv-python, Pillow.
"""
import argparse, glob, os, sys
import numpy as np, cv2
from PIL import Image
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def cam_dirs(W, H):
    """camera directions (x right, y down, z ahead) of each pixel of the layout"""
    v, u = np.mgrid[0:H, 0:W].astype(np.float64)
    lon = ((u + .5) / W * 2 - 1) * np.pi; lat = (0.5 - (v + .5) / H) * np.pi
    return np.stack([np.cos(lat) * np.sin(lon), -np.sin(lat), np.cos(lat) * np.cos(lon)], -1)


def ends(a):
    from walk_ends import sample_dirs
    from walk_ends_heading import faces
    W, H = map(int, a.size.split('x'))
    h, p = np.radians(a.heading - 180), np.radians(a.pitch)
    fwd = np.array([np.sin(h) * np.cos(p), -np.sin(p), np.cos(h) * np.cos(p)])
    right = np.array([np.cos(h), 0.0, -np.sin(h)]); down = np.cross(fwd, right)
    Rcam = np.stack([right, down, fwd]); os.makedirs(a.out, exist_ok=True)
    for name, pre in (('first', a.a), ('last', a.b)):
        Image.fromarray(sample_dirs(faces(pre), cam_dirs(W, H) @ Rcam)).save(os.path.join(a.out, f'{name}.png'))
    print(f'{W}x{H} standard equirectangular ends, heading {a.heading} -> {a.out}')


def todual(a):
    from seam_fix import pixel_dirs
    paths = sorted(glob.glob(os.path.join(a.frames, '*.png'))); os.makedirs(a.out, exist_ok=True)
    H, W = cv2.imread(paths[0]).shape[:2]
    OW, OH = (int(x) for x in a.size.split('x')); S = OW // 2
    maps = []
    for s in (0, 1):
        A, E = pixel_dirs(S, a.dual, a.fill_square, a.squash, s)
        A = np.nan_to_num(A); E = np.nan_to_num(E, nan=0.0)
        q = np.stack([np.cos(E) * np.cos(A), np.cos(E) * np.sin(A), np.sin(E)], -1)   # as polar_to_dual.py
        lon = np.arctan2(q[..., 0], q[..., 2]); lat = np.arcsin(np.clip(-q[..., 1], -1, 1))
        x = ((lon / np.pi + 1) / 2 * W - .5).astype(np.float32)
        y = np.clip((0.5 - lat / np.pi) * H - .5, 0, H - 1).astype(np.float32)
        maps.append((x, y))
    for i, p in enumerate(paths):
        im = cv2.imread(p); out = np.zeros((OH, OW, 3), np.uint8)
        for s, (x, y) in enumerate(maps):
            out[:, s * S:(s + 1) * S] = cv2.remap(im, x, y, cv2.INTER_CUBIC, borderMode=cv2.BORDER_WRAP)
        cv2.imwrite(os.path.join(a.out, f'{i:04d}.png'), out)
    print(f'{len(paths)} frames -> {a.out}')


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest='cmd', required=True)
    e = sp.add_parser('ends'); e.add_argument('a'); e.add_argument('b'); e.add_argument('out')
    e.add_argument('--heading', type=float, required=True); e.add_argument('--pitch', type=float, default=0.0)
    e.add_argument('--size', default='2912x1280')
    d = sp.add_parser('todual'); d.add_argument('frames'); d.add_argument('out'); d.add_argument('--size', default='2560x1280')
    d.add_argument('--dual', type=float, default=180.0); d.add_argument('--fill-square', action='store_true')
    d.add_argument('--squash', type=float, default=0.0)
    a = ap.parse_args()
    ends(a) if a.cmd == 'ends' else todual(a)


if __name__ == '__main__':
    main()
