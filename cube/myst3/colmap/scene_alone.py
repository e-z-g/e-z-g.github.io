#!/usr/bin/env python3
r"""
Nodes shown in a scene as their own pictures only (views.json's "alone": scene3d.html shows such a node's panorama
alone, with the mesh hidden, and does not project its pictures onto the mesh): interiors, which no picture ties to
the outside, and views of a changed scene (a chair moved, a platform raised). Adds them to a scene_mesh.py folder.

    python scene_alone.py MESH_DIR WALK.json [--from OLD_MESH_DIR --nodes 6003 3016 3018]
        [--place 6010=20.0,0.17,-5.03 ...] [--walk 6004 6005 ...] [--at 6203=6003 ...] [--height 4057=6007 ...] [--eye 0.226] [--pictures FACES]

MESH_DIR's views.json and nodes.json gain the nodes; its frame (scene_mesh.py's: nodes.json's first node at the
origin, y up, one unit the node spacing) is scales.json's unit. --nodes take their places from OLD_MESH_DIR's
views.json (the same first node; the place scaled by the two units), for nodes the old mesh fused and the new
one leaves out. --place puts a node at a place given in the frame (measured by hand). --walk nodes are placed one after another from a node already placed that links to them in WALK.json
(node_walk.py's), or that it links to (the hotspot turned round): along the hotspot's heading, at a distance and climb from the pitches of the pair of hotspots
(each pitch to the other's floor from an eye --eye spacings above one's own: d = 2e / (tan(-p_ab) + tan(-p_ba)),
climb = d (tan(-p_ba) - tan(-p_ab)) / 2, d held to 0.3-1.6), or from one hotspot at d 1 (0.5 past 45 degrees).
--at puts a node at another's place; --height gives it another's height. The turn of every added node is the
first node's (scene_mesh.py's views have nearly the same turn at every node). With --pictures (myst3_nodes.py's
faces folder, <ROOM>/<ROOM>-<node>-f<k>.jpg) each added node's picture atlas is written to MESH_DIR/pictures as
scene_attrs.py writes them (faces 1 2 3 above, 4 5 6 below). Needs Python 3, and Pillow for --pictures.
"""
import argparse
import json
import math
import os

ROOMS = {'MACA': 1, 'MAIS': 2, 'MALL': 3, 'MASS': 4, 'MAWW': 5, 'MATO': 6}
NAME = {v: k for k, v in ROOMS.items()}


def name(n):
    return f'{NAME[int(n) // 1000]}-{int(n) % 1000:04d}'


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('mesh'); ap.add_argument('walk')
    ap.add_argument('--from', dest='old'); ap.add_argument('--nodes', nargs='*', default=[])
    ap.add_argument('--walk', dest='walkn', nargs='*', default=[]); ap.add_argument('--place', nargs='*', default=[])
    ap.add_argument('--at', nargs='*', default=[]); ap.add_argument('--height', nargs='*', default=[])
    ap.add_argument('--eye', type=float, default=0.226); ap.add_argument('--pictures')
    a = ap.parse_args()
    vp, np_ = os.path.join(a.mesh, 'views.json'), os.path.join(a.mesh, 'nodes.json')
    views, nodes = json.load(open(vp)), json.load(open(np_))
    n0 = next(iter(nodes))
    rot = views[n0]['rot']
    pos = {n: v['pos'] for n, v in views.items()}
    added = {}
    if a.nodes:
        old = json.load(open(os.path.join(a.old, 'views.json')))
        unit = lambda d: json.load(open(os.path.join(d, 'scales.json')))['unit']
        k = unit(a.old) / unit(a.mesh)
        for n in a.nodes:
            added[n] = [x * k for x in old[n]['pos']]; print(f'node {n}: from {a.old}')
    for x in a.place:
        n, v = x.split('='); added[n] = [float(c) for c in v.split(',')]; print(f'node {n}: placed at {added[n]}')
    pos.update(added)
    walk = json.load(open(a.walk))['nodes']
    spots = lambda n, m: [s for s in walk.get(name(n), []) if s['to'] == name(m) and s['kind'] in ('walk', 'walk-room', 'zip', 'zip-room')]
    todo = list(a.walkn)
    while todo:
        for n in todo:
            # a placed node's hotspot to n, or else n's hotspot to a placed node (turned round)
            src = [(m, spots(m, n)[0], spots(n, m), 1) for m in pos if spots(m, n)] or \
                  [(m, spots(n, m)[0], [], -1) for m in pos if spots(n, m)]
            if src:
                break
        else:
            print('not linked to a placed node: ' + ' '.join(todo)); break
        m, s, back, sign = src[0]
        p_ab, hd = s['rects'][0][0], s['rects'][0][1]
        if back:
            p_ba = back[0]['rects'][0][0]
            den = math.tan(math.radians(-p_ab)) + math.tan(math.radians(-p_ba))
            d = min(1.6, max(0.3, 2 * a.eye / den)) if den > 0 else 1.0
            climb = d * (math.tan(math.radians(-p_ba)) - math.tan(math.radians(-p_ab))) / 2
        else:
            d = 0.5 if abs(p_ab) > 45 else 1.0
            climb = a.eye - d * math.tan(math.radians(-p_ab))
        h = math.radians(hd if sign > 0 else hd + 180)
        q = pos[m]
        added[n] = pos[n] = [q[0] - d * math.sin(h), q[1] + sign * climb, q[2] + d * math.cos(h)]
        how = f'pitches {p_ab}, {back[0]["rects"][0][0]}' if back else f'pitch {p_ab}, one way' + ('' if sign > 0 else f', from {n}')
        print(f'node {n}: from {m} heading {math.degrees(h) % 360:.0f} at {d:.2f}, climb {sign * climb:+.2f} ({how})')
        todo.remove(n)
    for x in a.at:
        n, m = x.split('='); added[n] = pos[n] = list(pos[m]); print(f'node {n}: at {m}')
    for x in a.height:
        n, m = x.split('='); added[n][1] = pos[m][1]; print(f'node {n}: at {m}\'s height')
    for n, p in added.items():
        views[n] = {'pos': p, 'rot': rot, 'alone': True}
        nodes[n] = p
    if a.pictures:
        from PIL import Image
        os.makedirs(os.path.join(a.mesh, 'pictures'), exist_ok=True)
        for n in added:
            faces = [Image.open(os.path.join(a.pictures, name(n)[:4], f'{name(n)}-f{k}.jpg')).convert('RGB') for k in range(1, 7)]
            fs = faces[0].size[0]; atlas = Image.new('RGB', (3 * fs, 2 * fs))
            for k, im in enumerate(faces):
                atlas.paste(im, (k % 3 * fs, k // 3 * fs))
            atlas.save(os.path.join(a.mesh, 'pictures', f'MA-{n}.jpg'), quality=92)
    json.dump(views, open(vp, 'w'), indent=1)
    json.dump(nodes, open(np_, 'w'), indent=1)
    print(f'{len(added)} nodes added as pictures only')


if __name__ == '__main__':
    main()
