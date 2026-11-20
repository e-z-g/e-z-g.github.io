#!/usr/bin/env python3
r"""
Writes "Shakespeare dance - Wan 2.2 Animate.json": a ComfyUI workflow (API format, loads by dropping it on ComfyUI)
that puts the person in a picture into a dance video in place of the dancer, with Wan 2.2 Animate and only core
ComfyUI nodes (no custom node packs):

    the dance video, cut to LENGTH frames and scaled to WIDTH x HEIGHT
      -> SDPose: the dancer's pose drawn as a stick figure (pose_video) and the face cropped to 512x512 (face_video)
      -> SAM 3.1 with the text "person": the dancer's mask, grown a little (character_mask), and the video with
         the dancer blacked out (background_video)
    the picture, scaled the same -> reference image and CLIP vision
    Wan 2.2 Animate 14B + lightx2v (6 steps, cfg 1) + relight LoRA + five more LoRA slots (strength 0 until set)
    -> WanAnimateToVideo -> KSampler -> decode -> video at the dance's own frame rate

"Replace" (a boolean node) true: the dancer is replaced and the stage kept; false: background_video and
character_mask are left out, and the person dances in a scene from the prompt.

    python make_shakespeare_wan22.py [OUT.json] [--image bard.png] [--video dance.mp4]
"""
import argparse
import json

ap = argparse.ArgumentParser()
ap.add_argument('out', nargs='?', default='Shakespeare dance - Wan 2.2 Animate.json')
ap.add_argument('--image', default='bard_2.png'); ap.add_argument('--video', default='dance.mp4')
a = ap.parse_args()

g = {}
def node(i, cls, title, **inp):
    g[str(i)] = {'class_type': cls, 'inputs': inp, '_meta': {'title': title}}
    return str(i)

W, H, LEN = 480, 832, 81
# settings
node(1, 'PrimitiveInt', 'Width (multiple of 16; match the dance video\'s shape)', value=W)
node(2, 'PrimitiveInt', 'Height (multiple of 16)', value=H)
node(3, 'PrimitiveInt', 'Frames (4n+1: 81, 121, 161 ...)', value=LEN)
node(4, 'PrimitiveBoolean', 'Replace the dancer, keep the stage (true) / dance in a scene from the prompt (false)', value=True)
node(5, 'PrimitiveInt', 'Seed', value=2)
# inputs
node(10, 'LoadImage', 'The person (full body, face clear)', image=a.image)
node(11, 'LoadVideo', 'The dance video', file=a.video)
node(12, 'GetVideoComponents', 'Dance frames', video=['11', 0])
node(13, 'ImageFromBatch', 'First frames of the dance', image=['12', 0], batch_index=0, length=['3', 0])
node(14, 'ImageScale', 'Dance scaled and centre-cropped', image=['13', 0], upscale_method='lanczos', width=['1', 0], height=['2', 0], crop='center')
node(15, 'ImageScale', 'Person scaled and centre-cropped', image=['10', 0], upscale_method='lanczos', width=['1', 0], height=['2', 0], crop='center')
# pose and face (SDPose)
node(20, 'CheckpointLoaderSimple', 'SDPose', ckpt_name='sdpose_wholebody_fp16.safetensors')
node(21, 'SDPoseKeypointExtractor', 'Dancer\'s pose', model=['20', 0], vae=['20', 2], image=['14', 0], batch_size=16)
node(22, 'SDPoseDrawKeypoints', 'Pose video', keypoints=['21', 0], draw_body=True, draw_hands=True, draw_face=False, draw_feet=True,
     stick_width=4, face_point_size=3, score_threshold=0.3, draw_head=True)
