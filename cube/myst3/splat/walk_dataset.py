# A COLMAP text dataset whose cameras walk from one node to another, for splat_render.py.
#   py -3 walk_dataset.py SPARSE_TXT OUT FROM TO [--frames 48] [--size 640x360] [--fov 90]
import argparse, os, sys
import numpy as np
from PIL import Image
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'colmap'))
from view_check import read_model
ap = argparse.ArgumentParser(); ap.add_argument('sparse'); ap.add_argument('out'); ap.add_argument('a'); ap.add_argument('b')
ap.add_argument('--frames', type=int, default=48); ap.add_argument('--size', default='640x360'); ap.add_argument('--fov', type=float, default=90)
a = ap.parse_args()
_, imgs = read_model(a.sparse)
c = lambda n: -imgs[f'f1/MA-{n}.jpg'][0].T @ imgs[f'f1/MA-{n}.jpg'][1]
CA, CB = c(a.a), c(a.b)
up = -imgs[f'f1/MA-{a.a}.jpg'][0][1]                 # minus the face camera's y (down)
fwd = CB - CA; fwd -= up * (fwd @ up); fwd /= np.linalg.norm(fwd)
right = np.cross(fwd, up); right /= np.linalg.norm(right)
R = np.stack([right, -up, fwd])
def qvec(R):
    w = np.sqrt(max(0, 1 + R[0, 0] + R[1, 1] + R[2, 2])) / 2
    x = np.copysign(np.sqrt(max(0, 1 + R[0, 0] - R[1, 1] - R[2, 2])) / 2, R[2, 1] - R[1, 2])
    y = np.copysign(np.sqrt(max(0, 1 - R[0, 0] + R[1, 1] - R[2, 2])) / 2, R[0, 2] - R[2, 0])
    z = np.copysign(np.sqrt(max(0, 1 - R[0, 0] - R[1, 1] + R[2, 2])) / 2, R[1, 0] - R[0, 1])
    return np.array([w, x, y, z]) / np.linalg.norm([w, x, y, z])
W, H = (int(v) for v in a.size.split('x')); f = W / 2 / np.tan(np.radians(a.fov) / 2)
os.makedirs(os.path.join(a.out, 'sparse', '0'), exist_ok=True); os.makedirs(os.path.join(a.out, 'images'), exist_ok=True)
open(os.path.join(a.out, 'sparse', '0', 'cameras.txt'), 'w').write(f'1 PINHOLE {W} {H} {f} {f} {W / 2} {H / 2}\n')
q = qvec(R)
with open(os.path.join(a.out, 'sparse', '0', 'images.txt'), 'w') as fh:
    for i in range(a.frames):
        t = -R @ (CA + i / (a.frames - 1) * (CB - CA))
        name = f'walk-{i:03d}.jpg'
        fh.write(f'{i + 1} {q[0]} {q[1]} {q[2]} {q[3]} {t[0]} {t[1]} {t[2]} 1 {name}\n0 0 -1\n')
        Image.new('RGB', (W, H)).save(os.path.join(a.out, 'images', name))
print(f'{a.frames} cameras from MA-{a.a} to MA-{a.b}, {np.linalg.norm(CB - CA):.3f} apart')
