"""How far apart two nodes are, in eye heights, from their floors alone: every node shares one orientation and stands at
the same eye height, so each node's floor drawn from above (an orthographic map of the plane one eye height below the
eye, from its six faces) differs from its neighbour's only by a shift, the walk between them. Phase correlation on the
two maps (gradients, so lighting matters less) finds it. Prints the shift's length, its game heading (to set against
the hotspots'), and the correlation's peak (low when the floor is hidden, not flat or not shared).

    python floor_shift.py FACES_A FACES_B [--range 4] [--res 0.01] [--save MAPS.png]

FACES_A and FACES_B are face prefixes (C:\\myst3_out\\faces\\TOHO\\TOHO-0002). Faces as node_view.py's FACES (x right, y
down, z into face 1; heading 180 the centre of face 1, growing to the right).
"""
import argparse, os, sys
import numpy as np, cv2
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from walk_ends import sample_dirs          # noqa: E402
from walk_ends_heading import faces        # noqa: E402


def floor_map(prefix, R, res):
    n = int(round(2 * R / res)); c = (np.arange(n) + 0.5) * res - R
    X, Z = np.meshgrid(c, -c)                                # map x to the right of face 1, up the map along face 1
    d = np.stack([X, np.ones_like(X), Z], -1); d /= np.linalg.norm(d, axis=-1, keepdims=True)
    return sample_dirs(faces(prefix), d)


def grad(img):
    g = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY).astype(np.float32)
    gx, gy = cv2.Sobel(g, cv2.CV_32F, 1, 0), cv2.Sobel(g, cv2.CV_32F, 0, 1)
    return np.hypot(gx, gy)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('a'); ap.add_argument('b'); ap.add_argument('--range', type=float, default=4.0); ap.add_argument('--res', type=float, default=0.01)
    ap.add_argument('--save')
    a = ap.parse_args()
    A, B = floor_map(a.a, a.range, a.res), floor_map(a.b, a.range, a.res)
    n = A.shape[0]; win = cv2.createHanningWindow((n, n), cv2.CV_32F)
    (dx, dy), peak = cv2.phaseCorrelate(grad(A), grad(B), win)
    # a feature at map position p in A is at p + (dx, dy) in B; B stands at A's position minus that
    mx, mz = -dx * a.res, dy * a.res                         # metres-in-eye-heights: x right of face 1, z along face 1
    length = np.hypot(mx, mz)
    # face 1's direction is heading 180; x right of it is heading 270 (headings grow to the right)
    heading = (180 + np.degrees(np.arctan2(mx, mz))) % 360
    print(f'{os.path.basename(a.a)} -> {os.path.basename(a.b)}: {length:.2f} eye heights at heading {heading:.1f} (peak {peak:.3f})')
    if a.save:
        cv2.imwrite(a.save, cv2.cvtColor(np.hstack([A, B]), cv2.COLOR_RGB2BGR))


if __name__ == '__main__':
    main()
