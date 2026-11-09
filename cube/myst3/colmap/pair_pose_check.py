#!/usr/bin/env python3
"""
Whether a model has two nodes in the right places relative to each other,
from the two nodes' pictures alone.

    python pair_pose_check.py IMAGES SPARSE_TXT NODE_A NODE_B [--wide 1024] [--check 1.5]

For each of A's six faces, both nodes' panoramas are drawn as one wide picture
looking that way (walk_flow.wide_view), with the model's rotations, so that if
the model is right the two differ by the step between the nodes only. RAFT
matches them both ways; matches that come back within --check px are kept.
From those, cv2.findEssentialMat and recoverPose give the turn and the
direction of the step that the pictures themselves imply, which is printed
beside the model's: the angle between the two directions, the turn the
pictures imply (should be about 0 degrees), and how far the matches lie
from their epipolar lines, in px, under each. Needs numpy, opencv-python,
torch, torchvision; walk_flow.py and view_check.py beside it.
"""
import argparse
import os
import sys

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from view_check import read_model  # noqa: E402
from walk_flow import load, wide_view  # noqa: E402

ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument('images'); ap.add_argument('sparse'); ap.add_argument('a'); ap.add_argument('b')
ap.add_argument('--wide', type=int, default=1024); ap.add_argument('--check', type=float, default=1.5)
ap.add_argument('--depth-dir', help='unused; walk_flow.load needs a depth dir: any with the nodes\' depths')
a = ap.parse_args()
import torch
from torchvision.models.optical_flow import raft_large, Raft_Large_Weights
dev = 'cuda' if torch.cuda.is_available() else 'cpu'
net = raft_large(weights=Raft_Large_Weights.DEFAULT).to(dev).eval()
flow = lambda p, q: net(torch.from_numpy(p).permute(2, 0, 1)[None].float().to(dev) / 127.5 - 1,
                        torch.from_numpy(q).permute(2, 0, 1)[None].float().to(dev) / 127.5 - 1,
                        num_flow_updates=24)[-1][0].permute(1, 2, 0).detach().cpu().numpy().astype(np.float64)
_, imgs = read_model(a.sparse)


def node(n):
    faces = {}
    for k in range(1, 7):
        R, t = imgs[f'f{k}/MA-{n}.jpg'][:2]
        img = cv2.cvtColor(cv2.imread(os.path.join(a.images, f'f{k}', f'MA-{n}.jpg')), cv2.COLOR_BGR2RGB)
        faces[k] = dict(R=R, t=t, img=img, N=img.shape[0])
    return dict(node=n, C=-faces[1]['R'].T @ faces[1]['t'], faces=faces)


A, B = node(a.a), node(a.b)
W = a.wide
P1, P2 = [], []
for k, fc in A['faces'].items():
    R = fc['R']; f = fc['N'] / 2
    pa, _ = wide_view(A, R, W, f); pb, _ = wide_view(B, R, W, f)
    with torch.no_grad():
        fab = flow(pa, pb); fba = flow(pb, pa)
    v, u = np.mgrid[0:W, 0:W].astype(np.float64)
    u2, v2 = u + fab[..., 0], v + fab[..., 1]
    back = np.stack([cv2.remap(fba[..., i].astype(np.float32), u2.astype(np.float32), v2.astype(np.float32),
                               cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=1e4) for i in range(2)], -1)
    err = np.hypot(fab[..., 0] + back[..., 0], fab[..., 1] + back[..., 1])
    texture = cv2.Laplacian(cv2.cvtColor(pa.astype(np.uint8), cv2.COLOR_RGB2GRAY), cv2.CV_32F, ksize=3)
    ok = (err < a.check) & (np.hypot(*fab.transpose(2, 0, 1)) > 2) & (np.abs(texture) > 8)
    ok[:8] = ok[-8:] = False; ok[:, :8] = ok[:, -8:] = False
    sel = np.flatnonzero(ok.ravel())
    if len(sel) > 4000:
        sel = np.random.default_rng(0).choice(sel, 4000, replace=False)
    yy, xx = np.unravel_index(sel, ok.shape)
    # normalised camera coordinates of this wide camera, then turned to the world (both cameras share R)
    c1 = np.stack([(xx + .5 - W / 2) / f, (yy + .5 - W / 2) / f, np.ones(len(xx))], 1)
    c2 = np.stack([(u2[yy, xx] + .5 - W / 2) / f, (v2[yy, xx] + .5 - W / 2) / f, np.ones(len(xx))], 1)
    P1.append(c1 @ R); P2.append(c2 @ R)
    print(f'face {k}: {len(xx)} matches kept (of {ok.sum()})', flush=True)
