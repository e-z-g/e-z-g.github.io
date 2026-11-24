"""A walk's first and last frames put back to the two nodes' own pictures, and the difference carried into the frames
next to them so nothing jumps: walk_polar3.ps1's final frames are H3's (pass 3 redraws every frame, so frame 0 is not
quite node A's picture: about 13 levels a pixel on TOHO 1 to 2, most of it detail). For each of the first K frames
the difference (A's picture less H3's frame 0) is moved with the picture (DIS flow from that frame back to frame 0,
per eye of the two-fisheye layout) and added, weighted 1 at frame 0 falling smoothly to 0 after frame K; the same from
the end with B's picture. Frames are read and written as PNG.

    python walk_ends_join.py FRAMES_DIR FIRST.png LAST.png OUT_DIR [--k 6]

FIRST.png and LAST.png are walk_polar3's ends_dual pictures (walk_ends.py / walk_ends_heading.py at the walk's size).
Prints the mean difference at each end before, and the step between frames 0-1 and the last two after.
"""
import argparse, glob, os
import numpy as np, cv2


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('frames'); ap.add_argument('first'); ap.add_argument('last'); ap.add_argument('out')
    ap.add_argument('--k', type=int, default=6)
    a = ap.parse_args()
    paths = sorted(glob.glob(os.path.join(a.frames, '*.png'))); n = len(paths)
    os.makedirs(a.out, exist_ok=True)
    dis = cv2.DISOpticalFlow_create(cv2.DISOPTICAL_FLOW_PRESET_MEDIUM)
    gray = lambda f: cv2.cvtColor(f, cv2.COLOR_BGR2GRAY)
    w = lambda k: 0.5 + 0.5 * np.cos(np.pi * min(k, a.k + 1) / (a.k + 1))       # 1 at the end, 0 from K+1 frames in
    done = {}
    for end, pic, idx in (('first', a.first, range(0, a.k + 1)), ('last', a.last, range(n - 1, n - 2 - a.k, -1))):
        f0 = cv2.imread(paths[idx[0]]); orig = cv2.imread(pic)
        if orig.shape != f0.shape:
            raise SystemExit(f'{pic} is {orig.shape[1]}x{orig.shape[0]}, the frames {f0.shape[1]}x{f0.shape[0]}')
        D = orig.astype(np.float32) - f0.astype(np.float32)
        print(f'{end}: H3 frame {idx[0]} differs from the picture by {np.abs(D).mean():.2f} levels')
        H = f0.shape[0]; g0 = gray(f0)
        for j, i in enumerate(idx):
            f = cv2.imread(paths[i]) if j else f0
            if j == 0:
                out = orig.copy()
            else:
                gk = gray(f); Dk = np.empty_like(D)
                for e in (0, 1):                                              # each eye on its own
                    sl = slice(e * H, (e + 1) * H)
                    fl = dis.calc(np.ascontiguousarray(gk[:, sl]), np.ascontiguousarray(g0[:, sl]), None)   # frame k -> frame 0
                    yy, xx = np.mgrid[0:H, 0:H].astype(np.float32)
                    Dk[:, sl] = cv2.remap(D[:, sl], xx + fl[..., 0], yy + fl[..., 1], cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
                out = np.clip(f.astype(np.float32) + w(j) * Dk, 0, 255).round().astype(np.uint8)
            done[i] = out
    for i, p in enumerate(paths):
        img = done.get(i)
        if img is None:
            img = cv2.imread(p)
        cv2.imwrite(os.path.join(a.out, os.path.basename(p)), img)
    rd = lambda i: cv2.imread(os.path.join(a.out, os.path.basename(paths[i]))).astype(np.float32)
    print(f'after: step 0-1 {np.abs(rd(1) - rd(0)).mean():.2f}, 1-2 {np.abs(rd(2) - rd(1)).mean():.2f}; '
          f'step {n - 2}-{n - 1} {np.abs(rd(n - 1) - rd(n - 2)).mean():.2f}, {n - 3}-{n - 2} {np.abs(rd(n - 2) - rd(n - 3)).mean():.2f}')


if __name__ == '__main__':
    main()
