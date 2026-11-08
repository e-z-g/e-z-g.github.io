# A COLMAP dataset for a Gaussian splat trainer (Brush): images/, sparse/0/{cameras,images,points3D}.txt
#   python splat_dataset.py SPARSE_TXT IMAGES TRUSTED MOVES.json FUSED.ply GHOSTS.ply OUT [--movies lemt] [--voxel 0.04]
# Keeps the faces of the trusted and moved nodes and the movie frames under the --movies folders;
# starting points: FUSED without GHOSTS, one per --voxel cell.
import argparse, os, re, json, shutil, sys
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'colmap'))
from ghost_points import read_ply
ap = argparse.ArgumentParser()
for k in ('sparse_txt', 'images', 'trusted', 'moves', 'fused', 'ghosts', 'out'):
    ap.add_argument(k)
ap.add_argument('--movies', nargs='*', default=['lemt']); ap.add_argument('--voxel', type=float, default=0.04)
ap.add_argument('--alpha', action='store_true', help='with --masks: the sky made transparent in the images (PNG) instead of a masks/ folder, so the trainer must leave it empty, not merely ignore it')
ap.add_argument('--masks', help='sky masks (MASKS/<image name>.png, black on the sky): written to masks/ so the trainer ignores the sky')
a = ap.parse_args()
good = set(re.findall(r'MA-\d+', open(a.trusted).read())) | set(json.load(open(a.moves)))
os.makedirs(os.path.join(a.out, 'sparse', '0'), exist_ok=True)
shutil.copy(os.path.join(a.sparse_txt, 'cameras.txt'), os.path.join(a.out, 'sparse', '0', 'cameras.txt'))
lines = [l for l in open(os.path.join(a.sparse_txt, 'images.txt')) if not l.startswith('#')]
kept = []
for head in lines[0::2]:
    p = head.split()
    if len(p) < 10:
        continue
    name = p[9]
    m = re.fullmatch(r'f\d/(MA-\d+)\.jpg', name)
    if (m and m.group(1) in good) or name.split('/')[0] in a.movies:
        kept.append(' '.join(p[:10]))
# Brush finds an image's mask in masks/ beside images/ by the file's stem alone, so the six
# faces of a node (f1/MA-1016.jpg ... f6/MA-1016.jpg) would share one: names are made flat.
flat = lambda name: name.replace('/', '_')
with open(os.path.join(a.out, 'sparse', '0', 'images.txt'), 'w') as f:
    for h in kept:
        p = h.split(); p[9] = flat(p[9])
        if a.alpha:
            p[9] = os.path.splitext(p[9])[0] + '.png'
        f.write(' '.join(p) + '\n0 0 -1\n')    # one observation of no point: a blank line confuses readers
os.makedirs(os.path.join(a.out, 'images'), exist_ok=True)
if a.masks and not a.alpha:
    os.makedirs(os.path.join(a.out, 'masks'), exist_ok=True)
missing = 0
for h in kept:
    name = h.split()[9]
    dst = os.path.join(a.out, 'images', flat(name))
    if a.alpha:
        from PIL import Image
        src = os.path.join(a.masks, name + '.png')
        im = Image.open(os.path.join(a.images, name)).convert('RGB')
        if os.path.exists(src):
            im.putalpha(Image.open(src).convert('L'))   # white kept, black (sky) transparent
        else:
            missing += 1
        im.save(os.path.splitext(dst)[0] + '.png')
        continue
    if not os.path.exists(dst):
        shutil.copy(os.path.join(a.images, name), dst)
    if a.masks:
        src = os.path.join(a.masks, name + '.png')
        if os.path.exists(src):
            shutil.copy(src, os.path.join(a.out, 'masks', os.path.splitext(flat(name))[0] + '.png'))
        else:
            missing += 1
if a.masks:
    print(f'masks for {len(kept) - missing} of {len(kept)} images')
A = read_ply(a.fused); G = read_ply(a.ghosts)
key = lambda P: np.stack([P['x'], P['y'], P['z']], 1).astype(np.float32).view(np.uint32).reshape(-1, 3).astype(np.uint64)
h = lambda k: k[:, 0] * np.uint64(1000003) ^ (k[:, 1] << np.uint64(21)) ^ (k[:, 2] << np.uint64(42))
A = A[~np.isin(h(key(A)), h(key(G)))]
X = np.stack([A['x'], A['y'], A['z']], 1)
_, u = np.unique(np.floor(X / a.voxel).astype(np.int64), axis=0, return_index=True)
with open(os.path.join(a.out, 'sparse', '0', 'points3D.txt'), 'w') as f:
    for i, j in enumerate(u):
        f.write(f'{i + 1} {X[j, 0]:.5f} {X[j, 1]:.5f} {X[j, 2]:.5f} {A["red"][j]} {A["green"][j]} {A["blue"][j]} 0\n')
# Brush 0.3.0 needs every image to be at least 16387 bytes: run pad_small.py on images/ after this
print(len(kept), 'images;', len(u), 'starting points of', len(A))
