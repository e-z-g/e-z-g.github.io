#!/usr/bin/env python3
r"""
Depth from a walk's two polar ends (walk_ends.py --polar, both drawn facing along the line from A to B) as a stereo
pair. In that layout a thing that stays still keeps its column and only slides down it, from the angle THETA_A from
straight ahead at A to THETA_B at B, so the two pictures are already rectified: turned a quarter turn, the columns
are rows, and OpenCV's StereoSGBM matches along them. The sine rule then gives each pixel's distance,
|AP| = APART sin(THETA_B) / sin(THETA_B - THETA_A), and where it is seen from any point on the line.

    python polar_stereo.py FIRST.png LAST.png OUT_DIR --apart 4.381 [--scale 0.5] [--max-deg 110] [--block 5]
        [--check MATCHES]   SIFT matches between the two ends, to check the disparities against
        [--mid 0.25 0.5 0.75]   pictures drawn from those points of the way, each column warped as a line of pixels

Writes OUT_DIR/disp_a.npy, disp_b.npy (rows of THETA moved, at each end's pixels; NaN where not found or where the
two directions disagree), dist_a.npy, dist_b.npy (in the model's units), depth.jpg (both ends and their distance),
and mid_T.png (black where neither end has a pixel). Needs numpy, opencv-python.
"""
import argparse
import os

import cv2
import numpy as np


def sgbm(left, right, D, block):
    # disparity on LEFT's pixels, matched along the rows: x_right = x_left - d, 0 <= d < D
    pad = lambda x: cv2.copyMakeBorder(x, 0, 0, D, 0, cv2.BORDER_REPLICATE)
    m = cv2.StereoSGBM_create(minDisparity=0, numDisparities=D, blockSize=block, P1=8 * 3 * block ** 2,
                              P2=32 * 3 * block ** 2, disp12MaxDiff=-1, uniquenessRatio=5, speckleWindowSize=100,
                              speckleRange=2, mode=cv2.STEREO_SGBM_MODE_HH)
    d = m.compute(pad(left), pad(right)).astype(np.float32)[:, D:] / 16.0
    d[d < 0] = np.nan
    return d


def disparities(A, B, D, block, tol=2.0):
    # polar pictures (rows: theta down from straight ahead) -> rows moved at A's and at B's pixels, cross-checked
    a, b = cv2.cvtColor(A, cv2.COLOR_BGR2GRAY).T.copy(), cv2.cvtColor(B, cv2.COLOR_BGR2GRAY).T.copy()
    dB = sgbm(b, a, D, block).T                                     # B is the left picture: v_A = v_B - d
    dA = sgbm(a[:, ::-1].copy(), b[:, ::-1].copy(), D, block)[:, ::-1].T   # flipped, A on the left: v_B = v_A + d
    H, W = dA.shape
    v, u = np.mgrid[0:H, 0:W].astype(np.float32)
    # cross-check: follow A's disparity to B and back
    vb = np.clip(np.rint(v + np.nan_to_num(dA, nan=-1e4)), -1, H)
    ok = (vb >= 0) & (vb < H)
    back = np.full_like(dA, np.nan)
    back[ok] = dB[vb[ok].astype(int), u[ok].astype(int)]
    dA[~(np.abs(back - dA) <= tol)] = np.nan
    va = np.clip(np.rint(v - np.nan_to_num(dB, nan=1e4)), -1, H)
    ok = (va >= 0) & (va < H)
    fwd = np.full_like(dB, np.nan)
    fwd[ok] = dA[va[ok].astype(int), u[ok].astype(int)]
    dB[~(np.abs(fwd - dB) <= tol)] = np.nan
    return dA, dB


def thetas(H):
    return (np.arange(H, dtype=np.float64) + .5) / H * np.pi


def to_3d(thA, thB, apart):
    # along the line from A and out from it, for a point at THETA_A from A and THETA_B from B (infinite if equal)
    with np.errstate(divide='ignore', invalid='ignore'):
        dA = apart * np.sin(thB) / np.sin(thB - thA)
    dA = np.where(np.isnan(thB - thA), np.nan, np.where(thB - thA > 1e-6, dA, np.inf))
    return dA * np.cos(thA), dA * np.sin(thA), dA


