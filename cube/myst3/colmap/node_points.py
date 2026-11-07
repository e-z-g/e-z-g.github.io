"""How many 3D points each face of the given nodes sees in a model.

    python node_points.py IMAGES.txt 1001,2018

Node numbers as in prepare_age.py (MA-NNNN); a node seeing only a handful is
placed by too little to trust."""
import re, sys, collections
L = [l for l in open(sys.argv[1]) if not l.startswith('#')]
want = set(sys.argv[2].split(','))
c = collections.defaultdict(dict)
for i in range(0, len(L) - 1, 2):
    name = L[i].split()[-1]
    m = re.match(r'(f\d)/MA-(\d+)\.jpg', name)
    if m and m.group(2) in want:
        ids = L[i + 1].split()[2::3]
        c[m.group(2)][m.group(1)] = sum(1 for k in ids if k != '-1')
for n in sorted(c):
    print(n, dict(sorted(c[n].items())), 'total', sum(c[n].values()))
