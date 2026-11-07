#!/usr/bin/env python3
"""
Depth maps by stereo for one node's six faces only, from a finished sparse model,
without running patch_match_stereo on every image.

    python node_stereo.py IMAGES SPARSE SPARSE_TXT WORK NODE [NODE ...] [--top 20] [--min-angle 1]
                          [--colmap C:\\colmap\\4.2.1\\COLMAP.bat]

IMAGES is the folder the model's image names are relative to (f1..f6, movie
frames); SPARSE the model (binary), SPARSE_TXT the same as text; NODE a node id
as in the face names (5001 for f1/MA-5001.jpg).

1. image_undistorter lays out WORK as run_dense.ps1 does (skipped if WORK/images
   exists); the faces and movie frames are pinhole views, so this only copies.
2. Each face's stereo sources: the images sharing the most sparse points with it
   (at most --top), among those whose rays to the shared points meet the face's at
   --min-angle degrees or more (75th percentile, COLMAP's own rule for its
   __auto__ choice). Faces of the same node are never sources: they share its
   centre and so give no parallax.
3. patch_match_stereo, photometric, for the faces and every source (each source
   with __auto__ sources of its own): the geometric pass reads its sources'
   photometric maps.
4. patch_match_stereo with geometric consistency for the node's faces alone.
WORK/stereo/depth_maps/<face>.geometric.bin are the results, as in a full dense
run (depth_fill.py and node_depth.py read them). WORK/sources.json lists each
face's sources with shared points and angle. Standard library and numpy.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from evaluate_model import qvec2rot  # noqa: E402


def read_model(txt):
    images, pts = {}, {}
    with open(os.path.join(txt, 'images.txt')) as fh:
        lines = [l for l in fh if not l.startswith('#')]
    for head in lines[::2]:
        p = head.split()
        if len(p) < 10:
            continue
        R = qvec2rot([float(v) for v in p[1:5]]); t = np.array([float(v) for v in p[5:8]])
        images[int(p[0])] = {'name': p[-1], 'centre': -R.T @ t}
    with open(os.path.join(txt, 'points3D.txt')) as fh:
        for l in fh:
            if l.startswith('#'):
                continue
            p = l.split()
            pts[int(p[0])] = (np.array([float(v) for v in p[1:4]]), {int(v) for v in p[8::2]})
    return images, pts


def run(colmap, args, log):
    t0 = time.time()
    with open(log, 'w') as fh:
        code = subprocess.call([colmap] + args, stdout=fh, stderr=subprocess.STDOUT)
    print(f'{os.path.basename(log):34s} exit {code}  {time.time() - t0:5.0f} s', flush=True)
    if code:
        sys.exit(open(log).read()[-2000:])


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('images'); ap.add_argument('sparse'); ap.add_argument('sparse_txt'); ap.add_argument('work')
    ap.add_argument('nodes', nargs='+', type=int)
    ap.add_argument('--top', type=int, default=20)
    ap.add_argument('--min-angle', type=float, default=1.0)
    ap.add_argument('--colmap', default=r'C:\colmap\4.2.1\COLMAP.bat')
    a = ap.parse_args()
    logs = os.path.join(a.work, 'logs')
    os.makedirs(logs, exist_ok=True)
    if not os.path.isdir(os.path.join(a.work, 'images')):
        run(a.colmap, ['image_undistorter', '--image_path', a.images, '--input_path', a.sparse,
                       '--output_path', a.work, '--output_type', 'COLMAP'], os.path.join(logs, '1-image_undistorter.log'))

    images, pts = read_model(a.sparse_txt)
    by_name = {v['name']: k for k, v in images.items()}
    per_image = {}
    for pid, (_, track) in pts.items():
        for i in track:
            per_image.setdefault(i, set()).add(pid)
    targets = [m for n in a.nodes for k in range(1, 7)
               for m in sorted(by_name) if re.fullmatch(rf'f{k}/(.*-)?{n}\.jpg', m)]
    if not targets:
        sys.exit(f'no faces of nodes {a.nodes} in the model')
    chosen, report = {}, {}
    for name in targets:
        i = by_name[name]; c = images[i]['centre']
        own = re.search(r'-(\d+)\.jpg$', name).group(1)
        count = {}
        for pid in per_image.get(i, ()):
            for j in pts[pid][1]:
                if j != i:
                    count.setdefault(j, []).append(pid)
        cands = []
        for j, shared in count.items():
            nj = images[j]['name']
            if re.search(rf'^f\d/.*-{own}\.jpg$', nj):
                continue                                  # same centre, no parallax
            X = np.array([pts[p][0] for p in shared])
            r1 = X - c; r2 = X - images[j]['centre']
            cos = np.sum(r1 * r2, 1) / (np.linalg.norm(r1, axis=1) * np.linalg.norm(r2, axis=1))
            ang = float(np.degrees(np.percentile(np.arccos(np.clip(cos, -1, 1)), 75)))
            if ang >= a.min_angle:
                cands.append((len(shared), ang, nj))
        cands.sort(reverse=True)
        chosen[name] = [n for _, _, n in cands[:a.top]]
        report[name] = {'points': len(per_image.get(i, ())),
                        'sources': [{'name': n, 'shared': s, 'angle': round(g, 2)} for s, g, n in cands[:a.top]]}
        print(f'{name}: {len(per_image.get(i, ()))} sparse points, {len(cands)} usable sources, '
              f'top {len(chosen[name])}: ' + ', '.join(f'{n} ({s})' for s, _, n in cands[:5]), flush=True)
    with open(os.path.join(a.work, 'sources.json'), 'w') as fh:
        json.dump(report, fh, indent=1)
    targets = [t for t in targets if chosen.get(t)]
    sources = sorted({s for t in targets for s in chosen[t]} - set(targets))
    cfg = os.path.join(a.work, 'stereo', 'patch-match.cfg')
    if not os.path.exists(cfg + '.all'):
        shutil.copyfile(cfg, cfg + '.all')                # image_undistorter's own (every image, __auto__)
    with open(cfg, 'w', newline='\n') as fh:
        for t in targets:
            fh.write(f'{t}\n{", ".join(chosen[t])}\n')
        for s in sources:
            fh.write(f'{s}\n__auto__, {a.top}\n')
    print(f'{len(targets)} faces, {len(sources)} sources', flush=True)
    run(a.colmap, ['patch_match_stereo', '--workspace_path', a.work, '--workspace_format', 'COLMAP',
                   '--PatchMatchStereo.geom_consistency', 'false', '--PatchMatchStereo.allow_missing_files', 'true'],
        os.path.join(logs, '2-photometric.log'))
    with open(cfg, 'w', newline='\n') as fh:
        for t in targets:
            fh.write(f'{t}\n{", ".join(chosen[t])}\n')
    run(a.colmap, ['patch_match_stereo', '--workspace_path', a.work, '--workspace_format', 'COLMAP',
                   '--PatchMatchStereo.geom_consistency', 'true'], os.path.join(logs, '3-geometric.log'))


if __name__ == '__main__':
    main()
