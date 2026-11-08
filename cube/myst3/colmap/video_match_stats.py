"""Verified matches between a movie's frames and node faces in a COLMAP database.

    python video_match_stats.py DATABASE.db TAG [IMAGES.txt]

Prints, per frame with any, its three best node faces; with IMAGES.txt (a model
as text) also which frames it registered."""
import sqlite3, sys, collections
db = sqlite3.connect(sys.argv[1]); tag = sys.argv[2]
names = dict(db.execute('select image_id, name from images'))
def pid(p):
    return p // 2147483647, p % 2147483647
rows = db.execute('select pair_id, rows from two_view_geometries where rows > 0').fetchall()
best = collections.defaultdict(list)
for p, n in rows:
    a, b = pid(p); na, nb = names.get(a, ''), names.get(b, '')
    if na.startswith(tag + '/') != nb.startswith(tag + '/'):
        fr, fc = (na, nb) if na.startswith(tag + '/') else (nb, na)
        best[fr].append((n, fc))
print(len(best), 'frames with any verified match to a node face')
for fr in sorted(best):
    top = sorted(best[fr], reverse=True)[:3]
    print(fr, ' '.join(f'{fc}:{n}' for n, fc in top))
reg = [l.split()[-1] for l in open(sys.argv[3]) if (' ' + tag + '/') in l] if len(sys.argv) > 3 else []
print('registered:', reg)
