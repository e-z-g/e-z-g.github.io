#!/usr/bin/env python3
"""
Draw the Myst III node maps as PNGs.

    python draw_maps.py rooms maps/rooms maps   one sheet per age, a panel per room
    python draw_maps.py ages  maps/ages  maps   one whole-age map per age

`rooms` reads the <ROOM>.json files myst3_nodes.py writes (--maps-only);
`ages` reads the <Age>.json files age_maps.py writes. Needs Pillow.
"""
import json, os, sys
from PIL import Image, ImageDraw, ImageFont

AGES = {'Tomahna': ['TOHO', 'TOHB'], "J'nanin": ['LEIS', 'LEOS', 'LEET', 'LELT', 'LEMT', 'LEOF'],
        'Edanna': ['LIDR', 'LISW', 'LIFO', 'LISP', 'LINE'], 'Voltaic': ['ENSI', 'ENPP', 'ENEM', 'ENLC', 'ENDD', 'ENCH', 'ENLI'],
        'Narayan': ['NACH'], 'Amateria': ['MACA', 'MAIS', 'MALL', 'MASS', 'MAWW', 'MATO']}
PALETTE = [(31, 119, 180), (255, 127, 14), (44, 160, 44), (214, 39, 40), (148, 103, 189), (140, 86, 75),
           (227, 119, 194), (23, 190, 207)]


def fonts():
    try:
        return (ImageFont.truetype('DejaVuSans.ttf', 10), ImageFont.truetype('DejaVuSans.ttf', 13),
                ImageFont.truetype('DejaVuSans-Bold.ttf', 16))
    except OSError:
        f = ImageFont.load_default(); return f, f, f


SMALL, MID, BIG = fonts()


def room_panel(path, k=34, pad=28, max_w=1500):
    d = json.load(open(path))
    P = {int(n): v for n, v in d['sketch_positions'].items()}
    place, ox, oy, rowh = {}, 0.0, 0.0, 0.0
    for g in d['walk_connected_groups']:
        xs = [P[n][0] for n in g]; ys = [P[n][1] for n in g]
        w, h = max(xs) - min(xs), max(ys) - min(ys)
        if ox > 0 and (ox + w) * k > max_w - 2 * pad:
            ox, oy, rowh = 0.0, oy + rowh + 1.6, 0.0
        for n in g:
            place[n] = ((P[n][0] - min(xs) + ox) * k + pad, (max(ys) - P[n][1] + oy) * k + pad + 24)
        ox += w + 1.6; rowh = max(rowh, h)
    W = int(max([x for x, _ in place.values()] + [300]) + pad)
    H = int(max([y for _, y in place.values()] + [40]) + pad + 6)
    singles = [n for n in d['nodes'] if n not in place]
    im = Image.new('RGB', (W, H + (22 if singles else 0)), 'white'); dr = ImageDraw.Draw(im)
    for l in d['links']:
        if l['kind'] == 'zip' and l['from'] in place and l['args'][0] in place:
            dr.line([place[l['from']], place[l['args'][0]]], fill=(220, 120, 120), width=1)
    for e in d['walk_bearings']:
        if e['from'] in place and e['to'] in place:
            dr.line([place[e['from']], place[e['to']]], fill=(70, 70, 70), width=2)
    for n, (x, y) in place.items():
        dr.ellipse([x - 10, y - 10, x + 10, y + 10], fill='white', outline=(40, 40, 40))
        t = str(n); dr.text((x - dr.textlength(t, font=SMALL) / 2, y - 7), t, fill='black', font=SMALL)
    dr.text((8, 4), f'{d["room"]}  ({len(d["nodes"])} nodes)', fill='black', font=BIG)
    if singles:
        txt = 'Not reached by walking (close-ups, puzzles, ladders): ' + ', '.join(map(str, singles))
        dr.text((8, H + 2), txt[:240] + ('…' if len(txt) > 240 else ''), fill=(110, 110, 110), font=SMALL)
    return im


