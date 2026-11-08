#!/usr/bin/env python3
"""
A copy of a dense workspace with nodes moved as node_resect.py placed them,
ready for stereo_fusion.

    python apply_moves.py DENSE RESECT.json SPARSE_TXT OUT [--min-lines 20] [--min-gain 1.5]
        [--max-spread 0.3] [--nodes MA-2001 ...]

SPARSE_TXT is DENSE's sparse model as text (model_converter --output_type TXT),
with rigs.txt and frames.txt: a node is one frame of a six-camera rig whose
reference camera is face 1, so moving a node is setting its frame's
translation to -R C for the new centre C. A node is moved when node_resect.py
found at least --min-lines agreeing lines, at least --min-gain times as many
as at its old centre, a spread under --max-spread and a depth scale (or the
nodes given with --nodes). OUT gets sparse/ (text; convert it to binary with
model_converter), stereo/ copied from DENSE with the moved nodes' geometric
depth maps multiplied by their depth scale (normals do not change), and a
link to DENSE's images. Prints what was moved. Needs numpy; evaluate_model.py
beside it.
"""
import argparse
import json
import os
import re
import shutil
import subprocess

import numpy as np

from evaluate_model import qvec2rot

NODE = re.compile(r'f(\d)/(.*)\.jpg')


def scale_depth(src, dst, k):
    with open(src, 'rb') as fh:
        raw = fh.read()
    n = amp = 0
    while n < 3:
        if raw[amp:amp + 1] == b'&':
            n += 1
        amp += 1
    data = np.frombuffer(raw[amp:], np.float32) * np.float32(k)
    with open(dst, 'wb') as fh:
        fh.write(raw[:amp]); fh.write(data.astype(np.float32).tobytes())


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('dense'); ap.add_argument('resect'); ap.add_argument('sparse_txt'); ap.add_argument('out')
    ap.add_argument('--min-lines', type=int, default=20)
    ap.add_argument('--min-gain', type=float, default=1.5)
    ap.add_argument('--max-spread', type=float, default=0.3)
    ap.add_argument('--nodes', nargs='*')
    a = ap.parse_args()
    res = json.load(open(a.resect))['nodes']
    move = {}
    for n, r in res.items():
        if a.nodes is not None:
            ok = n in a.nodes
        else:
            ok = (r['agree_new'] >= a.min_lines and r['agree_new'] >= a.min_gain * max(1, r['agree_old'])
                  and r['spread'] is not None and r['spread'] < a.max_spread and r.get('depth_scale'))
        if ok:
            move[n] = r
    # frames: which frame is which node, through images.txt
    img_node = {}
    head = True
    for line in open(os.path.join(a.sparse_txt, 'images.txt')):
        if line.startswith('#'):
            continue
        if head:
            p = line.split()
            m = NODE.fullmatch(p[9])
            if m:
                img_node[int(p[0])] = m.group(2)
        head = not head
    os.makedirs(os.path.join(a.out, 'sparse'), exist_ok=True)
    for f in os.listdir(a.sparse_txt):
        if f != 'frames.txt':
            shutil.copy(os.path.join(a.sparse_txt, f), os.path.join(a.out, 'sparse', f))
    moved = []
    with open(os.path.join(a.sparse_txt, 'frames.txt')) as fi, open(os.path.join(a.out, 'sparse', 'frames.txt'), 'w') as fo:
        for line in fi:
            if line.startswith('#'):
                fo.write(line); continue
            p = line.split()
            data = p[10:]
            ids = [int(data[1 + 3 * k + 2]) for k in range(int(data[0]))]
            node = next((img_node[i] for i in ids if i in img_node), None)
            if node in move:
                R = qvec2rot(np.array(p[2:6], float))
                C = np.array(move[node]['new'])
                t = -R @ C
                p[6:9] = [repr(float(v)) for v in t]
                moved.append(node)
                line = ' '.join(p) + '\n'
            fo.write(line)
    # images.txt holds each image's pose too; the frames are what COLMAP 4 reads,
    # but keep the two the same.
    lines = open(os.path.join(a.out, 'sparse', 'images.txt')).read().split('\n')
    out, head = [], True
    for line in lines:
        if line.startswith('#') or not line.strip():
            out.append(line); continue
        if head:
            p = line.split()
            m = NODE.fullmatch(p[9])
            if m and m.group(2) in move:
                R = qvec2rot(np.array(p[1:5], float))
                p[5:8] = [repr(float(v)) for v in -R @ np.array(move[m.group(2)]['new'])]
                line = ' '.join(p)
        out.append(line)
        head = not head
    open(os.path.join(a.out, 'sparse', 'images.txt'), 'w').write('\n'.join(out))
    print(f'moved {len(moved)} nodes:')
    for n in sorted(moved):
        r = move[n]
        print(f'  {n}: shift {r["shift"]:.2f}, depth x{r["depth_scale"]:.3f}, lines {r["agree_old"]} -> {r["agree_new"]}')
    # stereo: everything copied, the moved nodes' geometric depths scaled
    st_in, st_out = os.path.join(a.dense, 'stereo'), os.path.join(a.out, 'stereo')
    if not os.path.exists(st_out):
        shutil.copytree(st_in, st_out)
    prev = os.path.join(a.out, 'moves.json')
    for n in (json.load(open(prev)) if os.path.exists(prev) else {}):
        for k in range(1, 7):                     # undo an earlier run's scaling
            name = f'f{k}/{n}.jpg.geometric.bin'
            if os.path.exists(os.path.join(st_in, 'depth_maps', name)):
                shutil.copy(os.path.join(st_in, 'depth_maps', name), os.path.join(st_out, 'depth_maps', name))
    for n in moved:
        for k in range(1, 7):
            name = f'f{k}/{n}.jpg.geometric.bin'
            src = os.path.join(st_in, 'depth_maps', name)
            if os.path.exists(src):
                scale_depth(src, os.path.join(st_out, 'depth_maps', name), move[n]['depth_scale'])
    img = os.path.join(a.out, 'images')
    if not os.path.exists(img):
        if os.name == 'nt':
            subprocess.run(['cmd', '/c', 'mklink', '/J', img, os.path.join(a.dense, 'images')], check=True)
        else:
            os.symlink(os.path.join(a.dense, 'images'), img)
    json.dump({n: move[n] for n in moved}, open(os.path.join(a.out, 'moves.json'), 'w'), indent=1)


if __name__ == '__main__':
    main()
