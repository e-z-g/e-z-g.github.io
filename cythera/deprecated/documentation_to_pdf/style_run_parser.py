import struct
from resource_fork_parser import res

TEXTS = dict((r[0], r[2]) for r in res['TEXT'])
STYLS = dict((r[0], r[2]) for r in res['styl'])

def parse_styl(pid):
    d = STYLS[pid]
    n = struct.unpack('>H', d[:2])[0]
    runs = []
    for i in range(n):
        o = 2 + i*20
        start, height, ascent, font = struct.unpack('>ihhh', d[o:o+10])
        face = d[o+10]
        size = struct.unpack('>h', d[o+12:o+14])[0]
        rr, gg, bb = struct.unpack('>HHH', d[o+14:o+20])
        runs.append(dict(start=start, height=height, ascent=ascent, font=font,
                         face=face, size=size, color=(rr>>8, gg>>8, bb>>8)))
    return runs

if __name__ == '__main__':
    for pid in sorted(STYLS):
        runs = parse_styl(pid)
        print('=== styl', pid, len(runs), 'runs, text len', len(TEXTS[pid]))
        for r in runs[:14]:
            print('   ', r)
        big = [r for r in runs if r['height'] > 40]
        print('   large-height runs:', [(r['start'], r['height'], r['ascent'], r['size']) for r in big])
