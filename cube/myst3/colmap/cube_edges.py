"""usage: cube_edges.py VIDEO [layout.json]. All 12 edges of the cube in a walk_ends.py --cross-floor video: for points along each edge, the colour each of the
two faces gives one pixel inside it; the mean difference (0-255) per edge, at the start, the worst frame and the
median over the walk. Faces in the walk's camera axes (right, down, forward), as walk_ends.py draws them."""
import sys
import cv2
import numpy as np

R, D, F = np.eye(3)
U = -D
FACES = {'back': ((1, 0), (D, R, -F)), 'floor': ((1, 1), (F, R, D)), 'front': ((1, 2), (U, R, F)),
         'sky': ((1, 3), (-F, R, U)), 'left': ((0, 1), (F, D, -R)), 'right': ((2, 1), (F, U, R))}
JOINED = {('back', 'floor'), ('floor', 'front'), ('front', 'sky'), ('left', 'floor'), ('floor', 'right')}


GRID = (3, 4)   # rows, columns


def project(face, d, W, H):
    (r, c), (a1, a2, a3) = FACES[face]
    z = d @ a3
    x, y = d @ a1 / z, d @ a2 / z
    cw, ch = W / GRID[1], H / GRID[0]
    return (c + (x + 1) / 2) * cw - .5, (r + (y + 1) / 2) * ch - .5


def edges():
    out = []
    names = list(FACES)
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            na, nb = FACES[a][1][2], FACES[b][1][2]
            if abs(na @ nb) > 0.5:
                continue                                   # opposite faces share no edge
            e = np.cross(na, nb)                           # along the edge
            t = np.linspace(-0.9, 0.9, 40)[:, None]
            pts = (na + nb)[None, :] + t * e[None, :]      # on the edge
            out.append((a, b, pts + 0.02 * na, pts + 0.02 * nb))   # a hair inside each face
    return out


if len(sys.argv) > 2:      # walk_ends.py --cross-hub's layout.json: each cell's face, place and axes
    import json
    L = json.load(open(sys.argv[2]))
    FACES = {c['face']: ((c['row'], c['col']), tuple(np.array(v) for v in c['axes'])) for c in L['cells']}
    GRID = (L.get('rows', 3), L.get('cols', 4))
    # joined in the picture: cells that share a side in the grid
    JOINED = {(p['face'], q['face']) for p in L['cells'] for q in L['cells']
              if abs(p['row'] - q['row']) + abs(p['col'] - q['col']) == 1}
cap = cv2.VideoCapture(sys.argv[1]); E = edges(); series = []
while True:
    r, f = cap.read()
    if not r:
        break
    H, W = f.shape[:2]; f = f.astype(np.float32); row = []
    for a, b, pa, pb in E:
        sa = [cv2.getRectSubPix(f, (1, 1), project(a, p / np.linalg.norm(p), W, H))[0, 0] for p in pa]
        sb = [cv2.getRectSubPix(f, (1, 1), project(b, p / np.linalg.norm(p), W, H))[0, 0] for p in pb]
        row.append(np.abs(np.array(sa) - np.array(sb)).mean())
    series.append(row)
s = np.array(series)
for i, (a, b, _, _) in enumerate(E):
    tag = 'joined in the picture' if (a, b) in JOINED or (b, a) in JOINED else 'apart in the picture'
    print(f'{a:6s}|{b:6s} {tag:22s} start {s[0, i]:5.1f}  median {np.median(s[:, i]):5.1f}  worst {s[:, i].max():5.1f}')
apart = [i for i, (a, b, _, _) in enumerate(E) if not ((a, b) in JOINED or (b, a) in JOINED)]
rise = s[:, apart] - s[0, apart]
print(f'SCORE (edges apart in the picture, mean rise over the walk above the first frame; lower is better): {rise.mean():.2f}; worst rise {rise.max():.1f}')
