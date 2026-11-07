#!/usr/bin/env python3
"""
Which way do Myst III's hotspot headings turn? Measure it from the pictures.

    python heading_check.py FACES_DIR ROOM_JSON [--max-links N]

ScummVM's camera is the rotation 180 - heading about y
(Renderer::setupCameraPerspective), stored row by row and loaded with
glLoadMatrixf, which reads column by column; worked through, heading h looks
along (-sin h, 0, cos h) in the cube frame of face_geometry.py: 0 back, 90 left,
180 front, 270 right, increasing clockwise seen from above. The mirror reading
would be (sin h, 0, cos h). This script tells them apart without trusting
either derivation.

For each walk or zip from node A to node B it matches SIFT features between
the two nodes' six faces, turns them into viewing directions, and solves for
the direction of travel t. Every node shares one world orientation, so the
rotation between A and B is the identity and each match (a, b) only has to
satisfy t . (a x b) = 0; two matches fix t, RANSAC picks the best, and the
sign is the one that puts the matched points in front of both nodes. The
horizontal angle of t is then read as a heading both ways and compared with
the hotspot's own heading. Its vertical angle is how steeply the walk climbs
or falls, which the age maps do not have.

Needs numpy, Pillow and opencv-python.
"""
import json
import math
import os
import sys

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from face_geometry import FACES, face_dir  # noqa: E402


def features(faces_dir, room, node, sift):
    dirs, descs = [], []
    for f in FACES:
        img = cv2.imread(os.path.join(faces_dir, room, f'{room}-{node:04d}-f{f}.jpg'), cv2.IMREAD_GRAYSCALE)
        kps, d = sift.detectAndCompute(img, None)
        if d is None:
            continue
        n = img.shape[0]
        for k in kps:
            v = np.array(face_dir(f, k.pt[0] / n, k.pt[1] / n), float)
            dirs.append(v / np.linalg.norm(v))
        descs.append(d)
    return np.array(dirs), np.vstack(descs)


def match(d1, d2, ratio=0.75):
    m = cv2.BFMatcher(cv2.NORM_L2).knnMatch(d1, d2, k=2)
    return [(a.queryIdx, a.trainIdx) for a, b in (p for p in m if len(p) == 2) if a.distance < ratio * b.distance]


def solve_t(a, b, iters=2000, thr_deg=0.5, rng=np.random.default_rng(0)):
    """Direction of travel from A to B, given matched unit bearings a (from A) and b (from B)."""
    n = np.cross(a, b)
    norms = np.linalg.norm(n, axis=1)
    keep = norms > 1e-4           # matches far away (a = b) say nothing about t
    n, a, b = n[keep] / norms[keep, None], a[keep], b[keep]
    if len(n) < 8:
        return None
    thr = math.sin(math.radians(thr_deg))
    best = None
    for _ in range(iters):
        i, j = rng.choice(len(n), 2, replace=False)
        t = np.cross(n[i], n[j])
        if np.linalg.norm(t) < 1e-6:
            continue
        t /= np.linalg.norm(t)
        inl = np.abs(n @ t) < thr
        if best is None or inl.sum() > best[1].sum():
            best = (t, inl)
    t, inl = best
    _, _, vt = np.linalg.svd(n[inl])     # refine: the direction most nearly perpendicular to every n
    t = vt[-1]
    # sign: A sees X along a at distance la, B along b at lb, with la a = t + lb b
    la_lb = [np.linalg.lstsq(np.stack([ai, -bi], 1), t, rcond=None)[0] for ai, bi in zip(a[inl], b[inl])]
    front = sum(1 for la, lb in la_lb if la > 0 and lb > 0)
    back = sum(1 for la, lb in la_lb if la < 0 and lb < 0)
    if back > front:
        t = -t
    return t, int(inl.sum()), len(n), max(front, back) / max(1, front + back)


def ang(d):
    return (d + 180) % 360 - 180


def main():
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    faces_dir, room_json = sys.argv[1], sys.argv[2]
    max_links = int(sys.argv[sys.argv.index('--max-links') + 1]) if '--max-links' in sys.argv else 10 ** 9
    data = json.load(open(room_json))
    room = data['room']
    have = {int(x.split('-')[1]) for x in os.listdir(os.path.join(faces_dir, room)) if x.endswith('-f1.jpg')}
    links = [l for l in data['links'] if l['kind'] in ('walk', 'zip') and l['args']
             and l['from'] in have and l['args'][0] in have and l['from'] != l['args'][0]][:max_links]
    sift = cv2.SIFT_create(nfeatures=4000)
    cache = {}
    rows = []
    print('from  to  kind  heading  | measured as heading: this way  mirrored | climb  inliers/matches  in front')
    for l in links:
        a, b = l['from'], l['args'][0]
        for n in (a, b):
            if n not in cache:
                cache[n] = features(faces_dir, room, n, sift)
        (da, fa), (db, fb) = cache[a], cache[b]
        m = match(fa, fb)
        if len(m) < 8:
            print(f'{a:4d} {b:4d}  {l["kind"]:4s}  {l["heading"]:5d}    too few matches ({len(m)})')
            continue
        r = solve_t(da[[i for i, _ in m]], db[[j for _, j in m]])
        if r is None:
            print(f'{a:4d} {b:4d}  {l["kind"]:4s}  {l["heading"]:5d}    too few usable matches')
            continue
        t, ninl, nm, front = r
        h_this = math.degrees(math.atan2(-t[0], t[2])) % 360     # (-sin h, 0, cos h)
        h_mirror = math.degrees(math.atan2(t[0], t[2])) % 360    # (sin h, 0, cos h)
        climb = math.degrees(math.asin(max(-1, min(1, t[1]))))
        e1, e2 = ang(h_this - l['heading']), ang(h_mirror - l['heading'])
        rows.append((abs(e1), abs(e2), ninl / nm))
        print(f'{a:4d} {b:4d}  {l["kind"]:4s}  {l["heading"]:5d}    | {h_this:6.1f} ({e1:+6.1f})  {h_mirror:6.1f} ({e2:+6.1f}) '
              f'| {climb:+5.1f}  {ninl:4d}/{nm:<5d}  {front:.2f}')
    if rows:
        e1 = sorted(r[0] for r in rows); e2 = sorted(r[1] for r in rows)
        print(f'{len(rows)} links. Heading error, median and 90th percentile: this way {e1[len(e1) // 2]:.1f} / '
              f'{e1[int(len(e1) * 0.9)]:.1f} deg; mirrored {e2[len(e2) // 2]:.1f} / {e2[int(len(e2) * 0.9)]:.1f} deg')


if __name__ == '__main__':
    main()
