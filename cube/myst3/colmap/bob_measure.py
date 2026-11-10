"""Bobbing in a cube-cross walk video (walk_ends.py --cross / --cross-floor, 4x3 cells): for each face, the shift
between consecutive frames by phase correlation; the bob is that shift less its own running mean over 9 frames
(the steady drift a forward move gives). Prints each face's bob (RMS, px of a 256 px face) and how far the faces
disagree with each other frame by frame."""
import sys
import cv2
import numpy as np

CELLS = {'cross-floor': {'back': (1, 0), 'floor': (1, 1), 'front': (1, 2), 'sky': (1, 3), 'left': (0, 1), 'right': (2, 1)}}
path = sys.argv[1]; cells = CELLS[sys.argv[2] if len(sys.argv) > 2 else 'cross-floor']
cap = cv2.VideoCapture(path); prev = None; shifts = {k: [] for k in cells}
win = cv2.createHanningWindow((256, 256), cv2.CV_32F)
while True:
    r, f = cap.read()
    if not r:
        break
    g = cv2.cvtColor(f, cv2.COLOR_BGR2GRAY).astype(np.float32)
    H, W = g.shape; cw, ch = W // 4, H // 3
    faces = {k: cv2.resize(g[r0 * ch:(r0 + 1) * ch, c0 * cw:(c0 + 1) * cw], (256, 256)) for k, (r0, c0) in cells.items()}
    if prev is not None:
        for k in cells:
            (dx, dy), _ = cv2.phaseCorrelate(prev[k], faces[k], win)
            shifts[k].append((dx, dy))
    prev = faces
bob = {}
for k, s in shifts.items():
    s = np.array(s)
    trend = np.stack([np.convolve(s[:, i], np.ones(9) / 9, mode='same') for i in range(2)], 1)
    bob[k] = s - trend
    print(f'{k:6s} bob RMS {np.sqrt((bob[k] ** 2).sum(1).mean()):.2f} px')
mag = np.stack([np.sqrt((b ** 2).sum(1)) for b in bob.values()])
print(f'all faces: bob RMS {np.sqrt((mag ** 2).mean()):.2f} px; frames with any face jolting over 2 px: {(mag.max(0) > 2).sum()} of {mag.shape[1]}')
