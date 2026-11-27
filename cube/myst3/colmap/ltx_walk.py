#!/usr/bin/env python3
r"""
A walk between two pictures made by LTX-2.5 (the 22B distilled model), through a running ComfyUI, with h3_flf.py's
interface so walk_wan.ps1 -Engine ltx can run walk_polar3.ps1's recipe on it (the maintainer, 26 November 2026: try
LTX with this exact workflow, adapted to its strengths).

    python ltx_walk.py FIRST.png LAST.png OUT_DIR [--size 1280x640] [--frames 81] [--fps 24] [--seed 4]
        [--sigmas "1.0, ..."] [--init VIDEO.mp4 --denoise 0.3] [--guide-strength 1] [--prompt ...] [--neg ...]

As ComfyUI's own LTX-2.5 first-and-last-frame template (video_ltx2_5_flf2v.json, its subgraph): the distilled
transformer and the Gemma 4 12B text encoder as int8 convrot (type ltxv), LTXVConditioning at the frame rate, each
end picture through LTXVPreprocess (18) and LTXVAddGuide at frame 0 and -1, an empty audio latent joined to the video
latent (the model makes both), LTXVDualCFGGuider at 1 and 1, Euler ancestral (eta 0) on the template's 8 distilled
sigmas, LTXVSeparateAVLatent, LTXVCropGuides, tiled decode. Its prompt enhancer is left out (the prompt is used as
written) and the guides are at --guide-strength 1 (the template's 0.7 leaves the ends loose; walk_ends_join.py puts the
node pictures back in any case). With --init: the video VAE-encoded (tiled) as the latent, the guides added to it, and
sampled from sigma --denoise down: the distilled schedule's sigmas below it, with --denoise put first. Frames are 8n+1
(the VAE's 8 frames a latent), sizes multiples of 32; the VAE's 32x32x8 compression keeps 2560x1280 cheap.
Writes every frame losslessly as OUT_DIR/frames_s<seed>/0000.png ... . Standard library only.
"""
import argparse, json, os, shutil, time, urllib.request, uuid

SIGMAS = '1.0, 0.99375, 0.9875, 0.98125, 0.975, 0.909375, 0.725, 0.421875, 0.0'
NEG = ('blurry, out of focus, soft, smeared, low detail, flickering, shimmering textures, warping, morphing, melting, '
       'ghosting, double image, jittery movement, camera shake, tilted camera, turning, cut, scene change, people, text, '
       'watermark, cartoonish rendering, 3D CGI look, inconsistent lighting')


