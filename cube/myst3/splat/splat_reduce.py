#!/usr/bin/env python3
"""
A lighter copy of a 3DGS .ply for a device that cannot load the full one (a
phone): the splats that show most, without view-dependent colour.

    python splat_reduce.py FULL.ply OUT.ply [--keep 1500000] [--sh 0]

Splats are ranked by opacity times their largest extent (a faint or tiny splat
changes little of any picture) and the --keep largest kept; spherical
harmonics above degree --sh are dropped. The full file stays the reference:
this is only for display. Needs numpy.
"""
import argparse
import re

import numpy as np


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('full'); ap.add_argument('out')
    ap.add_argument('--keep', type=int, default=1500000); ap.add_argument('--sh', type=int, default=0)
    a = ap.parse_args()
    with open(a.full, 'rb') as f:
        head = b''
        while not head.endswith(b'end_header\n'):
            head += f.readline()
        n = int(re.search(rb'element vertex (\d+)', head).group(1))
        props = [p.decode() for p in re.findall(rb'property float (\S+)', head)]
        data = np.fromfile(f, dtype='<f4', count=n * len(props)).reshape(n, len(props))
    ix = {p: i for i, p in enumerate(props)}
    opac = 1 / (1 + np.exp(-data[:, ix['opacity']]))
    extent = np.exp(data[:, [ix['scale_0'], ix['scale_1'], ix['scale_2']]].max(1))
    order = np.argsort(-(opac * extent))[:a.keep]
    # f_rest is stored channel by channel (all of red's coefficients, then green's, then blue's)
    per = sum(p.startswith('f_rest_') for p in props) // 3
    k_rest = min(per, (a.sh + 1) ** 2 - 1)
    rest_keep = [f'f_rest_{c * per + k}' for c in range(3) for k in range(k_rest)]
    keep_props = [p for p in props if not p.startswith('f_rest_')] + rest_keep
    out = data[order][:, [ix[p] for p in keep_props]]
    names = [p for p in props if not p.startswith('f_rest_')] + [f'f_rest_{i}' for i in range(len(rest_keep))]
    lines = [l for l in head.split(b'\n') if not l.startswith(b'property')]
    hdr = b'\n'.join(l for l in lines if l and l != b'end_header')
    hdr = re.sub(rb'element vertex \d+', b'element vertex %d' % len(out), hdr)
    hdr = re.sub(rb'SH degree: \d+', b'SH degree: %d' % min(a.sh, 3), hdr)
    hdr += b'\n' + b''.join(b'property float %s\n' % p.encode() for p in names) + b'end_header\n'
    with open(a.out, 'wb') as f:
        f.write(hdr); f.write(out.astype('<f4').tobytes())
    print(f'{len(out)} of {n} splats, spherical harmonics to degree {a.sh} -> {a.out}')


if __name__ == '__main__':
    main()
