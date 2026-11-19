#!/usr/bin/env python3
r"""
The game's own fine detail carried onto every frame of a walk video, along the video's own motion.

    python detail_transfer.py FRAMES_DIR FIRST.png LAST.png OUT_DIR [--only first|last] [--sigma 2] [--fb 1.5]
        [--flow-scale 0.5] [--split 2]

FRAMES_DIR holds the walk's lossless frames (h3_flf.py's frames_s1/0000.png ...); FIRST.png and LAST.png are
walk_ends.py's drawings of the two nodes in the same layout and size (what the video model was given, before its
VAE took detail away). For each frame k, at s = k / (n - 1) along the walk:
  - the fine detail of FIRST and LAST (the picture less its Gaussian blur, --sigma px);
  - where each pixel of frame k is in the video's first frame and in its last: the optical flow (RAFT,
    torchvision's raft_large) between neighbouring frames, chained (one flow straight across a whole walk, --direct,
    trusted only 7% of LEIS 62 to 78's last frame); a pixel any of whose steps there and back misses by over --fb px
    (at full size) is not trusted;
  - FIRST's detail warped into frame k along the flow, and LAST's, mixed (1 - s) : s where trusted;
  - frame k's own fine detail replaced by the mix, as far as it is trusted: out = frame + c (mix - frame's detail).
Colour, light and broad shapes stay the video's. The flow is found at --flow-scale of the size, in --split squares
side by side (two for the two-fisheye layout, so no flow crosses the seam), and scaled up.
--nearest: each frame's detail from the nearer end only, at full weight (mid-walk the mix of both halves the
trust). --soft: trust falls smoothly with the misses rather than stopping at --fb (try --fb 3).
--only first (or last): every frame from that end alone, for testing: --only first, scored on the last frame
against the last node's faces (walk_fidelity.py --last), shows how far the detail carries across a whole walk.
Writes OUT_DIR/0000.png ... Needs torch, torchvision, numpy, opencv-python.
"""
import argparse
import glob
import os

import cv2
import numpy as np
import torch
from torchvision.models.optical_flow import Raft_Large_Weights, raft_large


def detail(img, sigma):
    f = img.astype(np.float32)
    return f - cv2.GaussianBlur(f, (0, 0), sigma)


class Flow:
    def __init__(self, scale):
        self.dev = 'cuda' if torch.cuda.is_available() else 'cpu'
        self.model = raft_large(weights=Raft_Large_Weights.DEFAULT).eval().to(self.dev)
        self.scale = scale
        self.cache = {}

    def __call__(self, a, b):
        key = (id(a), id(b))                                 # the same frames' flow is asked for again and again
        if key not in self.cache:
            self.cache[key] = self.find(a, b)
        return self.cache[key]

    @torch.no_grad()
    def find(self, a, b):
        """Flow from a to b (for each pixel of a, where it is in b), at full size, float32 HxWx2."""
        H, W = a.shape[:2]
        h, w = (int(round(H * self.scale / 8)) * 8, int(round(W * self.scale / 8)) * 8)
        t = lambda x: (torch.from_numpy(cv2.resize(x, (w, h), interpolation=cv2.INTER_AREA)).permute(2, 0, 1)[None]
                       .float().to(self.dev) / 127.5 - 1)
        f = self.model(t(a), t(b))[-1][0].permute(1, 2, 0).cpu().numpy()
        f = cv2.resize(f, (W, H), interpolation=cv2.INTER_LINEAR)
        f[..., 0] *= W / w; f[..., 1] *= H / h
        return f


def warp(img, flow):
    H, W = flow.shape[:2]
    gx, gy = np.meshgrid(np.arange(W, dtype=np.float32), np.arange(H, dtype=np.float32))
    return cv2.remap(img, gx + flow[..., 0], gy + flow[..., 1], cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)


