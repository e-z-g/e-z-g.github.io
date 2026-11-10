#!/usr/bin/env python3
r"""
A pattern hidden in a generated video, the way QR Code Monster hides one in a
still: Wan 2.2 VACE-Fun through a running ComfyUI, with a greyscale picture
(a QR code) as the control video, given only to the high-noise expert (the
first half of the steps); the low-noise expert finishes with the same text and
no control, so the picture can settle into the scene.

    python vace_qr.py PATTERN.png OUT_DIR --prompt "..." [--strength 0.8] [--size 512x512]
        [--length 49] [--steps 20] [--seed 1] [--all-steps] [--server http://127.0.0.1:8188]

The pattern is held still for every frame (RepeatImageBatch). With
--all-steps the control is given to both experts (for comparison). Writes
OUT_DIR/qr.mp4 at 16 fps. Standard library only.
"""
import argparse
import json
import os
import shutil
import time
import urllib.request
import uuid

NEG = 'blurry, low quality, text, watermark, flat, grey, washed out, distorted'


def api(server, path, data=None):
    req = urllib.request.Request(server + path, data=json.dumps(data).encode() if data is not None else None,
                                 headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read())


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('pattern'); ap.add_argument('out'); ap.add_argument('--prompt', required=True)
    ap.add_argument('--strength', type=float, default=0.8); ap.add_argument('--size', default='512x512')
    ap.add_argument('--length', type=int, default=49); ap.add_argument('--steps', type=int, default=20)
    ap.add_argument('--seed', type=int, default=1); ap.add_argument('--all-steps', action='store_true')
    ap.add_argument('--init-step', type=int, default=0,
                    help='start from the pattern itself (VAE-encoded, every frame), noised only from this step on: video-to-video, '
                         'so its light and dark carry through (the control alone made the layout follow the code, not its brightness)')
    ap.add_argument('--server', default='http://127.0.0.1:8188')
    ap.add_argument('--comfy-input', default=r'C:\ComfyUI\input'); ap.add_argument('--comfy-output', default=r'C:\ComfyUI\output')
    ap.add_argument('--timeout', type=int, default=4000)
    a = ap.parse_args()
    W, H = (int(x) for x in a.size.split('x'))
    shutil.copy(a.pattern, os.path.join(a.comfy_input, os.path.basename(a.pattern)))
    half = a.steps // 2
    g = {
        '1': {'class_type': 'UnetLoaderGGUF', 'inputs': {'unet_name': 'Wan2.2-VACE-Fun-A14B-high-noise-Q4_K_M.gguf'}},
        '2': {'class_type': 'UnetLoaderGGUF', 'inputs': {'unet_name': 'Wan2.2-VACE-Fun-A14B-low-noise-Q4_K_M.gguf'}},
        '3': {'class_type': 'ModelSamplingSD3', 'inputs': {'model': ['1', 0], 'shift': 8.0}},
        '4': {'class_type': 'ModelSamplingSD3', 'inputs': {'model': ['2', 0], 'shift': 8.0}},
        '5': {'class_type': 'CLIPLoader', 'inputs': {'clip_name': 'umt5_xxl_fp8_e4m3fn_scaled.safetensors', 'type': 'wan'}},
        '6': {'class_type': 'CLIPTextEncode', 'inputs': {'clip': ['5', 0], 'text': a.prompt}},
        '7': {'class_type': 'CLIPTextEncode', 'inputs': {'clip': ['5', 0], 'text': NEG}},
        '8': {'class_type': 'VAELoader', 'inputs': {'vae_name': 'wan_2.1_vae.safetensors'}},
        '9': {'class_type': 'LoadImage', 'inputs': {'image': os.path.basename(a.pattern)}},
        '10': {'class_type': 'ImageScale', 'inputs': {'image': ['9', 0], 'upscale_method': 'nearest-exact', 'width': W, 'height': H, 'crop': 'center'}},
        '11': {'class_type': 'RepeatImageBatch', 'inputs': {'image': ['10', 0], 'amount': a.length}},
        # with the pattern: for the high-noise half (and both with --all-steps)
        '12': {'class_type': 'WanVaceToVideo', 'inputs': {'positive': ['6', 0], 'negative': ['7', 0], 'vae': ['8', 0], 'width': W,
                                                          'height': H, 'length': a.length, 'batch_size': 1, 'strength': a.strength,
                                                          'control_video': ['11', 0]}},
        # without: the low-noise half
        '13': {'class_type': 'WanVaceToVideo', 'inputs': {'positive': ['6', 0], 'negative': ['7', 0], 'vae': ['8', 0], 'width': W,
                                                          'height': H, 'length': a.length, 'batch_size': 1, 'strength': 1.0}},
        '14': {'class_type': 'KSamplerAdvanced', 'inputs': {
            'model': ['3', 0], 'add_noise': 'enable', 'noise_seed': a.seed, 'steps': a.steps, 'cfg': 3.5,
            'sampler_name': 'euler', 'scheduler': 'simple', 'positive': ['12', 0], 'negative': ['12', 1],
            'latent_image': ['19', 0] if a.init_step else ['12', 2], 'start_at_step': a.init_step, 'end_at_step': max(half, a.init_step + 1),
            'return_with_leftover_noise': 'enable'}},
        '15': {'class_type': 'KSamplerAdvanced', 'inputs': {
            'model': ['4', 0], 'add_noise': 'disable', 'noise_seed': a.seed, 'steps': a.steps, 'cfg': 3.5,
            'sampler_name': 'euler', 'scheduler': 'simple',
            'positive': ['12' if a.all_steps else '13', 0], 'negative': ['12' if a.all_steps else '13', 1],
            'latent_image': ['14', 0], 'start_at_step': max(half, a.init_step + 1), 'end_at_step': 10000, 'return_with_leftover_noise': 'disable'}},
        '16': {'class_type': 'VAEDecode', 'inputs': {'samples': ['15', 0], 'vae': ['8', 0]}},
        '19': {'class_type': 'VAEEncode', 'inputs': {'pixels': ['11', 0], 'vae': ['8', 0]}},
        '17': {'class_type': 'CreateVideo', 'inputs': {'images': ['16', 0], 'fps': 16.0}},
        '18': {'class_type': 'SaveVideo', 'inputs': {'video': ['17', 0], 'filename_prefix': 'video/vace_qr', 'format': 'auto', 'codec': 'auto'}},
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
        time.sleep(5)
    os.makedirs(a.out, exist_ok=True)
    for key, items in h[pid]['outputs'].get('18', {}).items():
        for it in items if isinstance(items, list) else []:
            if isinstance(it, dict) and 'filename' in it:
                shutil.copy(os.path.join(a.comfy_output, it.get('subfolder', ''), it['filename']), os.path.join(a.out, 'qr.mp4'))
    print(f'{a.out}: strength {a.strength}{" all steps" if a.all_steps else ""}'
          f'{f", from the pattern at step {a.init_step}" if a.init_step else ""}, done in {time.time() - t0:.0f} s', flush=True)


if __name__ == '__main__':
    main()
