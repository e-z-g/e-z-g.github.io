#!/usr/bin/env python3
"""
How many states each move in Myst III has to be rendered in: the spot items (patches over part of a node's picture,
shown by game variables) at both ends of every walk, and the close-ups (flat frame nodes) the walks lead into.

    python node_states.py MYST3_DAT FACES_INDEX.csv WALK.json [WALK.json ...] --out STATES.json [--spots SPOT_ITEMS.txt]

MYST3_DAT is ScummVM's myst3.dat (the game's node scripts); FACES_INDEX.csv myst3_nodes.py's index (which nodes have
cube faces); each WALK.json node_walk.py's data for an age (its moves, with the room numbering resolved). --spots is a
list of the spot items in the archives ("ROOM entry sub" a line, from m3a_list.py), to check the scripts' item numbers.

A node's record in myst3.dat (engines/myst3/database.cpp) holds its entry scripts, each with a condition, then its
hotspots. The scripts add spot items with opcodes 13 spotItemAdd (item; always), 14 spotItemAddCond (item, condition),
15 spotItemAddCondFade (item, condition; faded in) and 16 spotItemAddMenu (item, condition, ...) (engines/myst3/
script.cpp). A condition (GameState::evaluate, engines/myst3/state.cpp) reads variable |c| & 2047 against the value
(|c| >> 11) - 1: equal to it, or non-zero when that is -1; a negative condition inverts the test. Close-ups are nodes
with no cube faces (drawn as a flat frame: opcodes 7-9), reached by the same hotspot moves.

For each move, every variable the two ends' spot items (and the move's own hotspot condition) read is given each
value the conditions name, 0 and one other value; the states are the distinct pairs (items shown at the start, items
shown at the end) over those values with the move's condition true. That is an upper bound: it takes the variables
as independent, and the game's logic may never reach some combinations. Standard library only.
"""
import argparse, csv, itertools, json, os, sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from myst3_nodes import Reader, opcodes, load_dat   # noqa: E402

SPOT_OPS = {13, 14, 15, 16}
MOVE_OPS = {136, 137, 138}        # goToNodeTransition, goToNodeTrans2, goToNodeTrans1: the node's number first
ZIP_OP = 140


def records(blob):
    """Each node record: (node ids, [(condition, opcodes)] entry scripts, [(condition, opcodes)] hotspots)."""
    r = Reader(blob); out = []
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
        scripts = []
        while not r.eos():
            c = r.s16()
            if c == 0:
                break
            scripts.append((c, opcodes(r)))
        spots = []
        while not r.eos():
            c = r.s16()
            if c == 0:
                break
            if c != -1:
                while True:
                    pitch, heading, w, h = r.u16(), r.u16(), r.s16(), r.s16()
                    if w >= 0 or r.eos():
                        break
                r.u16()
            spots.append((c, opcodes(r)))
        out.append((ids, scripts, spots))
    return out


def var_of(c): return abs(c) & 2047


