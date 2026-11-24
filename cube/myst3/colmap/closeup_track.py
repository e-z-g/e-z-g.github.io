"""Where each frame of a close-up's move in lies within its first frame: a similarity (zoom, turn, shift) per frame,
for showing the move in the room with every frame set where its content is (tomahna_walks.html). SIFT matches between
consecutive frames, a RANSAC similarity (cv2.estimateAffinePartial2D), chained from the first frame; each step's
inliers and error are printed.

    python closeup_track.py VIDEO.mp4 [VIDEO.mp4 ...] --out TRACK.json [--colour COLOUR.json]

TRACK.json: { "<video name without .mp4>": [[a, b, tx], [c, d, ty]] per frame }, frame k's pixel (x, y, 1) to frame 0's
pixel, both in the video's own pixels (640x360), frame 0 the identity.
COLOUR.json: { "<name>": [[r, g, b] per frame] }, how much brighter each frame is than the first frame where they show
the same things (frame k set into frame 0 by its similarity, both blurred, the ratio of their means per channel, in the
video's own sRGB levels): the game's close-up pictures are graded unlike the node's faces (30 to 40 levels brighter
for some, up to 60 darker for others), and H3 drifts between the two.
"""
import argparse, json, os
import numpy as np, cv2


def frames(path):
    cap = cv2.VideoCapture(path)
    while True:
        ok, f = cap.read()
        if not ok:
            return
        yield cv2.cvtColor(f, cv2.COLOR_BGR2GRAY)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('videos', nargs='+'); ap.add_argument('--out', required=True); ap.add_argument('--colour')
    a = ap.parse_args()
    sift = cv2.SIFT_create(4000); bf = cv2.BFMatcher(cv2.NORM_L2)
    out = json.load(open(a.out)) if os.path.exists(a.out) else {}
    for v in a.videos:
        name = os.path.basename(v)[:-4]
        fr = list(frames(v)); M = [np.eye(3)]
        kp0, d0 = sift.detectAndCompute(fr[0], None)
        for k in range(1, len(fr)):
            kp1, d1 = sift.detectAndCompute(fr[k], None)
            good = [m for m, n in bf.knnMatch(d1, d0, k=2) if m.distance < 0.75 * n.distance]
            p1 = np.float32([kp1[m.queryIdx].pt for m in good]); p0 = np.float32([kp0[m.trainIdx].pt for m in good])
            A, inl = cv2.estimateAffinePartial2D(p1, p0, method=cv2.RANSAC, ransacReprojThreshold=2.0, maxIters=5000)
            if A is None:
                raise SystemExit(f'{name}: frame {k} not matched to {k - 1}')
            n_in = int(inl.sum()); res = np.abs((np.c_[p1, np.ones(len(p1))] @ A.T - p0)[inl[:, 0] == 1]).mean()
            M.append(M[-1] @ np.vstack([A, [0, 0, 1]]))
            s = np.sqrt(abs(np.linalg.det(M[-1][:2, :2])))
            print(f'{name} {k:2d}: {n_in:4d} of {len(good):4d} matches, error {res:.2f} px; frame k is 1/{1 / s:.2f} of frame 0, centre at '
                  f'({(M[-1] @ [320, 180, 1])[0]:.0f}, {(M[-1] @ [320, 180, 1])[1]:.0f})')
            kp0, d0 = kp1, d1
        out[name] = [m[:2].round(6).tolist() for m in M]
        if a.colour:
            col = json.load(open(a.colour)) if os.path.exists(a.colour) else {}
            cap = cv2.VideoCapture(v); rgb = []
            while True:
                ok, f = cap.read()
                if not ok:
                    break
                rgb.append(cv2.GaussianBlur(f.astype(np.float32), (0, 0), 3))
            g = []
            for k, f in enumerate(rgb):
                A = np.float32(M[k][:2]); w = cv2.warpAffine(f, A, (640, 360), flags=cv2.INTER_AREA)
                m = cv2.erode((cv2.warpAffine(np.ones((360, 640), np.float32), A, (640, 360)) > 0.99).astype(np.uint8), np.ones((5, 5))) > 0
                g.append((w[m].mean(0) / np.maximum(rgb[0][m].mean(0), 1))[::-1].round(4).tolist())   # BGR to RGB
            col[name] = g; json.dump(col, open(a.colour, 'w'), indent=0)
            print(f'{name}: last frame against the first, brighter by', ' '.join(f'{x:.2f}' for x in g[-1]))
    json.dump(out, open(a.out, 'w'), indent=0)


if __name__ == '__main__':
    main()
