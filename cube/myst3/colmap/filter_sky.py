#!/usr/bin/env python3
"""
Takes sky out of a COLMAP database and model whose node faces were matched
before sky masks existed.

    python filter_sky.py MASKS DB_IN DB_OUT [--model-txt TXT_IN TXT_OUT] [--min-matches 15]

MASKS holds sky_masks.py's masks (<image name>.png, black = sky, sea, water). In
a copy of the database every verified match (two_view_geometries) with either
keypoint on black in its image's mask is dropped; a pair left with fewer than
--min-matches is deleted, except that an image left with no pair at all keeps
its best one as it was: the mapper crashed on such an image of the model (exit
0xC0000409, no message), also when only pairs between two images of the model
were kept so (13 images then still had none). With --model-txt, a text model (images.txt,
points3D.txt and the rest) is copied with every 3D point dropped whose
observations in masked images lie at least half on black; convert it back to
binary with model_converter.

Why: sky_masks.py kept the movies' features off the sky, but the node faces were
matched with one another long before, and those matches still held cloud points.
Registering the flyover with them placed MAWW 1, MASS 57, MATO 7 and MATO 10 on
some twenty cloud points each, two pairs of nodes 0.17 and 0.49 apart that look
at quite different places. Needs numpy and Pillow.
"""
import argparse
import os
import shutil
import sqlite3

import numpy as np
from PIL import Image

PAIR = 2147483647


class Masks:
    def __init__(self, root):
        self.root, self.cache = root, {}

    def get(self, name):
        if name not in self.cache:
            p = os.path.join(self.root, name + '.png')
            self.cache[name] = np.asarray(Image.open(p).convert('L')) < 128 if os.path.exists(p) else None
        return self.cache[name]

    def sky(self, name, xy):
        m = self.get(name)
        if m is None:
            return None
        h, w = m.shape
        x = np.clip(xy[:, 0].astype(int), 0, w - 1); y = np.clip(xy[:, 1].astype(int), 0, h - 1)
        return m[y, x]


def filter_db(masks, src, dst, min_matches):
    shutil.copyfile(src, dst)
    db = sqlite3.connect(dst)
    names = dict(db.execute('select image_id, name from images'))
    sky = {}
    for i, r, c, d in db.execute('select image_id, rows, cols, data from keypoints'):
        if d is None or r == 0:
            continue
        s = masks.sky(names[i], np.frombuffer(d, np.float32).reshape(r, c)[:, :2])
        if s is not None:
            sky[i] = s
    pairs = db.execute('select pair_id, rows, data from two_view_geometries where rows > 0').fetchall()
    kept = dropped = 0
    best = {}     # image -> (matches, pair) before filtering
    update = {}   # pair -> filtered matches, for pairs that lose any
    gone = set()  # pairs left under min_matches
    for pid, r, d in pairs:
        i, j = pid // PAIR, pid % PAIR
        for k in (i, j):
            if r > best.get(k, (0, None))[0]:
                best[k] = (r, pid)
        if i not in sky and j not in sky:
            kept += r
            continue
        m = np.frombuffer(d, np.uint32).reshape(r, 2)
        bad = np.zeros(r, bool)
        if i in sky:
            bad |= sky[i][m[:, 0]]
        if j in sky:
            bad |= sky[j][m[:, 1]]
        if len(m) - bad.sum() < min_matches:
            gone.add(pid)
        elif bad.any():
            update[pid] = np.ascontiguousarray(m[~bad])
        kept += r - int(bad.sum()); dropped += int(bad.sum())
    # An image of the model left with no pair at all crashes the mapper (exit
    # 0xC0000409, no message), so such an image keeps its best pair as it was.
    left = {}
    for pid, r, d in pairs:
        if pid not in gone:
            for k in (pid // PAIR, pid % PAIR):
                left[k] = left.get(k, 0) + 1
    restored = []
    for k, (r, pid) in sorted(best.items()):
        if not left.get(k) and pid in gone:
            gone.discard(pid); update.pop(pid, None); restored.append(names[k])
            for kk in (pid // PAIR, pid % PAIR):
                left[kk] = left.get(kk, 0) + 1
    for pid, m2 in update.items():
        db.execute('update two_view_geometries set rows = ?, data = ? where pair_id = ?', (len(m2), m2.tobytes(), pid))
    for pid in gone:
        db.execute('delete from two_view_geometries where pair_id = ?', (pid,))
    print(f'database: {len(sky)} images with masks; verified matches {kept} kept, {dropped} on sky dropped; '
          f'{len(gone)} of {len(pairs)} pairs left under {min_matches} and deleted')
    if restored:
        print(f'database: {len(restored)} images would have had no pair left and keep their best one unfiltered: '
              + ', '.join(restored[:12]) + (' ...' if len(restored) > 12 else ''))
    db.commit(); db.execute('vacuum'); db.close()


def filter_model(masks, src, dst):
    os.makedirs(dst, exist_ok=True)
    for f in os.listdir(src):
        if f not in ('images.txt', 'points3D.txt'):
            shutil.copyfile(os.path.join(src, f), os.path.join(dst, f))
    votes = {}  # point id -> [observations in masked images, of which on sky]
    with open(os.path.join(src, 'images.txt')) as f:
        head, name = True, None
        for line in f:
            if line.startswith('#'):
                continue
            if head:
                name = line.split()[9]
            else:
                a = np.array(line.split(), float).reshape(-1, 3)
                a = a[a[:, 2] >= 0]
                s = masks.sky(name, a[:, :2]) if len(a) else None
                if s is not None:
                    for pid, on in zip(a[:, 2].astype(np.int64), s):
                        v = votes.setdefault(int(pid), [0, 0]); v[0] += 1; v[1] += int(on)
            head = not head
    drop = {p for p, (n, k) in votes.items() if 2 * k >= n}
    with open(os.path.join(src, 'images.txt')) as f, open(os.path.join(dst, 'images.txt'), 'w', newline='\n') as g:
        head = True
        for line in f:
            if line.startswith('#'):
                g.write(line); continue
            if head:
                g.write(line)
            else:
                p = line.split()
                for k in range(2, len(p), 3):
                    if p[k] != '-1' and int(p[k]) in drop:
                        p[k] = '-1'
                g.write(' '.join(p) + '\n')
            head = not head
    total = 0
    with open(os.path.join(src, 'points3D.txt')) as f, open(os.path.join(dst, 'points3D.txt'), 'w', newline='\n') as g:
        for line in f:
            if line.startswith('#'):
                g.write(line); continue
            total += 1
            if int(line.split(None, 1)[0]) not in drop:
                g.write(line)
    print(f'model: {len(drop)} of {total} points dropped as sky ({len(votes)} seen in masked images)')


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('masks'); ap.add_argument('db_in'); ap.add_argument('db_out')
    ap.add_argument('--model-txt', nargs=2, metavar=('TXT_IN', 'TXT_OUT'))
    ap.add_argument('--min-matches', type=int, default=15)
    a = ap.parse_args()
    masks = Masks(a.masks)
    filter_db(masks, a.db_in, a.db_out, a.min_matches)
    if a.model_txt:
        filter_model(masks, *a.model_txt)


if __name__ == '__main__':
    main()
