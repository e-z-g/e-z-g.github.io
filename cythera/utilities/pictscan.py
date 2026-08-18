import struct, sys
from resource_fork_parser import res

PICTS = dict((r[0], r[2]) for r in res['PICT'])

# opcode -> fixed data size (v2). -1 means special handling
SIZES = {
0x0000:0,0x0001:-1,0x0002:8,0x0003:2,0x0004:1,0x0005:2,0x0006:4,0x0007:4,0x0008:2,
0x0009:8,0x000A:8,0x000B:4,0x000C:4,0x000D:2,0x000E:4,0x000F:4,0x0010:8,0x0011:1,
0x0012:-1,0x0013:-1,0x0014:-1,0x0015:2,0x0016:2,0x0017:0,0x0018:0,0x0019:0,
0x001A:6,0x001B:6,0x001C:0,0x001D:6,0x001E:0,0x001F:6,0x0020:8,0x0021:4,0x0022:6,
0x0023:2,0x0024:-2,0x0025:-2,0x0026:-2,0x0027:-2,0x0028:-3,0x0029:-4,0x002A:-5,
0x002B:-4,0x002C:-2,0x002D:-2,0x002E:-2,0x002F:-2,0x0030:8,0x0031:8,0x0032:8,0x0033:8,
0x0034:8,0x0035:8,0x0036:8,0x0037:8,0x0038:0,0x0039:0,0x003A:0,0x003B:0,0x003C:0,
0x003D:0,0x003E:0,0x003F:0,0x0040:8,0x0041:8,0x0042:8,0x0043:8,0x0044:8,0x0045:8,
0x0046:8,0x0047:8,0x0048:0,0x0049:0,0x004A:0,0x004B:0,0x004C:0,0x004D:0,0x004E:0,
0x004F:0,0x0050:8,0x0051:8,0x0052:8,0x0053:8,0x0054:8,0x0055:8,0x0056:8,0x0057:8,
0x0058:0,0x0059:0,0x005A:0,0x005B:0,0x005C:0,0x005D:0,0x005E:0,0x005F:0,
0x0060:12,0x0061:12,0x0062:12,0x0063:12,0x0064:12,0x0065:12,0x0066:12,0x0067:12,
0x0068:4,0x0069:0,0x006A:0,0x006B:0,0x006C:4,0x006D:0,0x006E:0,0x006F:0,
0x0070:-1,0x0071:-1,0x0072:-1,0x0073:-1,0x0074:-1,0x0075:-1,0x0076:-1,0x0077:-1,
0x0078:0,0x0079:0,0x007A:0,0x007B:0,0x007C:0,0x007D:0,0x007E:0,0x007F:0,
0x0080:-1,0x0081:-1,0x0082:-1,0x0083:-1,0x0084:-1,0x0085:-1,0x0086:-1,0x0087:-1,
0x0088:0,0x0089:0,0x008A:0,0x008B:0,0x008C:0,0x008D:0,0x008E:0,0x008F:0,
0x0090:-10,0x0091:-10,0x0092:-1,0x0093:-1,0x0094:-1,0x0095:-1,0x0096:-1,0x0097:-1,
0x0098:-10,0x0099:-10,0x009A:-11,0x009B:-11,
0x00A0:2,0x00A1:-1,0x00FF:0,
0x0C00:24,
}

def scan(pid, verbose=True):
    d = PICTS[pid]
    p = 0
    size, t, l, b, r = struct.unpack('>Hhhhh', d[:10])
    if verbose: print(f'PICT {pid}: size={size} bounds=({t},{l},{b},{r}) len={len(d)}')
    p = 10
    n = 0
    while p < len(d) and n < 200:
        if p % 2: p += 1
        op = struct.unpack('>H', d[p:p+2])[0]
        p += 2
        if op == 0x00FF:
            if verbose: print(' OpEndPic')
            break
        sz = SIZES.get(op)
        info = ''
        if sz is None:
            if verbose: print(f' UNKNOWN op {op:04x} at {p-2}')
            break
        if sz >= 0:
            p += sz
        elif sz == -1:
            if op in (0x0001,):
                ln = struct.unpack('>H', d[p:p+2])[0]
                p += ln
            elif op in (0x00A1,):
                kind, ln = struct.unpack('>HH', d[p:p+4])
                info = f'kind={kind} len={ln}'
                p += 4 + ln
            elif op in (0x0012,0x0013,0x0014,0x0070,0x0071,0x0072,0x0073,0x0074,0x0075,0x0076,0x0077,
                        0x0080,0x0081,0x0082,0x0083,0x0084,0x0085,0x0086,0x0087,
                        0x0092,0x0093,0x0094,0x0095,0x0096,0x0097):
                ln = struct.unpack('>H', d[p:p+2])[0]
                p += 2 + ln
            else:
                print(' unhandled -1', hex(op)); break
        elif sz in (-2,-3,-4,-5):
            # text ops
            if op == 0x0028:
                p += 4
            elif op == 0x0029:
                p += 1
            elif op == 0x002A:
                p += 2
            elif op == 0x002B:
                p += 1
            else:
                p += 2
            ln = d[p]; txt = d[p+1:p+1+ln]
            info = repr(txt[:40])
            p += 1 + ln
        elif sz == -10:
            # BitsRect / PackBitsRect
            newp, info = do_bits(d, p, op, packed=True, region=(op in (0x0091,0x0099)))
            p = newp
        elif sz == -11:
            newp, info = do_bits(d, p, op, direct=True, region=(op == 0x009B))
            p = newp
        if verbose: print(f' op {op:04x} {info}')
        n += 1
    return p

def do_bits(d, p, op, packed=False, direct=False, region=False):
    start = p
    if direct:
        p += 4  # baseAddr pmVersion? actually pixMap ptr
    rowBytes = struct.unpack('>H', d[p:p+2])[0]
    pm = rowBytes & 0x8000
    rb = rowBytes & 0x3FFF
    t,l,b,r = struct.unpack('>hhhh', d[p+2:p+10])
    info = f'rowBytes={rb} pixmap={bool(pm)} bounds=({t},{l},{b},{r})'
    if pm or direct:
        ver, packType, packSize, hres, vres, pixelType, pixelSize, cmpCount, cmpSize, planeBytes, pmTable, pmReserved = struct.unpack('>HHIIIHHHHIII', d[p+10:p+10+36])
        info += f' packType={packType} pixelSize={pixelSize} cmpCount={cmpCount} cmpSize={cmpSize}'
        p += 46
        if not direct:
            # color table
            seed, flags, cnt = struct.unpack('>IHH', d[p:p+8])
            p += 8 + (cnt+1)*8
            info += f' ctSize={cnt+1}'
    else:
        p += 10
    p += 8+8+2  # srcRect dstRect mode
    if region:
        ln = struct.unpack('>H', d[p:p+2])[0]
        p += ln
    # pixel data
    rows = b - t
    if rb < 8:
        p += rows * rb
    else:
        for i in range(rows):
            if rb > 250:
                ln = struct.unpack('>H', d[p:p+2])[0]; p += 2
            else:
                ln = d[p]; p += 1
            p += ln
    return p, info

if __name__ == '__main__':
    for pid in [int(x) for x in sys.argv[1:]]:
        scan(pid)
        print()
