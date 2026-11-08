#!/usr/bin/env python3
"""
Depths in one face from its verified matches with one other face, by two-view
geometry alone: for a node no model has placed, but which shares something near
with another node (MAWW 1 and MAWW 2 stand on the same moving platform).

    python pair_points.py DATABASE FACE OTHER OUT.txt [--focal 320] [--size 640]

DATABASE is a COLMAP database with both faces matched and verified (features from
feature_extractor, matches from a matcher). The inlier matches give an essential
matrix (OpenCV, RANSAC), the relative pose and, by triangulation, a 3D point for
each match, in FACE's camera, at an arbitrary scale (the baseline is 1). Points
behind either camera or seen at under --min-angle degrees between the two rays are
dropped. OUT.txt has one line per point: face pixel x, y and depth z, for
node_depth.py --pair-depths, which needs depths only up to scale.
Needs numpy and opencv-python.
"""
import argparse
import sqlite3

import cv2
import numpy as np

PAIR = 2147483647


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('db'); ap.add_argument('face'); ap.add_argument('other'); ap.add_argument('out')
    ap.add_argument('--focal', type=float, default=320.0); ap.add_argument('--size', type=int, default=640)
    ap.add_argument('--min-angle', type=float, default=0.5)
    a = ap.parse_args()
    db = sqlite3.connect(a.db)
    ids = {n: i for i, n in db.execute('select image_id, name from images')}
    i, j = ids[a.face], ids[a.other]
    lo, hi = min(i, j), max(i, j)
    rows, data = db.execute('select rows, data from two_view_geometries where pair_id = ?',
                            (lo * PAIR + hi,)).fetchone()
    m = np.frombuffer(data, np.uint32).reshape(rows, 2)
    if i > j:
        m = m[:, ::-1]

    def kps(k):
        r, c, d = db.execute('select rows, cols, data from keypoints where image_id = ?', (k,)).fetchone()
        return np.frombuffer(d, np.float32).reshape(r, c)[:, :2].astype(np.float64)
    p1, p2 = kps(i)[m[:, 0]], kps(j)[m[:, 1]]
    K = np.array([[a.focal, 0, a.size / 2], [0, a.focal, a.size / 2], [0, 0, 1]])
    E, inl = cv2.findEssentialMat(p1, p2, K, cv2.RANSAC, 0.999, 1.5)
    n, R, t, inl2 = cv2.recoverPose(E, p1, p2, K, mask=inl.copy())
    good = inl2.ravel() > 0
    P1 = K @ np.hstack([np.eye(3), np.zeros((3, 1))]); P2 = K @ np.hstack([R, t])
    X = cv2.triangulatePoints(P1, P2, p1[good].T, p2[good].T)
    X = (X[:3] / X[3]).T
    z1 = X[:, 2]; z2 = (X @ R.T + t.ravel())[:, 2]
    c2 = -R.T @ t.ravel()
    r1 = X; r2 = X - c2
    ang = np.degrees(np.arccos(np.clip(np.sum(r1 * r2, 1) / (np.linalg.norm(r1, axis=1) * np.linalg.norm(r2, axis=1)), -1, 1)))
    keep = (z1 > 0) & (z2 > 0) & (ang >= a.min_angle)
    # reprojection error in FACE
    pr = (X[keep] @ K.T); pr = pr[:, :2] / pr[:, 2:]
    err = np.linalg.norm(pr - p1[good][keep], axis=1)
    with open(a.out, 'w', newline='\n') as fh:
        for (x, y), z in zip(p1[good][keep], z1[keep]):
            fh.write(f'{x:.2f} {y:.2f} {z:.5f}\n')
    print(f'{rows} verified matches, {int(inl.sum())} essential-matrix inliers, {int(good.sum())} in front; '
          f'{int(keep.sum())} kept (angle >= {a.min_angle} deg): angle median {np.median(ang[keep]):.1f} deg, '
          f'depth {np.percentile(z1[keep], 10):.2f}-{np.percentile(z1[keep], 90):.2f} baselines (10-90%), '
          f'reprojection median {np.median(err):.2f} px; the other camera at {np.round(c2, 3)} (FACE camera axes)')


if __name__ == '__main__':
    main()
