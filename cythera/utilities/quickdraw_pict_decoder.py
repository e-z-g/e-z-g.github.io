import struct
from PIL import Image
from resource_fork_parser import res
from pictscan import SIZES

PICTS = dict((r[0], r[2]) for r in res['PICT'])

def unpackbits(data, p, expected):
    out = bytearray()
    end = p
    while len(out) < expected:
        b = data[end]; end += 1
        if b & 0x80:
            n = 257 - b
            out.extend(bytes([data[end]]) * n); end += 1
        else:
            n = b + 1
            out.extend(data[end:end+n]); end += n
    return bytes(out[:expected]), end

def read_bits(d, p, op):
    direct = op in (0x009A, 0x009B)
    region = op in (0x0091, 0x0099, 0x009B)
    if direct: p += 4
    rowBytes = struct.unpack('>H', d[p:p+2])[0]
    ispm = bool(rowBytes & 0x8000) or direct
    rb = rowBytes & 0x3FFF
    t, l, b, r = struct.unpack('>hhhh', d[p+2:p+10])
    palette = None
    packType = 0; pixelSize = 1; cmpCount = 1
    if ispm:
        (ver, packType, packSize, hres, vres, pixelType, pixelSize,
         cmpCount, cmpSize, planeBytes, pmTable, pmRes) = struct.unpack('>HHIIIHHHHIII', d[p+10:p+46])
        p += 46
        if not direct:
            seed, flags, cnt = struct.unpack('>IHH', d[p:p+8]); p += 8
            pal = [0]*768
            for i in range(cnt+1):
                idx, rr, gg, bb = struct.unpack('>HHHH', d[p:p+8]); p += 8
                if flags & 0x8000: idx = i
                idx &= 0xFF
                pal[idx*3], pal[idx*3+1], pal[idx*3+2] = rr >> 8, gg >> 8, bb >> 8
            palette = pal
    else:
        p += 10
        pixelSize = 1
    p += 18  # srcRect(8) dstRect(8) mode(2)
    if region:
        ln = struct.unpack('>H', d[p:p+2])[0]
        p += ln
    w, h = r - l, b - t
    rows = []
    packed = (rb >= 8) and packType not in (1, 2)
    for i in range(h):
        if not packed:
            rows.append(d[p:p+rb]); p += rb
        else:
            if rb > 250:
                ln = struct.unpack('>H', d[p:p+2])[0]; p += 2
            else:
                ln = d[p]; p += 1
            rows.append(d[p:p+ln]); p += ln
    # build image
    if direct and packType == 4:
        img = Image.new('RGB', (w, h))
        px = img.load()
        for y, chunk in enumerate(rows):
            raw, _ = unpackbits(chunk, 0, w*cmpCount)
            off = 0 if cmpCount == 3 else w
            for x in range(w):
                px[x, y] = (raw[off+x], raw[off+w+x], raw[off+2*w+x])
        return img, p
    if direct and packType == 3 and pixelSize == 16:
        img = Image.new('RGB', (w, h))
        px = img.load()
        for y, chunk in enumerate(rows):
            raw = bytearray()
            q = 0
            while len(raw) < w*2:
                fl = chunk[q]; q += 1
                if fl & 0x80:
                    n = 257 - fl
                    raw.extend(chunk[q:q+2] * n); q += 2
                else:
                    n = fl + 1
                    raw.extend(chunk[q:q+2*n]); q += 2*n
            for x in range(w):
                v = (raw[2*x] << 8) | raw[2*x+1]
                px[x, y] = (((v >> 10) & 31) * 255 // 31, ((v >> 5) & 31) * 255 // 31, (v & 31) * 255 // 31)
        return img, p
    if pixelSize == 8:
        buf = bytearray()
        for chunk in rows:
            raw = chunk if not packed else unpackbits(chunk, 0, rb)[0]
            buf.extend(raw[:w].ljust(w, b'\x00'))
        img = Image.frombytes('P', (w, h), bytes(buf))
        img.putpalette(palette or sum(([i, i, i] for i in range(256)), []))
        return img.convert('RGB'), p
    if pixelSize == 1:
        buf = bytearray()
        for chunk in rows:
            raw = chunk if not packed else unpackbits(chunk, 0, rb)[0]
            buf.extend(raw[:rb].ljust(rb, b'\x00'))
        img = Image.frombytes('1', (w, h), bytes(buf))
        img = img.point(lambda v: 255 - v)  # 1 = black in QuickDraw
        return img.convert('RGB'), p
    if pixelSize in (2, 4):
        buf = bytearray()
        ppb = 8 // pixelSize
        for chunk in rows:
            raw = chunk if not packed else unpackbits(chunk, 0, rb)[0]
            line = bytearray()
            for byte in raw:
                for k in range(ppb):
                    shift = 8 - pixelSize*(k+1)
                    line.append((byte >> shift) & ((1 << pixelSize)-1))
            buf.extend(line[:w].ljust(w, b'\x00'))
        img = Image.frombytes('P', (w, h), bytes(buf))
        img.putpalette(palette or sum(([i, i, i] for i in range(256)), []))
        return img.convert('RGB'), p
    raise Exception('unsupported pixelSize=%d packType=%d' % (pixelSize, packType))

def decode(pid):
    d = PICTS[pid]
    p = 10
    imgs = []
    while p < len(d):
        if p % 2: p += 1
        op = struct.unpack('>H', d[p:p+2])[0]; p += 2
        if op == 0x00FF: break
        if op in (0x0090, 0x0091, 0x0098, 0x0099, 0x009A, 0x009B):
            img, p = read_bits(d, p, op)
            imgs.append(img)
            continue
        sz = SIZES.get(op)
        if sz is None:
            raise Exception('unknown op %04x in PICT %d' % (op, pid))
        if sz >= 0:
            p += sz
        elif sz == -1:
            if op == 0x0001:
                p += struct.unpack('>H', d[p:p+2])[0]
            elif op == 0x00A1:
                p += 4 + struct.unpack('>H', d[p+2:p+4])[0]
            else:
                p += 2 + struct.unpack('>H', d[p:p+2])[0]
        elif sz in (-2, -3, -4, -5):
            p += {0x0028: 4}.get(op, 2 if sz == -2 else 1)
            p += 1 + d[p]
        else:
            raise Exception('op %04x needs handling' % op)
    if not imgs:
        raise Exception('no image in PICT %d' % pid)
    return imgs[0]

if __name__ == '__main__':
    import os
    os.makedirs('build/img', exist_ok=True)
    for pid in sorted(PICTS):
        if pid == 128:
            continue
        try:
            im = decode(pid)
            im.save('build/img/%d.png' % pid)
            print(pid, im.size)
        except Exception as e:
            print(pid, 'ERR', e)
