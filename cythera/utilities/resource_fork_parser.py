import struct, sys, json

d = open('build/out.rsrc','rb').read()
dataOff, mapOff, dataLen, mapLen = struct.unpack('>IIII', d[:16])
m = d[mapOff:mapOff+mapLen]
typeListOff, nameListOff = struct.unpack('>HH', m[24:28])
tl = m[typeListOff:]
numTypes = struct.unpack('>H', tl[:2])[0] + 1
res = {}
for i in range(numTypes):
    off = 2 + i*8
    rtype = tl[off:off+4].decode('latin-1')
    cnt = struct.unpack('>H', tl[off+4:off+6])[0] + 1
    refOff = struct.unpack('>H', tl[off+6:off+8])[0]
    items = []
    for j in range(cnt):
        ro = refOff + j*12
        rid, nameOff = struct.unpack('>hH', tl[ro:ro+4])
        attr = tl[ro+4]
        doff = struct.unpack('>I', b'\x00'+tl[ro+5:ro+8])[0]
        name = ''
        if nameOff != 0xFFFF:
            nl = m[nameListOff+nameOff]
            name = m[nameListOff+nameOff+1:nameListOff+nameOff+1+nl].decode('mac-roman')
        abs_off = dataOff + doff
        ln = struct.unpack('>I', d[abs_off:abs_off+4])[0]
        payload = d[abs_off+4:abs_off+4+ln]
        items.append((rid, name, payload))
    res[rtype] = items

if __name__ == '__main__':
    for t, items in sorted(res.items()):
        print(f"{t}: {len(items)} resources, ids {[x[0] for x in items][:12]}{'...' if len(items)>12 else ''}, total {sum(len(x[2]) for x in items)} bytes")
