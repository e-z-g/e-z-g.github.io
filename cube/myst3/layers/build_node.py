#!/usr/bin/env python3
"""
Build a site node's Layered version from its file in nodes/.

    python build_node.py nodes/mass84.json [--steps sharpen,backdrop,layers]
        [--work DIR] [--colmap C:\\myst3_colmap] [--out C:\\myst3_out] [--dry-run]

A node file is JSON: which faces (names, in node_depth.py's order: front,
bottom, back, right, left, top), where its inputs are, every setting each step
was run with, and why each setting differs from the default ("why"). Paths may
use {colmap} and {out} (the PC's C:\\myst3_colmap and C:\\myst3_out by default)
and {work} (the node's working folder, "work" in the file unless --work).

The steps, each run only if the file has it:

  sharpen   myst3/colmap/sharpen_depth.py: the measured depth (node_depth.py's,
            "site" holds it beside the colour) redrawn at 1280 px to follow
            the picture. Writes {work}/sharp.
  backdrop  myst3/colmap/model_backdrop.py: what other nodes of the 3D model
            saw behind the near objects. Writes {work}/model_bg.
  layers    build_layers.py: the four slots' face images. Writes {work}/faces.

and prints the stitch_layers.js command that makes the four atlases (it needs
a browser and stitcher.html, so it is not run here). The measured depth itself
is made before, by node_depth.py with the command in "measured_depth".

Settings in the file are passed as --name value (a list as several values, true
as a bare flag). Scripts are looked for beside this one and in ../colmap.
"""
import argparse
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
STEPS = ('sharpen', 'backdrop', 'layers')


def find(script):
    for d in (HERE, os.path.join(HERE, '..', 'colmap')):
        p = os.path.join(d, script)
        if os.path.exists(p):
            return p
    sys.exit(f'{script} not found beside build_node.py or in ../colmap')


def flags(settings):
    out = []
    for k, v in settings.items():
        if v is False or v is None:
            continue
        out.append('--' + k)
        if v is True:
            continue
        out += [str(x) for x in v] if isinstance(v, list) else [str(v)]
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('node_file')
    ap.add_argument('--steps', default=','.join(STEPS))
    ap.add_argument('--work'); ap.add_argument('--colmap', default=r'C:\myst3_colmap')
    ap.add_argument('--out', default=r'C:\myst3_out')
    ap.add_argument('--lama', help='LaMa weights (default {out}/models/big-lama.pt)')
    ap.add_argument('--dry-run', action='store_true')
    a = ap.parse_args()
    cfg = json.load(open(a.node_file))
    roots = {'colmap': a.colmap, 'out': a.out}
    roots['work'] = (a.work or cfg['work']).format(**roots)
    sub = lambda v: v.format(**roots) if isinstance(v, str) else [sub(x) for x in v] if isinstance(v, list) else v
    W = roots['work']
    names = cfg['names']
    steps = cfg['steps']
    py = [sys.executable]
    runs = []
    sharp = os.path.join(W, 'sharp')
    if 'sharpen' in steps:
        s = dict(steps['sharpen'])
        runs.append(('sharpen', py + [find('sharpen_depth.py'), sub(cfg['site']), sharp, '--names', *names]
                     + flags({k: sub(v) for k, v in s.items()})))
    mbg = None
    if 'backdrop' in steps:
        s = {k: sub(v) for k, v in steps['backdrop'].items()}
        mbg = os.path.join(W, 'model_bg')
        pos = [s.pop('dense'), s.pop('sparse_txt'), s.pop('node'), sharp, s.pop('node_depth_json'), mbg]
        runs.append(('backdrop', py + [find('model_backdrop.py'), *pos, '--names', *names] + flags(s)))
    if 'layers' in steps:
        s = {k: sub(v) for k, v in steps['layers'].items()}
        if cfg.get('builder', 'build_layers.py') == 'build_layers.py':
            s.setdefault('lama', a.lama or os.path.join(roots['out'], 'models', 'big-lama.pt'))
            if mbg:
                s.setdefault('model-bg', mbg)
            if 'sharpen' in steps:
                s.setdefault('src', sharp)
                s.setdefault('colour-suffix', '_sharp-colour.png'); s.setdefault('depth-suffix', '_sharp-depth.png')
        builder = cfg.get('builder', 'build_layers.py')
        if builder == 'build_layers.py':
            runs.append(('layers', py + [find(builder), os.path.join(W, 'faces'), '--names', *names] + flags(s)))
        else:                                    # a node with its own method takes only its own settings
            runs.append(('layers', py + [find(builder), os.path.join(W, 'faces')] + flags(steps['layers'])))
    want = a.steps.split(',')
    for step, cmd in runs:
        if step not in want:
            continue
        # a value starting with '-' (a suffix like -orig.jpg) must be joined to its flag
        fixed = []
        for i, c in enumerate(cmd):
            if i and cmd[i - 1].startswith('--') and c.startswith('-') and not c.startswith('--'):
                fixed[-1] = fixed[-1] + '=' + c
            else:
                fixed.append(c)
        print(f'[{step}]', ' '.join(f'"{c}"' if ' ' in c else c for c in fixed), flush=True)
        if not a.dry_run:
            r = subprocess.run(fixed)
            if r.returncode:
                sys.exit(f'{step} failed ({r.returncode})')
    st = cfg.get('stitch', {})
    print('[stitch, on a machine with Playwright, serving the repo on :8000]\n  node stitch_layers.js '
          f'http://localhost:8000/cube/stitcher.html {os.path.join(W, "faces")} {os.path.join(W, "stitched")} '
          f'{st.get("cell", 1296)} {st.get("prefix", "layered")} {",".join(st.get("names", names))}')


if __name__ == '__main__':
    main()
