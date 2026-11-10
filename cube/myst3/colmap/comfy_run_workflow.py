#!/usr/bin/env python3
"""
Run a ComfyUI workflow saved from its editor (the "UI" .json, with nodes,
links and widget values) through a running ComfyUI's HTTP API, which takes
only the "API" form: to check that a workflow left for someone to open and
change actually runs as saved.

    python comfy_run_workflow.py WORKFLOW.json [--server http://127.0.0.1:8189] [--timeout 3600]

Only nodes switched on (mode 0) are sent; notes, and groups muted or bypassed
(mode 2 and 4) are left out, and a link from a bypassed node is followed
through to its matching input. Each node's widget values are given to its
inputs in the order the server's /object_info lists them, skipping the
"control after generate" value that follows a seed. Subgraphs are not
handled (ComfyUI's flat templates only). Prints the outputs' file names.
Standard library only.
"""
import argparse
import json
import os
import time
import urllib.request
import uuid


def api(server, path, data=None):
    req = urllib.request.Request(server + path, data=json.dumps(data).encode() if data is not None else None,
                                 headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read())


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('workflow'); ap.add_argument('--server', default=os.environ.get('COMFY_SERVER', 'http://127.0.0.1:8189'))
    ap.add_argument('--timeout', type=int, default=3600)
    a = ap.parse_args()
    w = json.load(open(a.workflow, encoding='utf-8'))
    info = api(a.server, '/object_info')
    nodes = {n['id']: n for n in w['nodes']}
    links = {l[0]: l for l in w['links']}          # id, from node, from slot, to node, to slot, type
    live = {i for i, n in nodes.items() if n.get('mode', 0) == 0 and n['type'] in info}

    def source(link_id):
        """The live node and slot a link comes from, through bypassed nodes."""
        l = links[link_id]
        src, slot = l[1], l[2]
        n = nodes[src]
        if n.get('mode', 0) == 4:                   # bypassed: take its input of the same type
            want = l[5]
            for inp in n.get('inputs', []):
                if inp.get('link') is not None and inp.get('type') == want:
                    return source(inp['link'])
            return None
        return (str(src), slot) if src in live else None

    prompt = {}
    for i in sorted(live):
        n = nodes[i]
        spec = info[n['type']]['input']
        order = list(spec.get('required', {}).items()) + list(spec.get('optional', {}).items())
        linked = {inp['name']: inp['link'] for inp in n.get('inputs', []) if inp.get('link') is not None}
        widgets = list(n.get('widgets_values') or [])
        if isinstance(n.get('widgets_values'), dict):
            widgets = []
        inputs = {}
        # what the editor draws as a connection point (no "widget" on it) is a socket; every
        # other input of the node is a setting with a value in widgets_values, in this order
        sockets = {inp['name'] for inp in n.get('inputs', []) if 'widget' not in inp}
        for name, s in order:
            is_widget = name not in sockets
            if name in linked:
                src = source(linked[name])
                if src:
                    inputs[name] = [src[0], src[1]]
                if is_widget and widgets:               # a widget turned into an input still holds a value
                    widgets.pop(0)
                    if name in ('seed', 'noise_seed') and widgets and widgets[0] in ('fixed', 'randomize', 'increment', 'decrement'):
                        widgets.pop(0)
                continue
            if is_widget and widgets:
                inputs[name] = widgets.pop(0)
                if name in ('seed', 'noise_seed') and widgets and widgets[0] in ('fixed', 'randomize', 'increment', 'decrement'):
                    widgets.pop(0)
        if n['type'] == 'LoadImage' and 'upload' in inputs:
            inputs.pop('upload')
        prompt[str(i)] = {'class_type': n['type'], 'inputs': inputs}
    print('sending', len(prompt), 'nodes:', ', '.join(sorted({v["class_type"] for v in prompt.values()})), flush=True)
    r = api(a.server, '/prompt', {'prompt': prompt, 'client_id': uuid.uuid4().hex})
    if r.get('node_errors'):
        raise SystemExit('node errors: ' + json.dumps(r['node_errors'])[:3000])
    pid = r['prompt_id']
    t0 = time.time()
    while True:
        if time.time() - t0 > a.timeout:
            api(a.server, '/interrupt', {})
            raise SystemExit(f'timed out after {a.timeout} s')
        h = api(a.server, f'/history/{pid}')
        if pid in h:
            st = h[pid].get('status', {})
            if st.get('status_str') == 'error':
                raise SystemExit('ComfyUI error: ' + json.dumps(st.get('messages', []))[:3000])
            if st.get('completed'):
                break
        time.sleep(5)
    print(f'done in {time.time() - t0:.0f} s')
    for nid, out in h[pid]['outputs'].items():
        for key, items in out.items():
            if isinstance(items, list):
                for it in items:
                    if isinstance(it, dict) and 'filename' in it:
                        print(' ', key, it.get('subfolder', ''), it['filename'])


if __name__ == '__main__':
    main()