def api(server, path, data=None):
    req = urllib.request.Request(server + path, data=json.dumps(data).encode() if data is not None else None,
                                 headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read())


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('first'); ap.add_argument('last'); ap.add_argument('out')
    ap.add_argument('--size', default='1280x640'); ap.add_argument('--frames', type=int, default=81)
    ap.add_argument('--fps', type=float, default=24.0); ap.add_argument('--seed', type=int, default=4)
    ap.add_argument('--sigmas', default=SIGMAS); ap.add_argument('--guide-strength', type=float, default=1.0)
    ap.add_argument('--unet', default='ltx-2.5-22b-distilled-transformer-comfy-int8-convrot.safetensors')
    ap.add_argument('--clip', default='gemma4-12b-with-proj-ltx-2.5-comfy-int8-convrot.safetensors')
    ap.add_argument('--vae', default='ltx-2.5-video-vae-bf16.safetensors')
    ap.add_argument('--audio-vae', default='ltx-2.5-audio-vae-bf16.safetensors')
    ap.add_argument('--init', help='a video to start from (--frames frames at --size), sampled from sigma --denoise')
    ap.add_argument('--denoise', type=float, default=1.0)
    ap.add_argument('--tiled', action='store_true', help='accepted for wan_walk.py\'s interface (always tiled here)')
    ap.add_argument('--prompt', required=True); ap.add_argument('--neg', default=NEG)
    ap.add_argument('--server', default=os.environ.get('COMFY_SERVER', 'http://127.0.0.1:8189'))
    ap.add_argument('--comfy-input', default=r'C:\ComfyUI\input'); ap.add_argument('--comfy-output', default=r'C:\ComfyUI\output')
    ap.add_argument('--timeout', type=int, default=7200)
    a = ap.parse_args()
    W, H = (int(x) for x in a.size.split('x'))
    if (a.frames - 1) % 8: raise SystemExit('--frames must be 8n+1')
    sig = [float(s) for s in a.sigmas.split(',')]
    if a.init:
        sig = [a.denoise] + [s for s in sig if s < a.denoise]
        if sig[-1] != 0.0: sig.append(0.0)
    sigmas = ', '.join(f'{s:g}' for s in sig)
    for f, n in ((a.first, 'ltx_first.png'), (a.last, 'ltx_last.png')):
        shutil.copy(f, os.path.join(a.comfy_input, n))
    if a.init: shutil.copy(a.init, os.path.join(a.comfy_input, 'ltx_init.mp4'))
    g = {
        '1': {'class_type': 'UNETLoader', 'inputs': {'unet_name': a.unet, 'weight_dtype': 'default'}},
        '2': {'class_type': 'CLIPLoader', 'inputs': {'clip_name': a.clip, 'type': 'ltxv', 'device': 'default'}},
        '3': {'class_type': 'VAELoader', 'inputs': {'vae_name': a.vae}},
        '4': {'class_type': 'VAELoader', 'inputs': {'vae_name': a.audio_vae}},
        '5': {'class_type': 'CLIPTextEncode', 'inputs': {'clip': ['2', 0], 'text': a.prompt}},
        '6': {'class_type': 'CLIPTextEncode', 'inputs': {'clip': ['2', 0], 'text': a.neg}},
        '7': {'class_type': 'LTXVConditioning', 'inputs': {'positive': ['5', 0], 'negative': ['6', 0], 'frame_rate': a.fps}},
        '8': {'class_type': 'LoadImage', 'inputs': {'image': 'ltx_first.png'}},
        '9': {'class_type': 'LoadImage', 'inputs': {'image': 'ltx_last.png'}},
        '10': {'class_type': 'LTXVPreprocess', 'inputs': {'image': ['8', 0], 'img_compression': 18}},
        '11': {'class_type': 'LTXVPreprocess', 'inputs': {'image': ['9', 0], 'img_compression': 18}},
        '12': {'class_type': 'EmptyLTXVLatentVideo', 'inputs': {'width': W, 'height': H, 'length': a.frames, 'batch_size': 1}},
        '13': {'class_type': 'LTXVAddGuide', 'inputs': {'positive': ['7', 0], 'negative': ['7', 1], 'vae': ['3', 0], 'latent': ['12', 0],
                                                        'image': ['10', 0], 'frame_idx': 0, 'strength': a.guide_strength}},
        '14': {'class_type': 'LTXVAddGuide', 'inputs': {'positive': ['13', 0], 'negative': ['13', 1], 'vae': ['3', 0], 'latent': ['13', 2],
                                                        'image': ['11', 0], 'frame_idx': -1, 'strength': a.guide_strength}},
        '15': {'class_type': 'LTXVEmptyLatentAudio', 'inputs': {'audio_vae': ['4', 0], 'frames_number': a.frames, 'frame_rate': int(round(a.fps)), 'batch_size': 1}},
        '16': {'class_type': 'LTXVConcatAVLatent', 'inputs': {'video_latent': ['14', 2], 'audio_latent': ['15', 0]}},
        '17': {'class_type': 'LTXVDualCFGGuider', 'inputs': {'model': ['1', 0], 'positive': ['14', 0], 'negative': ['14', 1], 'video_cfg': 1.0, 'audio_cfg': 1.0}},
        '18': {'class_type': 'RandomNoise', 'inputs': {'noise_seed': a.seed}},
        '19': {'class_type': 'SamplerEulerAncestral', 'inputs': {'eta': 0.0, 's_noise': 1.0}},
        '20': {'class_type': 'ManualSigmas', 'inputs': {'sigmas': sigmas}},
        '21': {'class_type': 'SamplerCustomAdvanced', 'inputs': {'noise': ['18', 0], 'guider': ['17', 0], 'sampler': ['19', 0],
                                                                 'sigmas': ['20', 0], 'latent_image': ['16', 0]}},
        '22': {'class_type': 'LTXVSeparateAVLatent', 'inputs': {'av_latent': ['21', 1]}},
        '23': {'class_type': 'LTXVCropGuides', 'inputs': {'positive': ['14', 0], 'negative': ['14', 1], 'latent': ['22', 0]}},
        '24': {'class_type': 'VAEDecodeTiled', 'inputs': {'samples': ['23', 2], 'vae': ['3', 0], 'tile_size': 512, 'overlap': 64,
                                                          'temporal_size': 64, 'temporal_overlap': 16}},
        '25': {'class_type': 'SaveImage', 'inputs': {'images': ['24', 0], 'filename_prefix': f'ltx_frames/{uuid.uuid4().hex[:8]}_s{a.seed}'}},
    }
    if a.init:
        g['40'] = {'class_type': 'LoadVideo', 'inputs': {'file': 'ltx_init.mp4'}}
        g['41'] = {'class_type': 'GetVideoComponents', 'inputs': {'video': ['40', 0]}}
        g['42'] = {'class_type': 'VAEEncodeTiled', 'inputs': {'pixels': ['41', 0], 'vae': ['3', 0], 'tile_size': 512, 'overlap': 64,
                                                              'temporal_size': 64, 'temporal_overlap': 8}}
        g['13']['inputs']['latent'] = ['42', 0]
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
    imgs = [it for it in h[pid]['outputs'].get('25', {}).get('images', []) if isinstance(it, dict) and 'filename' in it]
    for k, it in enumerate(imgs):
        shutil.move(os.path.join(a.comfy_output, it.get('subfolder', ''), it['filename']), os.path.join(fdir, f'{k:04d}.png'))
    print(f'{fdir}: {len(imgs)} frames {W}x{H}, sigmas {sigmas}, seed {a.seed}, {time.time() - t0:.0f} s', flush=True)


if __name__ == '__main__':
    main()
