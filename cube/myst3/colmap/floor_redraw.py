"""How much a walk redraws the floor underfoot: each frame warped onto the next along DIS flow, and the difference left
(mean absolute, 0-255) within --cone degrees of straight down, per eye of the two-fisheye layout; printed per step and
as the median over steps. Motion moves the picture; what the flow cannot explain is redrawing (or flow failing).

    python floor_redraw.py FRAMES_DIR [--cone 35] [--dual 180 --fill-square --squash 0.35]
"""
import argparse, glob, os, sys
import numpy as np, cv2
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from seam_fix import pixel_dirs  # noqa: E402

ap = argparse.ArgumentParser(); ap.add_argument('frames'); ap.add_argument('--cone', type=float, default=35)
ap.add_argument('--dual', type=float, default=180); ap.add_argument('--fill-square', action='store_true', default=True); ap.add_argument('--squash', type=float, default=0.35)
a = ap.parse_args()
paths = sorted(glob.glob(os.path.join(a.frames, '*.png'))); H = cv2.imread(paths[0]).shape[0]
masks = []
for s in (0, 1):
    A, E = pixel_dirs(H, a.dual, a.fill_square, a.squash, s)
    down = np.cos(E) * np.sin(A)                      # camera y (down) component; the back eye keeps y
    masks.append(np.nan_to_num(down) > np.cos(np.radians(a.cone)))
dis = cv2.DISOpticalFlow_create(cv2.DISOPTICAL_FLOW_PRESET_MEDIUM)
prev = cv2.imread(paths[0]); res = []
yy, xx = np.mgrid[0:H, 0:H].astype(np.float32)
for k in range(1, len(paths)):
    cur = cv2.imread(paths[k]); r = []
    for s in (0, 1):
        P, Cc = np.ascontiguousarray(prev[:, s * H:(s + 1) * H]), np.ascontiguousarray(cur[:, s * H:(s + 1) * H])
        f = dis.calc(cv2.cvtColor(Cc, cv2.COLOR_BGR2GRAY), cv2.cvtColor(P, cv2.COLOR_BGR2GRAY), None)   # where each pixel of cur was in prev
        w = cv2.remap(P, xx + f[..., 0], yy + f[..., 1], cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
        d = np.abs(w.astype(np.float32) - Cc.astype(np.float32)).mean(-1)
        r.append(d[masks[s]].mean())
    res.append(r); prev = cur
    print(f'{k - 1:2d}->{k:2d}: front {r[0]:5.2f}  back {r[1]:5.2f}')
r = np.array(res)
print(f'{a.frames}: floor left over after the flow, median over steps: front {np.median(r[:, 0]):.2f}, back {np.median(r[:, 1]):.2f}, both {np.median(r.mean(1)):.2f}')