node(23, 'SDPoseFaceBBoxes', 'Dancer\'s face', keypoints=['21', 0], scale=1.5, force_square=True)
node(24, 'CropByBBoxes', 'Face video', image=['14', 0], bboxes=['23', 0], output_width=512, output_height=512, padding=0, keep_aspect='stretch')
# mask and background (SAM 3.1)
node(30, 'CheckpointLoaderSimple', 'SAM 3.1', ckpt_name='sam3.1_multiplex_fp16.safetensors')
node(31, 'CLIPTextEncode', 'What to mask', clip=['30', 1], text='person')
node(32, 'SAM3_Detect', 'Dancer\'s mask', model=['30', 0], image=['14', 0], conditioning=['31', 0], threshold=0.5, refine_iterations=2, individual_masks=False)
node(33, 'GrowMask', 'Mask grown (raise expand if hair or clothes are cut off)', mask=['32', 0], expand=16, tapered_corners=True)
node(34, 'EmptyImage', 'Black', width=['1', 0], height=['2', 0], batch_size=1, color=0)
node(35, 'ImageCompositeMasked', 'Stage with the dancer blacked out', destination=['14', 0], source=['34', 0], x=0, y=0, resize_source=False, mask=['33', 0])
node(36, 'ComfySwitchNode', 'background_video (only when replacing)', switch=['4', 0], on_true=['35', 0])
node(37, 'ComfySwitchNode', 'character_mask (only when replacing)', switch=['4', 0], on_true=['33', 0])
# model
node(40, 'UNETLoader', 'Wan 2.2 Animate 14B', unet_name='wan2.2_animate_14B_int8_convrot.safetensors', weight_dtype='default')
node(41, 'LoraLoaderModelOnly', 'Speed LoRA (6 steps at cfg 1)', model=['40', 0], lora_name='lightx2v_I2V_14B_480p_cfg_step_distill_rank64_bf16.safetensors', strength_model=1.0)
node(42, 'LoraLoaderModelOnly', 'Relight LoRA (lighting matched to the stage)', model=['41', 0], lora_name='wan2.2_animate_14B_relight_lora_bf16.safetensors', strength_model=1.0)
last = '42'
for k in range(5):
    last = node(43 + k, 'LoraLoaderModelOnly', f'LoRA {k + 1} (pick a file, then raise the strength from 0)', model=[last, 0],
                lora_name='wan2.2_animate_14B_relight_lora_bf16.safetensors', strength_model=0.0)
node(48, 'ModelSamplingSD3', 'Shift', model=[last, 0], shift=8.0)
node(50, 'CLIPLoader', 'Text encoder', clip_name='umt5_xxl_fp8_e4m3fn_scaled.safetensors', type='wan', device='default')
node(51, 'CLIPTextEncode', 'Prompt: who, and what they do', clip=['50', 0],
     text='A man in his late thirties with a high receding hairline, shoulder-length dark brown hair, a short neat beard and moustache '
          'and a small gold hoop earring, wearing a black Elizabethan doublet with a plain white falling collar and white cuffs, '
          'dancing with a microphone stand on a small stage.')
node(52, 'CLIPTextEncode', 'Negative prompt', clip=['50', 0],
     text='色调艳丽，过曝，静态，细节模糊不清，字幕，风格，作品，画作，画面，静止，整体发灰，最差质量，低质量，JPEG压缩残留，丑陋的，残缺的，多余的手指，画得不好的手部，画得不好的脸部，畸形的，毁容的，形态畸形的肢体，手指融合，静止不动的画面，杂乱的背景，三条腿，背景人很多，倒着走')
node(53, 'VAELoader', 'VAE', vae_name='wan_2.1_vae.safetensors')
node(54, 'CLIPVisionLoader', 'CLIP vision', clip_name='clip_vision_h.safetensors')
node(55, 'CLIPVisionEncode', 'The person, seen', clip_vision=['54', 0], image=['15', 0], crop='none')
node(60, 'WanAnimateToVideo', 'Wan 2.2 Animate', positive=['51', 0], negative=['52', 0], vae=['53', 0], width=['1', 0], height=['2', 0],
     length=['3', 0], batch_size=1, clip_vision_output=['55', 0], reference_image=['15', 0], face_video=['24', 0], pose_video=['22', 0],
     continue_motion_max_frames=5, background_video=['36', 0], character_mask=['37', 0], video_frame_offset=0)
node(61, 'KSampler', 'Sampler (6 steps, cfg 1 with the speed LoRA)', model=['48', 0], seed=['5', 0], steps=6, cfg=1.0, sampler_name='euler',
     scheduler='simple', positive=['60', 0], negative=['60', 1], latent_image=['60', 2], denoise=1.0)
node(62, 'TrimVideoLatent', 'Trim', samples=['61', 0], trim_amount=['60', 3])
node(63, 'VAEDecode', 'Decode', samples=['62', 0], vae=['53', 0])
node(64, 'ImageFromBatch', 'Trim frames', image=['63', 0], batch_index=['60', 4], length=4096)
node(65, 'CreateVideo', 'Video at the dance\'s frame rate', images=['64', 0], fps=['12', 2])
node(66, 'SaveVideo', 'Save', video=['65', 0], filename_prefix='video/shakespeare_dance', format='auto', codec='auto')
node(70, 'CreateVideo', 'Check: pose', images=['22', 0], fps=['12', 2])
node(71, 'SaveVideo', 'Save the pose check', video=['70', 0], filename_prefix='video/shakespeare_pose', format='auto', codec='auto')
node(72, 'CreateVideo', 'Check: stage without the dancer', images=['35', 0], fps=['12', 2])
node(73, 'SaveVideo', 'Save the mask check', video=['72', 0], filename_prefix='video/shakespeare_mask', format='auto', codec='auto')
json.dump(g, open(a.out, 'w', encoding='utf-8'), indent=1, ensure_ascii=False)
print(a.out, len(g), 'nodes')