d1 = np.concatenate(P1); d2 = np.concatenate(P2)
d1 /= np.linalg.norm(d1, axis=1, keepdims=True); d2 /= np.linalg.norm(d2, axis=1, keepdims=True)
tm = B['C'] - A['C']; tm /= np.linalg.norm(tm)


def epi(t, Rr=np.eye(3)):
    """Angle (degrees) of each match from its epipolar plane: B's ray turned by Rr, the step t."""
    n = np.cross(t, d1)
    n /= np.linalg.norm(n, axis=1, keepdims=True)
    return np.degrees(np.abs(np.arcsin(np.clip(((d2 @ Rr.T) * n).sum(1), -1, 1))))


# the pictures' own: a robust fit over all the matches, in a shared frame (world directions as camera
# coordinates of one camera looking along +z would wrap; fit with a general essential matrix on unit rays)
def fit(d1, d2, iters=4000, thr=0.15):
    rng = np.random.default_rng(1)
    best, bi = None, -1
    for _ in range(iters):
        i = rng.choice(len(d1), 2, replace=False)
        # with no turn, t is perpendicular to both d1 x d2 (two matches fix it)
        c = np.cross(np.cross(d1[i[0]], d2[i[0]]), np.cross(d1[i[1]], d2[i[1]]))
        if np.linalg.norm(c) < 1e-9:
            continue
        t = c / np.linalg.norm(c)
        # the step's sign: points must be in front of both
        if np.median(((d1 - d2) @ t)) < 0:
            t = -t
        inl = (epi(t) < thr).sum()
        if inl > bi:
            best, bi = t, inl
    inl = epi(best) < thr
    # refine on the inliers: smallest singular vector of the stacked (d1 x d2)
    M = np.cross(d1[inl], d2[inl])
    t = np.linalg.svd(M)[2][-1]
    return (t if t @ best > 0 else -t), inl.mean()


tp, share = fit(d1, d2)
ang = np.degrees(np.arccos(np.clip(tp @ tm, -1, 1)))
print(f'{len(d1)} matches. Step {a.a} -> {a.b}: the model\'s direction {np.round(tm, 3)}, the pictures\' {np.round(tp, 3)}: '
      f'{ang:.1f} degrees apart')
for lab, t in (("model's", tm), ("pictures'", tp)):
    e = epi(t)
    print(f'  under the {lab} direction: matches from their epipolar planes median {np.median(e):.3f} deg, '
          f'90% {np.percentile(e, 90):.3f} deg (1 px at the face scale is {np.degrees(1 / 320):.3f} deg); within 0.15 deg {np.mean(e < .15) * 100:.0f}%')
# a turn between the nodes: fit a small rotation with the pictures' step (Gauss-Newton on the epipolar error)
Rr = np.eye(3); t = tp.copy()
for _ in range(10):
    def res(w, t):
        th = np.linalg.norm(w)
        Rw = cv2.Rodrigues(w)[0] if th > 0 else np.eye(3)
        n = np.cross(t, d1); n /= np.linalg.norm(n, axis=1, keepdims=True)
        return ((d2 @ (Rw @ Rr).T) * n).sum(1)
    w0 = np.zeros(3)
    r0 = res(w0, t)
    keep = np.abs(r0) < np.percentile(np.abs(r0), 80)
    J = np.stack([(res(e * 1e-5, t) - r0) / 1e-5 for e in np.eye(3)], 1)
    dw = np.linalg.lstsq(J[keep], -r0[keep], rcond=None)[0]
    Rr = cv2.Rodrigues(dw)[0] @ Rr
turn = np.degrees(np.linalg.norm(cv2.Rodrigues(Rr)[0]))
e = epi(tp, Rr)
print(f'  with a turn of {turn:.2f} degrees between the nodes as well: median {np.median(e):.3f} deg, 90% {np.percentile(e, 90):.3f} deg')
