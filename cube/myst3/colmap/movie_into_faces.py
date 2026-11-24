"""One frame of a node's scripted movie drawn into the node's six cube faces where the game draws it, for walk ends that
show a scene the movie plays (a character, a prop): ScummVM's Movie::loadPosition (engines/myst3/movie.cpp) puts the
frame on a plane facing V1 (the entry's metadata, archive.cpp getVideoData) 50 units out, its rectangle U, V, WIDTH,
HEIGHT in a 640x640 face's units measured from the centre (1/320 a unit), the plane's across axis level.

    python movie_into_faces.py FACES_PREFIX OUT_PREFIX FRAME.png --v1 X Y Z --rect U V WIDTH HEIGHT [--flip-check]

FACES_PREFIX and OUT_PREFIX are paths without "-f<k>.jpg"; the faces written are PNG (OUT_PREFIX-f<k>.png) so nothing is
lost a second time. ScummVM's directions (directionToVector: heading 180 straight at face 1, pitch up) turned into
node_view.py's frame (x right, y down, z into face 1): ours = -S, found by trying every signed permutation of the
axes and flip of the frame on TOHO 1's movie 11001, whose empty first frame then matches the still best (9.9 levels,
the next 30.7; what is left is the bench, which the still has and that frame lacks). Prints the mean difference between the
frame and the face pixels it covers: with a movie's empty first frame that checks the placement (near 0 when right).
"""
import argparse, os, sys
import numpy as np, cv2
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from node_view import FACES  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('faces'); ap.add_argument('out'); ap.add_argument('frame')
    ap.add_argument('--v1', type=float, nargs=3, required=True); ap.add_argument('--rect', type=int, nargs=4, required=True)
    a = ap.parse_args()
    fr = cv2.imread(a.frame); FH, FW = fr.shape[:2]
    n = np.array(a.v1, float); n /= np.linalg.norm(n)
    ua = np.array([n[2], 0.0, -n[0]]); ua /= np.linalg.norm(ua)
    va = np.cross(n, ua); va /= np.linalg.norm(va)
    U, V, Wd, Hd = a.rect
    left, right = (U - 320) / 320, (U + Wd - 320) / 320
    top, bottom = (320 - V) / 320, (320 - V - Hd) / 320
    diffs = []; covered = 0
    for k, (r, dn, fw) in FACES.items():
        img = cv2.imread(f'{a.faces}-f{k}.jpg'); N = img.shape[0]
        v, u = np.mgrid[0:N, 0:N].astype(np.float64)
        x, y = (u + .5) / N * 2 - 1, (v + .5) / N * 2 - 1
        d = x[..., None] * np.array(r, float) + y[..., None] * np.array(dn, float) + np.array(fw, float)   # our frame
        S = -d                                                                                               # ScummVM's
        sn = S @ n
        with np.errstate(all='ignore'):
            P = S * (1.0 / np.where(sn > 1e-6, sn, np.nan))[..., None]       # on the plane at distance 1 (50 scales out)
            s, t = P @ ua, P @ va
        ok = (sn > 1e-6) & (s >= left) & (s <= right) & (t >= bottom) & (t <= top)
        if ok.any():
            mx = ((s - left) / (right - left) * FW - .5).astype(np.float32); my = ((top - t) / (top - bottom) * FH - .5).astype(np.float32)
            smp = cv2.remap(fr, np.where(ok, mx, 0), np.where(ok, my, 0), cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)
            diffs.append(np.abs(smp[ok].astype(np.float32) - img[ok].astype(np.float32)).mean() * ok.sum()); covered += ok.sum()
            img = np.where(ok[..., None], smp, img)
        cv2.imwrite(f'{a.out}-f{k}.png', img)
    print(f'{os.path.basename(a.out)}: {covered} face pixels covered; mean difference from the faces there '
          f'{(sum(diffs) / covered) if covered else float("nan"):.2f} levels')


if __name__ == '__main__':
    main()
