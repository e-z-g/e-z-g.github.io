#!/usr/bin/env python3
"""
Frames of a Myst III movie as extra views for a room or age already laid out for
COLMAP, with the image list and match pairs to register them.

    python video_frames.py WORK MOVIE.bik TAG [--every 2] [--key-every 8] [--seq 6]
                           [--ffmpeg PATH] [--mask MASK.png]

Writes WORK/images/<TAG>/<TAG>-NNNN.jpg (every --every-th frame, from ffmpeg),
brightened copies in WORK/images_feat/<TAG>/ (CLAHE as brighten_faces.py), and
WORK/<TAG>/:
  list.txt        the frames' names, for feature_extractor --image_list_path
  pairs_seq.txt   each frame with the next --seq frames (video alone)
  pairs_all.txt   the same, plus every --key-every-th frame with every node face in
                  WORK/images (f1..f6), for registering the movie among the nodes
--mask copies a mask (white = use) to WORK/masks/<TAG>/<frame>.png for each
frame, for parts that move with the camera (a cockpit, a glass ball).
Needs opencv-python.
"""
import argparse
import os
import shutil
import subprocess

import cv2


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('work'); ap.add_argument('movie'); ap.add_argument('tag')
    ap.add_argument('--every', type=int, default=2)
    ap.add_argument('--key-every', type=int, default=8)
    ap.add_argument('--seq', type=int, default=6)
    ap.add_argument('--ffmpeg', default='ffmpeg')
    ap.add_argument('--mask')
    a = ap.parse_args()
    img_dir = os.path.join(a.work, 'images', a.tag)
    feat_dir = os.path.join(a.work, 'images_feat', a.tag)
    meta = os.path.join(a.work, a.tag)
    for d in (img_dir, feat_dir, meta):
        os.makedirs(d, exist_ok=True)
    subprocess.run([a.ffmpeg, '-v', 'error', '-y', '-i', a.movie, '-vf', f'select=not(mod(n\\,{a.every}))',
                    '-fps_mode', 'passthrough', '-q:v', '2', os.path.join(img_dir, f'{a.tag}-%04d.jpg')], check=True)
    frames = sorted(os.listdir(img_dir))
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
    for f in frames:
        img = cv2.imread(os.path.join(img_dir, f))
        lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
        lab[:, :, 0] = clahe.apply(lab[:, :, 0])
        cv2.imwrite(os.path.join(feat_dir, f), cv2.cvtColor(lab, cv2.COLOR_LAB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 98])
        if a.mask:
            md = os.path.join(a.work, 'masks', a.tag)
            os.makedirs(md, exist_ok=True)
            shutil.copyfile(a.mask, os.path.join(md, f + '.png'))
    names = [f'{a.tag}/{f}' for f in frames]
    with open(os.path.join(meta, 'list.txt'), 'w', newline='\n') as fh:
        fh.writelines(n + '\n' for n in names)
    seq = [(names[i], names[j]) for i in range(len(names)) for j in range(i + 1, min(len(names), i + 1 + a.seq))]
    with open(os.path.join(meta, 'pairs_seq.txt'), 'w', newline='\n') as fh:
        fh.writelines(f'{p} {q}\n' for p, q in seq)
    faces = [f'f{k}/{n}' for k in range(1, 7) for n in sorted(os.listdir(os.path.join(a.work, 'images', f'f{k}')))]
    cross = [(names[i], face) for i in range(0, len(names), a.key_every) for face in faces]
    with open(os.path.join(meta, 'pairs_all.txt'), 'w', newline='\n') as fh:
        fh.writelines(f'{p} {q}\n' for p, q in seq + cross)
    print(f'{len(frames)} frames; {len(seq)} sequential pairs; {len(cross)} key-frame x face pairs '
          f'({len(range(0, len(names), a.key_every))} key frames, {len(faces)} faces)')


if __name__ == '__main__':
    main()
