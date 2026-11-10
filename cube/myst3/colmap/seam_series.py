"""Frame by frame, how well two cells of a walk_ends.py --cross-floor video meet along their shared edge: the mean
difference between the 2 px strips either side of it (0-255). The front wall's edge toward the sky (where MASS 84's
roof and its insignia cross) and the floor's edge to the front wall."""
import sys
import cv2
import numpy as np
cap = cv2.VideoCapture(sys.argv[1]); out = []
while True:
    r, f = cap.read()
    if not r:
        break
    f = f.astype(np.float32); H, W = f.shape[:2]; c, h = W // 4, H // 3
    cell = lambda i, j: f[i * h:(i + 1) * h, j * c:(j + 1) * c]
    out.append((np.abs(cell(1, 2)[:, -2:] - cell(1, 3)[:, :2]).mean(), np.abs(cell(1, 1)[:, -2:] - cell(1, 2)[:, :2]).mean()))
s = np.array(out)
for i, name in enumerate(('front|sky', 'floor|front')):
    x = s[:, i]
    print(f'{name:12s} start {x[0]:5.1f} end {x[-1]:5.1f}  median {np.median(x):5.1f}  worst {x.max():5.1f} at frame {x.argmax()}  frames over twice the start: {(x > 2 * x[0]).sum()} of {len(x)}')
