"""A walk's two end pictures (first.png, last.png) drawn from the two nodes' cube faces facing a game heading, with no
model: for ages or rooms whose nodes are not all placed. Every node shares one world orientation, so the walk's
direction is the bearing of the hotspot that leads from A to B; walk_polar3.ps1 -Heading passes the mean of that and
the reverse of B's hotspot back to A. Both ends face the same way (as walk_ends.py --along-motion), level unless
--pitch is given. Faces follow node_view.py's directions (heading 180 the centre of face 1, growing to the right).

    python walk_ends_heading.py FACES_A FACES_B OUT --heading H [--pitch 0] [--size 2560x1280]
        (--polar 20 [--polar-join up] | --dual-fisheye 180 [--fill-square] [--squash 0.35])

FACES_A and FACES_B are paths without "-f<k>.jpg" (myst3_nodes.py's names, e.g. C:\\myst3_out\\faces\\TOHO\\TOHO-0004).
"""
import argparse, os, sys
import numpy as np
from PIL import Image
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from walk_ends import draw_polar_equirect, draw_dual_fisheye  # noqa: E402
from node_view import FACES  # noqa: E402


def faces(prefix):
    return [(np.array(FACES[k], float), None, np.asarray(Image.open(f'{prefix}-f{k}.jpg').convert('RGB'))) for k in FACES]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('a'); ap.add_argument('b'); ap.add_argument('out')
    ap.add_argument('--heading', type=float, required=True); ap.add_argument('--pitch', type=float, default=0.0)
    ap.add_argument('--size', default='2560x1280')
    ap.add_argument('--polar', type=float); ap.add_argument('--polar-join', choices=['down', 'up'], default='down')
    ap.add_argument('--dual-fisheye', type=float); ap.add_argument('--fill-square', action='store_true')
    ap.add_argument('--squash', type=float, default=0.0)
    a = ap.parse_args(); W, H = map(int, a.size.split('x'))
    h, p = np.radians(a.heading - 180), np.radians(a.pitch)
    fwd = np.array([np.sin(h) * np.cos(p), -np.sin(p), np.cos(h) * np.cos(p)])
    right = np.array([np.cos(h), 0.0, -np.sin(h)]); down = np.cross(fwd, right)
    Rcam = np.stack([right, down, fwd])                     # the walk's camera axes in face 1's frame
    os.makedirs(a.out, exist_ok=True)
    for name, pre in (('first', a.a), ('last', a.b)):
        F = faces(pre)
        if a.polar is not None:
            img = draw_polar_equirect(F, Rcam, W, H, a.polar, a.polar_join)
        else:
            img = draw_dual_fisheye(F, Rcam, W, H, a.dual_fisheye, 0.0, a.squash, a.fill_square)
        Image.fromarray(img).save(os.path.join(a.out, f'{name}.png'))
    print(f'{os.path.basename(a.a)} -> {os.path.basename(a.b)}: heading {a.heading:.1f}, pitch {a.pitch:.1f}; {W}x{H} -> {a.out}')


if __name__ == '__main__':
    main()
