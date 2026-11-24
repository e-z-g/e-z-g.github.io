"""How far a walk's picture moves at each step: median DIS flow between consecutive frames, per eye of the two-fisheye
layout (W = 2H), and in the lower half of the frame where the ground usually is.  python step_sizes.py FRAMES_DIR"""
import sys, glob
import numpy as np, cv2
paths = sorted(glob.glob(sys.argv[1] + '/*.png'))
dis = cv2.DISOpticalFlow_create(cv2.DISOPTICAL_FLOW_PRESET_MEDIUM)
prev = cv2.cvtColor(cv2.imread(paths[0]), cv2.COLOR_BGR2GRAY); H = prev.shape[0]; rows = []
for k in range(1, len(paths)):
    cur = cv2.cvtColor(cv2.imread(paths[k]), cv2.COLOR_BGR2GRAY); m = []
    for e in (0, 1):
        f = dis.calc(np.ascontiguousarray(prev[:, e * H:(e + 1) * H]), np.ascontiguousarray(cur[:, e * H:(e + 1) * H]), None)
        mag = np.hypot(f[..., 0], f[..., 1]); m += [np.median(mag), np.median(mag[H // 2:])]
    rows.append(m); prev = cur
    print(f'{k - 1:2d}->{k:2d}: front {m[0]:5.1f} (lower half {m[1]:5.1f})  back {m[2]:5.1f} (lower half {m[3]:5.1f})')
r = np.array(rows); mid = np.median(r[2:-2], axis=0)
print('first step / median of the middle steps: front %.2f back %.2f; last step: front %.2f back %.2f' % (r[0, 0] / mid[0], r[0, 2] / mid[2], r[-1, 0] / mid[0], r[-1, 2] / mid[2]))
