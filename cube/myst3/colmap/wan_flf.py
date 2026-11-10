#!/usr/bin/env python3
r"""
A walk between two nodes made by Wan 2.2's first-last-frame video model,
through a running ComfyUI (its HTTP API, default 127.0.0.1:8189).

    python wan_flf.py FIRST.png LAST.png OUT_DIR [--frames 81] [--steps 20]
        [--size 832x480] [--high HIGH.gguf] [--low LOW.gguf] [--prompt ...]
        [--seed 1] [--server http://127.0.0.1:8189] [--timeout 3600] [--comfy-output C:\ComfyUI\output]

FIRST and LAST (walk_ends.py's: each node's panorama drawn looking along the
walk) are the clip's first and last frames; Wan 2.2 I2V A14B (two experts as
GGUF, ComfyUI-GGUF's UnetLoaderGGUF: the high-noise one for the first half of
the steps, the low-noise one for the rest, both with ModelSamplingSD3 shift
8), its umt5 text encoder and the 2.1 VAE make --frames frames between them
(81 at 16 a second is about 5 s; Wan wants 4n+1). Node inputs are checked
against the server's /object_info before the job is sent. Writes the frames
as OUT_DIR/frame_NNNNN.png and walk.mp4 (ffmpeg, 16 fps). Needs requests
(or urllib), Pillow; ffmpeg on the path for the video.
"""
import argparse
import json
import os
import shutil
import subprocess
import time
import urllib.request
import uuid

NEG = ('cut, scene change, jump, blurry, distorted, warped, melting, flicker, ghosting, double image, '
       'text, watermark, people, camera shake, fast motion')


