#!/usr/bin/env python3
r"""
Wan Animate 2 (distilled) through a running ComfyUI: the person in a reference
picture performs the motion of a driving video, in a setting described by the
prompt (the background comes from the text, not from either input).

    python animate2_run.py REFERENCE.png DRIVING.mp4 OUT_DIR --prompt "Character Description: ... Background description: ..."
        [--pose-prompt "..."] [--size 512x896] [--length 81] [--offset 0] [--steps 10] [--seed 2]
        [--server http://127.0.0.1:8189] [--comfy-input C:\ComfyUI\input] [--comfy-output C:\ComfyUI\output]

As ComfyUI's video_wan_animate2_distilled template, one window long (no
context windows, no continuation): wan_animate_2_distill_int8_convrot with
WanAnimate2Cache (int8, in system memory unless --cache-device gpu), ModelSamplingSD3 shift 5, LCM with the simple
schedule, cfg 1; the reference and the driving frames scaled (ImageScale,
centre crop) to --size; clip_vision_h read from the reference and the
driving video's first frame; WanAnimate2ToVideo's settings by name from the
server's /object_info. Writes OUT_DIR/animate.mp4 (the video's own frame
rate). Standard library only.
"""
import argparse
import json
import os
import shutil
import time
import urllib.request
import uuid

NEG = ('色调艳丽，过曝，静态，细节模糊不清，字幕，风格，作品，画作，画面，静止，整体发灰，最差质量，低质量，JPEG压缩残留，'
       '丑陋的，残缺的，多余的手指，画得不好的手部，画得不好的脸部，畸形的，毁容的，形态畸形的肢体，手指融合')


