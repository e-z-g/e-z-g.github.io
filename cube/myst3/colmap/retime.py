"""Frame times for a walk from its measured motion, so it plays at an even speed and eases in and out at the ends:
each step (frame k to k+1) is shown for a time proportional to how far the picture moves in it (median DIS flow over
both eyes of the two-fisheye layout), at the speed of the middle steps played at --fps, and the first and last --ease
steps are slowed by a smooth ramp (to --start of full speed at the ends). Writes ffmpeg concat lists for the forward and
reversed videos and a times file for the viewer.

    python retime.py FRAMES_DIR OUT_PREFIX [--fps 24] [--ease 4] [--start 0.35]

OUT_PREFIX_fwd.vf, OUT_PREFIX_back.vf: ffmpeg -framerate 24 -i FRAMES_DIR/%04d.png -filter_script:v VF -fps_mode passthrough
  -enc_time_base 1/90000 -video_track_timescale 90000 ... (the concat lists, OUT_PREFIX_fwd.txt and _back.txt, round to 1/25 s)
OUT_PREFIX_times.json: {"fwd": [start of each frame, s], "back": [...], "dur": [each frame's time, forward order]}
"""
import argparse, glob, json, os
import numpy as np, cv2


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('frames'); ap.add_argument('out')
    ap.add_argument('--fps', type=float, default=24); ap.add_argument('--ease', type=int, default=4); ap.add_argument('--start', type=float, default=0.35)
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
    step = np.array(step); v = np.median(step[2:-2]) * a.fps                   # px per second: the middle steps at --fps
    ramp = np.ones(n - 1)
    for i in range(min(a.ease, (n - 1) // 2)):                                 # smoothstep from --start to 1 over --ease steps
        x = (i + 0.5) / a.ease; e = a.start + (1 - a.start) * x * x * (3 - 2 * x)
        ramp[i] = min(ramp[i], e); ramp[n - 2 - i] = min(ramp[n - 2 - i], e)
    d = np.maximum(step, 1e-3) / v / ramp                                       # each step's time
    d = np.maximum(d, 1 / 60)                                                   # no step shorter than a 60 Hz refresh
    dur = np.append(d, 1 / a.fps)                                              # the last frame: one tick
    fwd = np.concatenate([[0], np.cumsum(dur[:-1])])
    rdur = dur[::-1][1:].tolist() + [1 / a.fps]                                # the reversed walk: step k's time between the same two frames
    back = np.concatenate([[0], np.cumsum(rdur[:-1])])
    for name, order, durs in (('fwd', list(range(n)), dur.tolist()), ('back', list(range(n))[::-1], rdur)):
        with open(f'{a.out}_{name}.txt', 'w') as f:
            for k, t in zip(order, durs): f.write(f"file '{os.path.abspath(paths[k]).replace(os.sep, "/")}'\nduration {t:.6f}\n")
            f.write(f"file '{os.path.abspath(paths[order[-1]]).replace(os.sep, "/")}'\n")
    for name, st, rev in (('fwd', fwd, ''), ('back', back, 'reverse,')):     # ffmpeg -filter_script:v: each frame's time by its number
        open(f'{a.out}_{name}.vf', 'w').write(rev + 'settb=1/90000,setpts=(' + '+'.join(f'eq(N\\,{k})*{t:.6f}' for k, t in enumerate(st)) + ')/TB')
    json.dump({'fwd': [round(x, 6) for x in fwd], 'back': [round(x, 6) for x in back], 'dur': [round(x, 6) for x in dur]}, open(f'{a.out}_times.json', 'w'))
    print('steps (px):', ' '.join(f'{x:.0f}' for x in step))
    print('times (ms):', ' '.join(f'{x * 1000:.0f}' for x in d))
    print(f'{n} frames, {fwd[-1] + dur[-1]:.2f} s (at an even {a.fps:g} fps: {n / a.fps:.2f} s); middle speed {v:.0f} px/s')


if __name__ == '__main__':
    main()
