#!/usr/bin/env python3
"""Every place Myst III's node scripts read or change a game variable: entry scripts, hotspot conditions and hotspot
scripts, with ScummVM's opcode names (engines/myst3/script.cpp, its OP(...) table, read from a local copy).

    python var_uses.py MYST3_DAT SCRIPT_CPP VAR [VAR ...] [--room TOHO]

An argument counts as the variable when it is the variable itself or a condition on it (|c| & 2047, the encoding
node_states.py describes). An opcode's argument types ("v" variable, "e" condition, "i" number) come from the same
table, so a number that only looks like the variable is marked "(number)". Standard library only.
"""
import argparse, os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from myst3_nodes import load_dat           # noqa: E402
from node_states import records            # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('dat'); ap.add_argument('script_cpp'); ap.add_argument('vars', type=int, nargs='+')
    ap.add_argument('--room')
    a = ap.parse_args()
    names = {int(n): (nm, sig) for n, nm, sig in re.findall(r'OP\(\s*(\d+),\s*(\w+),\s*"(\w*)"', open(a.script_cpp).read())}
    want = set(a.vars)
    hits = lambda c: (abs(c) & 2047) in want
    def show(c):
        v, val = abs(c) & 2047, (abs(c) >> 11) - 1
        t = f'var {v} != 0' if val == -1 else f'var {v} == {val}'
        return ('not ' if c < 0 else '') + t
    for room, blob in sorted(load_dat(a.dat).items()):
        if a.room and room != a.room:
            continue
        for ids, scripts, spots in records(blob):
            where = f'{room} {",".join(map(str, ids)) or "?"}'
            for kind, lst in (('entry', scripts), ('hotspot', spots)):
                for i, (c, ops) in enumerate(lst):
                    cond = show(c) if c not in (-1, 1) else 'always'
                    found = []
                    for op, args in ops:
                        nm, sig = names.get(op, (f'op{op}', ''))
                        if any(hits(x) for x in args):
                            mark = []
                            for j, x in enumerate(args):
                                t = sig[j] if j < len(sig) else '?'
                                mark.append(show(x) if t == 'e' else f'var {x}' if t == 'v' else f'{x}')
                            found.append(f'{nm}({", ".join(mark)})')
                    if found or hits(c):
                        print(f'{where} {kind} {i} [{cond}]: ' + ('; '.join(found) or '(condition only)'))


if __name__ == '__main__':
    main()
