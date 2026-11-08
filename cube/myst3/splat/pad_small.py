# Brush 0.3.0 reads the first 16387 bytes of every image with read_exact, so a smaller file
# fails with "early eof". Pad such JPEGs with zero bytes after their end marker (decoders stop there).
import os, sys
from PIL import Image
n = 0
for root, _, files in os.walk(sys.argv[1]):
    for f in files:
        p = os.path.join(root, f)
        s = os.path.getsize(p)
        if s < 20000:
            with open(p, 'ab') as fh:
                fh.write(b'\0' * (20000 - s))
            with Image.open(p) as im:
                im.load()
            n += 1
print(n, 'images padded')
