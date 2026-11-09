#!/usr/bin/env python3
"""
A 3DGS .ply as an .spz (the compressed splat format Spark reads), for the web.

    python ply_to_spz.py IN.ply OUT.spz [--sh 0]

Positions, log scales, rotations (w, x, y, z), opacities (before the
sigmoid) and the zeroth spherical harmonic are taken as the .ply has them;
higher harmonics up to --sh (0-3), rearranged from the .ply's colour-major
order to the coefficient-major order SPZ keeps. No change of axes. Uses the
compiled module of the `spz` package (pip install spz, Jackneill/spz) loaded
straight from its file, as its __init__.py (0.0.1) fails on import. Needs
numpy.
"""
import argparse
import glob
import importlib.machinery
import importlib.util
import os
import site
import sys

import numpy as np


def spz_module():
    for d in site.getsitepackages() + [site.getusersitepackages()] + sys.path:
        for p in glob.glob(os.path.join(d, 'spz', 'spz*.pyd')) + glob.glob(os.path.join(d, 'spz', 'spz*.so')):
            spec = importlib.util.spec_from_file_location('spz', p, loader=importlib.machinery.ExtensionFileLoader('spz', p))
            m = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(m)
            return m
    raise SystemExit('the spz package is not installed (pip install spz)')


def read_ply(path):
    with open(path, 'rb') as f:
        props, n = [], 0
        while True:
            line = f.readline().decode().strip()
            if line.startswith('element vertex'):
                n = int(line.split()[-1])
            elif line.startswith('property'):
                _, t, name = line.split()
                props.append((name, {'float': '<f4', 'double': '<f8', 'uchar': 'u1'}[t]))
            elif line == 'end_header':
                break
        return np.frombuffer(f.read(), dtype=np.dtype(props), count=n)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('src'); ap.add_argument('out'); ap.add_argument('--sh', type=int, default=0)
    a = ap.parse_args()
    v = read_ply(a.src)
    col = lambda *ns: np.stack([v[n] for n in ns], 1).astype(np.float32)
    pos = col('x', 'y', 'z'); sc = col('scale_0', 'scale_1', 'scale_2')
    rot = col('rot_0', 'rot_1', 'rot_2', 'rot_3')
    rot /= np.linalg.norm(rot, axis=1, keepdims=True)
    alpha = v['opacity'].astype(np.float32)
    dc = col('f_dc_0', 'f_dc_1', 'f_dc_2')
    rest = sorted((n for n in v.dtype.names if n.startswith('f_rest_')), key=lambda n: int(n[7:]))
    per = len(rest) // 3                                   # coefficients per colour in the file
    keep = {0: 0, 1: 3, 2: 8, 3: 15}[a.sh]
    sh = None
    if keep:
        R = col(*rest).reshape(-1, 3, per)[:, :, :keep]     # colour-major in the .ply
        sh = np.ascontiguousarray(R.transpose(0, 2, 1).reshape(len(v), keep * 3))
    m = spz_module()
    g = m.GaussianSplat(pos, sc, rot, alpha, dc, sh_degree=a.sh, spherical_harmonics=sh)
    g.save(a.out)
    print(f'{len(v)} splats, harmonics to degree {a.sh} -> {a.out} {os.path.getsize(a.out) / 1e6:.1f} MB')


if __name__ == '__main__':
    main()
