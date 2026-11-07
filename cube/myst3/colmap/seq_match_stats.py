"""Frame-to-frame verified matches along a movie, from a COLMAP database.

    python seq_match_stats.py DATABASE.db

Shows where a movie breaks (motion blur, a cut): stretches of frames with few
matches to the next."""
import sqlite3, sys, numpy as np
db = sqlite3.connect(sys.argv[1])
names = dict(db.execute('select image_id, name from images'))
kp = dict(db.execute('select image_id, rows from keypoints'))
idx = {n: i for i, n in names.items()}
order = sorted(names.values())
pos = {n: k for k, n in enumerate(order)}
tv = {}
for p, n in db.execute('select pair_id, rows from two_view_geometries'):
    a, b = p // 2147483647, p % 2147483647
    tv[(min(pos[names[a]], pos[names[b]]), max(pos[names[a]], pos[names[b]]))] = n
nxt = [tv.get((k, k + 1), 0) for k in range(len(order) - 1)]
nxt = np.array(nxt)
kps = np.array([kp[idx[n]] for n in order])
print('frames', len(order), 'keypoints per frame: median', int(np.median(kps)), '10%', int(np.percentile(kps, 10)))
print('verified matches to the next frame: median', int(np.median(nxt)), '; frames with under 30:', int((nxt < 30).sum()))
for s in range(0, len(nxt), 150):
    print(f'  frames {s+1:4d}-{s+150:4d}: median next-frame matches {int(np.median(nxt[s:s+150])):4d}, min {int(nxt[s:s+150].min())}')