def chained(flow, frames, k, j, fb, soft=False):
    """Where each pixel of frame k is in frame j, by composing the flows between neighbouring frames (each step
    small), and whether every step passed the there-and-back check."""
    H, W = frames[k].shape[:2]
    gx, gy = np.meshgrid(np.arange(W, dtype=np.float32), np.arange(H, dtype=np.float32))
    px, py, ok = gx.copy(), gy.copy(), (np.ones((H, W), np.float32) if soft else np.ones((H, W), bool))
    step = -1 if j < k else 1
    for i in range(k, j, step):
        f, g = flow(frames[i], frames[i + step]), flow(frames[i + step], frames[i])
        fx = cv2.remap(f[..., 0], px, py, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
        fy = cv2.remap(f[..., 1], px, py, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
        qx, qy = px + fx, py + fy
        bx = cv2.remap(g[..., 0], qx, qy, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
        by = cv2.remap(g[..., 1], qx, qy, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
        err = np.hypot(fx + bx, fy + by)
        inside = (qx >= 0) & (qx < W) & (qy >= 0) & (qy < H)
        if soft:                                           # each step's miss lowers the trust smoothly
            ok *= np.exp(-(err / fb) ** 2).astype(np.float32) * inside
        else:
            ok &= (err < fb) & inside
        px, py = qx, qy
    return px, py, ok


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('frames'); ap.add_argument('first'); ap.add_argument('last'); ap.add_argument('out')
    ap.add_argument('--only', choices=['first', 'last']); ap.add_argument('--sigma', type=float, default=2.0)
    ap.add_argument('--fb', type=float, default=1.5); ap.add_argument('--flow-scale', type=float, default=0.5)
    ap.add_argument('--split', type=int, default=2); ap.add_argument('--frames-only', type=int, nargs='*')
    ap.add_argument('--nearest', action='store_true', help='each frame from the nearer end alone (weight 1), not both mixed')
    ap.add_argument('--soft', action='store_true', help='trust falls smoothly with each step\'s there-and-back miss, exp(-(miss / fb)^2), not cut at --fb')
    ap.add_argument('--direct', action='store_true', help='one flow straight to the end frame, not chained through the frames between')
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    paths = sorted(glob.glob(os.path.join(a.frames, '*.png')))
    rd = lambda p: cv2.cvtColor(cv2.imread(p), cv2.COLOR_BGR2RGB)
    frames = [rd(p) for p in paths]
    n = len(frames)
    ends = {'first': (0, rd(a.first)), 'last': (n - 1, rd(a.last))}
    dends = {k: detail(v[1], a.sigma) for k, v in ends.items()}
    flow = Flow(a.flow_scale)
    H, W = frames[0].shape[:2]
    S = W // a.split
    circles = [[np.ascontiguousarray(f[:, c * S:(c + 1) * S]) for f in frames] for c in range(a.split)]
    stats = []
    for k in (a.frames_only if a.frames_only else range(n)):
        s = k / (n - 1)
        fr = frames[k]
        mix, wsum = np.zeros((H, W, 3), np.float32), np.zeros((H, W), np.float32)
        for name, (j, _) in ends.items():
            if a.only and name != a.only:
                continue
            if a.nearest and name != ('first' if s <= .5 else 'last'):
                continue
            wt = (1 - s if name == 'first' else s) if not (a.only or a.nearest) else 1.0
            if wt <= 0:
                continue
            for c in range(a.split):
                sl = np.s_[:, c * S:(c + 1) * S]
                fk, fj = fr[sl], frames[j][sl]
                if j == k:
                    w_hf, ok = dends[name][sl], np.ones(fk.shape[:2], bool)
                elif a.direct:
                    f_kj, f_jk = flow(fk, fj), flow(fj, fk)
                    back = warp(f_jk, f_kj)                     # f_jk at the point f_kj lands on
                    ok = np.linalg.norm(f_kj + back, axis=-1) < a.fb
                    w_hf = warp(np.ascontiguousarray(dends[name][sl]), f_kj)
                else:
                    px, py, ok = chained(flow, circles[c], k, j, a.fb, a.soft)
                    w_hf = cv2.remap(np.ascontiguousarray(dends[name][sl]), px, py, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
                mix[sl] += wt * ok[..., None] * w_hf; wsum[sl] += wt * ok
        tot = 1.0 if a.only else 1.0                          # (1 - s) + s
        conf = np.clip(wsum / tot, 0, 1)
        mix = mix / np.maximum(wsum, 1e-6)[..., None]
        out = fr.astype(np.float32) + conf[..., None] * (mix - detail(fr, a.sigma))
        cv2.imwrite(os.path.join(a.out, f'{k:04d}.png'), cv2.cvtColor(np.clip(np.rint(out), 0, 255).astype(np.uint8), cv2.COLOR_RGB2BGR))
        stats.append((k, float(conf.mean())))
        print(f'frame {k}: trusted {conf.mean() * 100:.0f}% of pixels', flush=True)


if __name__ == '__main__':
    main()
