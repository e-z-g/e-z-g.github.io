"""Whether a walk video steps like a person walking (bob, pitch nod, surges in speed) or glides: dense optical flow (DIS)
between consecutive frames of a walk, read at the horizon. The viewer's videos are two 180-degree fisheyes side by side
(ahead on the left), filled to their squares and squashed (walk_ends.py --dual-fisheye 180 --fill-square --squash
0.35); each frame is turned into a level equirectangular panorama with the way ahead in the middle first.

    python walk_gait.py VIDEO.mp4 [VIDEO.mp4 ...] [--frames 22] [--width 1024] [--squash 0.35] [--steps]

Forward is found as the column where the horizon's sideways flow, summed over the walk, crosses zero spreading
outward; back is the column opposite. For each step (frame k to k+1), in pixels of a WIDTH-wide frame:
  speed  the median sideways flow at the horizon 60-120 degrees either side of forward (how far the walls slide by);
  rise   the median vertical flow along the whole horizon band (the camera moving up or down; a pitch turn cancels);
  nod    half the difference of the vertical flow ahead and behind (the camera pitching);
  yaw    the mean sideways flow ahead and behind (the camera turning).
  travel the step's length in eye heights, from the floor beside the camera (60-120 degrees either side of forward,
         45-65 degrees below the horizon, taken as level ground): a floor point at bearing L and depression D moves
         round by dL = t sin L tan D for a step t (in eye heights), less the yaw. A second band, 30-45 degrees down,
         is printed beside it as a check (it agrees where the ground there is floor, not plants or a wall).
Printed per walk: speed's mean and its variation (standard deviation over mean, steps 2 to n-2, the ends left out as
they meet the stills), and the RMS of rise, nod and yaw about their means. A glide has low speed variation and near-zero
rise, nod and yaw; a walking gait shows up as rise and nod swinging, and speed pulsing, at the step rate.
Reads only the first --frames frames (the viewer's key videos repeat the last four). Frames are read one at a time.
"""
import argparse, os, sys
import numpy as np, cv2
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from walk_ends import disc_to_square, squash_y   # noqa: E402


def dual_maps(S, W, squash):
    """remap tables from a dual-fisheye frame (two S x S eyes) to a W x W/2 equirectangular, forward in the middle."""
    H = W // 2
    lon = ((np.arange(W) + .5) / W * 2 - 1) * np.pi; lat = (0.5 - (np.arange(H) + .5) / H) * np.pi
    lon, lat = np.meshgrid(lon, lat)
    x, y, z = np.sin(lon) * np.cos(lat), -np.sin(lat), np.cos(lon) * np.cos(lat)     # right, down, forward
    back = z < 0
    x = np.where(back, -x, x); z = np.abs(z)                                         # the back eye: right and ahead flipped
    th = np.arccos(np.clip(z, -1, 1)); ph = np.arctan2(y, x); r = th / (np.pi / 2)
    sx, sy = disc_to_square(r * np.cos(ph), r * np.sin(ph))
    if squash:
        sy = squash_y(sy, squash)
    mx = ((sx + 1) / 2 * S - .5 + np.where(back, S, 0)).astype(np.float32); my = ((sy + 1) / 2 * S - .5).astype(np.float32)
    return mx, my