def api(server, path, data=None):
    req = urllib.request.Request(server + path, data=json.dumps(data).encode() if data is not None else None,
                                 headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read())


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('reference'); ap.add_argument('driving'); ap.add_argument('out')
    ap.add_argument('--prompt', required=True)
    ap.add_argument('--pose-prompt', default='A reference video of a person dancing in front of a plain blue background')
    ap.add_argument('--size', default='512x896'); ap.add_argument('--length', type=int, default=81)
    ap.add_argument('--offset', type=int, default=0); ap.add_argument('--steps', type=int, default=10)
    ap.add_argument('--seed', type=int, default=2)
    ap.add_argument('--cache-device', default='cpu', choices=('cpu', 'gpu'), help="where WanAnimate2Cache keeps the pose branch's activations")
    ap.add_argument('--server', default=os.environ.get('COMFY_SERVER', 'http://127.0.0.1:8189'))
    ap.add_argument('--comfy-input', default=r'C:\ComfyUI\input'); ap.add_argument('--comfy-output', default=r'C:\ComfyUI\output')
    ap.add_argument('--timeout', type=int, default=5000)
    a = ap.parse_args()
    W, H = (int(x) for x in a.size.split('x'))
    info = api(a.server, '/object_info')
    spec = info['WanAnimate2ToVideo']
    req, opt = spec['input'].get('required', {}), spec['input'].get('optional', {})
    print('WanAnimate2ToVideo required:', list(req), 'optional:', list(opt), 'outputs:', spec.get('output_name') or spec.get('output'), flush=True)
    for f in (a.reference, a.driving):
        shutil.copy(f, os.path.join(a.comfy_input, os.path.basename(f)))
    links = {'positive': ['6', 0], 'negative': ['7', 0], 'vae': ['9', 0], 'reference_image': ['12', 0],
             'pose_video': ['15', 0], 'clip_vision_output': ['16', 0], 'positive_pose': ['8', 0],
             'clip_vision_output_pose': ['18', 0]}
    values = {'width': W, 'height': H, 'length': a.length, 'batch_size': 1, 'video_frame_offset': a.offset,
              'pose_strength': 1.0, 'pose_start_percent': 0.0, 'pose_end_percent': 1.0, 'reference_image_strength': 1.0}
    anim = {}
    for name, s in list(req.items()) + list(opt.items()):
        if name in links:
            anim[name] = links[name]
        elif name in values:
            anim[name] = values[name]
        elif name in req:
            kind = s[0] if isinstance(s, (list, tuple)) else None
            default = s[1].get('default') if isinstance(s, (list, tuple)) and len(s) > 1 and isinstance(s[1], dict) else None
            if default is None:
                raise SystemExit(f'WanAnimate2ToVideo needs {name} ({kind}) and this script does not set it')
            anim[name] = default
    outs = list(spec.get('output_name') or spec.get('output'))
    i_pos, i_neg, i_lat = 0, 1, 2
    i_trim = next((i for i, n in enumerate(outs) if 'trim' in str(n).lower()), 3)
    g = {
        '1': {'class_type': 'UNETLoader', 'inputs': {'unet_name': 'wan_animate_2_distill_int8_convrot.safetensors', 'weight_dtype': 'default'}},
        # the pose cache in system memory: on the graphics card (the template's choice, for 24 GB cards) it ran a 16 GB card out of memory
        '2': {'class_type': 'WanAnimate2Cache', 'inputs': {'model': ['1', 0], 'device': a.cache_device, 'dtype': 'int8'}},
        '3': {'class_type': 'ModelSamplingSD3', 'inputs': {'model': ['2', 0], 'shift': 5.0}},
        '4': {'class_type': 'BasicScheduler', 'inputs': {'model': ['2', 0], 'scheduler': 'simple', 'steps': a.steps, 'denoise': 1.0}},
        '5': {'class_type': 'CLIPLoader', 'inputs': {'clip_name': 'umt5_xxl_fp8_e4m3fn_scaled.safetensors', 'type': 'wan'}},
        '6': {'class_type': 'CLIPTextEncode', 'inputs': {'clip': ['5', 0], 'text': a.prompt}},
        '7': {'class_type': 'CLIPTextEncode', 'inputs': {'clip': ['5', 0], 'text': NEG}},
        '8': {'class_type': 'CLIPTextEncode', 'inputs': {'clip': ['5', 0], 'text': a.pose_prompt}},
        '9': {'class_type': 'VAELoader', 'inputs': {'vae_name': 'Wan2_1_VAE_bf16.safetensors'}},
        '10': {'class_type': 'CLIPVisionLoader', 'inputs': {'clip_name': 'clip_vision_h.safetensors'}},
        '11': {'class_type': 'LoadImage', 'inputs': {'image': os.path.basename(a.reference)}},
        '12': {'class_type': 'ImageScale', 'inputs': {'image': ['11', 0], 'upscale_method': 'area', 'width': W, 'height': H, 'crop': 'center'}},
        '13': {'class_type': 'LoadVideo', 'inputs': {'file': os.path.basename(a.driving)}},
        '14': {'class_type': 'GetVideoComponents', 'inputs': {'video': ['13', 0]}},
        '15': {'class_type': 'ImageScale', 'inputs': {'image': ['14', 0], 'upscale_method': 'area', 'width': W, 'height': H, 'crop': 'center'}},
        '16': {'class_type': 'CLIPVisionEncode', 'inputs': {'clip_vision': ['10', 0], 'image': ['12', 0], 'crop': 'none'}},
        '17': {'class_type': 'ImageFromBatch', 'inputs': {'image': ['15', 0], 'batch_index': a.offset, 'length': 1}},
        '18': {'class_type': 'CLIPVisionEncode', 'inputs': {'clip_vision': ['10', 0], 'image': ['17', 0], 'crop': 'none'}},
        '19': {'class_type': 'WanAnimate2ToVideo', 'inputs': anim},
        '20': {'class_type': 'KSamplerSelect', 'inputs': {'sampler_name': 'lcm'}},
        '21': {'class_type': 'SamplerCustom', 'inputs': {'model': ['3', 0], 'add_noise': True, 'noise_seed': a.seed, 'cfg': 1.0,
                                                         'positive': ['19', i_pos], 'negative': ['19', i_neg], 'sampler': ['20', 0],
                                                         'sigmas': ['4', 0], 'latent_image': ['19', i_lat]}},
        '22': {'class_type': 'TrimVideoLatent', 'inputs': {'samples': ['21', 0], 'trim_amount': ['19', i_trim]}},
        '23': {'class_type': 'VAEDecode', 'inputs': {'samples': ['22', 0], 'vae': ['9', 0]}},
        '24': {'class_type': 'CreateVideo', 'inputs': {'images': ['23', 0], 'fps': ['14', 2]}},
        '25': {'class_type': 'SaveVideo', 'inputs': {'video': ['24', 0], 'filename_prefix': 'video/animate2', 'format': 'auto', 'codec': 'auto'}},
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
    for key, items in h[pid]['outputs'].get('25', {}).items():
        for it in items if isinstance(items, list) else []:
            if isinstance(it, dict) and 'filename' in it:
                shutil.copy(os.path.join(a.comfy_output, it.get('subfolder', ''), it['filename']), os.path.join(a.out, 'animate.mp4'))
    print(f'done in {time.time() - t0:.0f} s')


if __name__ == '__main__':
    main()
