#!/usr/bin/env python3
r"""
A walk between two pictures made by MiniMax H3 (first and last frame to video
with audio) through a running ComfyUI.

    python h3_flf.py FIRST.png LAST.png OUT_DIR [--size 1280x768] [--frames 124] [--steps 8]
        [--turbo h3\minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors] [--turbo-strength 1]
        [--seed 1 | --seeds 1 2 3 4] [--prompt ...] [--server $COMFY_SERVER] [--comfy-output C:\ComfyUI\output]

As ComfyUI's MiniMax H3 image-to-video template: the pruned int8 fl2va model,
the Qwen3-VL text encoder (type minimax), MiniMaxH3ImageToVideo with both
frames, BasicGuider, res_multistep on the simple schedule, the 8-step turbo
LoRA at 8 steps (--turbo-strength 0 and --steps 20 for the model alone).
Width and height are multiples of 32; frames are 17k+5 (124 is 5.2 s at 24
fps). Writes OUT_DIR/walk.mp4 (24 fps, with H3's sound); with --seeds, one
walk_s<seed>.mp4 for each, all queued at once on the one server, so the models
load once. Standard library only.
"""
import argparse
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
    ap.add_argument('first'); ap.add_argument('last'); ap.add_argument('out')
    ap.add_argument('--size', default='1280x768'); ap.add_argument('--frames', type=int, default=124)
    ap.add_argument('--steps', type=int, default=8); ap.add_argument('--seed', type=int, default=1)
    ap.add_argument('--seeds', type=int, nargs='+', help='several walks, one for each seed, queued together')
    ap.add_argument('--turbo', default='h3\\minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors')
    ap.add_argument('--turbo-strength', type=float, default=1.0)
    ap.add_argument('--prompt', default='A smooth, steady first-person camera walking slowly forward along the pier, the same place '
                    'throughout, the scene getting nearer, no cuts, static lighting. Audio: soft footsteps on wood, gentle waves.')
    ap.add_argument('--server', default=os.environ.get('COMFY_SERVER', 'http://127.0.0.1:8189'))
    ap.add_argument('--comfy-input', default=r'C:\ComfyUI\input'); ap.add_argument('--comfy-output', default=r'C:\ComfyUI\output')
    ap.add_argument('--timeout', type=int, default=5400)
    a = ap.parse_args()
    W, H = (int(x) for x in a.size.split('x'))
    names = []
    for f, n in ((a.first, 'h3_first.png'), (a.last, 'h3_last.png')):
        shutil.copy(f, os.path.join(a.comfy_input, n)); names.append(n)
    seeds = a.seeds or [a.seed]
    queued = []
    for seed in seeds:
      g = {
          '1': {'class_type': 'UNETLoader', 'inputs': {'unet_name': 'minimax_h3_fl2va_pruned_int8_convrot.safetensors', 'weight_dtype': 'default'}},
          '2': {'class_type': 'LoraLoaderModelOnly', 'inputs': {'model': ['1', 0], 'lora_name': a.turbo, 'strength_model': a.turbo_strength}},
          '3': {'class_type': 'CLIPLoader', 'inputs': {'clip_name': 'qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors', 'type': 'minimax'}},
          '4': {'class_type': 'VAELoader', 'inputs': {'vae_name': 'minimax_h3_video_vae_fp16.safetensors'}},
          '5': {'class_type': 'VAELoader', 'inputs': {'vae_name': 'minimax_h3_audio_vae_fp32.safetensors'}},
          '6': {'class_type': 'LoadImage', 'inputs': {'image': names[0]}},
          '7': {'class_type': 'LoadImage', 'inputs': {'image': names[1]}},
          '8': {'class_type': 'MiniMaxH3ImageToVideo', 'inputs': {'clip': ['3', 0], 'vae': ['4', 0], 'prompt': a.prompt, 'width': W, 'height': H,
                                                                  'length': a.frames, 'first_frame': ['6', 0], 'last_frame': ['7', 0]}},
          '9': {'class_type': 'BasicGuider', 'inputs': {'model': ['2', 0], 'conditioning': ['8', 0]}},
          '10': {'class_type': 'RandomNoise', 'inputs': {'noise_seed': seed}},
          '11': {'class_type': 'KSamplerSelect', 'inputs': {'sampler_name': 'res_multistep'}},
          '12': {'class_type': 'BasicScheduler', 'inputs': {'model': ['2', 0], 'scheduler': 'simple', 'steps': a.steps, 'denoise': 1.0}},
          '13': {'class_type': 'SamplerCustomAdvanced', 'inputs': {'noise': ['10', 0], 'guider': ['9', 0], 'sampler': ['11', 0],
                                                                   'sigmas': ['12', 0], 'latent_image': ['8', 1]}},
          '14': {'class_type': 'VAEDecode', 'inputs': {'samples': ['13', 0], 'vae': ['4', 0]}},
          '15': {'class_type': 'VAEDecodeAudio', 'inputs': {'samples': ['13', 0], 'vae': ['5', 0]}},
          '16': {'class_type': 'CreateVideo', 'inputs': {'images': ['14', 0], 'audio': ['15', 0], 'fps': 24.0}},
          '17': {'class_type': 'SaveVideo', 'inputs': {'video': ['16', 0], 'filename_prefix': 'video/h3_flf', 'format': 'auto', 'codec': 'auto'}},
      }
      r = api(a.server, '/prompt', {'prompt': g, 'client_id': uuid.uuid4().hex})
      if r.get('node_errors'):
          raise SystemExit('node errors: ' + json.dumps(r['node_errors'])[:3000])
      queued.append((seed, r['prompt_id']))
    os.makedirs(a.out, exist_ok=True)
    t0 = time.time()
    for seed, pid in queued:
      while True:
        if time.time() - t0 > a.timeout * len(queued):
            api(a.server, '/interrupt', {})
            raise SystemExit(f'timed out after {time.time() - t0:.0f} s')
        h = api(a.server, f'/history/{pid}')
        if pid in h:
          st = h[pid].get('status', {})
          if st.get('status_str') == 'error':
              raise SystemExit('ComfyUI error: ' + json.dumps(st.get('messages', []))[-3000:])
          if st.get('completed'):
              break
        time.sleep(10)
      name = 'walk.mp4' if not a.seeds else f'walk_s{seed}.mp4'
      for key, items in h[pid]['outputs'].get('17', {}).items():
          for it in items if isinstance(items, list) else []:
              if isinstance(it, dict) and 'filename' in it:
                  shutil.copy(os.path.join(a.comfy_output, it.get('subfolder', ''), it['filename']), os.path.join(a.out, name))
      print(f'{a.out}\\{name}: {W}x{H}, {a.frames} frames, {a.steps} steps, seed {seed}, {time.time() - t0:.0f} s since queued', flush=True)


if __name__ == '__main__':
    main()