def warp_column_set(img, th_src, along, out_r, T, apart, H):
    # every column of IMG warped to the point T of the way: each pair of neighbours in a column drawn as a span,
    # unless they are far apart in depth; nearest wins. Returns colour and distance from the new point.
    Hs, W = th_src.shape
    with np.errstate(invalid='ignore'):
        th_t = np.where(np.isinf(along), th_src, np.arctan2(out_r, along - T * apart))     # NaN where not found
        dist = np.where(np.isinf(along), np.inf, np.hypot(out_r, along - T * apart))
    vt = th_t / np.pi * H - .5
    col = np.zeros((H, W, 3), np.float32); zb = np.full((H, W), np.inf)
    good = np.isfinite(th_t)
    for u in range(W):
        g = good[:, u]
        idx = np.nonzero(g)[0]
        if len(idx) < 2:
            continue
        i0, i1 = idx[:-1], idx[1:]
        cont = (i1 - i0 == 1)
        z0, z1 = dist[i0, u], dist[i1, u]
        with np.errstate(invalid='ignore'):
            near = np.where(np.isfinite(z0) & np.isfinite(z1), np.abs(z0 - z1) / np.minimum(z0, z1) < 0.08, np.isinf(z0) & np.isinf(z1))
        seg = cont & near
        y0, y1 = vt[i0[seg], u], vt[i1[seg], u]
        lo, hi = np.ceil(np.minimum(y0, y1)), np.floor(np.maximum(y0, y1))
        n = np.maximum(hi - lo + 1, 0).astype(int)
        if n.sum() == 0:
            continue
        k = np.repeat(np.arange(len(n)), n)
        y = (np.repeat(lo, n) + np.arange(n.sum()) - np.repeat(np.cumsum(n) - n, n)).astype(int)
        inb = (y >= 0) & (y < H)
        k, y = k[inb], y[inb]
        f = np.clip((y - y0[k]) / np.where(y1[k] != y0[k], y1[k] - y0[k], 1), 0, 1)
        a, b = i0[seg][k], i1[seg][k]
        c = img[a, u] * (1 - f)[:, None] + img[b, u] * f[:, None]
        z = np.where(np.isfinite(z0[seg][k]), z0[seg][k] * (1 - f) + z1[seg][k] * f, np.inf)
        z = np.where(np.isnan(z), np.inf, z)
        order = np.argsort(-z, kind='stable')                     # far first, so the near ones are written last
        y, c, z = y[order], c[order], z[order]
        col[y, u] = c; zb[y, u] = z
    filled = np.zeros((H, W), bool)
    filled[zb < np.inf] = True
    filled |= col.sum(-1) > 0                                       # far (infinite) pixels drawn too
    return col, zb, filled


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('first'); ap.add_argument('last'); ap.add_argument('out')
    ap.add_argument('--apart', type=float, required=True); ap.add_argument('--scale', type=float, default=0.5)
    ap.add_argument('--max-deg', type=float, default=110.0); ap.add_argument('--block', type=int, default=5)
    ap.add_argument('--check'); ap.add_argument('--mid', type=float, nargs='*', default=[])
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    A0, B0 = cv2.imread(a.first), cv2.imread(a.last)
    A = cv2.resize(A0, None, fx=a.scale, fy=a.scale, interpolation=cv2.INTER_AREA)
    B = cv2.resize(B0, None, fx=a.scale, fy=a.scale, interpolation=cv2.INTER_AREA)
    H, W = A.shape[:2]
    D = int(np.ceil(a.max_deg / 180 * H / 16)) * 16
    dA, dB = disparities(A, B, D, a.block)
    np.save(os.path.join(a.out, 'disp_a.npy'), dA); np.save(os.path.join(a.out, 'disp_b.npy'), dB)
    th = thetas(H)[:, None] * np.ones((1, W))
    print(f'{W}x{H}, disparities up to {D} rows ({D / H * 180:.0f} degrees); found at A {np.isfinite(dA).mean():.0%}, '
          f'at B {np.isfinite(dB).mean():.0%}')
    alongA, outA, distA = to_3d(th, th + dA / H * np.pi, a.apart)
    alongB, outB, _ = to_3d(th - dB / H * np.pi, th, a.apart)
    distB = np.hypot(alongB - a.apart, outB)
    np.save(os.path.join(a.out, 'dist_a.npy'), distA); np.save(os.path.join(a.out, 'dist_b.npy'), distB)

    def vis(d):
        x = np.clip(np.log(np.nan_to_num(d, nan=np.inf, posinf=1e9)) / np.log(60), 0, 1)
        c = cv2.applyColorMap((255 * (1 - x)).astype(np.uint8), cv2.COLORMAP_TURBO)
        c[~np.isfinite(d)] = 0
        c[np.isinf(d)] = (90, 40, 40)
        return c
    cv2.imwrite(os.path.join(a.out, 'depth.jpg'), np.vstack([np.hstack([A, vis(distA)]), np.hstack([B, vis(distB)])]),
                [cv2.IMWRITE_JPEG_QUALITY, 85])

    if a.check:
        m = np.load(a.check)                                         # rows: xA yA xB yB at full size
        xa, ya, xb, yb = (m[:, i] * a.scale for i in range(4))
        true = yb - ya
        got = dA[np.clip(np.rint(ya - .5).astype(int), 0, H - 1), np.clip(np.rint(xa - .5).astype(int), 0, W - 1)]
        k = np.isfinite(got)
        err = np.abs(got[k] - true[k]) / H * 180
        print(f'check: {k.sum()} of {len(true)} matches have a disparity at A; error median {np.median(err):.2f} deg, '
              f'90% {np.percentile(err, 90):.2f}, worst {err.max():.2f} (true moves {np.median(true / H * 180):.1f} deg median)')

    for T in a.mid:
        cA, zA, fA = warp_column_set(A.astype(np.float32), th, alongA, outA, T, a.apart, H)
        cB, zB, fB = warp_column_set(B.astype(np.float32), th, alongB, outB, T, a.apart, H)
        both = fA & fB
        close = both & (np.abs(np.where(np.isfinite(zA), zA, 1e9) - np.where(np.isfinite(zB), zB, 1e9))
                        <= 0.08 * np.minimum(np.where(np.isfinite(zA), zA, 1e9), np.where(np.isfinite(zB), zB, 1e9)) + 1e-9)
        out = np.zeros_like(cA)
        out[fA & ~fB] = cA[fA & ~fB]; out[fB & ~fA] = cB[fB & ~fA]
        out[close] = (1 - T) * cA[close] + T * cB[close]
        pickA = both & ~close & (zA < zB); pickB = both & ~close & ~(zA < zB)
        out[pickA] = cA[pickA]; out[pickB] = cB[pickB]
        print(f'mid {T}: from A only {(fA & ~fB).mean():.0%}, B only {(fB & ~fA).mean():.0%}, both {both.mean():.0%}, '
              f'neither {(~fA & ~fB).mean():.0%}')
        cv2.imwrite(os.path.join(a.out, f'mid_{T:g}.png'), np.clip(out, 0, 255).astype(np.uint8))


if __name__ == '__main__':
    main()
