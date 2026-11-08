#!/usr/bin/env python3
"""
Brightened copies of a room's faces, for feature extraction only.

    python brighten_faces.py WORK/images WORK/images_feat

Nodes 27-41 of Voltaic's ENSI room sit in a nearly black cave passage, where
SIFT finds a fifth of the features it finds in daylight and seven links match
not at all. Features are only positions in the image, so they can be found on
an enhanced copy and used with the original: COLMAP is given images_feat for
feature_extractor and the original images for everything after (colours of the
points come from there). The originals stay the images of record.

Every face gets the same treatment, CLAHE on the lightness channel (OpenCV,
clip limit 3, 8x8 tiles), so a surface seen in daylight from one node and in
shade from the next is enhanced the same way and its descriptors still match.
Saved as JPEG at quality 98 under the same names, which the rig needs.

Needs opencv-python.
"""
import os
import sys

import cv2


def main():
    src, dst = sys.argv[1], sys.argv[2]
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
    n = 0
    for folder in sorted(os.listdir(src)):
        os.makedirs(os.path.join(dst, folder), exist_ok=True)
        for name in sorted(os.listdir(os.path.join(src, folder))):
            img = cv2.imread(os.path.join(src, folder, name))
            lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
            lab[:, :, 0] = clahe.apply(lab[:, :, 0])
            cv2.imwrite(os.path.join(dst, folder, name), cv2.cvtColor(lab, cv2.COLOR_LAB2BGR),
                        [cv2.IMWRITE_JPEG_QUALITY, 98])
            n += 1
    print(f'{n} faces brightened into {dst}')


if __name__ == '__main__':
    main()
