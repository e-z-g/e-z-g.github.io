#!/usr/bin/env python3
"""
Myst III cube faces: the direction of every pixel, each face's camera rotation,
and a check that the six faces of a node join up.

    python face_geometry.py rotations                       print the rotations (JSON)
    python face_geometry.py check FACES_DIR NODE [PANO.png]  seam check on one node,
                                                             e.g. faces/ENSI ENSI-0001
    python face_geometry.py room FACES_DIR                   the same on every node there,
                                                             one line each

Directions are in the game's own frame: ScummVM's Myst III engine draws a node
as a cube with face i (0-5) textured from the archive's cube face i+1
(engines/myst3/nodecube.cpp) at the corners listed in Renderer::cubeVertices
(engines/myst3/gfx.cpp). Read from that table, with s, t the image's column and
row as fractions (t down), a pixel of each face looks along

    face 1 front   ( 2s-1, 1-2t,   -1 )
    face 2 bottom  ( 1-2s,   -1, 1-2t )
    face 3 back    ( 1-2s, 1-2t,    1 )
    face 4 right   (    1, 1-2t, 2s-1 )
    face 5 left    (   -1, 1-2t, 1-2s )
    face 6 top     ( 1-2s,    1, 2t-1 )

x right, y up, z towards the back (OpenGL; the front face is -z). With u = s
and v = 1 - t (v up) these are exactly faceUvToDir() in cube/atlas-layout.js
for viewer slots front 5, bottom 3, back 4, right 1, left 0, top 2. The
viewer's (-1, 1, 1) scale on its cube is undone by its gnomonicUV, so
faceUvToDir is already in the game's frame, not mirrored.

COLMAP cameras look along +z with x right and y down in the image. A face's
cam_from_node rotation therefore has rows (right, down, forward): the
direction of increasing s, of increasing t, and of the face's centre. Each of
the six has determinant +1, which a mirrored mapping could not give (a mirror
turns right x down into -forward); with the seams checked below that proves
the mapping.

Needs numpy and Pillow for "check"; "rotations" needs neither.
"""
import json
import math
import sys

FACES = {1: 'front', 2: 'bottom', 3: 'back', 4: 'right', 5: 'left', 6: 'top'}


def face_dir(face, s, t):
    """Unnormalised direction of image point (s, t), s right and t down, in [0, 1]."""
    a, b = 2 * s - 1, 1 - 2 * t
    return {1: (a, b, -1), 2: (-a, -1, b), 3: (-a, b, 1),
            4: (1, b, a), 5: (-1, b, -a), 6: (-a, 1, -b)}[face]


def dir_to_face(x, y, z):
    """(face, s, t) of a direction: the inverse of face_dir."""
    ax, ay, az = abs(x), abs(y), abs(z)
    if ax >= ay and ax >= az:
        if x > 0:
            return 4, (z / ax + 1) / 2, (1 - y / ax) / 2
        return 5, (-z / ax + 1) / 2, (1 - y / ax) / 2
    if ay >= az:
        if y > 0:
            return 6, (-x / ay + 1) / 2, (1 + z / ay) / 2
        return 2, (-x / ay + 1) / 2, (1 - z / ay) / 2
    if z > 0:
        return 3, (-x / az + 1) / 2, (1 - y / az) / 2
    return 1, (x / az + 1) / 2, (1 - y / az) / 2


def unit(v):
    n = math.sqrt(sum(c * c for c in v))
    return tuple(c / n for c in v)


def cam_from_node(face):
    """3x3 rotation, node frame -> COLMAP camera frame (rows: right, down, forward)."""
    c = face_dir(face, 0.5, 0.5)
    right = unit(tuple(p - q for p, q in zip(face_dir(face, 1, 0.5), face_dir(face, 0, 0.5))))
    down = unit(tuple(p - q for p, q in zip(face_dir(face, 0.5, 1), face_dir(face, 0.5, 0))))
    return [list(right), list(down), list(unit(c))]


def det3(m):
    return (m[0][0] * (m[1][1] * m[2][2] - m[1][2] * m[2][1])
            - m[0][1] * (m[1][0] * m[2][2] - m[1][2] * m[2][0])
            + m[0][2] * (m[1][0] * m[2][1] - m[1][1] * m[2][0]))


def matmul(a, b):
    return [[sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)] for i in range(3)]


def transpose(m):
    return [list(r) for r in zip(*m)]


