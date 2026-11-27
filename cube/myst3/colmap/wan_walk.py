#!/usr/bin/env python3
r"""
A walk between two pictures made by Wan 2.2 I2V A14B (first and last frame to video), through a running ComfyUI, with
h3_flf.py's interface so walk_wan.ps1 can run walk_polar3.ps1's recipe on it (the maintainer, 26 November 2026: try
Wan with this exact workflow, adapted to its strengths).

    python wan_walk.py FIRST.png LAST.png OUT_DIR [--size 1280x640] [--frames 81] [--seed 4] [--lightning]
        [--steps 20] [--cfg 3.5] [--shift 8] [--init VIDEO.mp4 --denoise 0.3] [--prompt ...] [--neg ...]

The two experts as GGUF (ComfyUI-GGUF's UnetLoaderGGUF), each through ModelSamplingSD3 (--shift), umt5 (type wan),
the 2.1 VAE, WanFirstLastFrameToVideo with both frames. From noise: the high-noise expert for the first half of the
steps and the low-noise expert for the rest (KSamplerAdvanced, ComfyUI's Wan 2.2 template). With --lightning: the
lightx2v 4-step LoRAs on both experts, 4 steps, cfg 1, shift 5 (the template's; cfg 1 leaves the negative unused).
With --init: the video's frames VAE-encoded as the starting latent, sampled at --denoise by the low-noise expert
alone (KSampler with denoise: at shift 5 and denoise 0.3 the first sigma is about 0.68, under Wan 2.2 I2V's 0.9
boundary between the experts, so the high-noise expert has no part in it); WanFirstLastFrameToVideo still gives the
two end frames as conditioning. Frames are 4n+1 (Wan's VAE: 4 frames a latent), sizes multiples of 16.
Writes every frame losslessly as OUT_DIR/frames_s<seed>/0000.png ... . Standard library only.
"""
import argparse, json, os, shutil, time, urllib.request, uuid

NEG = ('cut, scene change, jump, blurry, soft focus, smeared, distorted, warped, melting, morphing, flicker, '
       'shimmering textures, ghosting, double image, text, watermark, people, camera shake, turning, fast motion')