def rooms_sheets(src, out):
    for age, rooms in AGES.items():
        panels = [room_panel(os.path.join(src, f'{r}.json')) for r in rooms if os.path.exists(os.path.join(src, f'{r}.json'))]
        if not panels:
            continue
        W = max(p.width for p in panels); H = sum(p.height for p in panels) + 10 * len(panels) + 30
        sheet = Image.new('RGB', (W, H), 'white'); dr = ImageDraw.Draw(sheet)
        dr.text((8, 6), f'{age} — node connections by room (grey: walk, red: zip). Every step drawn the same length.',
                fill='black', font=BIG)
        y = 32
        for p in panels:
            sheet.paste(p, (0, y)); dr.line([(0, y - 5), (W, y - 5)], fill=(220, 220, 220)); y += p.height + 10
        name = os.path.join(out, f'rooms-{age.replace(chr(39), "")}.png')
        sheet.save(name); print(name, sheet.size)


def age_map(path, out):
    d = json.load(open(path))
    col = {r: PALETTE[i % len(PALETTE)] for i, r in enumerate(d['rooms'])}
    P = d['positions']
    pieces = [g for g in d['pieces'] if len(g) >= 2]
    g0 = pieces[0]
    span = max(max(P[n][0] for n in g0) - min(P[n][0] for n in g0), max(P[n][1] for n in g0) - min(P[n][1] for n in g0), 1e-6)
    k = min(70.0, 1300.0 / span)
    place, x0, y0, rowh, pad, maxw = {}, 0.0, 0.0, 0.0, 40, 1400
    for g in pieces:
        xs = [P[n][0] for n in g]; ys = [P[n][1] for n in g]
        w, h = (max(xs) - min(xs)) * k, (max(ys) - min(ys)) * k
        if x0 > 0 and x0 + w > maxw:
            x0, y0, rowh = 0.0, y0 + rowh + 50, 0.0
        for n in g:
            place[n] = ((P[n][0] - min(xs)) * k + x0 + pad, (max(ys) - P[n][1]) * k + y0 + pad + 60)
        x0 += w + 60; rowh = max(rowh, h)
    W = max(900, int(max(x for x, _ in place.values()) + pad + 20)); H = int(max(y for _, y in place.values()) + pad + 20)
    im = Image.new('RGB', (W, H), 'white'); dr = ImageDraw.Draw(im)
    for a, b, h in d['zips']:
        if a in place and b in place: dr.line([place[a], place[b]], fill=(240, 170, 170), width=1)
    for a, b in d['same_place']:
        if a in place and b in place: dr.line([place[a], place[b]], fill=(0, 0, 0), width=3)
    for a, b, h in d['walks'] + d['cross_used']:
        if a in place and b in place:
            ra, rb = a.split(':')[0], b.split(':')[0]
            dr.line([place[a], place[b]], fill=col[ra] if ra == rb else (0, 0, 0), width=2 if ra == rb else 3)
    for n, (x, y) in place.items():
        dr.ellipse([x - 4, y - 4, x + 4, y + 4], fill=col[n.split(':')[0]])
        dr.text((x + 5, y - 6), n.split(':')[1], fill=(60, 60, 60), font=SMALL)
    s = d['stats']
    dr.text((10, 8), f"{d['age']} — whole-age node map ({s['cross_room_links_used']} of {s['cross_room_links']} "
                     f"room-to-room links agree and are used)", fill='black', font=BIG)
    lx = 10
    for r in d['rooms']:
        dr.rectangle([lx, 36, lx + 12, 48], fill=col[r]); dr.text((lx + 16, 34), r, fill='black', font=MID); lx += 80
    dr.text((lx + 10, 34), 'black: between rooms   pink: zip', fill=(90, 90, 90), font=MID)
    name = os.path.join(out, f"age-{os.path.basename(path).replace('.json', '.png')}")
    im.save(name); print(name, im.size)


def main():
    if len(sys.argv) != 4 or sys.argv[1] not in ('rooms', 'ages'):
        sys.exit(__doc__)
    mode, src, out = sys.argv[1:]
    os.makedirs(out, exist_ok=True)
    if mode == 'rooms':
        rooms_sheets(src, out)
    else:
        for fn in sorted(os.listdir(src)):
            if fn.endswith('.json'):
                age_map(os.path.join(src, fn), out)


if __name__ == '__main__':
    main()
