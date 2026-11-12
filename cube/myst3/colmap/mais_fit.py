#!/usr/bin/env python3
# Run from reference/myst3/scene_mesh (age_v2/views.json); writes mais_layout_c.json for layout_moves.py and warp_model.py.
# MAIS 6-9 moved as one piece (translation only; the cubes' turn is the age's) and MAIS 10, 11 placed, from the game's
# headings (hotspot centres) and the ladder MAIS 30-6 being near vertical; everything else where the model has it.
import json, math, numpy as np
from scipy.optimize import least_squares
v = json.load(open('age_v2/views.json'))
P = {n: np.array([v[n]['pos'][0], v[n]['pos'][2]]) for n in v}
C = ['2006', '2007', '2008', '2009']
H = [('2030', '2006', 176), ('2006', '2030', 359), ('2006', '2011', 164), ('2011', '2006', 344), ('2014', '2011', 287),
     ('2011', '2014', 102), ('2012', '2011', 285), ('2011', '2012', 102), ('2011', '2010', 343), ('2010', '2011', 173),
     ('2010', '2009', 308), ('2009', '2010', 146)]
STEPS = [('2009', '2010'), ('2010', '2011'), ('2011', '2012')]
SIG_H, LADDER, SIG_L = 10.0, 0.5, 0.5
def pos(x):
    p = dict(P); t = x[:2]
    for n in C: p[n] = P[n] + t
    p['2010'] = x[2:4]; p['2011'] = x[4:6]
    return p
def bearing(a, b, p):
    d = p[b] - p[a]; return math.degrees(math.atan2(-d[0], d[1]))
def res(x):
    p = pos(x); r = []
    for a, b, h in H:
        r.append(((bearing(a, b, p) - h + 180) % 360 - 180) / SIG_H)
    for a, b in STEPS:
        r.append((np.linalg.norm(p[a] - p[b]) - 1.0) / 0.4)
    r.append((np.linalg.norm(p['2030'] - p['2006']) - LADDER) / SIG_L)
    return r
best = None
for tx in (-2, 0, 2):
    for tz in (-2, 0, 2):
        x0 = np.r_[tx, tz, (P['2009'] + P['2012']) / 2, (P['2009'] + P['2012']) / 2 + 0.3]
        s = least_squares(res, x0)
        if best is None or s.cost < best.cost: best = s
x = best.x; p = pos(x)
print('C moved by', np.round(x[:2], 2), '%.2f spacings' % np.linalg.norm(x[:2]), 'cost %.2f' % best.cost)
for a, b, h in H:
    print(f'  {a}->{b}: heading {h}, bearing {bearing(a, b, p) % 360:.0f}, dist {np.linalg.norm(p[a] - p[b]):.2f}')
for n in C + ['2010', '2011', '2012', '2014', '2030']:
    print(n, np.round(p[n], 2))
out = {n: p[n].tolist() for n in C + ['2010', '2011']}
json.dump(out, open('mais_layout_c.json', 'w'), indent=1)
