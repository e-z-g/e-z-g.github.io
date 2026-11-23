"""One node_depth.py-form depth (DIR/LE<n>/face<k>_measured-depth.png) with the sky (0) of another laid over it:
for Depth Anything 3's multi-view depth, which gives the sky a finite distance, with MapAnything's sky mask.

    python depth_sky_from.py DEPTH_DIR SKY_DIR OUT_DIR
"""
import os, shutil, sys
import cv2
src, sky, out = sys.argv[1:4]
os.makedirs(out, exist_ok=True)
for f in sorted(os.listdir(src)):
    if not f.endswith('_measured-depth.png'):
        shutil.copy(os.path.join(src, f), os.path.join(out, f)); continue
    d = cv2.imread(os.path.join(src, f), cv2.IMREAD_GRAYSCALE); s = cv2.imread(os.path.join(sky, f), cv2.IMREAD_GRAYSCALE)
    d[s == 0] = 0
    cv2.imwrite(os.path.join(out, f), d)
    print(f, f'sky {(d == 0).mean():.2f}')
