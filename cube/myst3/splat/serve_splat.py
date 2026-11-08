#!/usr/bin/env python3
"""
Serve a folder of splat files with the headers a web splat viewer on another
site needs to fetch them (Access-Control-Allow-Origin), and byte ranges for
viewers that stream.

    python serve_splat.py FOLDER [--port 8780]

Put a tunnel in front (cloudflared tunnel --url http://127.0.0.1:8780) and open,
for example, Brush's web viewer with ?url=https://<tunnel>/<file>.ply.
"""
import argparse
import functools
import http.server
import os
import re


class Handler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Headers', 'Range')
        self.send_header('Access-Control-Expose-Headers', 'Content-Length, Content-Range, Accept-Ranges')
        self.send_header('Accept-Ranges', 'bytes')
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(204); self.end_headers()

    def send_head(self):
        rng = self.headers.get('Range')
        path = self.translate_path(self.path)
        if not rng or not os.path.isfile(path):
            return super().send_head()
        m = re.fullmatch(r'bytes=(\d*)-(\d*)', rng.strip())
        size = os.path.getsize(path)
        if not m:
            return super().send_head()
        a = int(m.group(1)) if m.group(1) else max(0, size - int(m.group(2)))
        b = int(m.group(2)) if m.group(1) and m.group(2) else size - 1
        b = min(b, size - 1)
        f = open(path, 'rb'); f.seek(a)
        self.send_response(206)
        self.send_header('Content-Type', self.guess_type(path))
        self.send_header('Content-Range', f'bytes {a}-{b}/{size}')
        self.send_header('Content-Length', str(b - a + 1))
        self.end_headers()
        self._left = b - a + 1
        return f

    def copyfile(self, source, outputfile):
        left = getattr(self, '_left', None)
        if left is None:
            return super().copyfile(source, outputfile)
        while left > 0:
            chunk = source.read(min(1 << 20, left))
            if not chunk:
                break
            outputfile.write(chunk); left -= len(chunk)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('folder'); ap.add_argument('--port', type=int, default=8780)
    a = ap.parse_args()
    handler = functools.partial(Handler, directory=a.folder)
    http.server.ThreadingHTTPServer(('127.0.0.1', a.port), handler).serve_forever()


if __name__ == '__main__':
    main()
