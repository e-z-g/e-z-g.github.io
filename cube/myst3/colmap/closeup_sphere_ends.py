"""The two end pictures for a close-up rendered as a whole 360-degree move (two 180-degree fisheyes, as the walks): the first
the node's six faces facing the hotspot (walk_ends_heading.py's drawing, at the hotspot's heading and pitch), the last the
close-up picture straight ahead, 90 degrees across as the game shows it, and black all round it (the letterbox and
pillarbox the close-up's view ends in), so H3 draws the move into the object out of the whole room.

    python closeup_sphere_ends.py FACES_PREFIX CLOSEUP.png OUT_DIR --heading H --pitch P [--size 2560x1280]

Writes OUT_DIR/first.png and OUT_DIR/last.png.
"""
import argparse, os, subprocess, sys
import numpy as np, cv2
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from walk_ends import draw_dual_fisheye   # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('faces'); ap.add_argument('closeup'); ap.add_argument('out')
    ap.add_argument('--heading', type=float, required=True); ap.add_argument('--pitch', type=float, required=True)
    ap.add_argument('--size', default='2560x1280')
    a = ap.parse_args(); W, H = map(int, a.size.split('x'))
    os.makedirs(a.out, exist_ok=True)
    here = os.path.dirname(os.path.abspath(__file__))
    tmp = os.path.join(a.out, 'room')
    subprocess.run([sys.executable, os.path.join(here, 'walk_ends_heading.py'), a.faces, a.faces, tmp, '--heading', f'{a.heading:.6f}',
                    '--pitch', f'{a.pitch:.6f}', '--size', a.size, '--dual-fisheye', '180', '--fill-square', '--squash', '0.35'], check=True)
    os.replace(os.path.join(tmp, 'first.png'), os.path.join(a.out, 'first.png'))
    # the close-up as one face straight ahead in the camera's own frame (x right, y down, z ahead): a square face spans
    # 90 degrees both ways, so the 16:9 picture sits in its middle rows, black above and below; outside it, black
    c = cv2.cvtColor(cv2.imread(a.closeup), cv2.COLOR_BGR2RGB); S = c.shape[1]
    sq = np.zeros((S, S, 3), np.uint8); h = round(S * 9 / 16); y0 = (S - h) // 2
    sq[y0:y0 + h] = cv2.resize(c, (S, h), interpolation=cv2.INTER_CUBIC)
    img = draw_dual_fisheye([(np.eye(3), None, sq)], np.eye(3), W, H, 180.0, 0.0, 0.35, True)
    cv2.imwrite(os.path.join(a.out, 'last.png'), cv2.cvtColor(img, cv2.COLOR_RGB2BGR))
    print(f'{os.path.basename(a.faces)} at heading {a.heading}, pitch {a.pitch}; {a.closeup} ahead, 90 degrees across -> {a.out}')


if __name__ == '__main__':
    main()
