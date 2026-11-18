#!/usr/bin/env python3
r"""
A COLMAP database's images given position priors from hotspot_layout.py, for pose_prior_mapper.

    python add_priors.py DATABASE.db LAYOUT.json [--prefix LE] [--std 1.5] [--group 0]

Every image <f>/<prefix>-<node>.jpg (all six faces of a node) gets its node's place in LAYOUT.json (a node of
another state, n % 1000 >= 100, the place of n % 100), with a covariance of --std squared on each axis, in the
Cartesian frame (pose_priors: corr_sensor_type 0, a camera; coordinate_system 1, Cartesian). Only nodes of
linked group --group. Existing priors are deleted. Writes the database in place: copy it first.
"""
import argparse
import json
import re
import sqlite3

import numpy as np


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('db'); ap.add_argument('layout')
    ap.add_argument('--prefix', default='MA'); ap.add_argument('--std', type=float, default=1.5)
    ap.add_argument('--group', type=int, default=0)
    a = ap.parse_args()
    L = json.load(open(a.layout))
    c = sqlite3.connect(a.db)
    c.execute('delete from pose_priors')
    cov = (np.eye(3) * a.std ** 2).astype(np.float64).tobytes()
    n_in, n_out = 0, 0
    for iid, name, cam in c.execute('select image_id, name, camera_id from images').fetchall():
        m = re.search(rf'{a.prefix}-(\d+)\.jpg$', name)
        if not m:
            continue
        n = int(m.group(1)); k = str(n // 1000 * 1000 + n % 1000 % 100)
        if k not in L or L[k]['group'] != a.group:
            n_out += 1; continue
        c.execute('insert into pose_priors (pose_prior_id, corr_data_id, corr_sensor_id, corr_sensor_type, position, '
                  'position_covariance, gravity, coordinate_system) values (?, ?, ?, 0, ?, ?, NULL, 1)',
                  (iid, iid, cam, np.array(L[k]['pos'], np.float64).tobytes(), cov))
        n_in += 1
    c.commit()
    print(f'{n_in} images given priors, {n_out} without (no place in the layout)')


if __name__ == '__main__':
    main()
