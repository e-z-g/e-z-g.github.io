#!/usr/bin/env python3
r"""
A walk's six cube faces at full size, each drawn by Wan 2.2 VACE-Fun from a
low-resolution 360-degree walk and fixed at both ends to the game's own faces.

    python vace_face_walk.py IMAGES SPARSE_TXT EQ_WALK.mp4 OUT_DIR NODE_A NODE_B
        [--faces 1 2 3 4 5 6] [--size 640] [--frames 81] [--init-step 7] [--steps 20]
        [--prompt ...] [--server http://127.0.0.1:8189] [--comfy-input C:\ComfyUI\input]
        [--comfy-output C:\ComfyUI\output] [--ffmpeg ffmpeg]

EQ_WALK is a whole-view walk from NODE_A to NODE_B (walk_ends.py --equirect
frames, wan_flf.py, walk_finish.py), with the walk's direction in the middle;
its frames are taken evenly to --frames. For each face of NODE_A's cube (the
model's rotations, the same for both nodes), every frame of the walk is
drawn as that face sees it (about 320 px of the 1280 px panorama, enlarged
to --size): the guide. Its first and last frames are replaced by the game's
own face of NODE_A and NODE_B, marked as kept (mask 0); the rest are to be
drawn (mask 1). VACE gets that as its control video and masks, and the
sampling starts from the guide itself, encoded and noised from --init-step
of --steps (as an image-to-image pass: the guide's layout and motion carry
through, the model draws the detail); the high-noise expert runs up to half
way, the low-noise one the rest. Writes OUT_DIR/face<k>.mp4 (16 fps) and the
guides as OUT_DIR/guide<k>.mp4. Needs numpy, opencv-python, Pillow;
view_check.py beside it; ffmpeg; a running ComfyUI with ComfyUI-GGUF and the
VACE-Fun GGUF experts.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
import uuid

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from view_check import read_model  # noqa: E402

NEG = ('blurry, smeared, warped, melting, ghosting, double image, flicker, distorted, low quality, text, watermark, '
       'cut, scene change')


def api(server, path, data=None):
    req = urllib.request.Request(server + path, data=json.dumps(data).encode() if data is not None else None,
                                 headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read())


def write_video(ffmpeg, frames, path, fps=16, crf=12):
    H, W = frames[0].shape[:2]
    p = subprocess.Popen([ffmpeg, '-v', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'bgr24', '-s', f'{W}x{H}', '-r', str(fps),
                          '-i', '-', '-c:v', 'libx264', '-crf', str(crf), '-pix_fmt', 'yuv420p', path], stdin=subprocess.PIPE)
    for f in frames:
        p.stdin.write(np.ascontiguousarray(f).tobytes())
    p.stdin.close(); p.wait()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('images'); ap.add_argument('sparse'); ap.add_argument('walk'); ap.add_argument('out')
    ap.add_argument('a'); ap.add_argument('b')
    ap.add_argument('--faces', type=int, nargs='+', default=[1, 2, 3, 4, 5, 6])
    ap.add_argument('--size', type=int, default=640); ap.add_argument('--frames', type=int, default=81)
    ap.add_argument('--init-step', type=int, default=7); ap.add_argument('--steps', type=int, default=20)
    ap.add_argument('--prompt', default='A smooth, steady camera moving slowly forward through a fantasy place at dusk, '
                    'sharp detailed textures, the same place throughout, static lighting, no cuts, photorealistic')
    ap.add_argument('--server', default=os.environ.get('COMFY_SERVER', 'http://127.0.0.1:8189'))
    ap.add_argument('--comfy-input', default=r'C:\ComfyUI\input'); ap.add_argument('--comfy-output', default=r'C:\ComfyUI\output')
    ap.add_argument('--ffmpeg', default='ffmpeg'); ap.add_argument('--timeout', type=int, default=5400)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    _, imgs = read_model(a.sparse)
    face = lambda node, k: imgs[f'f{k}/MA-{node}.jpg']
    CA = -face(a.a, 1)[0].T @ face(a.a, 1)[1]; CB = -face(a.b, 1)[0].T @ face(a.b, 1)[1]
    # the equirectangular walk's camera, as walk_ends.py made it: level, facing from A to B
    up = -face(a.a, 1)[0][1]
    fwd = CB - CA; fwd -= up * (fwd @ up); fwd /= np.linalg.norm(fwd)
    right = np.cross(fwd, up); right /= np.linalg.norm(right)
    down = np.cross(fwd, right); down /= np.linalg.norm(down)
    Rcam = np.stack([right, down, fwd])
    cap = cv2.VideoCapture(a.walk)
    eq = []
    while True:
        r, f = cap.read()
        if not r:
            break
        eq.append(f)
    pick = np.round(np.linspace(0, len(eq) - 1, a.frames)).astype(int)
    eq = [eq[i] for i in pick]
    EH, EW = eq[0].shape[:2]
    S = a.size
    for k in a.faces:
        R = face(a.a, k)[0]
        v, u = np.mgrid[0:S, 0:S].astype(np.float64)
        d = np.stack([(u + .5) / S * 2 - 1, (v + .5) / S * 2 - 1, np.ones_like(u)], -1) @ R     # world directions
        c = d @ Rcam.T
        lon = np.arctan2(c[..., 0], c[..., 2]); lat = np.arcsin(np.clip(-c[..., 1] / np.linalg.norm(c, axis=-1), -1, 1))
        mx = ((lon / np.pi + 1) / 2 * EW - .5).astype(np.float32); my = ((0.5 - lat / np.pi) * EH - .5).astype(np.float32)
        guide = [cv2.remap(f, mx, my, cv2.INTER_CUBIC, borderMode=cv2.BORDER_WRAP) for f in eq]
        A = cv2.resize(cv2.imread(os.path.join(a.images, f'f{k}', f'MA-{a.a}.jpg')), (S, S), interpolation=cv2.INTER_AREA)
        B = cv2.resize(cv2.imread(os.path.join(a.images, f'f{k}', f'MA-{a.b}.jpg')), (S, S), interpolation=cv2.INTER_AREA)
        guide[0], guide[-1] = A, B
        gname, mname = f'walkguide_{a.a}_{k}.mp4', f'walkmask_{a.a}_{k}.mp4'
        write_video(a.ffmpeg, guide, os.path.join(a.comfy_input, gname))
        shutil.copy(os.path.join(a.comfy_input, gname), os.path.join(a.out, f'guide{k}.mp4'))
        masks = [np.full((S, S, 3), 255, np.uint8) for _ in guide]
        masks[0][:] = 0; masks[-1][:] = 0
        write_video(a.ffmpeg, masks, os.path.join(a.comfy_input, mname), crf=0)
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
            '9': {'class_type': 'LoadVideo', 'inputs': {'file': gname}},
            '10': {'class_type': 'GetVideoComponents', 'inputs': {'video': ['9', 0]}},
            '11': {'class_type': 'LoadVideo', 'inputs': {'file': mname}},
            '12': {'class_type': 'GetVideoComponents', 'inputs': {'video': ['11', 0]}},
            '13': {'class_type': 'ImageToMask', 'inputs': {'image': ['12', 0], 'channel': 'red'}},
            '14': {'class_type': 'WanVaceToVideo', 'inputs': {'positive': ['6', 0], 'negative': ['7', 0], 'vae': ['8', 0],
                                                              'width': S, 'height': S, 'length': a.frames, 'batch_size': 1,
                                                              'strength': 1.0, 'control_video': ['10', 0], 'control_masks': ['13', 0]}},
            '15': {'class_type': 'VAEEncode', 'inputs': {'pixels': ['10', 0], 'vae': ['8', 0]}},
            '16': {'class_type': 'KSamplerAdvanced', 'inputs': {
                'model': ['3', 0], 'add_noise': 'enable', 'noise_seed': 1, 'steps': a.steps, 'cfg': 3.5,
                'sampler_name': 'euler', 'scheduler': 'simple', 'positive': ['14', 0], 'negative': ['14', 1],
                'latent_image': ['15', 0], 'start_at_step': a.init_step, 'end_at_step': max(half, a.init_step + 1),
                'return_with_leftover_noise': 'enable'}},
            '17': {'class_type': 'KSamplerAdvanced', 'inputs': {
                'model': ['4', 0], 'add_noise': 'disable', 'noise_seed': 1, 'steps': a.steps, 'cfg': 3.5,
                'sampler_name': 'euler', 'scheduler': 'simple', 'positive': ['14', 0], 'negative': ['14', 1],
                'latent_image': ['16', 0], 'start_at_step': max(half, a.init_step + 1), 'end_at_step': 10000,
                'return_with_leftover_noise': 'disable'}},
            '18': {'class_type': 'TrimVideoLatent', 'inputs': {'samples': ['17', 0], 'trim_amount': ['14', 3]}},
            '19': {'class_type': 'VAEDecode', 'inputs': {'samples': ['18', 0], 'vae': ['8', 0]}},
            '20': {'class_type': 'CreateVideo', 'inputs': {'images': ['19', 0], 'fps': 16.0}},
            '21': {'class_type': 'SaveVideo', 'inputs': {'video': ['20', 0], 'filename_prefix': f'video/facewalk_{a.a}_{k}',
                                                         'format': 'auto', 'codec': 'auto'}},
        }
        r = api(a.server, '/prompt', {'prompt': g, 'client_id': uuid.uuid4().hex})
        if r.get('node_errors'):
            raise SystemExit('node errors: ' + json.dumps(r['node_errors'])[:3000])
        pid, t0 = r['prompt_id'], time.time()
        while True:
            if time.time() - t0 > a.timeout:
                api(a.server, '/interrupt', {})
                raise SystemExit(f'face {k}: timed out after {a.timeout} s')
            h = api(a.server, f'/history/{pid}')
            if pid in h:
                st = h[pid].get('status', {})
                if st.get('status_str') == 'error':
                    raise SystemExit(f'face {k}: ComfyUI error: ' + json.dumps(st.get('messages', []))[:3000])
                if st.get('completed'):
                    break
            time.sleep(10)
        for key, items in h[pid]['outputs'].get('21', {}).items():
            for it in items if isinstance(items, list) else []:
                if isinstance(it, dict) and 'filename' in it:
                    shutil.copy(os.path.join(a.comfy_output, it.get('subfolder', ''), it['filename']), os.path.join(a.out, f'face{k}.mp4'))
        print(f'face {k}: {time.time() - t0:.0f} s', flush=True)


if __name__ == '__main__':
    main()
