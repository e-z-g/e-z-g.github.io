# Error against the measured depth near the cube's edges (within BAND px) and inside, for depth maps in
# the site's 8-bit form. Does blending the seams cost accuracy there?
import sys, numpy as np, cv2
from PIL import Image
site, names, band = sys.argv[1], sys.argv[2].split(','), int(sys.argv[3])
sets = {lab: path for lab, path in (a.split('=') for a in sys.argv[4:])}
N = 1280
def q(path):
    d = cv2.resize(np.asarray(Image.open(path).convert('L')).astype(np.float32), (N, N), interpolation=cv2.INTER_NEAREST)
    return np.where(d > 0, 1 + 19 * d / 255, 0.0)
yy, xx = np.mgrid[0:N, 0:N]
edge = np.minimum(np.minimum(xx, N - 1 - xx), np.minimum(yy, N - 1 - yy)) < band
for lab, pat in sets.items():
    e_in, e_edge = [], []
    for n in names:
        qm = q(f'{site}/{n}_measured-depth.png'); qq = q(pat.format(n=n))
        ok = (qm > 0) & (qq > 0)
        rel = np.abs(qq - qm) / np.maximum(qm, 1e-9)
        e_edge.append(rel[ok & edge]); e_in.append(rel[ok & ~edge])
    e_edge = np.concatenate(e_edge); e_in = np.concatenate(e_in)
    print(f'{lab:10s} inside: median {np.median(e_in)*100:.1f}% p90 {np.percentile(e_in,90)*100:.1f}%   within {band} px of an edge: median {np.median(e_edge)*100:.1f}% p90 {np.percentile(e_edge,90)*100:.1f}%')
