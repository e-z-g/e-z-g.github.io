#!/usr/bin/env python3
r"""
A video upscaled by SeedVR2 (the ComfyUI-SeedVR2_VideoUpscaler add-on)
through a running ComfyUI.

    python seedvr2_run.py IN.mp4 OUT.mp4 [--resolution 1280] [--batch 21] [--overlap 4]
        [--model seedvr2_ema_7b_sharp_fp8_e4m3fn.safetensors] [--swap 36] [--color lab] [--every 1]
        [--server http://127.0.0.1:8188] [--comfy-input C:\ComfyUI\input] [--comfy-output C:\ComfyUI\output]

--resolution is the short edge of the result (1280 makes a 1280x640
panorama 2560x1280). --every N takes every Nth frame first (walk_finish.py's
64 fps clip with --every 4 is the tone-matched 16 fps clip, before FILM).
The add-on's four nodes are found by name in the server's /object_info and
each input set by name: the settings here where given, the node's default
otherwise. For a 16 GB card: the DiT kept in system memory and swapped in
block by block (--swap), the VAE tiled. Writes OUT.mp4 at the input's frame
rate divided by --every. Standard library only.
"""
import argparse
import json
import os
import shutil
import subprocess
import time
import urllib.request
import uuid


def api(server, path, data=None):
    req = urllib.request.Request(server + path, data=json.dumps(data).encode() if data is not None else None,
                                 headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read())


def fill(spec, given, name):
    out = {}
    req, opt = spec['input'].get('required', {}), spec['input'].get('optional', {})
    for k, s in list(req.items()) + list(opt.items()):
        if k in given:
            out[k] = given[k]
        elif k in req:
            if isinstance(s, (list, tuple)) and isinstance(s[0], list):      # a choice: its first entry
                out[k] = s[0][0]
            elif isinstance(s, (list, tuple)) and len(s) > 1 and isinstance(s[1], dict) and 'default' in s[1]:
                out[k] = s[1]['default']
            elif isinstance(s, (list, tuple)) and s[0] == 'COMBO' and len(s) > 1 and s[1].get('options'):
                out[k] = s[1].get('default', s[1]['options'][0])
            else:
                raise SystemExit(f'{name} needs {k} ({s}) and this script does not set it')
    unknown = set(given) - set(out)
    if unknown:
        print(f'{name}: no inputs called {sorted(unknown)}; it has {list(req) + list(opt)}', flush=True)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('video'); ap.add_argument('out')
    ap.add_argument('--resolution', type=int, default=1280); ap.add_argument('--batch', type=int, default=21)
    ap.add_argument('--overlap', type=int, default=4); ap.add_argument('--every', type=int, default=1)
    ap.add_argument('--model', default='seedvr2_ema_7b_sharp_fp8_e4m3fn.safetensors')
    ap.add_argument('--swap', type=int, default=36); ap.add_argument('--color', default='lab')
    ap.add_argument('--seed', type=int, default=42)
    ap.add_argument('--server', default='http://127.0.0.1:8188')
    ap.add_argument('--comfy-input', default=r'C:\ComfyUI\input'); ap.add_argument('--comfy-output', default=r'C:\ComfyUI\output')
    ap.add_argument('--ffmpeg', default='ffmpeg'); ap.add_argument('--timeout', type=int, default=7200)
    a = ap.parse_args()
    name = 'seedvr2_in.mp4'
    src = os.path.join(a.comfy_input, name)
    if a.every > 1:
        subprocess.run([a.ffmpeg, '-v', 'error', '-y', '-i', a.video, '-vf', f"select='not(mod(n\\,{a.every}))',setpts=N/FRAME_RATE/TB",
                        '-fps_mode', 'passthrough', '-c:v', 'libx264', '-crf', '10', '-pix_fmt', 'yuv420p', src], check=True)
    else:
        shutil.copy(a.video, src)
    info = api(a.server, '/object_info')
    nodes = {k: v for k, v in info.items() if 'seedvr2' in k.lower()}
    print('SeedVR2 nodes:', {k: v.get('display_name') for k, v in nodes.items()}, flush=True)
    pick = lambda *words: next(k for k, v in nodes.items() if all(w in (k + ' ' + str(v.get('display_name'))).lower() for w in words))
    # (ComfyUI has SeedVR2 nodes of its own, SeedVR2Conditioning and others, which are not the add-on's)
    n_dit, n_vae, n_up = pick('load', 'dit'), pick('load', 'vae'), pick('video', 'upscaler')
    dit = fill(nodes[n_dit], {'model': a.model, 'device': 'cuda:0', 'offload_device': 'cpu', 'blocks_to_swap': a.swap,
                              'swap_io_components': True, 'attention_mode': 'sdpa', 'cache_model': False}, n_dit)
    vae = fill(nodes[n_vae], {'model': 'ema_vae_fp16.safetensors', 'device': 'cuda:0', 'offload_device': 'cpu',
                              'encode_tiled': True, 'encode_tile_size': 1024, 'encode_tile_overlap': 128,
                              'decode_tiled': True, 'decode_tile_size': 1024, 'decode_tile_overlap': 128, 'cache_model': False}, n_vae)
    up = fill(nodes[n_up], {'image': ['11', 0], 'dit': ['1', 0], 'vae': ['2', 0], 'seed': a.seed, 'resolution': a.resolution,
                            'max_resolution': 0, 'batch_size': a.batch, 'uniform_batch_size': True,
                            'temporal_overlap': a.overlap, 'prepend_frames': 0, 'color_correction': a.color,
                            'input_noise_scale': 0.0, 'latent_noise_scale': 0.0, 'offload_device': 'cpu',
                            'enable_debug': False}, n_up)
    out_idx = 0
    g = {
        '1': {'class_type': n_dit, 'inputs': dit},
        '2': {'class_type': n_vae, 'inputs': vae},
        '10': {'class_type': 'LoadVideo', 'inputs': {'file': name}},
        '11': {'class_type': 'GetVideoComponents', 'inputs': {'video': ['10', 0]}},
        '3': {'class_type': n_up, 'inputs': up},
        '4': {'class_type': 'CreateVideo', 'inputs': {'images': ['3', out_idx], 'fps': ['11', 2]}},
        '5': {'class_type': 'SaveVideo', 'inputs': {'video': ['4', 0], 'filename_prefix': 'video/seedvr2', 'format': 'auto', 'codec': 'auto'}},
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
                raise SystemExit('ComfyUI error: ' + json.dumps(st.get('messages', []))[-3000:])
            if st.get('completed'):
                break
        time.sleep(10)
    for key, items in h[pid]['outputs'].get('5', {}).items():
        for it in items if isinstance(items, list) else []:
            if isinstance(it, dict) and 'filename' in it:
                shutil.copy(os.path.join(a.comfy_output, it.get('subfolder', ''), it['filename']), a.out)
    print(f'{a.out}: done in {time.time() - t0:.0f} s', flush=True)


if __name__ == '__main__':
    main()
