"""A flat view from one node's six cube faces, looking at a game heading and pitch, with no model: the start frame of a
close-up transition, drawn as the player sees the node when they click the close-up's hotspot.

    python node_view.py FACES_PREFIX HEADING PITCH OUT.png [--fov 90] [--size 1280x720]

FACES_PREFIX is the path of a node's faces without "-f<k>.jpg" (myst3_nodes.py's names, e.g. faces/TOHO/TOHO-0007).
Headings and pitches are the game's, as its hotspots give them: heading 180 is the centre of face 1 (front) and grows
to the right (270 face 4, right; 0 face 3, back; 90 face 5, left); pitch is positive up (face 6, top; face 2, bottom).
Found from Tomahna's study, where each close-up's hotspot heading points at the thing on the faces, and from ScummVM's
scene.cpp (heading grows as the mouse moves right, pitch as it moves up). --fov is the horizontal field of view.
"""
import argparse
import numpy as np, cv2

# each face's camera axes (right, down, forward in its picture) in the frame of face 1: x right, y down, z forward
FACES = {1: ((1, 0, 0), (0, 1, 0), (0, 0, 1)),        # front
         4: ((0, 0, -1), (0, 1, 0), (1, 0, 0)),       # right
         3: ((-1, 0, 0), (0, 1, 0), (0, 0, -1)),      # back
         5: ((0, 0, 1), (0, 1, 0), (-1, 0, 0)),       # left
         6: ((-1, 0, 0), (0, 0, -1), (0, -1, 0)),     # top: meets front along its own top edge, running the other way
         2: ((-1, 0, 0), (0, 0, 1), (0, 1, 0))}       # bottom: meets front along its own bottom edge, the other way
# (top and bottom found by matching their edges to face 1's top and bottom rows: the same on every node tried, TOHO 1-8
# and MAIS 1-3)


def view(prefix, heading, pitch, W, H, fov):
    a, p = np.radians(heading - 180), np.radians(pitch)
    fwd = np.array([np.sin(a) * np.cos(p), -np.sin(p), np.cos(a) * np.cos(p)])
    right = np.array([np.cos(a), 0, -np.sin(a)]); down = np.cross(fwd, right)
    f = W / 2 / np.tan(np.radians(fov) / 2)
    v, u = np.mgrid[0:H, 0:W].astype(np.float64)
    d = (((u + .5 - W / 2) / f)[..., None] * right + ((v + .5 - H / 2) / f)[..., None] * down + fwd)
    out = np.zeros((H, W, 3), np.float32); best = np.full((H, W), -np.inf)
    for k, (r, dn, fw) in FACES.items():
        img = cv2.imread(f'{prefix}-f{k}.jpg'); N = img.shape[0]
        z = d @ np.array(fw, float)
        with np.errstate(all='ignore'):
            x = (d @ np.array(r, float)) / z; y = (d @ np.array(dn, float)) / z
        ok = (z > 0) & (np.abs(x) <= 1.001) & (np.abs(y) <= 1.001)
        score = np.where(ok, z / np.linalg.norm(d, axis=-1), -np.inf); take = score > best
        mx = ((x + 1) * N / 2 - .5).astype(np.float32); my = ((y + 1) * N / 2 - .5).astype(np.float32)
        s = cv2.remap(img, np.where(ok, mx, 0), np.where(ok, my, 0), cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)
        out[take] = s[take]; best[take] = score[take]
    return np.clip(np.rint(out), 0, 255).astype(np.uint8)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('prefix'); ap.add_argument('heading', type=float); ap.add_argument('pitch', type=float); ap.add_argument('out')
    ap.add_argument('--fov', type=float, default=90); ap.add_argument('--size', default='1280x720')
    a = ap.parse_args(); W, H = map(int, a.size.split('x'))
    cv2.imwrite(a.out, view(a.prefix, a.heading, a.pitch, W, H, a.fov))


if __name__ == '__main__':
    main()
