#!/usr/bin/env python3
"""
Lay out a whole Myst III age's cube faces as one COLMAP input: every room's nodes,
the walks and zips inside each room, and the walks from one room into the next.

    python prepare_age.py FACES_DIR ROOMS_DIR AGE_JSON OUT [--prefix MA] [--rooms MACA,MAIS]
    python prepare_age.py C:\\myst3_out\\faces C:\\myst3_out\\maps_repo C:\\myst3_out\\maps_repo\\Amateria.json C:\\myst3_colmap\\Amateria

The same as prepare_colmap.py (same files, same rig, same pairs rule) except that
nodes of different rooms need different numbers, because every later script reads
a node's number from its file name. A node gets the number

    1000 x (the room's place in the age's room list, from 1) + its node number

so Amateria's MAIS node 18 (MAIS second in the list) is node 2018, file
f<face>/MA-2018.jpg. Room-to-room walks are the room maps' 'walk-room' links,
whose first argument is 1000 + the other room's place in that same list; every one
decoded is checked against the age map's cross_used list. nodes.json also gets
'rooms' (number -> room) so the numbers can be read back. Standard library only.
"""
import argparse
import json
import os
import re
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from face_geometry import FACES, rotations  # noqa: E402
from prepare_colmap import CAMERA, base  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('faces'); ap.add_argument('rooms_dir'); ap.add_argument('age'); ap.add_argument('out')
    ap.add_argument('--prefix', help='file name prefix (default: the first two letters of the first room)')
    ap.add_argument('--rooms', help='only these rooms, comma-separated (numbers stay as in the full list)')
    a = ap.parse_args()
    age = json.load(open(a.age))
    order = age['rooms']
    rooms = a.rooms.split(',') if a.rooms else order
    prefix = a.prefix or order[0][:2]
    gid = lambda room, n: (order.index(room) + 1) * 1000 + n
    cross = {tuple(sorted((p, q))) for p, q, _ in age['cross_used']}

    nodes, skipped, room_of = [], [], {}
    for room in rooms:
        have = {}
        for name in os.listdir(os.path.join(a.faces, room)):
            m = re.fullmatch(rf'{room}-(\d+)-f([1-6])\.jpg', name)
            if m:
                have.setdefault(int(m.group(1)), set()).add(int(m.group(2)))
        for n, fs in sorted(have.items()):
            if n < 100 and fs == set(FACES):
                nodes.append(gid(room, n)); room_of[gid(room, n)] = (room, n)
            else:
                skipped.append(f'{room}:{n}')
    node_set = set(nodes)

    links, used, n_cross, bad_cross = set(), [], 0, []
    for room in rooms:
        for l in json.load(open(os.path.join(a.rooms_dir, f'{room}.json')))['links']:
            if not l['args']:
                continue
            if l['kind'] in ('walk', 'zip'):
                other, b = room, l['args'][0]
            elif l['kind'] == 'walk-room' and len(l['args']) >= 2 and 1001 <= l['args'][0] <= 1000 + len(order):
                other, b = order[l['args'][0] - 1001], l['args'][1]
                pair = tuple(sorted((f'{room}:{base(l["from"])}', f'{other}:{base(b)}')))
                if pair not in cross:
                    bad_cross.append(pair)
                    continue
                n_cross += 1
            else:
                continue
            x, y = gid(room, base(l['from'])), gid(other, base(b))
            if x == y or x not in node_set or y not in node_set:
                continue
            links.add((min(x, y), max(x, y)))
            used.append({'from': x, 'to': y, 'kind': 'walk' if l['kind'] == 'walk-room' else l['kind'],
                         'room_link': l['kind'] == 'walk-room',
                         'heading': l['heading'], 'pitch': l['pitch']})
    links = sorted(links)

    def img(n, f):
        return f'f{f}/{prefix}-{n:04d}.jpg'

    for f in FACES:
        os.makedirs(os.path.join(a.out, 'images', f'f{f}'), exist_ok=True)
    for n in nodes:
        room, k = room_of[n]
        for f in FACES:
            shutil.copyfile(os.path.join(a.faces, room, f'{room}-{k:04d}-f{f}.jpg'),
                            os.path.join(a.out, 'images', img(n, f)))

    pairs = [(img(n, i), img(n, j)) for n in nodes for i in FACES for j in FACES if i < j]
    pairs += [(img(x, i), img(y, j)) for x, y in links for i in FACES for j in FACES]
    with open(os.path.join(a.out, 'pairs.txt'), 'w', newline='\n') as fh:
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
    with open(os.path.join(a.out, 'rig_config.json'), 'w', newline='\n') as fh:
        json.dump([{'cameras': cams}], fh, indent=1)

    pos = {n: age['positions'].get(f'{room_of[n][0]}:{room_of[n][1]}') for n in nodes}
    with open(os.path.join(a.out, 'nodes.json'), 'w', newline='\n') as fh:
        json.dump({'room': prefix, 'age': age['age'], 'rooms': {str(n): f'{r}:{k}' for n, (r, k) in room_of.items()},
                   'nodes': nodes, 'skipped_with_faces': skipped,
                   'links': [list(p) for p in links], 'links_used': used,
                   'age_map_positions_steps': {str(n): p for n, p in pos.items()},
                   'face_cam_from_node': {f'f{f}': rot[f]['cam_from_node'] for f in FACES},
                   'camera': {'model': CAMERA[0], 'params': CAMERA[1], 'width': 640, 'height': 640}},
                  fh, indent=1)

    print(f'{age["age"]}: {len(nodes)} nodes in {len(rooms)} rooms, {len(nodes) * 6} images; '
          f'skipped {len(skipped)} ({", ".join(skipped)})')
    for room in rooms:
        print(f'  {room} = {order.index(room) + 1}xxx: {sum(1 for r, _ in room_of.values() if r == room)} nodes')
    print(f'  {len(links)} linked node pairs; {n_cross} room-to-room hotspots'
          + (f'; NOT in the age map: {sorted(set(bad_cross))}' if bad_cross else ''))
    print(f'  {len(pairs)} image pairs')
    linked = {n for p in links for n in p}
    missing = [f'{room_of[n][0]}:{room_of[n][1]}' for n in nodes if n not in linked]
    if missing:
        print(f'  not linked to any other node: {missing}')


if __name__ == '__main__':
    main()