def holds(c, vals):
    v, t = vals.get(var_of(c), 1 if var_of(c) == 1 else 0), (abs(c) >> 11) - 1
    r = (v == t) if t >= 0 else (v != 0)
    return r if c > 0 else not r


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('dat'); ap.add_argument('faces'); ap.add_argument('walks', nargs='+')
    ap.add_argument('--out', required=True); ap.add_argument('--spots')
    a = ap.parse_args()
    blobs = load_dat(a.dat)
    cube = {(row['room'], int(row['node'])) for row in csv.DictReader(open(a.faces))}
    items = defaultdict(list)          # (room, node) -> [(item, [conditions that must all hold])]
    moves_from = defaultdict(list)     # (room, node) -> [(target node, hotspot condition)] inside the room
    for room, blob in blobs.items():
        for ids, scripts, hs in records(blob):
            for i in ids:
                for sc, ops in scripts:
                    for op, args in ops:
                        if op in SPOT_OPS and args:
                            conds = [sc] if sc != 1 else []
                            if op != 13 and len(args) > 1 and args[1] != 1:
                                conds.append(args[1])
                            items[(room, i)].append((args[0], conds))
                for hc, ops in hs:
                    for op, args in ops:
                        if op in MOVE_OPS and args and args[0] > 0:
                            moves_from[(room, i)].append((args[0], hc))
    known = None
    if a.spots:
        known = defaultdict(set)
        for line in open(a.spots):
            p = line.split()
            if len(p) == 3: known[p[0]].add(int(p[1]))
        n_all = sum(len(v) for v in items.values()); n_ok = sum(1 for (room, _), v in items.items() for it, _ in v if it in known[room])
        print(f'spot items added by scripts: {n_all}; their numbers found in the archives: {n_ok}')

    def states(ends, conds):
        """Distinct (items shown at each end) over the values of the variables involved, with all of conds true."""
        lists = [items.get(e, []) for e in ends]
        cs = [c for lst in lists for _, cc in lst for c in cc] + list(conds)
        vs = sorted({var_of(c) for c in cs})
        cand = {}
        for v in vs:
            named = sorted({(abs(c) >> 11) - 1 for c in cs if var_of(c) == v} - {-1})
            cand[v] = sorted(set([0] + named + [max(named + [0]) + 1]))
        if len(vs) > 14 or (vs and max(len(cand[v]) for v in vs) ** len(vs) > 2_000_000):
            return None, vs
        seen = set()
        for combo in itertools.product(*[cand[v] for v in vs]):
            vals = dict(zip(vs, combo))
            if not all(holds(c, vals) for c in conds):
                continue
            seen.add(tuple(frozenset(it for it, cc in lst if all(holds(c, vals) for c in cc)) for lst in lists))
        return len(seen), vs

    out = {'ages': {}}
    grand = defaultdict(int)
    for wf in a.walks:
        d = json.load(open(wf))['nodes']
        age = os.path.basename(os.path.dirname(os.path.abspath(wf))) or 'amateria'
        if age == 'node_walk': age = 'amateria'
        pairs = {}; close = {}
        for node, hs in d.items():
            room, n = node.split('-')[0], int(node.split('-')[1])
            for h in hs:
                if h['kind'] not in ('walk', 'walk-room'):
                    continue
                if h.get('to'):
                    tr, tn = h['to'].split('-')[0], int(h['to'].split('-')[1])
                    key = tuple(sorted([(room, n), (tr, tn)]))
                    pairs.setdefault(key, []).append(h.get('cond', 1))
                elif h['kind'] == 'walk' and h.get('args') and (room, h['args'][0]) not in cube:
                    close[((room, n), (room, h['args'][0]))] = h.get('cond', 1)
        # close-ups led to from close-ups (frame to frame), followed through the scripts
        todo = [t for _, t in close]; done = set()
        while todo:
            f = todo.pop()
            if f in done: continue
            done.add(f)
            for tgt, hc in moves_from.get(f, []):
                t = (f[0], tgt)
                if t not in cube and t != f:
                    close.setdefault((f, t), hc); todo.append(t)
        rows = []
        for (A, B), conds in pairs.items():
            best = None
            for c in set(conds):        # a move may have several hotspots; the most states over them
                n, vs = states([A, B], [c] if c != 1 else [])
                best = n if best is None or (n is not None and n > best) else best
            rows.append({'kind': 'walk', 'a': f'{A[0]}-{A[1]:04d}', 'b': f'{B[0]}-{B[1]:04d}', 'states': best})
        for (A, B), c in close.items():
            n, vs = states([A, B], [c] if c != 1 else [])
            rows.append({'kind': 'close-up' if A in cube else 'close-up to close-up', 'a': f'{A[0]}-{A[1]:04d}', 'b': f'{B[0]}-{B[1]:04d}', 'states': n})
        out['ages'][age] = rows
        for kind in ('walk', 'close-up', 'close-up to close-up'):
            rk = [r for r in rows if r['kind'] == kind]
            s = sum(r['states'] or 0 for r in rk); big = sum(1 for r in rk if r['states'] is None)
            multi = sum(1 for r in rk if (r['states'] or 0) > 1)
            grand[kind + ' moves'] += len(rk); grand[kind + ' renders'] += s
            print(f'{age:9s} {kind:21s} {len(rk):4d} moves, {multi:4d} with more than one state, {s:5d} renders'
                  + (f' ({big} too many variables to count)' if big else ''))
    print('all:', dict(grand))
    json.dump(out, open(a.out, 'w'), indent=1)


if __name__ == '__main__':
    main()