def api(server, path, data=None):
    req = urllib.request.Request(server + path, data=json.dumps(data).encode() if data is not None else None,
                                 headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


def upload(server, path):
    boundary = uuid.uuid4().hex
    name = os.path.basename(path)
    body = (f'--{boundary}\r\nContent-Disposition: form-data; name="image"; filename="{name}"\r\n'
            f'Content-Type: image/png\r\n\r\n').encode() + open(path, 'rb').read() + \
           f'\r\n--{boundary}\r\nContent-Disposition: form-data; name="overwrite"\r\n\r\ntrue\r\n--{boundary}--\r\n'.encode()
    req = urllib.request.Request(server + '/upload/image', data=body,
                                 headers={'Content-Type': f'multipart/form-data; boundary={boundary}'})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())['name']


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('first'); ap.add_argument('last'); ap.add_argument('out')
    ap.add_argument('--frames', type=int, default=81); ap.add_argument('--steps', type=int, default=20)
    ap.add_argument('--size', default='832x480'); ap.add_argument('--seed', type=int, default=1)
    ap.add_argument('--cfg', type=float, default=3.5); ap.add_argument('--shift', type=float, default=8.0)
    ap.add_argument('--lora-high', help='a LoRA on the high-noise expert (models/loras), e.g. the 4-step Lightning one')
    ap.add_argument('--lora-low', help='a LoRA on the low-noise expert')
    ap.add_argument('--lightning', action='store_true',
                    help="Wan 2.2's I2V Lightning (lightx2v) 4-step LoRAs on both experts, 4 steps, cfg 1, shift 5 (ComfyUI's template)")
    ap.add_argument('--high', default='Wan2.2-I2V-A14B-HighNoise-Q4_K_M.gguf')
    ap.add_argument('--low', default='Wan2.2-I2V-A14B-LowNoise-Q4_K_M.gguf')
    ap.add_argument('--clip', default='umt5_xxl_fp8_e4m3fn_scaled.safetensors')
    ap.add_argument('--vae', default='wan_2.1_vae.safetensors')
    ap.add_argument('--prompt', default='A smooth, steady first-person camera walking slowly forward along a wooden pier, '
                    'the same place throughout, the scene getting nearer, no cuts, static lighting, fantasy architecture at dusk')
    ap.add_argument('--server', default=os.environ.get('COMFY_SERVER', 'http://127.0.0.1:8189')); ap.add_argument('--timeout', type=int, default=3600)
    ap.add_argument('--comfy-output', default=r'C:\ComfyUI\output', help="ComfyUI's output folder")
    a = ap.parse_args()
    W, H = (int(x) for x in a.size.split('x'))
    if a.lightning:
        a.lora_high = a.lora_high or 'wan2.2_i2v_lightx2v_4steps_lora_v1_high_noise.safetensors'
        a.lora_low = a.lora_low or 'wan2.2_i2v_lightx2v_4steps_lora_v1_low_noise.safetensors'
        a.steps, a.cfg, a.shift = 4, 1.0, 5.0
    info = api(a.server, '/object_info')
    for node in ('UnetLoaderGGUF', 'WanFirstLastFrameToVideo', 'KSamplerAdvanced', 'ModelSamplingSD3', 'CLIPLoader'):
        if node not in info:
            raise SystemExit(f'ComfyUI has no {node} node')
    flf_in = info['WanFirstLastFrameToVideo']['input']
    print('WanFirstLastFrameToVideo inputs:', {k: list(v) for k, v in flf_in.items()})
    first = upload(a.server, a.first); last = upload(a.server, a.last)
    half = a.steps // 2
    g = {
        '1': {'class_type': 'UnetLoaderGGUF', 'inputs': {'unet_name': a.high}},
        '2': {'class_type': 'UnetLoaderGGUF', 'inputs': {'unet_name': a.low}},
        '3': {'class_type': 'ModelSamplingSD3', 'inputs': {'model': ['21' if a.lora_high else '1', 0], 'shift': a.shift}},
        '4': {'class_type': 'ModelSamplingSD3', 'inputs': {'model': ['22' if a.lora_low else '2', 0], 'shift': a.shift}},
        '5': {'class_type': 'CLIPLoader', 'inputs': {'clip_name': a.clip, 'type': 'wan'}},
        '6': {'class_type': 'CLIPTextEncode', 'inputs': {'clip': ['5', 0], 'text': a.prompt}},
        '7': {'class_type': 'CLIPTextEncode', 'inputs': {'clip': ['5', 0], 'text': NEG}},
        '8': {'class_type': 'VAELoader', 'inputs': {'vae_name': a.vae}},
        '9': {'class_type': 'LoadImage', 'inputs': {'image': first}},
        '10': {'class_type': 'LoadImage', 'inputs': {'image': last}},
        '11': {'class_type': 'WanFirstLastFrameToVideo', 'inputs': {
            'positive': ['6', 0], 'negative': ['7', 0], 'vae': ['8', 0], 'width': W, 'height': H,
            'length': a.frames, 'batch_size': 1, 'start_image': ['9', 0], 'end_image': ['10', 0]}},
        '12': {'class_type': 'KSamplerAdvanced', 'inputs': {
            'model': ['3', 0], 'add_noise': 'enable', 'noise_seed': a.seed, 'steps': a.steps, 'cfg': a.cfg,
            'sampler_name': 'euler', 'scheduler': 'simple', 'positive': ['11', 0], 'negative': ['11', 1],
            'latent_image': ['11', 2], 'start_at_step': 0, 'end_at_step': half, 'return_with_leftover_noise': 'enable'}},
        '13': {'class_type': 'KSamplerAdvanced', 'inputs': {
            'model': ['4', 0], 'add_noise': 'disable', 'noise_seed': a.seed, 'steps': a.steps, 'cfg': a.cfg,
            'sampler_name': 'euler', 'scheduler': 'simple', 'positive': ['11', 0], 'negative': ['11', 1],
            'latent_image': ['12', 0], 'start_at_step': half, 'end_at_step': 10000, 'return_with_leftover_noise': 'disable'}},
        '14': {'class_type': 'VAEDecode', 'inputs': {'samples': ['13', 0], 'vae': ['8', 0]}},
        '15': {'class_type': 'SaveImage', 'inputs': {'images': ['14', 0], 'filename_prefix': 'walk_flf'}},
    }
    if a.lora_high:
        g['21'] = {'class_type': 'LoraLoaderModelOnly', 'inputs': {'model': ['1', 0], 'lora_name': a.lora_high, 'strength_model': 1.0}}
    if a.lora_low:
        g['22'] = {'class_type': 'LoraLoaderModelOnly', 'inputs': {'model': ['2', 0], 'lora_name': a.lora_low, 'strength_model': 1.0}}
    for k in [k for k in g['11']['inputs'] if k not in {**flf_in.get('required', {}), **flf_in.get('optional', {})}]:
        raise SystemExit(f'WanFirstLastFrameToVideo has no input {k}')
    pid = api(a.server, '/prompt', {'prompt': g, 'client_id': uuid.uuid4().hex})['prompt_id']
    t0 = time.time()
    print('queued', pid, flush=True)
    while True:
        if time.time() - t0 > a.timeout:
            api(a.server, '/interrupt', {})
            raise SystemExit(f'timed out after {a.timeout} s')
        h = api(a.server, f'/history/{pid}')
        if pid in h:
            st = h[pid].get('status', {})
            if st.get('status_str') == 'error':
                raise SystemExit('ComfyUI error: ' + json.dumps(st.get('messages', []))[:2000])
            if st.get('completed'):
                break
        time.sleep(5)
    imgs = h[pid]['outputs']['15']['images']
    os.makedirs(a.out, exist_ok=True)
    outdir = a.comfy_output
    for i, im in enumerate(imgs):
        shutil.copy(os.path.join(outdir, im.get('subfolder', ''), im['filename']), os.path.join(a.out, f'frame_{i:05d}.png'))
    print(f'{len(imgs)} frames in {time.time() - t0:.0f} s', flush=True)
    try:
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-framerate', '16', '-i', os.path.join(a.out, 'frame_%05d.png'),
                        '-c:v', 'libx264', '-crf', '16', '-pix_fmt', 'yuv420p', os.path.join(a.out, 'walk.mp4')], check=True)
        print('walk.mp4 written')
    except (OSError, subprocess.CalledProcessError) as e:
        print('no video:', e)


if __name__ == '__main__':
    main()
