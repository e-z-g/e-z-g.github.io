#!/usr/bin/env python3
"""
Lay out one Myst III room's cube faces as COLMAP input, with a match-pairs list
taken from the room's links and a rig file that fixes the six faces of a node
to one centre and their known rotations.

    python prepare_colmap.py FACES_DIR ROOM_JSON AGE_JSON OUT
    python prepare_colmap.py C:\\myst3_out\\faces maps\\rooms\\ENSI.json maps\\ages\\Voltaic.json C:\\myst3_colmap\\ENSI

FACES_DIR is myst3_nodes.py's faces folder (<ROOM>\\<ROOM>-<node>-f<face>.jpg).
Standard library only. Writes under OUT:

    images/f<face>/<ROOM>-<node>.jpg   the faces, copied byte for byte. One folder per
                                       face, because a COLMAP rig takes each sensor's
                                       images by folder prefix and groups a frame's
                                       images by the name that follows it, so a node's
                                       six faces are the six files called <ROOM>-<node>.jpg
    pairs.txt                          image pairs to match (matches_importer)
    rig_config.json                    rig_configurator: face 1 the reference sensor,
                                       faces 2-6 rotated about the same centre
    nodes.json                         the nodes, the links used and their starting
                                       positions from the age map (steps, no heights)

Only nodes with faces are used, and of those only the base nodes: a node numbered
100 or more is the same place as node n-100 in another state, sharing every face
that does not show the change. A link to such a node counts as a link to its base;
one from a node to its own variant is dropped. Links are the room's walks and zips
between nodes of the room; moves into other rooms are left out.

The pairs are, for every two linked nodes, all 36 pairings of their faces, and for
every node its own 15. The camera is PINHOLE 320 320 320 320: each face is a
640x640 gnomonic view of exactly 90 degrees.
"""
import json
import os
import re
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from face_geometry import FACES, rotations  # noqa: E402

CAMERA = ('PINHOLE', [320.0, 320.0, 320.0, 320.0])


def base(n):
    return n - 100 if 100 <= n < 1000 else n


def main():
    if len(sys.argv) != 5:
        sys.exit(__doc__)
    faces_dir, room_json, age_json, out = sys.argv[1:]
    room_data = json.load(open(room_json))
    room = room_data['room']
    src = os.path.join(faces_dir, room)

    have = {}
    for name in os.listdir(src):
        m = re.fullmatch(rf'{room}-(\d+)-f([1-6])\.jpg', name)
        if m:
            have.setdefault(int(m.group(1)), set()).add(int(m.group(2)))
    nodes = sorted(n for n, fs in have.items() if n < 100 and fs == set(FACES))
    skipped = sorted(n for n in have if n not in nodes)
    node_set = set(nodes)

    links = set()
    used = []
    for l in room_data['links']:
        if l['kind'] not in ('walk', 'zip') or not l['args']:
            continue
        a, b = base(l['from']), base(l['args'][0])
        if a == b or a not in node_set or b not in node_set:
            continue
        links.add((min(a, b), max(a, b)))
        used.append({'from': l['from'], 'to': l['args'][0], 'kind': l['kind'],
                     'heading': l['heading'], 'pitch': l['pitch']})
    links = sorted(links)

    def img(n, f):
        return f'f{f}/{room}-{n:04d}.jpg'

    for f in FACES:
        os.makedirs(os.path.join(out, 'images', f'f{f}'), exist_ok=True)
    for n in nodes:
        for f in FACES:
            shutil.copyfile(os.path.join(src, f'{room}-{n:04d}-f{f}.jpg'), os.path.join(out, 'images', img(n, f)))

    pairs = []
    for n in nodes:
        for i in FACES:
            for j in FACES:
                if i < j:
                    pairs.append((img(n, i), img(n, j)))
    for a, b in links:
        for i in FACES:
            for j in FACES:
                pairs.append((img(a, i), img(b, j)))
    with open(os.path.join(out, 'pairs.txt'), 'w', newline='\n') as fh:
        fh.writelines(f'{p} {q}\n' for p, q in pairs)

    rot = rotations(ref_face=1)
    cams = []
    for f in FACES:
        c = {'image_prefix': f'f{f}/', 'camera_model_name': CAMERA[0], 'camera_params': CAMERA[1]}
        if f == 1:
            c['ref_sensor'] = True
        else:
            c['cam_from_rig_rotation'] = rot[f]['cam_from_rig_wxyz']
            c['cam_from_rig_translation'] = [0.0, 0.0, 0.0]
        cams.append(c)
    with open(os.path.join(out, 'rig_config.json'), 'w', newline='\n') as fh:
        json.dump([{'cameras': cams}], fh, indent=1)

    age = json.load(open(age_json))
    pos = {n: age['positions'].get(f'{room}:{n}') for n in nodes}
    with open(os.path.join(out, 'nodes.json'), 'w', newline='\n') as fh:
        json.dump({'room': room, 'nodes': nodes, 'skipped_with_faces': skipped,
                   'links': [list(p) for p in links], 'links_used': used,
                   'age_map_positions_steps': {str(n): p for n, p in pos.items()},
                   'face_cam_from_node': {f'f{f}': rot[f]['cam_from_node'] for f in FACES},
                   'camera': {'model': CAMERA[0], 'params': CAMERA[1], 'width': 640, 'height': 640}},
                  fh, indent=1)

    print(f'{room}: {len(nodes)} nodes, {len(nodes) * 6} images; skipped {skipped or "none"}')
    print(f'  {len(links)} linked node pairs ({sum(1 for u in used if u["kind"] == "walk")} walk and '
          f'{sum(1 for u in used if u["kind"] == "zip")} zip hotspots)')
    print(f'  {len(pairs)} image pairs: {len(nodes) * 15} within nodes + {len(links) * 36} between linked nodes')
    missing = [n for n in nodes if not any(n in p for p in links)]
    if missing:
        print(f'  not linked to any other node of the room: {missing}')


if __name__ == '__main__':
    main()
