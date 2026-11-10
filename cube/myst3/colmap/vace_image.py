#!/usr/bin/env python3
"""
A still picture from Wan 2.2 VACE-Fun (A14B, two experts as GGUF) through a
running ComfyUI: text to a one-frame video, saved as a PNG. Made for a test
reference picture of an invented person (no real person's likeness).

    python vace_image.py OUT.png --prompt "..." [--size 512x896] [--steps 20] [--seed 1]
        [--high NAME.gguf] [--low NAME.gguf] [--server http://127.0.0.1:8188]
        [--comfy-output C:\\ComfyUI\\output]

The high-noise expert runs the first half of the steps and the low-noise one
the rest (ModelSamplingSD3 shift 8, cfg 3.5, euler); WanVaceToVideo with no
control video or reference gives plain text-to-video, here one frame long.
Standard library only.
"""
import argparse
import json
import os
import shutil
import time
import urllib.request
import uuid

NEG = ('blurry, distorted face, extra fingers, deformed hands, cartoon, painting, illustration, text, watermark, '
       'low quality, jpeg artifacts, cropped head')


def api(server, path, data=None):
    req = urllib.request.Request(server + path, data=json.dumps(data).encode() if data is not None else None,
                                 headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read())


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('out'); ap.add_argument('--prompt', required=True)
    ap.add_argument('--size', default='512x896'); ap.add_argument('--steps', type=int, default=20)
    ap.add_argument('--seed', type=int, default=1)
    ap.add_argument('--high', default='Wan2.2-VACE-Fun-A14B-high-noise-Q4_K_M.gguf')
    ap.add_argument('--low', default='Wan2.2-VACE-Fun-A14B-low-noise-Q4_K_M.gguf')
    ap.add_argument('--server', default='http://127.0.0.1:8188')
    ap.add_argument('--comfy-output', default=r'C:\ComfyUI\output')
    ap.add_argument('--timeout', type=int, default=3000)
    a = ap.parse_args()
    W, H = (int(x) for x in a.size.split('x'))
    info = api(a.server, '/object_info')
    vin = info['WanVaceToVideo']['input']
    print('WanVaceToVideo inputs:', list(vin.get('required', {})), list(vin.get('optional', {})), flush=True)
    half = a.steps // 2
    g = {
        '1': {'class_type': 'UnetLoaderGGUF', 'inputs': {'unet_name': a.high}},
        '2': {'class_type': 'UnetLoaderGGUF', 'inputs': {'unet_name': a.low}},
        '3': {'class_type': 'ModelSamplingSD3', 'inputs': {'model': ['1', 0], 'shift': 8.0}},
        '4': {'class_type': 'ModelSamplingSD3', 'inputs': {'model': ['2', 0], 'shift': 8.0}},
        '5': {'class_type': 'CLIPLoader', 'inputs': {'clip_name': 'umt5_xxl_fp8_e4m3fn_scaled.safetensors', 'type': 'wan'}},
        '6': {'class_type': 'CLIPTextEncode', 'inputs': {'clip': ['5', 0], 'text': a.prompt}},
        '7': {'class_type': 'CLIPTextEncode', 'inputs': {'clip': ['5', 0], 'text': NEG}},
        '8': {'class_type': 'VAELoader', 'inputs': {'vae_name': 'wan_2.1_vae.safetensors'}},
        '9': {'class_type': 'WanVaceToVideo', 'inputs': {'positive': ['6', 0], 'negative': ['7', 0], 'vae': ['8', 0],
                                                         'width': W, 'height': H, 'length': 1, 'batch_size': 1, 'strength': 1.0}},
        '10': {'class_type': 'KSamplerAdvanced', 'inputs': {
            'model': ['3', 0], 'add_noise': 'enable', 'noise_seed': a.seed, 'steps': a.steps, 'cfg': 3.5,
            'sampler_name': 'euler', 'scheduler': 'simple', 'positive': ['9', 0], 'negative': ['9', 1],
            'latent_image': ['9', 2], 'start_at_step': 0, 'end_at_step': half, 'return_with_leftover_noise': 'enable'}},
        '11': {'class_type': 'KSamplerAdvanced', 'inputs': {
            'model': ['4', 0], 'add_noise': 'disable', 'noise_seed': a.seed, 'steps': a.steps, 'cfg': 3.5,
            'sampler_name': 'euler', 'scheduler': 'simple', 'positive': ['9', 0], 'negative': ['9', 1],
            'latent_image': ['10', 0], 'start_at_step': half, 'end_at_step': 10000, 'return_with_leftover_noise': 'disable'}},
        '12': {'class_type': 'VAEDecode', 'inputs': {'samples': ['11', 0], 'vae': ['8', 0]}},
        '13': {'class_type': 'SaveImage', 'inputs': {'images': ['12', 0], 'filename_prefix': 'vace_still'}},
    }
    r = api(a.server, '/prompt', {'prompt': g, 'client_id': uuid.uuid4().hex})
    if r.get('node_errors'):
        raise SystemExit('node errors: ' + json.dumps(r['node_errors'])[:3000])
    pid, t0 = r['prompt_id'], time.time()
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
        time.sleep(3)
    im = h[pid]['outputs']['13']['images'][0]
    shutil.copy(os.path.join(a.comfy_output, im.get('subfolder', ''), im['filename']), a.out)
    print(f'{a.out} in {time.time() - t0:.0f} s')


if __name__ == '__main__':
    main()
