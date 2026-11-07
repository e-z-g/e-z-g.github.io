#!/usr/bin/env python3
"""
Write solved node poses as a COLMAP text model, ready for point_triangulator and
bundle_adjuster.

    python build_model.py WORK/runs/TAG/database.db SOLVED.json OUT_DIR

SOLVED.json is solve_nodes.py's nodes_solved.json. Each node becomes one frame of
the six-face rig already in the database (frame and image ids are read from it,
so the model and the database agree), posed at the solved centre and rotation;
points3D.txt is left empty for point_triangulator to fill.

Why: solve_nodes.py gets every node's rotation and the direction of every step
from the pictures, but a direction says nothing about how far, so along a chain
of nodes with no loop every step comes out the minimum length. COLMAP measures
lengths from the 3D points two steps share. Triangulating with these poses held,
then bundle adjustment with the rotations held (constant_rig_from_world_rotation)
and only positions and points free, takes the lengths from the points and keeps
everything the pictures already settled.

Frames: COLMAP's rig_from_world is the reference sensor's (face 1) camera pose,
cam_from_node(face 1) times node_from_world; the world is the solve's reference
node's frame. Standard library and numpy.
"""
import json
import os
import re
import sqlite3
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from face_geometry import cam_from_node, quat_wxyz, rotations  # noqa: E402


def main():
    db_path, solved_path, out = sys.argv[1:4]
    db = sqlite3.connect(db_path)
    solved = json.load(open(solved_path))
    os.makedirs(out, exist_ok=True)

    images = {i: (name, cam) for i, name, cam in db.execute('select image_id, name, camera_id from images')}
    face_of_cam = {}
    for i, (name, cam) in images.items():
        face_of_cam[cam] = int(re.match(r'f(\d)/', name).group(1))
    (rig_id,) = db.execute('select rig_id from rigs').fetchone()
    frames = {}
    for fid, did in db.execute('select frame_id, data_id from frame_data'):
        node = int(re.search(r'-(\d+)\.jpg$', images[did][0]).group(1))
        frames.setdefault(node, (fid, []))[1].append(did)

    rot = rotations(ref_face=1)
    ref_cam = [c for c, f in face_of_cam.items() if f == 1][0]

    with open(os.path.join(out, 'cameras.txt'), 'w', newline='\n') as fh:
        for cam in sorted(face_of_cam):
            fh.write(f'{cam} PINHOLE 640 640 320 320 320 320\n')
    with open(os.path.join(out, 'rigs.txt'), 'w', newline='\n') as fh:
        sensors = []
        for cam in sorted(face_of_cam):
            if cam == ref_cam:
                continue
            q = rot[face_of_cam[cam]]['cam_from_rig_wxyz']
            sensors.append(f'CAMERA {cam} 1 ' + ' '.join(repr(float(v)) for v in q) + ' 0 0 0')
        fh.write(f'{rig_id} {len(face_of_cam)} CAMERA {ref_cam} ' + ' '.join(sensors) + '\n')

    f1 = np.array(cam_from_node(1))
    fr_lines, im_lines = [], []
    for node_s, v in solved['nodes'].items():
        node = int(node_s)
        if node not in frames:
            continue
        fid, dids = frames[node]
        R = f1 @ np.array(v['node_from_ref'])
        t = -R @ np.array(v['centre'])
        q = quat_wxyz(R.tolist())
        data = ' '.join(f'CAMERA {images[d][1]} {d}' for d in sorted(dids))
        fr_lines.append(f'{fid} {rig_id} ' + ' '.join(repr(float(x)) for x in list(q) + list(t)) + f' {len(dids)} {data}\n')
        for d in sorted(dids):
            name, cam = images[d]
            Rc = np.array(rot[face_of_cam[cam]]['cam_from_rig']) @ R
            tc = np.array(rot[face_of_cam[cam]]['cam_from_rig']) @ t
            qc = quat_wxyz(Rc.tolist())
            im_lines.append(f'{d} ' + ' '.join(repr(float(x)) for x in list(qc) + list(tc)) + f' {cam} {name}\n\n')
    with open(os.path.join(out, 'frames.txt'), 'w', newline='\n') as fh:
        fh.writelines(fr_lines)
    with open(os.path.join(out, 'images.txt'), 'w', newline='\n') as fh:
        fh.writelines(im_lines)
    open(os.path.join(out, 'points3D.txt'), 'w').close()
    print(f'{len(fr_lines)} frames, {len(im_lines)} images written to {out}')


if __name__ == '__main__':
    main()
