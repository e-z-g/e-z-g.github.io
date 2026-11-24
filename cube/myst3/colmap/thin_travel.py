"""A walk's frames thinned to one distance a frame (the maintainer's idea, 24 November 2026: render more frames, then
keep those that make the walk move the same distance every frame, at the same speed in every walk). The distance of
each step comes from walk_gait.py --steps (the "travel" column: eye heights, from the floor beside the camera); the
frames kept, the first and last always among them, are chosen together (dynamic programming on the squared misfit of
each kept step to the target), their number from the walk's length over the target.

    python thin_travel.py VIDEO.mp4 TRAVEL.txt --step 0.073 [--frames 39] --out OUT.mp4 [--pad 4]

TRAVEL.txt holds the steps' lengths, space separated (frame 0 to 1, 1 to 2, ...). OUT.mp4 is the kept frames at 24 a
second, every frame a keyframe, the last repeated --pad times (as the viewers want), tagged BT.601. Prints the frames
kept and the kept steps' lengths.
"""
import argparse, subprocess
import numpy as np


def choose(s, m):
    """indices 0 = i0 < ... < im = n-1 into cumulative distances s, m steps, each near (s[-1] / m)"""
    n = len(s); d0 = s[-1] / m
    INF = float('inf'); cost = np.full((m + 1, n), INF); prev = np.zeros((m + 1, n), int); cost[0, 0] = 0
    for j in range(1, m + 1):
        for i in range(j, n):
            c = cost[j - 1, :i] + (s[i] - s[:i] - d0) ** 2
            p = int(np.argmin(c)); cost[j, i] = c[p]; prev[j, i] = p
    idx = [n - 1]
    for j in range(m, 0, -1):
        idx.append(prev[j, idx[-1]])
    return idx[::-1]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('video'); ap.add_argument('travel'); ap.add_argument('--step', type=float, required=True)
    ap.add_argument('--frames', type=int, default=39); ap.add_argument('--out', required=True); ap.add_argument('--pad', type=int, default=4)
    a = ap.parse_args()
    t = np.array([float(x) for x in open(a.travel).read().split()])[:a.frames - 1]
    s = np.concatenate([[0], np.cumsum(t)])
    m = max(1, round(s[-1] / a.step))
    idx = choose(s, m)
    steps = np.diff(s[idx])
    print(f'{len(idx)} of {len(s)} frames kept for {s[-1]:.3f} eye heights at {a.step} a frame: {idx}')
    print('kept steps', ' '.join(f'{x:.3f}' for x in steps), f'(spread {steps.std() / steps.mean() * 100:.0f}%)')
    sel = '+'.join(f'eq(n\\,{i})' for i in idx)
    subprocess.run(['ffmpeg', '-loglevel', 'error', '-y', '-i', a.video, '-vf', f"select='{sel}',setpts=N/24/TB,tpad=stop_mode=clone:stop={a.pad}",
                    '-fps_mode', 'passthrough', '-c:v', 'libx264', '-preset', 'slow', '-crf', '17', '-g', '1', '-pix_fmt', 'yuv420p',
                    '-colorspace', 'smpte170m', '-color_primaries', 'smpte170m', '-color_trc', 'smpte170m', '-color_range', 'tv',
                    '-movflags', '+faststart', a.out], check=True)


if __name__ == '__main__':
    main()