def frames(path, n, W, squash):
    cap = cv2.VideoCapture(path); k = 0; maps = None
    while k < n:
        ok, f = cap.read()
        if not ok:
            break
        g = cv2.cvtColor(f, cv2.COLOR_BGR2GRAY)
        if maps is None:
            maps = dual_maps(g.shape[0], W, squash)
        yield cv2.remap(g, *maps, cv2.INTER_LINEAR); k += 1


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('videos', nargs='+'); ap.add_argument('--frames', type=int, default=22)
    ap.add_argument('--width', type=int, default=1024); ap.add_argument('--steps', action='store_true', help='print each step')
    ap.add_argument('--squash', type=float, default=0.35)
    a = ap.parse_args(); W = a.width; H = W // 2
    dis = cv2.DISOpticalFlow_create(cv2.DISOPTICAL_FLOW_PRESET_MEDIUM)
    band = slice(H // 2 - H // 9, H // 2 + H // 9)              # the horizon, +-20 degrees
    print(f'{"walk":28s} {"speed":>6s} {"var":>5s} {"rise":>5s} {"nod":>5s} {"yaw":>5s} {"length":>6s} {"check":>6s} {"tvar":>5s}')
    lam = ((np.arange(W) + .5) / W * 2 - 1) * np.pi; dep = ((np.arange(H) + .5) / H - 0.5) * np.pi   # bearing; depression

    def travel(fx, fw, yaw_px, d0, d1):
        rows = slice(int((d0 / 180 + .5) * H), int((d1 / 180 + .5) * H))
        L = np.roll(lam, W // 2 - fw)                                  # bearings from the way ahead
        side = (np.abs(np.abs(L) - np.pi / 2) < np.pi / 6)
        dl = (fx[rows][:, side] - yaw_px) * 2 * np.pi / W
        t = dl / (np.sin(L[side])[None] * np.tan(dep[rows])[:, None])
        return float(np.median(t))
    for v in a.videos:
        flows = []; fulls = []; prev = None
        for g in frames(v, a.frames, W, a.squash):
            if prev is not None:
                full = dis.calc(prev, g, None); f = full[band]
                flows.append((np.median(f[..., 0], axis=0), np.median(f[..., 1], axis=0)))   # per column
                fulls.append(full[..., 0].copy())
            prev = g
        dx = np.array([x for x, _ in flows]); dy = np.array([y for _, y in flows])         # steps x columns
        k = np.exp(-0.5 * (np.arange(-W // 16, W // 16 + 1) / (W / 64)) ** 2); s0 = dx.sum(0)
        tot = np.convolve(np.concatenate([s0[-(W // 16):], s0, s0[:W // 16]]), k / k.sum(), 'valid')   # smoothed, wrapping
        cross = [c for c in range(W) if tot[c - 1] < 0 <= tot[c] or tot[c - 1] <= 0 < tot[c]]   # spreading outward
        fw = max(cross, key=lambda c: tot[(c + W // 8) % W] - tot[c - W // 8]) if cross else W // 2
        bk = (fw + W // 2) % W
        cols = lambda c, deg: [(c + d) % W for d in range(-int(W * deg / 360), int(W * deg / 360) + 1)]
        right = [(fw + d) % W for d in range(W // 6, W // 3)]; left = [(fw - d) % W for d in range(W // 6, W // 3)]
        speed = (np.median(dx[:, right], 1) - np.median(dx[:, left], 1)) / 2
        rise = np.median(dy, 1)
        nod = (np.median(dy[:, cols(fw, 15)], 1) - np.median(dy[:, cols(bk, 15)], 1)) / 2
        yaw = (np.median(dx[:, cols(fw, 15)], 1) + np.median(dx[:, cols(bk, 15)], 1)) / 2
        tr = np.array([travel(fx, fw, yaw[k], 45, 65) for k, fx in enumerate(fulls)])
        tr2 = np.array([travel(fx, fw, yaw[k], 30, 45) for k, fx in enumerate(fulls)])
        mid = slice(1, len(speed) - 1)
        var = speed[mid].std() / abs(speed[mid].mean())
        rms = lambda s: np.sqrt(((s[mid] - s[mid].mean()) ** 2).mean())
        print(f'{os.path.basename(v)[:28]:28s} {speed[mid].mean():6.2f} {var:5.2f} {rms(rise):5.2f} {rms(nod):5.2f} {rms(yaw):5.2f} {tr.sum():6.2f} {tr2.sum():6.2f} {tr[mid].std() / tr[mid].mean():5.2f}'
              f'   (forward at {fw * 360 / W:.0f} deg)')
        if a.steps:
            for k in range(len(speed)):
                print(f'   {k:2d}->{k + 1:2d}  speed {speed[k]:6.2f}  rise {rise[k]:6.2f}  nod {nod[k]:6.2f}  yaw {yaw[k]:6.2f}  travel {tr[k]:6.3f} ({tr2[k]:6.3f})')


if __name__ == '__main__':
    main()