def quat_wxyz(m):
    """Rotation matrix -> unit quaternion (w, x, y, z), w >= 0 (Eigen / COLMAP order)."""
    tr = m[0][0] + m[1][1] + m[2][2]
    if tr > 0:
        s = math.sqrt(tr + 1) * 2
        q = (s / 4, (m[2][1] - m[1][2]) / s, (m[0][2] - m[2][0]) / s, (m[1][0] - m[0][1]) / s)
    elif m[0][0] > m[1][1] and m[0][0] > m[2][2]:
        s = math.sqrt(1 + m[0][0] - m[1][1] - m[2][2]) * 2
        q = ((m[2][1] - m[1][2]) / s, s / 4, (m[0][1] + m[1][0]) / s, (m[0][2] + m[2][0]) / s)
    elif m[1][1] > m[2][2]:
        s = math.sqrt(1 + m[1][1] - m[0][0] - m[2][2]) * 2
        q = ((m[0][2] - m[2][0]) / s, (m[0][1] + m[1][0]) / s, s / 4, (m[1][2] + m[2][1]) / s)
    else:
        s = math.sqrt(1 + m[2][2] - m[0][0] - m[1][1]) * 2
        q = ((m[1][0] - m[0][1]) / s, (m[0][2] + m[2][0]) / s, (m[1][2] + m[2][1]) / s, s / 4)
    if q[0] < 0:
        q = tuple(-c for c in q)
    return [round(c, 12) + 0.0 for c in q]


def rotations(ref_face=1):
    """Per face: cam_from_node (matrix, quaternion) and cam_from_rig with face ref_face as the rig."""
    ref = cam_from_node(ref_face)
    out = {}
    for f in FACES:
        r = cam_from_node(f)
        rig = matmul(r, transpose(ref))
        out[f] = {'name': FACES[f], 'cam_from_node': r, 'cam_from_node_wxyz': quat_wxyz(r),
                  'det': round(det3(r), 9), 'cam_from_rig': [[round(c, 12) + 0.0 for c in row] for row in rig],
                  'cam_from_rig_wxyz': quat_wxyz(rig)}
    return out


# ── seam check ──────────────────────────────────────────────────────────────

def load_faces(faces_dir, node):
    import numpy as np
    from PIL import Image
    return {f: np.asarray(Image.open(f'{faces_dir}/{node}-f{f}.jpg').convert('RGB'), dtype=np.float32)
            for f in FACES}


def sample(img, s, t):
    """Bilinear sample at fractional image coordinates (s, t in [0, 1], pixel centres at (i+0.5)/n)."""
    import numpy as np
    h, w, _ = img.shape
    x = np.clip(s * w - 0.5, 0, w - 1.0001)
    y = np.clip(t * h - 0.5, 0, h - 1.0001)
    x0, y0 = np.floor(x).astype(int), np.floor(y).astype(int)
    fx, fy = (x - x0)[..., None], (y - y0)[..., None]
    return (img[y0, x0] * (1 - fx) * (1 - fy) + img[y0, x0 + 1] * fx * (1 - fy)
            + img[y0 + 1, x0] * (1 - fx) * fy + img[y0 + 1, x0 + 1] * fx * fy)


def seam_scores(imgs, mapping=None):
    """For every face edge: mean colour step across the seam, against the same step
    one pixel inside the face. A ratio near 1 means the seam is invisible.
    mapping(face, s, t) -> (face, s, t) lets a wrong layout be tried for comparison."""
    import numpy as np
    n = next(iter(imgs.values())).shape[0]
    k = (np.arange(n) + 0.5) / n
    e0, e1 = 0.5 / n, 1.5 / n        # the edge pixel and the one inside it
    out_ = -0.5 / n                   # one pixel beyond the edge, on the neighbour
    rows = []
    for f in FACES:
        for side, (s_edge, t_edge, s_in, t_in, s_out, t_out) in {
                'left': (np.full(n, e0), k, np.full(n, e1), k, np.full(n, out_), k),
                'right': (np.full(n, 1 - e0), k, np.full(n, 1 - e1), k, np.full(n, 1 - out_), k),
                'top': (k, np.full(n, e0), k, np.full(n, e1), k, np.full(n, out_)),
                'bottom': (k, np.full(n, 1 - e0), k, np.full(n, 1 - e1), k, np.full(n, 1 - out_))}.items():
            edge = sample(imgs[f], s_edge, t_edge)
            inside = sample(imgs[f], s_in, t_in)
            d = np.array([face_dir(f, a, b) for a, b in zip(s_out, t_out)])
            across = np.empty_like(edge)
            nbrs = set()
            for i, v in enumerate(d):
                g, s2, t2 = dir_to_face(*v)
                if mapping:
                    g, s2, t2 = mapping(g, s2, t2)
                nbrs.add(g)
                across[i] = sample(imgs[g], np.array([s2]), np.array([t2]))[0]
            step_in = float(np.mean(np.abs(edge - inside)))
            step_across = float(np.mean(np.abs(edge - across)))
            rows.append((f, side, sorted(nbrs), step_in, step_across))
    return rows