def api(server, path, data=None):
    req = urllib.request.Request(server + path, data=json.dumps(data).encode() if data is not None else None,
                                 headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read())


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('first'); ap.add_argument('last'); ap.add_argument('out')
    ap.add_argument('--size', default='1280x640'); ap.add_argument('--frames', type=int, default=81)
    ap.add_argument('--steps', type=int, default=20); ap.add_argument('--seed', type=int, default=4)
    ap.add_argument('--cfg', type=float, default=3.5); ap.add_argument('--shift', type=float, default=8.0)
    ap.add_argument('--lightning', action='store_true')
    ap.add_argument('--high', default='Wan2.2-I2V-A14B-HighNoise-Q4_K_M.gguf')
    ap.add_argument('--low', default='Wan2.2-I2V-A14B-LowNoise-Q4_K_M.gguf')
    ap.add_argument('--lora-high', default=''); ap.add_argument('--lora-low', default='')
    ap.add_argument('--clip', default='umt5_xxl_fp8_e4m3fn_scaled.safetensors')
    ap.add_argument('--vae', default='wan_2.1_vae.safetensors')
    ap.add_argument('--init', help='a video to start from (a rendered walk, --frames frames at --size), sampled at --denoise')
    ap.add_argument('--denoise', type=float, default=1.0)
    ap.add_argument('--tiled', action='store_true', help='encode and decode with the tiled VAE nodes')
    ap.add_argument('--prompt', required=True); ap.add_argument('--neg', default=NEG)
    ap.add_argument('--server', default=os.environ.get('COMFY_SERVER', 'http://127.0.0.1:8189'))
    ap.add_argument('--comfy-input', default=r'C:\ComfyUI\input'); ap.add_argument('--comfy-output', default=r'C:\ComfyUI\output')
    ap.add_argument('--timeout', type=int, default=7200)
    a = ap.parse_args()
    W, H = (int(x) for x in a.size.split('x'))
    if (a.frames - 1) % 4: raise SystemExit('--frames must be 4n+1')
    if a.lightning:
        a.lora_high = a.lora_high or 'wan2.2_i2v_lightx2v_4steps_lora_v1_high_noise.safetensors'
        a.lora_low = a.lora_low or 'wan2.2_i2v_lightx2v_4steps_lora_v1_low_noise.safetensors'
        a.steps, a.cfg, a.shift = 4, 1.0, 5.0
    for f, n in ((a.first, 'wan_first.png'), (a.last, 'wan_last.png')):
        shutil.copy(f, os.path.join(a.comfy_input, n))
    if a.init: shutil.copy(a.init, os.path.join(a.comfy_input, 'wan_init.mp4'))
    tile = {'tile_size': 512, 'overlap': 64, 'temporal_size': 64, 'temporal_overlap': 8}
    g = {
        '2': {'class_type': 'UnetLoaderGGUF', 'inputs': {'unet_name': a.low}},
        '4': {'class_type': 'ModelSamplingSD3', 'inputs': {'model': ['22' if a.lora_low else '2', 0], 'shift': a.shift}},
        '5': {'class_type': 'CLIPLoader', 'inputs': {'clip_name': a.clip, 'type': 'wan'}},
        '6': {'class_type': 'CLIPTextEncode', 'inputs': {'clip': ['5', 0], 'text': a.prompt}},
        '7': {'class_type': 'CLIPTextEncode', 'inputs': {'clip': ['5', 0], 'text': a.neg}},
        '8': {'class_type': 'VAELoader', 'inputs': {'vae_name': a.vae}},
        '9': {'class_type': 'LoadImage', 'inputs': {'image': 'wan_first.png'}},
        '10': {'class_type': 'LoadImage', 'inputs': {'image': 'wan_last.png'}},
        '11': {'class_type': 'WanFirstLastFrameToVideo', 'inputs': {
            'positive': ['6', 0], 'negative': ['7', 0], 'vae': ['8', 0], 'width': W, 'height': H,
            'length': a.frames, 'batch_size': 1, 'start_image': ['9', 0], 'end_image': ['10', 0]}},
        '14': {'class_type': 'VAEDecodeTiled' if a.tiled else 'VAEDecode',
               'inputs': dict({'samples': ['13', 0], 'vae': ['8', 0]}, **(tile if a.tiled else {}))},
        '15': {'class_type': 'SaveImage', 'inputs': {'images': ['14', 0], 'filename_prefix': f'wan_frames/{uuid.uuid4().hex[:8]}_s{a.seed}'}},
    }
    if a.lora_low:
        g['22'] = {'class_type': 'LoraLoaderModelOnly', 'inputs': {'model': ['2', 0], 'lora_name': a.lora_low, 'strength_model': 1.0}}
    if a.init:
        g['40'] = {'class_type': 'LoadVideo', 'inputs': {'file': 'wan_init.mp4'}}
        g['41'] = {'class_type': 'GetVideoComponents', 'inputs': {'video': ['40', 0]}}
        g['42'] = {'class_type': 'VAEEncodeTiled' if a.tiled else 'VAEEncode',
                   'inputs': dict({'pixels': ['41', 0], 'vae': ['8', 0]}, **(tile if a.tiled else {}))}
        g['13'] = {'class_type': 'KSampler', 'inputs': {
            'model': ['4', 0], 'seed': a.seed, 'steps': a.steps, 'cfg': a.cfg, 'sampler_name': 'euler', 'scheduler': 'simple',
            'positive': ['11', 0], 'negative': ['11', 1], 'latent_image': ['42', 0], 'denoise': a.denoise}}
    else:
        half = a.steps // 2
        g['1'] = {'class_type': 'UnetLoaderGGUF', 'inputs': {'unet_name': a.high}}
        g['3'] = {'class_type': 'ModelSamplingSD3', 'inputs': {'model': ['21' if a.lora_high else '1', 0], 'shift': a.shift}}
        if a.lora_high:
            g['21'] = {'class_type': 'LoraLoaderModelOnly', 'inputs': {'model': ['1', 0], 'lora_name': a.lora_high, 'strength_model': 1.0}}
        g['12'] = {'class_type': 'KSamplerAdvanced', 'inputs': {
            'model': ['3', 0], 'add_noise': 'enable', 'noise_seed': a.seed, 'steps': a.steps, 'cfg': a.cfg,
            'sampler_name': 'euler', 'scheduler': 'simple', 'positive': ['11', 0], 'negative': ['11', 1],
            'latent_image': ['11', 2], 'start_at_step': 0, 'end_at_step': half, 'return_with_leftover_noise': 'enable'}}
        g['13'] = {'class_type': 'KSamplerAdvanced', 'inputs': {
            'model': ['4', 0], 'add_noise': 'disable', 'noise_seed': a.seed, 'steps': a.steps, 'cfg': a.cfg,
            'sampler_name': 'euler', 'scheduler': 'simple', 'positive': ['11', 0], 'negative': ['11', 1],
            'latent_image': ['12', 0], 'start_at_step': half, 'end_at_step': 10000, 'return_with_leftover_noise': 'disable'}}
    r = api(a.server, '/prompt', {'prompt': g, 'client_id': uuid.uuid4().hex})
    if r.get('node_errors'): raise SystemExit('node errors: ' + json.dumps(r['node_errors'])[:3000])
    pid = r['prompt_id']; t0 = time.time()
    while True:
        if time.time() - t0 > a.timeout:
            api(a.server, '/interrupt', {}); raise SystemExit(f'timed out after {a.timeout} s')
        h = api(a.server, f'/history/{pid}')
        if pid in h:
            st = h[pid].get('status', {})
            if st.get('status_str') == 'error': raise SystemExit('ComfyUI error: ' + json.dumps(st.get('messages', []))[-3000:])
            if st.get('completed'): break
        time.sleep(10)
    fdir = os.path.join(a.out, f'frames_s{a.seed}'); os.makedirs(fdir, exist_ok=True)
    imgs = [it for it in h[pid]['outputs'].get('15', {}).get('images', []) if isinstance(it, dict) and 'filename' in it]
    for k, it in enumerate(imgs):
        shutil.move(os.path.join(a.comfy_output, it.get('subfolder', ''), it['filename']), os.path.join(fdir, f'{k:04d}.png'))
    print(f'{fdir}: {len(imgs)} frames {W}x{H}, {a.steps} steps, denoise {a.denoise}, seed {a.seed}, {time.time() - t0:.0f} s', flush=True)


if __name__ == '__main__':
    main()
