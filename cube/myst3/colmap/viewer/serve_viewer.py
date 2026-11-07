#!/usr/bin/env python3
"""
Serve viewer/index.html with a room's packed data beside it, for a browser on this
machine or, through a tunnel, on a phone.

    python serve_viewer.py DATA_DIR [--port 8765] [--token TOKEN]

DATA_DIR is export_viewer_data.py's output, served at data/. Everything is under a
path prefix /TOKEN/ (random unless given) and every other path answers 404, so a
public tunnel to the port shows nothing to someone who has only the host name.
--token '' serves at the root instead: some phone chat apps drop a link's path.
Prints the local address. Standard library only.
"""
import argparse
import functools
import http.server
import os
import secrets

HERE = os.path.dirname(os.path.abspath(__file__))


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, token, data, **kw):
        self.token, self.data = token, data
        super().__init__(*a, directory=HERE, **kw)

    def translate_path(self, path):
        path = path.split('?', 1)[0].split('#', 1)[0]
        pre = f'/{self.token}/' if self.token else '/'
        if not path.startswith(pre):
            return os.path.join(HERE, '.no-such-file')
        rest = path[len(pre):]
        if rest in ('', 'index.html'):
            return os.path.join(HERE, 'index.html')
        if rest.startswith('data/') and '/' not in rest[5:] and not rest[5:].startswith('.'):
            return os.path.join(self.data, rest[5:])
        return os.path.join(HERE, '.no-such-file')

    def end_headers(self):
        self.send_header('Cache-Control', 'no-cache')
        super().end_headers()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('data'); ap.add_argument('--port', type=int, default=8765)
    ap.add_argument('--token', default=secrets.token_urlsafe(9))
    a = ap.parse_args()
    h = functools.partial(Handler, token=a.token, data=os.path.abspath(a.data))
    srv = http.server.ThreadingHTTPServer(('127.0.0.1', a.port), h)
    print(f'http://127.0.0.1:{a.port}/' + (f'{a.token}/' if a.token else ''), flush=True)
    srv.serve_forever()


if __name__ == '__main__':
    main()