def equirect(imgs, width=2048):
    import numpy as np
    h = width // 2
    lon = (np.arange(width) + 0.5) / width * 2 * np.pi - np.pi      # 0 = front (-z), + to the right
    lat = np.pi / 2 - (np.arange(h) + 0.5) / h * np.pi
    lon, lat = np.meshgrid(lon, lat)
    x, y, z = np.cos(lat) * np.sin(lon), np.sin(lat), -np.cos(lat) * np.cos(lon)
    out = np.zeros((h, width, 3), np.float32)
    ax, ay, az = np.abs(x), np.abs(y), np.abs(z)
    for f in FACES:
        if f == 4:   m = (ax >= ay) & (ax >= az) & (x > 0)
        elif f == 5: m = (ax >= ay) & (ax >= az) & (x <= 0)
        elif f == 6: m = ~((ax >= ay) & (ax >= az)) & (ay >= az) & (y > 0)
        elif f == 2: m = ~((ax >= ay) & (ax >= az)) & (ay >= az) & (y <= 0)
        elif f == 3: m = ~((ax >= ay) & (ax >= az)) & ~(ay >= az) & (z > 0)
        else:        m = ~((ax >= ay) & (ax >= az)) & ~(ay >= az) & (z <= 0)
        st = [dir_to_face(a, b, c) for a, b, c in zip(x[m], y[m], z[m])]
        s = np.array([p[1] for p in st]); t = np.array([p[2] for p in st])
        out[m] = sample(imgs[f], s, t)
    return out


def check(faces_dir, node, pano=None):
    import numpy as np
    from PIL import Image
    imgs = load_faces(faces_dir, node)
    excess = seam_report(imgs, node)
    if pano:
        Image.fromarray(np.clip(equirect(imgs), 0, 255).astype(np.uint8)).save(pano)
        print('panorama written to', pano)
    return excess

def seam_report(imgs, node):
    rows = seam_scores(imgs)
    # The step across a seam includes the scene's own change over one pixel, so it is
    # compared with the step one pixel inside: the excess is what the seam adds, in
    # grey levels (0-255, mean over the edge's 640 pixels and three channels).
    excess = [a - i for _, _, _, i, a in rows]
    print(f'{node}: 24 face edges; colour step across the seam, one pixel inside, and the excess')
    for (f, side, nb, i, a), x in zip(rows, excess):
        print(f'  f{f} {FACES[f]:6s} {side:6s} -> f{nb[0] if len(nb) == 1 else nb}: inside {i:5.1f}  across {a:5.1f}  excess {x:5.1f}')
    print(f'  excess: median {sorted(excess)[12]:.1f}, worst {max(excess):.1f}')
    # The same check with left and right exchanged and mirrored, which keeps the
    # walls in order but flips the world: it must fail, or the check proves nothing.
    swap = {4: 5, 5: 4}
    bad = seam_scores(imgs, lambda g, s, t: (swap.get(g, g), 1 - s if g in swap else s, t))
    bad_x = [a - i for _, _, _, i, a in bad]
    print(f'  with left/right swapped and mirrored: median {sorted(bad_x)[12]:.1f}, worst {max(bad_x):.1f}')
    return excess


def main():
    if len(sys.argv) >= 2 and sys.argv[1] == 'rotations':
        print(json.dumps(rotations(), indent=1))
        return
    if len(sys.argv) == 3 and sys.argv[1] == 'room':
        import contextlib, io, os, re
        nodes = sorted({m.group(1) for m in (re.fullmatch(r'(.+)-f[1-6]\.jpg', x) for x in os.listdir(sys.argv[2])) if m})
        worst = []
        for node in nodes:
            with contextlib.redirect_stdout(io.StringIO()):
                ex = seam_report(load_faces(sys.argv[2], node), node)
            worst.append(max(ex))
            print(f'{node}: median excess {sorted(ex)[12]:4.1f}, worst {max(ex):5.1f}, edges over 5: {sum(e > 5 for e in ex)}')
        print(f'{len(nodes)} nodes; worst edge anywhere {max(worst):.1f}')
        return
    if len(sys.argv) < 4 or sys.argv[1] != 'check':
        sys.exit(__doc__)
    print('determinants:', {FACES[f]: r['det'] for f, r in rotations().items()})
    check(sys.argv[2], sys.argv[3], sys.argv[4] if len(sys.argv) > 4 else None)


if __name__ == '__main__':
    main()
