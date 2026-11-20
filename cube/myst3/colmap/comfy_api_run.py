#!/usr/bin/env python3
r"""
Queues an API-format ComfyUI workflow on a running ComfyUI and waits for it: prints each node's outputs (files
written) or the error.

    python comfy_api_run.py WORKFLOW.json [--server 127.0.0.1:8189] [--timeout 5400]
"""
import argparse
import json
import time
import urllib.request

ap = argparse.ArgumentParser(); ap.add_argument('workflow'); ap.add_argument('--server', default='127.0.0.1:8189')
ap.add_argument('--timeout', type=float, default=5400)
a = ap.parse_args()
g = json.load(open(a.workflow, encoding='utf-8'))
req = urllib.request.Request(f'http://{a.server}/prompt', data=json.dumps({'prompt': g}).encode(), headers={'Content-Type': 'application/json'})
try:
    pid = json.load(urllib.request.urlopen(req))['prompt_id']
except urllib.error.HTTPError as e:
    raise SystemExit(e.read().decode()[:3000])
t0 = time.time()
while time.time() - t0 < a.timeout:
    h = json.load(urllib.request.urlopen(f'http://{a.server}/history/{pid}'))
    if pid in h:
        st = h[pid].get('status', {})
        for k, o in h[pid].get('outputs', {}).items():
            print(k, json.dumps(o)[:300])
        for m in st.get('messages', []):
            if m[0] == 'execution_error':
                print('ERROR', json.dumps(m[1])[:2000])
        print('status', st.get('status_str'), f'{time.time() - t0:.0f} s')
        break
    time.sleep(10)
else:
    print('timed out waiting')
