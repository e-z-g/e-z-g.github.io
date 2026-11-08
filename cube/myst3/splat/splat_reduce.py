#!/usr/bin/env python3
"""
A lighter copy of a 3DGS .ply for a device that cannot load the full one (a
phone): the splats that show most, without view-dependent colour.

    python splat_reduce.py FULL.ply OUT.ply [--keep 1500000] [--sh 0]

Splats are ranked by opacity times the area of their two longest axes (a
faint, tiny or needle-thin splat changes little of any picture; --rank length
for the longest axis alone) and the --keep largest kept; with --shell, the
sky shell at the end is thinned on its own to --shell-keep larger splats; spherical
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
    ap.add_argument('--rank', choices=['area', 'length'], default='area',
                    help='rank by opacity times the area of the two longest axes (a thin needle counts little) or the longest axis')
    ap.add_argument('--max-aspect', type=float, default=0,
                    help='shorten any splat\'s longest axis to at most this many times its middle one (0: leave them)')
    ap.add_argument('--shell', type=int, default=0, help="the last N splats are sky_dome.py's shell")
    ap.add_argument('--shell-keep', type=int, default=0,
                    help='keep this many of the shell, evenly spread and grown to cover the same sky (counted in --keep)')
    a = ap.parse_args()
    with open(a.full, 'rb') as f:
        head = b''
        while not head.endswith(b'end_header\n'):
            head += f.readline()
        n = int(re.search(rb'element vertex (\d+)', head).group(1))
        props = [p.decode() for p in re.findall(rb'property float (\S+)', head)]
        data = np.fromfile(f, dtype='<f4', count=n * len(props)).reshape(n, len(props))
    ix = {p: i for i, p in enumerate(props)}
    shell = None
    if a.shell:
        shell, data = data[-a.shell:].copy(), data[:-a.shell]
        n -= a.shell
        if a.shell_keep and a.shell_keep < a.shell:
            # the shell is a Fibonacci lattice: an even stride keeps it even
            shell = shell[np.linspace(0, a.shell - 1, a.shell_keep).astype(int)]
            grow = np.log(np.sqrt(a.shell / a.shell_keep))
            for c in range(3):
                shell[:, ix[f'scale_{c}']] += grow
        a.keep -= len(shell)
    opac = 1 / (1 + np.exp(-data[:, ix['opacity']]))
    sc = np.sort(data[:, [ix['scale_0'], ix['scale_1'], ix['scale_2']]], 1)     # log scales, small to large
    size = np.exp(sc[:, 2] + sc[:, 1]) if a.rank == 'area' else np.exp(sc[:, 2])
    order = np.argsort(-(opac * size))[:a.keep]
    if a.max_aspect:
        # Training makes many splats needles (half are 5 times longer than wide, 1% over 500
        # times), which views it was not trained on show as heaps of sticks.
        cap = np.log(a.max_aspect)
        s3 = data[:, [ix['scale_0'], ix['scale_1'], ix['scale_2']]]
        mid = np.median(s3, 1)
        long_ = s3.max(1)
        over = long_ - mid > cap
        k = s3.argmax(1)
        for c in range(3):
            m = over & (k == c)
            data[m, ix[f'scale_{c}']] = mid[m] + cap
        print(f'{over.sum()} splats ({over.mean() * 100:.1f}%) shortened to {a.max_aspect:g} times their middle axis')
    # f_rest is stored channel by channel (all of red's coefficients, then green's, then blue's)
    per = sum(p.startswith('f_rest_') for p in props) // 3
    k_rest = min(per, (a.sh + 1) ** 2 - 1)
    rest_keep = [f'f_rest_{c * per + k}' for c in range(3) for k in range(k_rest)]
    keep_props = [p for p in props if not p.startswith('f_rest_')] + rest_keep
    out = data[order][:, [ix[p] for p in keep_props]]
    if shell is not None:
        out = np.concatenate([out, shell[:, [ix[p] for p in keep_props]]])
        n += a.shell
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
