#!/usr/bin/env python3
r"""
Pictures through MiniMax H3's video VAE and back (encode, decode, nothing generated) on a running ComfyUI: how much
detail the VAE alone loses, to score with walk_fidelity.py against what H3's walks keep.

    python vae_roundtrip.py IN.png [IN2.png ...] --out DIR [--vae minimax_h3_video_vae_fp16.safetensors]
        [--server $COMFY_SERVER] [--comfy-input C:\ComfyUI\input] [--comfy-output C:\ComfyUI\output]

Writes DIR/<name>_vae.png for each. Standard library only.
"""
import argparse
import glob
import json
import os
import shutil
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
    ap.add_argument('images', nargs='+'); ap.add_argument('--out', required=True)
    ap.add_argument('--vae', default='minimax_h3_video_vae_fp16.safetensors')
    ap.add_argument('--server', default=os.environ.get('COMFY_SERVER', 'http://127.0.0.1:8189'))
    ap.add_argument('--comfy-input', default=r'C:\ComfyUI\input'); ap.add_argument('--comfy-output', default=r'C:\ComfyUI\output')
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    for path in a.images:
        tag = uuid.uuid4().hex[:8]
        name = f'vae_rt_{tag}.png'
        shutil.copy(path, os.path.join(a.comfy_input, name))
        g = {'1': {'class_type': 'VAELoader', 'inputs': {'vae_name': a.vae}},
             '2': {'class_type': 'LoadImage', 'inputs': {'image': name}},
             '3': {'class_type': 'VAEEncode', 'inputs': {'pixels': ['2', 0], 'vae': ['1', 0]}},
             '4': {'class_type': 'VAEDecode', 'inputs': {'samples': ['3', 0], 'vae': ['1', 0]}},
             '5': {'class_type': 'SaveImage', 'inputs': {'images': ['4', 0], 'filename_prefix': f'vae_rt/{tag}'}}}
        pid = api(a.server, '/prompt', {'prompt': g, 'client_id': tag})['prompt_id']
        t0 = time.time()
        while True:
            h = api(a.server, f'/history/{pid}')
            if pid in h:
                st = h[pid].get('status', {})
                if st.get('status_str') == 'error':
                    raise SystemExit(f'ComfyUI error: {st}')
                if st.get('completed'):
                    break
            if time.time() - t0 > 1800:
                raise SystemExit('timed out')
            time.sleep(2)
        got = sorted(glob.glob(os.path.join(a.comfy_output, 'vae_rt', f'{tag}*.png')))[-1]
        dst = os.path.join(a.out, os.path.splitext(os.path.basename(os.path.dirname(path)))[0] + '_vae.png')
        shutil.copy(got, dst)
        print(f'{path} -> {dst} ({time.time() - t0:.0f} s)')


if __name__ == '__main__':
    main()
