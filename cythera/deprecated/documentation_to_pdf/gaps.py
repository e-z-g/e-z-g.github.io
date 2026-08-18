import struct
from style_run_parser import parse_styl, TEXTS
from resource_fork_parser import res

pinf = {}
for rid, name, p in res['pInf']:
    page = rid // 100 - 2   # 0-based page index
    vals = struct.unpack('>%dH' % (len(p)//2), p)
    pinf.setdefault(page, []).append((rid, vals))
for k in pinf: pinf[k].sort()

PICTS = dict((r[0], r[2]) for r in res['PICT'])
def picsize(pid):
    t,l,b,r = struct.unpack('>hhhh', PICTS[pid][2:10])
    return (r-l, b-t)

def style_at(runs, pos):
    cur = runs[0]
    for r in runs:
        if r['start'] <= pos: cur = r
        else: break
    return cur

for pi in range(10):
    tid = 128 + pi
    txt = TEXTS[tid]
    runs = parse_styl(tid)
    lines = txt.split(b'\r')
    print('===== page', pi+1, 'lines', len(lines))
    pos = 0
    gaps = []
    cur = None
    for i, ln in enumerate(lines):
        st = style_at(runs, pos)
        blank = ln.strip(b' \xca\t') == b''
        if blank:
            if cur is None: cur = [i, 0, 0]
            cur[1] += 1
            cur[2] += st['height']
        else:
            if cur is not None and cur[1] >= 2:
                gaps.append(tuple(cur))
            cur = None
        pos += len(ln) + 1
    if cur is not None and cur[1] >= 2: gaps.append(tuple(cur))
    print('  gaps (startline, nlines, px):', gaps)
    print('  pics:', [(v[0], picsize(v[0]), v[1:]) for rid, v in pinf.get(pi, [])])
