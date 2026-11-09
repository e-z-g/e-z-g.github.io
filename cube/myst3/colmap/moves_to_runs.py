#!/usr/bin/env python3
"""
A moved workspace's moves.json (apply_moves.py's record, per node) regrouped by
run in node_align.py --runs form, so the same moves can be applied to another
dense workspace of the same model (one with more movie frames).

    python moves_to_runs.py MOVES.json OUT.json [--frames RUN PREFIX SPARSE_TXT ...]

With --frames, the movie frames whose names start with PREFIX join RUN, moved
by the similarity fitted to the run's nodes' old centres (from SPARSE_TXT) and
new ones: frames registered while the run was misplaced sit where the run was
(MASS 11090's frames, registered among MASS 82-90). Needs numpy; view_check.py
beside it.
"""
import json, sys, os, argparse
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from view_check import read_model
ap = argparse.ArgumentParser(); ap.add_argument('moves'); ap.add_argument('out')
ap.add_argument('--frames', nargs=3, action='append', default=[], metavar=('RUN', 'PREFIX', 'SPARSE_TXT'))
a = ap.parse_args()
d = json.load(open(a.moves))
runs = {}
for n, v in d.items():
    r = runs.setdefault(v['run'], {'members': [], 'new_centres': {}, 'scale': v['depth_scale'], 'rot': v['rot'], 'kept': True, 'trusted': False})
    r['members'].append(n); r['new_centres'][n] = v['new']
for run, prefix, txt in a.frames:
    _, imgs = read_model(txt)
    c = lambda n: -imgs[n][0].T @ imgs[n][1]
    r = runs[run]
    old = np.array([c(f'f1/{m}.jpg') for m in r['members']]); new = np.array([r['new_centres'][m] for m in r['members']])
    mo, mn = old.mean(0), new.mean(0)
    U, S, Vt = np.linalg.svd((new - mn).T @ (old - mo))
    D = np.diag([1, 1, np.sign(np.linalg.det(U @ Vt))])
    Rs = U @ D @ Vt
    s = np.trace(np.diag(S) @ D) / ((old - mo) ** 2).sum()
    resid = np.linalg.norm((s * (old - mo) @ Rs.T + mn) - new, axis=1)
    print(f'{run}: similarity scale {s:.4f} (run says {r["scale"]:.4f}), node residual max {resid.max():.4f}')
    n_f = 0
    for name in imgs:
        if name.startswith(prefix):
            r['members'].append(name); r['new_centres'][name] = (s * Rs @ (c(name) - mo) + mn).tolist(); n_f += 1
    print(f'  {n_f} frames {prefix}* join {run}')
json.dump(runs, open(a.out, 'w'), indent=1)
print({k: len(v['members']) for k, v in runs.items()})
