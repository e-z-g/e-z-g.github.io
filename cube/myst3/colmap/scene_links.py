#!/usr/bin/env python3
r"""
The game's moves between the nodes of a scene_mesh.py mesh, for the viewer to walk them.

    python scene_links.py MAPS_ROOMS MESH_DIR [--age-map maps/ages/AGE.json]

MAPS_ROOMS is myst3_nodes.py's maps\rooms (one <ROOM>.json a room, its links as the game's scripts give
them); MESH_DIR a scene folder with views.json (scene_attrs.py's). Keeps the links that move the player
(walk 138/164, walk-room 139/165, zip 140, zip-room 141, and a movie that ends at another node of the room, 152,
such as MACA 35's lift to MACA 36, kept as a zip: the viewer cuts) between two nodes both in views.json, node names
as the mesh's (room number times 1000 plus the node, the room number its place in the age map's room list,
--age-map, or Amateria's: MACA 1, MAIS 2, MALL 3, MASS 4, MAWW 5, MATO 6; a walk-room's room argument ends in that
number: 1001-1006 in Amateria, 501-506 in J'nanin). Writes MESH_DIR\links.json: per node, its moves with
the game's hotspot heading and pitch and the bearing to the other node in the mesh, and prints how far
the two bearings differ (a large difference points at a node the mesh has in the wrong place; movies left out, as
their hotspot is a lever or a door, not the way to the other node).
"""
import argparse
import json
import math
import os

import numpy as np

ROOMS = {'MACA': 1, 'MAIS': 2, 'MALL': 3, 'MASS': 4, 'MAWW': 5, 'MATO': 6}
MOVE = {138: 'walk', 164: 'walk', 139: 'walk', 165: 'walk', 140: 'zip', 141: 'zip', 152: 'zip'}
MOVIE = 152                     # args: the node it ends at, the movie


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('rooms'); ap.add_argument('mesh'); ap.add_argument('--age-map')
    a = ap.parse_args()
    rooms = {r: i + 1 for i, r in enumerate(json.load(open(a.age_map))['rooms'])} if a.age_map else ROOMS
    views = json.load(open(os.path.join(a.mesh, 'views.json')))
    out, off = {}, []
    for room, num in rooms.items():
        f = os.path.join(a.rooms, room + '.json')
        if not os.path.exists(f):
            continue
        for l in json.load(open(f))['links']:
            if l['opcode'] not in MOVE:
                continue
            src = str(num * 1000 + l['from'])
            if l['opcode'] == MOVIE:
                dst = str(num * 1000 + l['args'][0])
            else:
                dst = str(l['args'][0] % 100 * 1000 + l['args'][1]) if len(l['args']) == 2 else str(num * 1000 + l['args'][0])
            if src not in views or dst not in views or src == dst:
                continue
            v = views[src]
            d = np.array(v['rot']) @ (np.array(views[dst]['pos']) - np.array(v['pos']))   # in the node's frame, face 1 = -z
            bearing = math.degrees(math.atan2(-d[0], d[2])) % 360       # the game's heading: 0 along +z, as face 3
            e = {'to': dst, 'kind': MOVE[l['opcode']], 'heading': l['heading'], 'pitch': l['pitch'],
                 'bearing': round(bearing, 1), 'dist': round(float(np.linalg.norm(d)), 3)}
            if l['opcode'] == MOVIE:
                e['movie'] = l['args'][1]
            if not any(x['to'] == dst for x in out.get(src, [])):
                out.setdefault(src, []).append(e)
                if l['heading'] is not None and l['opcode'] != MOVIE:
                    off.append(((bearing - l['heading'] + 180) % 360 - 180, src, dst))
    json.dump(out, open(os.path.join(a.mesh, 'links.json'), 'w'), indent=0)
    n = sum(len(x) for x in out.values())
    print(f'{n} moves from {len(out)} of {len(views)} nodes')
    if off:
        e = np.abs([o[0] for o in off])
        print(f'hotspot heading against bearing to the node: median {np.median(e):.1f}, 90% {np.percentile(e, 90):.1f} degrees')
        for o in sorted(off, key=lambda o: -abs(o[0]))[:15]:
            print(f'  {o[1]} -> {o[2]}: {o[0]:+.0f}')


if __name__ == '__main__':
    main()
