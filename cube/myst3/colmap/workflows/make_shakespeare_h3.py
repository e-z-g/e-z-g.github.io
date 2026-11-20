#!/usr/bin/env python3
r"""
Writes "Shakespeare dance - H3 character swap.json": a ComfyUI workflow (API format; drop it on ComfyUI) that puts
the person in a picture into a dance video in place of the dancer, with MiniMax H3's reference-to-video model
(ref2va) and akatz-ai's H3 Character Swap LoRA V1.5, by the LoRA's tested recipe: the Ref2VA INT8 base, the swap
LoRA at 1.0, the 8-step FL2V Turbo LoRA at 1.0, 8 steps, cfg 1, er_sde, normal. Core ComfyUI nodes only.

    the picture -> <Picture 1>; the dance video (24 fps) -> <Video 1>, its sound optionally as its soundtrack
    -> MiniMaxH3ReferenceToVideo (prompt names both) -> sampler -> video and sound decoded -> MP4 at 24 fps

Five more LoRA slots sit after the two (strength 0 until set).

    python make_shakespeare_h3.py [OUT.json] [--image bard_2.png] [--video dance.mp4]
"""
import argparse
import json

ap = argparse.ArgumentParser()
ap.add_argument('out', nargs='?', default='Shakespeare dance - H3 character swap.json')
ap.add_argument('--image', default='bard_2.png'); ap.add_argument('--video', default='dance.mp4')
a = ap.parse_args()

g = {}
def node(i, cls, title, **inp):
    g[str(i)] = {'class_type': cls, 'inputs': inp, '_meta': {'title': title}}
    return str(i)

node(1, 'PrimitiveInt', 'Width (multiple of 32; match the dance video\'s shape)', value=480)
node(2, 'PrimitiveInt', 'Height (multiple of 32)', value=832)
node(3, 'PrimitiveInt', 'Frames at 24 fps (17n+5: 124 = 5.2 s, 158, 192, 226 ...)', value=124)
node(4, 'PrimitiveInt', 'Seed', value=2)
node(10, 'LoadImage', '<Picture 1>: the person (full body, face clear)', image=a.image)
node(11, 'LoadVideo', '<Video 1>: the dance (convert to 24 fps first)', file=a.video)
node(12, 'GetVideoComponents', 'Dance frames and sound', video=['11', 0])
node(20, 'UNETLoader', 'H3 reference-to-video', unet_name='minimax_h3_ref2va_pruned_int8_convrot.safetensors', weight_dtype='default')
node(21, 'LoraLoaderModelOnly', 'Character swap LoRA V1.5', model=['20', 0], lora_name='h3_character_swap_v1.5.safetensors', strength_model=1.0)
node(22, 'LoraLoaderModelOnly', 'Turbo LoRA (8 steps at cfg 1)', model=['21', 0], lora_name='h3\\minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors', strength_model=1.0)
last = '22'
for k in range(5):
    last = node(23 + k, 'LoraLoaderModelOnly', f'LoRA {k + 1} (pick a file, then raise the strength from 0)', model=[last, 0],
                lora_name='h3_character_swap_v1.5.safetensors', strength_model=0.0)
node(30, 'CLIPLoader', 'Text encoder (Qwen3-VL)', clip_name='qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors', type='minimax', device='default')
node(31, 'VAELoader', 'Video VAE', vae_name='minimax_h3_video_vae_fp16.safetensors')
node(32, 'VAELoader', 'Audio VAE', vae_name='minimax_h3_audio_vae_fp32.safetensors')
node(40, 'MiniMaxH3ReferenceToVideo', 'H3 reference to video', clip=['30', 0], vae=['31', 0], audio_vae=['32', 0],
     prompt='Replace the dancing man in <Video 1> with the character in <Picture 1>. Keep the replacement character\'s face, hair, '
            'beard, earring and clothing from <Picture 1>: a man in his late thirties with a high receding hairline, shoulder-length '
            'dark brown hair, a short neat beard and moustache and a small gold hoop earring, in a black Elizabethan doublet with a '
            'plain white falling collar and white cuffs. Follow the source performance\'s pose, gaze, expression and movement exactly, '
            'including how he holds and moves the microphone stand. Preserve the source video\'s camera, framing, stage, lighting, '
            'objects and all other people. Do not show the reference picture or its background.',
     width=['1', 0], height=['2', 0], length=['3', 0], ref_image_size='match',
     **{'ref_images.ref_image_0': ['10', 0], 'ref_videos.ref_video_0': ['12', 0]})
node(50, 'BasicGuider', 'Guider', model=[last, 0], conditioning=['40', 0])
node(51, 'RandomNoise', 'Noise', noise_seed=['4', 0])
node(52, 'KSamplerSelect', 'Sampler', sampler_name='er_sde')
node(53, 'BasicScheduler', 'Steps (8 with the Turbo LoRA)', model=[last, 0], scheduler='normal', steps=8, denoise=1.0)
node(54, 'SamplerCustomAdvanced', 'Sample', noise=['51', 0], guider=['50', 0], sampler=['52', 0], sigmas=['53', 0], latent_image=['40', 1])
node(55, 'VAEDecode', 'Decode video', samples=['54', 0], vae=['31', 0])
node(56, 'VAEDecodeAudio', 'Decode sound', samples=['54', 0], vae=['32', 0])
node(57, 'CreateVideo', 'Video', images=['55', 0], audio=['56', 0], fps=24.0)
node(58, 'SaveVideo', 'Save', video=['57', 0], filename_prefix='video/shakespeare_h3', format='auto', codec='auto')
json.dump(g, open(a.out, 'w', encoding='utf-8'), indent=1, ensure_ascii=False)
print(a.out, len(g), 'nodes')
