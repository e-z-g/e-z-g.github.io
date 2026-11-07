#!/usr/bin/env python3
"""
Serve viewer/index.html with one or more packed reconstructions beside it, for a
browser on this machine or, through a tunnel, on a phone.

    python serve_viewer.py [NAME=]DATA_DIR ... [--port 8765] [--token TOKEN]

Each DATA_DIR is export_viewer_data.py's output, served at data/NAME/ (NAME
defaults to the folder's name); data/sets.json lists them, with the titles from
their scene.json, for the page's picker. Everything is under a path prefix
/TOKEN/ (random unless given) and every other path answers 404, so a public
tunnel to the port shows nothing to someone who has only the host name.
--token '' serves at the root instead: some phone chat apps drop a link's path.
Prints the local address. Standard library only.
"""
import argparse
import functools
import http.server
import json
import os
import secrets

HERE = os.path.dirname(os.path.abspath(__file__))
MISSING = os.path.join(HERE, '.no-such-file')


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, token, sets, **kw):
        self.token, self.sets = token, sets
        super().__init__(*a, directory=HERE, **kw)

    def rest(self):
        path = self.path.split('?', 1)[0].split('#', 1)[0]
        pre = f'/{self.token}/' if self.token else '/'
        return path[len(pre):] if path.startswith(pre) else None

    def do_GET(self):
        if self.rest() == 'data/sets.json':
            body = json.dumps([{'name': n, 'title': json.load(open(os.path.join(d, 'scene.json'))).get('title') or n}
                               for n, d in self.sets.items()]).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        super().do_GET()

    def translate_path(self, path):
        rest = self.rest()
        if rest is None:
            return MISSING
        if rest in ('', 'index.html'):
            return os.path.join(HERE, 'index.html')
        parts = rest.split('/')
        if len(parts) == 3 and parts[0] == 'data' and parts[1] in self.sets and not parts[2].startswith('.'):
            return os.path.join(self.sets[parts[1]], parts[2])
        return MISSING

    def end_headers(self):
        self.send_header('Cache-Control', 'no-cache')
        super().end_headers()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('data', nargs='+'); ap.add_argument('--port', type=int, default=8765)
    ap.add_argument('--token', default=secrets.token_urlsafe(9))
    a = ap.parse_args()
    sets = {}
    for d in a.data:
        name, _, path = d.partition('=') if '=' in d else ('', '', d)
        path = os.path.abspath(path)
        sets[name or os.path.basename(path.rstrip(os.sep))] = path
    h = functools.partial(Handler, token=a.token, sets=sets)
    srv = http.server.ThreadingHTTPServer(('127.0.0.1', a.port), h)
    print(f'http://127.0.0.1:{a.port}/' + (f'{a.token}/' if a.token else '') + '  sets: ' + ', '.join(sets), flush=True)
    srv.serve_forever()


if __name__ == '__main__':
    main()
