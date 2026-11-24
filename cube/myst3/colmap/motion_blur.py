"""Motion blur for a walk's two-fisheye frames, from optical flow, to hide detail the video model redraws as it
moves fast (the ground underfoot): each pixel is averaged along its own motion over a shutter of --shutter frame
intervals (0.5: half the way to the frame before and after, the "180-degree shutter"). Flow is DIS, per eye, from
each frame to the frames either side. The first and last frames (the node pictures) are left as they are, and the
shutter eases in over --ramp frames from each end, so the walk starts and ends on the untouched pictures.

    python motion_blur.py FRAMES_DIR OUT_DIR [--shutter 0.5] [--ramp 3] [--samples 15]

FRAMES_DIR holds 0000.png ... as walk_polar3.ps1's final; the frame is two squares side by side (W = 2H).
"""
import argparse, glob, os
import numpy as np, cv2


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('frames'); ap.add_argument('out')
    ap.add_argument('--shutter', type=float, default=0.5); ap.add_argument('--ramp', type=int, default=3)
    ap.add_argument('--samples', type=int, default=15)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    paths = sorted(glob.glob(os.path.join(a.frames, '*.png'))); n = len(paths)
    dis = cv2.DISOpticalFlow_create(cv2.DISOPTICAL_FLOW_PRESET_MEDIUM)
    gray = {}
    def g(k):
        if k not in gray:
            gray[k] = cv2.cvtColor(cv2.imread(paths[k]), cv2.COLOR_BGR2GRAY)
            for old in [j for j in gray if j < k - 1]: del gray[old]
        return gray[k]
    for k in range(n):
        img = cv2.imread(paths[k]); H = img.shape[0]
        r = min(1.0, k / a.ramp, (n - 1 - k) / a.ramp) if a.ramp > 0 else (0.0 if k in (0, n - 1) else 1.0)
        s = a.shutter * r
        if s <= 0:
            cv2.imwrite(os.path.join(a.out, os.path.basename(paths[k])), img); continue
        out = img.astype(np.float32); moved = []
        yy, xx = np.mgrid[0:H, 0:H].astype(np.float32)
        for e in (0, 1):
            sl = slice(e * H, (e + 1) * H)
            cur = np.ascontiguousarray(g(k)[:, sl])
            fp = dis.calc(cur, np.ascontiguousarray(g(k - 1)[:, sl]), None)   # where each pixel was a frame before
            fn = dis.calc(cur, np.ascontiguousarray(g(k + 1)[:, sl]), None)   # and will be a frame after
            src = np.ascontiguousarray(img[:, sl]); acc = np.zeros(src.shape, np.float32)
            for t in np.linspace(-s / 2, s / 2, a.samples):
                f = (fn * t if t >= 0 else fp * -t).astype(np.float32)        # the content's place at time t
                acc += cv2.remap(src, xx + f[..., 0], yy + f[..., 1], cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
            out[:, sl] = acc / a.samples
            moved.append(np.median(np.hypot(*fn.transpose(2, 0, 1))))
        cv2.imwrite(os.path.join(a.out, os.path.basename(paths[k])), np.clip(out + 0.5, 0, 255).astype(np.uint8))
        print(f'frame {k}: shutter {s:.2f}, median motion to the next frame {moved[0]:.1f} / {moved[1]:.1f} px (front / back eye)')
    print(f'{n} frames -> {a.out}')


if __name__ == '__main__':
    main()
