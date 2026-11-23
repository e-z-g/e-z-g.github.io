"""A site mesh (scene_mesh.py's scene.json and scene.bin.*) drawn into J'nanin's cliff walk's polar layout at 1060,
halfway and 1067, as mv3d_cliff.py draws its points, so the two can be set side by side. The mesh is fitted to the
sparse model by the nodes in both (nodes.json against the faces' centres). Vertices only, nearest wins.

    python mesh_cliff.py SPARSE_TXT MESH_DIR OUT.png [--size 960x480]
"""
import argparse, json, os, sys
import numpy as np, cv2
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mv3d_cliff import read_model, centre, umeyama, splat, A, B


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('sparse'); ap.add_argument('mesh'); ap.add_argument('out'); ap.add_argument('--size', default='960x480')
    a = ap.parse_args(); W, H = map(int, a.size.split('x'))
    _, ims = read_model(a.sparse)
    nodes = json.load(open(os.path.join(a.mesh, 'nodes.json')))
    ks = [k for k in nodes if f'f1/LE-{k}.jpg' in ims]
    X = np.array([centre(*ims[f'f1/LE-{k}.jpg'][:2]) for k in ks]); Y = np.array([nodes[k] for k in ks])
    s, R, t = umeyama(Y, X)                               # viewer frame -> sparse frame
    res = np.linalg.norm(Y @ R.T * s + t - X, axis=1)
    print(f'{len(ks)} nodes in both; misfit median {np.median(res):.3f} (sparse units)')
    meta = json.load(open(os.path.join(a.mesh, 'scene.json'))); pp = meta['parts']; n = meta['vertices']
    def part(name, dtype, width):                         # read one attribute across the scene.bin pieces, nothing more
        off = pp[name]['offset']; size = np.dtype(dtype).itemsize * width * n; buf = bytearray(); pos = 0
        for f in meta['files']:
            L = os.path.getsize(os.path.join(a.mesh, f))
            if off < pos + L and off + size > pos:
                with open(os.path.join(a.mesh, f), 'rb') as fh:
                    lo = max(off, pos); fh.seek(lo - pos); buf += fh.read(min(off + size, pos + L) - lo)
            pos += L
        return np.frombuffer(bytes(buf), dtype).reshape(-1, width)
    V = part('position', np.float32, 3); Cv = part('color', np.uint8, 3)
    P = (V @ R.T * s + t).astype(np.float32)
    CA, RA = centre(*ims[f'f1/LE-{A}.jpg'][:2]), ims[f'f1/LE-{A}.jpg'][0]; CB = centre(*ims[f'f1/LE-{B}.jpg'][:2])
    apart = np.linalg.norm(CB - CA); fwd = (CB - CA) / apart; up = -RA[1]
    right = np.cross(fwd, up); right /= np.linalg.norm(right); down = np.cross(fwd, right); Rc = np.stack([right, down, fwd])
    rows = []
    for T in (0, .5, 1):
        col, dep = splat(P, Cv, CA, Rc, apart, T, W, H)
        rows.append(np.hstack([col, dep]))
    cv2.imwrite(a.out, np.vstack(rows))
    print('wrote', a.out, f'{n} vertices')


if __name__ == '__main__':
    main()
