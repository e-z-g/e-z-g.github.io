#!/usr/bin/env python3
r"""
The data for node_walk.html, Myst III's nodes walked as the game walks them: every node's six faces as shipped,
and its movement hotspots with their full rectangles.

    python node_walk.py MYST3_DAT FACES OUT [--rooms MACA MAIS MALL MASS MATO MAWW]
                        [--views VIEWS.json] [--placed PLACED.json ...] [--proposed LAYOUT.json [--height-from 2010=2009 ...]]
                        [--sea 2006 2007 ... [--eye 0.226]]

MYST3_DAT is ScummVM's myst3.dat (the game's node scripts); FACES myst3_nodes.py's faces folder (<ROOM>/<ROOM>-
<node>-f<face>.jpg). Writes OUT/walk.json: per node ("MAIS-0006") its hotspots that move the player (walks,
walk-rooms, zips, zip-rooms, and the movies and age changes, shown but not followed), each with its rectangles as
the script gives them (centre pitch and heading in degrees, width and height in ScummVM's units: half the
rectangle's side over its distance, times 90), the condition (a game variable; the walk ignores it) and the target
node when it has faces. A hotspot whose target is a node with no cube faces (a close-up drawn as a flat frame) is
kept with no target. The rooms' numbers in walk-room and zip-room are 1000 plus the room's place in --rooms (Amateria's
order: MACA 1, MAIS 2, MALL 3, MASS 4, MAWW 5, MATO 6). With --views (a scene's views.json, scene_mesh.py's frame:
y up, one unit the node spacing, heading 0 along +z) it also writes OUT/layout.json for the page's map: each node's
place, "model" for the scene's nodes and "placed" for those in --placed (place_nodes.py's output, later files
winning; a placed node also proposed is left to the proposal), and under "proposed" a layout not yet built (warp_model.py's LAYOUT.json: [x, z] keeps the node's height,
or --height-from's node's). With --sea, layout.json's "sea" is the height taken as 0 on the map: the mean height of
those nodes less --eye (the eye's height over the floor in node spacings, from the hotspots' paired pitches); for
Amateria the walkway along MAIS 6-12, at the water. Needs only Python 3.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from myst3_nodes import NAV, Reader, cond_scripts, load_dat, opcodes  # noqa: E402

AMATERIA = {1001: 'MACA', 1002: 'MAIS', 1003: 'MALL', 1004: 'MASS', 1005: 'MAWW', 1006: 'MATO'}


def hotspots(r):
    """myst3_nodes.py's hotspots() with the rectangles' sizes and the condition kept."""
    out = []
    while not r.eos():
        cond = r.s16()
        if cond == 0:
            break
        rects, cursor = [], None
        if cond != -1:
            while True:
                pitch, heading, w, h = r.u16(), r.u16(), r.s16(), r.s16()
                rects.append([pitch if pitch < 32768 else pitch - 65536, heading, abs(w), h])
                if w >= 0 or r.eos():
                    break
            cursor = r.u16()
        out.append({'cond': cond, 'cursor': cursor, 'rects': rects, 'ops': opcodes(r)})
    return out


def room_hotspots(blob):
    r = Reader(blob)
    nodes = {}
    while not r.eos():
        nid = r.s16()
        if nid == 0:
            break
        if nid > 0:
            ids = [nid]
        elif nid == -10:
            ids = []
            while True:
                x = r.s16()
                if x == 0:
                    break
                ids += list(range(-x, r.u16() + 1)) if x < 0 else [x]
        else:
            ids = [r.u16() for _ in range(-nid)]
        cond_scripts(r)
        hs = hotspots(r)
        for i in ids:
            nodes.setdefault(i, []).extend(hs)
    return nodes


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('dat'); ap.add_argument('faces'); ap.add_argument('out')
    ap.add_argument('--rooms', nargs='+', default=['MACA', 'MAIS', 'MALL', 'MASS', 'MAWW', 'MATO'])
    ap.add_argument('--views'); ap.add_argument('--placed', nargs='*', default=[]); ap.add_argument('--proposed')
    ap.add_argument('--height-from', nargs='*', default=[])
    ap.add_argument('--sea', nargs='*', default=[]); ap.add_argument('--eye', type=float, default=0.226)
    a = ap.parse_args()
    scripts = load_dat(a.dat)
    rooms = {1001 + i: r for i, r in enumerate(a.rooms)}
    has = set()
    for room in a.rooms:
        for f in os.listdir(os.path.join(a.faces, room)):
            if f.endswith('-f1.jpg'):
                has.add(f[:-7])
    out, counts = {}, {'walks': 0, 'no faces': 0, 'other': 0}
    for room in a.rooms:
        hs = room_hotspots(scripts[room])
        for n, spots in sorted(hs.items()):
            name = f'{room}-{n:04d}'
            if name not in has:
                continue
            keep = []
            for s in spots:
                nav = [(op, args) for op, args in s['ops'] if op in NAV]
                if not nav or not s['rects']:
                    continue
                op, args = nav[0]
                kind = NAV[op]
                to = None
                if kind in ('walk', 'zip') and args:
                    to = f'{room}-{args[0]:04d}'
                elif kind in ('walk-room', 'zip-room') and len(args) >= 2 and args[0] in rooms:
                    to = f'{rooms[args[0]]}-{args[1]:04d}'
                if to is not None and to not in has:
                    counts['no faces'] += 1; to = None
                elif to is not None:
                    counts['walks'] += 1
                else:
                    counts['other'] += 1
                keep.append({'kind': kind, 'op': op, 'args': args, 'to': to, 'cond': s['cond'], 'rects': s['rects']})
            out[name] = keep
    os.makedirs(a.out, exist_ok=True)
    json.dump({'rooms': a.rooms, 'nodes': out}, open(os.path.join(a.out, 'walk.json'), 'w'), separators=(',', ':'))
    if a.views:
        lay = {n: {'pos': [round(x, 4) for x in v['pos']], 'kind': 'model'} for n, v in json.load(open(a.views)).items()}
        for f in a.placed:
            for n, v in json.load(open(f)).items():
                if n not in lay or lay[n]['kind'] == 'placed':
                    lay[n] = {'pos': [round(x, 4) for x in v['pos']], 'kind': 'placed'}
        prop = {}
        if a.proposed:
            hf = dict(x.split('=') for x in a.height_from)
            for n, p in json.load(open(a.proposed)).items():
                y = lay[hf.get(n, n)]['pos'][1] if len(p) == 2 else p[1]
                prop[n] = [round(p[0], 4), round(y, 4), round(p[-1], 4)]
        lay = {n: v for n, v in lay.items() if not (v['kind'] == 'placed' and n in prop)}   # proposed supersedes placed
        res = {'nodes': lay, 'proposed': prop}
        if a.sea:
            res['sea'] = round(sum(lay[n]['pos'][1] for n in a.sea) / len(a.sea) - a.eye, 4)
            res['sea_from'] = a.sea
        json.dump(res, open(os.path.join(a.out, 'layout.json'), 'w'), separators=(',', ':'))
        print(f"layout: {len(lay)} nodes placed, {len(prop)} proposed" + (f", sea at {res['sea']}" if a.sea else ''))
    print(f"{len(out)} nodes with faces; hotspots: {counts['walks']} to a node with faces, {counts['no faces']} to a node "
          f"without (a flat close-up), {counts['other']} movies, age changes and the like")


if __name__ == '__main__':
    main()
