#!/usr/bin/env python3
"""
Trial walks for the viewer: each video of a cube net (walk_ends.py --cross-hub, --net, --fill) scored by
cube_edges.py, encoded forwards and backwards, and listed for the viewer's ?crosswalk=NAME and for a page
of links sorted by score.

    python pack_walk_trials.py MANIFEST.json SITE_CUBE_DIR

MANIFEST is a list of {"name", "label", "video", "layout"} (paths on this computer; layout is a layout.json).
Writes SITE_CUBE_DIR/amateria/walk/trials/<name>.mp4 and <name>_back.mp4, trials.json there, and
SITE_CUBE_DIR/walk-trials.html. Needs ffmpeg, numpy, opencv-python (cube_edges.py beside it).
"""
import html
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def score(video, layout):
    net = json.load(open(layout)).get('net')
    if net == 'single-fisheye':
        return None, None                              # one picture: no seam to score
    tool = 'fisheye_seam.py' if net == 'dual-fisheye' else 'cube_edges.py'
    out = subprocess.run([sys.executable, os.path.join(HERE, tool), video, layout], capture_output=True, text=True).stdout
    m = re.search(r'SCORE .*?: (-?[\d.]+); worst rise (-?[\d.]+)', out)
    return (float(m.group(1)), float(m.group(2))) if m else (None, None)


def main():
    manifest, site = sys.argv[1], sys.argv[2]
    out = os.path.join(site, 'amateria', 'walk', 'trials')
    os.makedirs(out, exist_ok=True)
    items = []
    for e in json.load(open(manifest)):
        L = json.load(open(e['layout']))
        rows, cols = L.get('rows', 3), L.get('cols', 4)
        cells = []
        fisheye = None
        if L.get('net') in ('dual-fisheye', 'single-fisheye'):
            W, H = L['size']
            fisheye = {'fov': L['fov'], 'eyes': [e2['axes'] + [[e2['rect'][0] / W, e2['rect'][1] / H, e2['rect'][2] / W, e2['rect'][3] / H]]
                                                 for e2 in L['eyes']]}
            if len(fisheye['eyes']) == 1:              # one eye: the viewer's second slot is the same eye
                fisheye['eyes'].append(fisheye['eyes'][0])
        for c in L.get('cells', []):
            cell = [c['row'], c['col']] + [[int(round(v)) for v in ax] for ax in c['axes']]
            if 'rect' in c and 'size' in L:
                x, y, w, h = c['rect']; W, H = L['size']
                cell.append([x / W, y / H, w / W, h / H])
            cells.append(cell)
        s, worst = score(e['video'], e['layout'])
        for suffix, vf in (('', []), ('_back', ['-vf', 'reverse'])):
            dst = os.path.join(out, e['name'] + suffix + '.mp4')
            if not os.path.exists(dst) or os.path.getmtime(dst) < os.path.getmtime(e['video']):
                subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', e['video'], '-an', *vf, '-c:v', 'libx264', '-crf', '20',
                                '-g', '24', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', dst], check=True)
        item = {'name': e['name'], 'label': e['label'], 'score': s, 'worst': worst, 'rows': rows, 'cols': cols,
                'video': e['name'] + '.mp4', 'back': e['name'] + '_back.mp4',
                'made': os.path.getmtime(e['video'])}         # when the render came back to this computer
        item.update({'fisheye': fisheye} if fisheye else {'cells': cells})
        items.append(item)
        print(f"{e['name']}: score {s}, worst {worst}", flush=True)
    items.sort(key=lambda x: -x['made'])                # newest first
    json.dump(items, open(os.path.join(out, 'trials.json'), 'w'), indent=0)
    import time

    def line(x):
        s = '' if x['score'] is None else '%.2f (worst %.0f)' % (x['score'], x['worst'])
        when = time.strftime('%d %b %H:%M', time.localtime(x['made']))
        return (f'<tr><td class="t">{when}</td><td><a href="./?crosswalk={html.escape(x["name"])}">{html.escape(x["label"])}</a></td>'
                f'<td class="s">{s}</td></tr>')
    rows = '\n'.join(line(x) for x in items)
    page = f'''<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Walk trials: MASS 84 to 89</title>
<style>
body {{ font: 16px/1.4 system-ui, sans-serif; background: #1d1d22; color: #e6e6e6; margin: 0; padding: 16px; }}
h1 {{ font-size: 20px; margin: 0 0 6px; }} p {{ color: #aaa; margin: 0 0 14px; font-size: 14px; }}
table {{ border-collapse: collapse; width: 100%; }} td {{ padding: 7px 8px 7px 0; vertical-align: top; border-top: 1px solid #333; }}
td.t {{ color: #888; white-space: nowrap; font-size: 13px; }} td.s {{ color: #888; white-space: nowrap; font-size: 13px; text-align: right; }}
a {{ color: #9cc8ff; text-decoration: none; }}
</style></head><body>
<h1>Walk trials: Amateria MASS 84 to 89</h1>
<p>Newest first. Each opens the viewer at MASS 84; tap Walk. Score: how far the joins the picture does not
make drift beyond the first frame (lower is better; the worst moment in brackets); cube layouts and fisheye
pairs are scored differently, so compare within a kind. Trials are small and 56 frames long; "Full" ones are
full size.</p>
<table>
{rows}
</table></body></html>
'''
    open(os.path.join(site, 'walk-trials.html'), 'w').write(page)
    print(f'{len(items)} walks; {os.path.join(site, "walk-trials.html")}')


if __name__ == '__main__':
    main()
