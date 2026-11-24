"""Drop frames from a walk so that it moves an even distance per frame at a constant frame rate: the picture's motion
is measured between neighbouring frames (median DIS flow over both eyes of the two-fisheye layout, as retime.py), and
the frames kept are chosen together (dynamic programming) so that each kept step is as near as possible to one
spacing, the first and last always kept. The spacing is --spacing pixels, or chosen so that --frames are kept.
(Taking the frame nearest each evenly spaced point instead gave single and double steps in turn: no evener.)

    python thin_even.py FRAMES_DIR OUT_DIR (--frames N | --spacing PX) [--orient IN.json OUT.json]

--orient picks the kept frames' turns out of a viewer_orient.py file for the viewer.
"""
import argparse, glob, json, os, shutil
import numpy as np, cv2


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('frames'); ap.add_argument('out')
    ap.add_argument('--frames', type=int, dest='count'); ap.add_argument('--spacing', type=float)
    ap.add_argument('--orient', nargs=2)
    a = ap.parse_args()
    paths = sorted(glob.glob(os.path.join(a.frames, '*.png'))); n = len(paths)
    dis = cv2.DISOpticalFlow_create(cv2.DISOPTICAL_FLOW_PRESET_MEDIUM)
    prev = cv2.cvtColor(cv2.imread(paths[0]), cv2.COLOR_BGR2GRAY); H = prev.shape[0]; step = []
    for k in range(1, n):
        cur = cv2.cvtColor(cv2.imread(paths[k]), cv2.COLOR_BGR2GRAY); m = []
        for e in (0, 1):
            f = dis.calc(np.ascontiguousarray(prev[:, e * H:(e + 1) * H]), np.ascontiguousarray(cur[:, e * H:(e + 1) * H]), None)
            m.append(np.median(np.hypot(f[..., 0], f[..., 1])))
        step.append(np.mean(m)); prev = cur
    step = np.array(step); C = np.concatenate([[0], np.cumsum(step)])
    def fit(sp):                                       # the path from the first frame to the last with kept steps nearest sp
        cost = np.full(n, np.inf); prev = [-1] * n; cost[0] = 0
        for j in range(1, n):
            for i in range(max(0, j - 12), j):
                c = cost[i] + ((C[j] - C[i] - sp) / sp) ** 2
                if c < cost[j]: cost[j] = c; prev[j] = i
        k = n - 1; path = [k]
        while k: k = prev[k]; path.append(k)
        return path[::-1]
    if a.spacing: sp = a.spacing; keep = fit(sp)
    else:                                              # the spacing that keeps --frames, the evenest if several do
        best = None
        for sp in np.arange(np.median(step) * 0.5, C[-1] / 2, 0.25):
            p = fit(sp); d = np.diff(C[p]); sc = (abs(len(p) - a.count), d.std() / d.mean())
            if best is None or sc < best[0]: best = (sc, sp, p)
        _, sp, keep = best
    os.makedirs(a.out, exist_ok=True)
    for j, k in enumerate(keep): shutil.copyfile(paths[k], os.path.join(a.out, f'{j:04d}.png'))
    d = np.diff(C[keep])
    print('steps (px):', ' '.join(f'{x:.0f}' for x in step))
    print(f'spacing {sp:.1f} px; kept {len(keep)} of {n}:', ' '.join(map(str, keep)))
    print('kept steps (px):', ' '.join(f'{x:.0f}' for x in d), f'; spread {d.std() / d.mean() * 100:.0f}% of the mean (all frames: {step.std() / step.mean() * 100:.0f}%)')
    if a.orient:
        O = json.load(open(a.orient[0])); O['q'] = [O['q'][k] for k in keep]; json.dump(O, open(a.orient[1], 'w'))


if __name__ == '__main__':
    main()
