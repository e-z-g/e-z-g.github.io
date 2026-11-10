// Builds two looping image-to-video workflows in ComfyUI's own frontend (so the files are in its format), saves
// them, and test-runs each with 2 short segments: Wan 2.2 (GGUF, Lightning) and MiniMax H3 (turbo LoRA, with audio).
const { chromium } = require('playwright');
const fs = require('fs');
const OUT = process.env.HOME + '/e-z-g-disassembly/reference/myst3/pc_scripts/';
const ONLY = process.env.ONLY || 'wan,h3';
(async () => {
  const b = await chromium.launch({ channel: 'chrome' });
  const p = await b.newPage({ viewport: { width: 1800, height: 1100 } });
  await p.goto('http://127.0.0.1:8191/', { waitUntil: 'load' });
  await p.waitForFunction(() => window.app && window.app.graph && window.LiteGraph, null, { timeout: 120000 });
  await p.waitForTimeout(3000);
  await p.evaluate(() => {
    window.B = {
      N: {},
      add(key, type, pos, title, vals = {}, size) {
        const n = LiteGraph.createNode(type); if (!n) throw new Error('no node ' + type);
        n.pos = pos; app.graph.add(n); if (title) n.title = title;
        for (const [k, v] of Object.entries(vals)) { const w = (n.widgets || []).find(w => w.name === k); if (!w) throw new Error(type + ' has no widget ' + k + ': ' + (n.widgets || []).map(w => w.name)); w.value = v; }
        if (size) n.size = size; this.N[key] = n; return n;
      },
      link(a, out, bk, inp) {
        const A = this.N[a], Bn = this.N[bk];
        const o = typeof out === 'number' ? out : A.findOutputSlot(out); const i = Bn.findInputSlot(inp);
        if (o < 0 || i < 0) throw new Error(`no slot ${a}.${out} -> ${bk}.${inp}`);
        A.connect(o, Bn, i);
      },
      // a model's LoRA chain: the first on at strength 1, two spares at strength 0 (0 is off: the file is not even loaded)
      loras(prefix, from, x, y, first, spare, label) {
        let prev = from;
        const names = [first, spare, spare];
        names.forEach((name, i) => {
          const key = prefix + i;
          this.add(key, 'LoraLoaderModelOnly', [x, y + i * 110], i === 0 ? `${label}: ${i === 0 ? 'speed LoRA' : ''}` : `${label}: spare LoRA ${i} (strength 0 = off)`, { lora_name: name, strength_model: i === 0 ? 1 : 0 }, [400, 82]);
          this.link(prev, 0, key, 'model'); prev = key;
        });
        return prev;
      },
      note(text, pos, size) { const n = this.add('note', 'MarkdownNote', pos, 'How this works', {}, size); n.widgets[0].value = text; },
      async test(setup, timeoutMs) {
        setup();
        const { output } = await app.graphToPrompt();
        const r = await fetch('/prompt', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ prompt: output, client_id: 'build-test' }) });
        const j = await r.json(); if (!j.prompt_id) return { error: JSON.stringify(j).slice(0, 2000) };
        const t0 = Date.now();
        while (Date.now() - t0 < timeoutMs) {
          await new Promise(r => setTimeout(r, 5000));
          const h = await (await fetch('/history/' + j.prompt_id)).json(); const e = h[j.prompt_id];
          if (e && e.status && (e.status.completed || e.status.status_str === 'error')) return { status: e.status.status_str, msgs: JSON.stringify(e.status.messages).slice(-1200), outputs: JSON.stringify(e.outputs).slice(0, 500), secs: (Date.now() - t0) / 1000 };
        }
        await fetch('/interrupt', { method: 'POST' }); return { error: 'timed out' };
      },
    };
  });
  const NEG = '色调艳丽，过曝，静态，细节模糊不清，字幕，风格，作品，画作，画面，静止，整体发灰，最差质量，低质量，JPEG压缩残留，丑陋的，残缺的，多余的手指，画得不好的手部，画得不好的脸部，畸形的，毁容的，形态畸形的肢体，手指融合，静止不动的画面，杂乱的背景，三条腿，背景人很多，倒着走';
  const results = {};
  if (ONLY.includes('wan')) {
    const wf = await p.evaluate((NEG) => {
      app.graph.clear(); B.N = {};
      const { add, link } = { add: B.add.bind(B), link: B.link.bind(B) };
      add('hi', 'UnetLoaderGGUF', [0, 0], 'Wan 2.2 I2V high noise', { unet_name: 'Wan2.2-I2V-A14B-HighNoise-Q4_K_M.gguf' }, [330, 60]);
      add('lo', 'UnetLoaderGGUF', [0, 380], 'Wan 2.2 I2V low noise', { unet_name: 'Wan2.2-I2V-A14B-LowNoise-Q4_K_M.gguf' }, [330, 60]);
      const sp = 'lightx2v_I2V_14B_480p_cfg_step_distill_rank64_bf16.safetensors';
      const h = B.loras('lh', 'hi', 370, 0, 'wan2.2_i2v_lightx2v_4steps_lora_v1_high_noise.safetensors', sp, 'High noise');
      const l = B.loras('ll', 'lo', 370, 380, 'wan2.2_i2v_lightx2v_4steps_lora_v1_low_noise.safetensors', sp, 'Low noise');
      add('shi', 'ModelSamplingSD3', [810, 0], null, { shift: 5 }); add('slo', 'ModelSamplingSD3', [810, 380], null, { shift: 5 });
      link(h, 0, 'shi', 'model'); link(l, 0, 'slo', 'model');
      add('clip', 'CLIPLoader', [0, 760], null, { clip_name: 'umt5_xxl_fp8_e4m3fn_scaled.safetensors', type: 'wan' }, [330, 110]);
      add('pos', 'CLIPTextEncode', [370, 760], 'Prompt (the same for every segment)', { text: 'The camera slowly moves forward through the scene, steady and smooth, natural motion, no cuts.' }, [420, 160]);
      add('neg', 'CLIPTextEncode', [370, 960], 'Negative prompt', { text: NEG }, [420, 120]);
      add('vae', 'VAELoader', [0, 920], null, { vae_name: 'wan_2.1_vae.safetensors' }, [330, 60]);
      link('clip', 0, 'pos', 'clip'); link('clip', 0, 'neg', 'clip');
      add('img', 'LoadImage', [0, 1100], 'Start image', { image: 'example.png' }, [330, 330]);
      add('fit', 'ImageScaleToTotalPixels', [370, 1120], "Fit to Wan's size, keeping the shape (0.41 MP = 832x480; 0.92 = 1280x720)", { upscale_method: 'lanczos', megapixels: 0.41, resolution_steps: 16 }, [420, 110]);
      add('size', 'GetImageSize', [370, 1270], null, {}, [220, 80]);
      link('img', 0, 'fit', 'image'); link('fit', 0, 'size', 'image');
      add('start', 'StartLoop', [850, 760], 'Segments: how many times to run the prompt', { mode: 'simple' }, [330, 130]);
      B.N.start.widgets.find(w => w.name === 'mode.num_iterations').value = 3;
      link('fit', 0, 'start', 'initial_iteration_value');
      add('last', 'ImageFromBatch', [850, 940], 'Last frame so far: this segment starts from it', { batch_index: 4095, length: 1 }, [330, 90]);
      link('start', 'current_iteration_value', 'last', 'image');
      add('wan', 'WanImageToVideo', [1220, 760], 'Segment length (frames, 4n+1; 81 = 5 s)', { length: 81, batch_size: 1 }, [330, 200]);
      link('pos', 0, 'wan', 'positive'); link('neg', 0, 'wan', 'negative'); link('vae', 0, 'wan', 'vae'); link('last', 0, 'wan', 'start_image');
      link('size', 'width', 'wan', 'width'); link('size', 'height', 'wan', 'height');
      add('ks1', 'KSamplerAdvanced', [1220, 0], 'High noise: steps 0-2 of 4', { add_noise: 'enable', noise_seed: 1, control_after_generate: 'randomize', steps: 4, cfg: 1, sampler_name: 'euler', scheduler: 'simple', start_at_step: 0, end_at_step: 2, return_with_leftover_noise: 'enable' }, [330, 330]);
      add('ks2', 'KSamplerAdvanced', [1590, 0], 'Low noise: steps 2-4', { add_noise: 'disable', noise_seed: 0, control_after_generate: 'fixed', steps: 4, cfg: 1, sampler_name: 'euler', scheduler: 'simple', start_at_step: 2, end_at_step: 10000, return_with_leftover_noise: 'disable' }, [330, 330]);
      link('shi', 0, 'ks1', 'model'); link('wan', 'positive', 'ks1', 'positive'); link('wan', 'negative', 'ks1', 'negative'); link('wan', 'latent', 'ks1', 'latent_image');
      link('slo', 0, 'ks2', 'model'); link('wan', 'positive', 'ks2', 'positive'); link('wan', 'negative', 'ks2', 'negative'); link('ks1', 0, 'ks2', 'latent_image');
      add('dec', 'VAEDecode', [1590, 400], null, {}, [220, 50]);
      link('ks2', 0, 'dec', 'samples'); link('vae', 0, 'dec', 'vae');
      add('drop', 'ImageFromBatch', [1590, 500], 'The segment without its first frame (the start, already in)', { batch_index: 1, length: 4096 }, [330, 90]);
      link('dec', 0, 'drop', 'image');
      add('join', 'ImageBatch', [1590, 650], 'All frames so far', {}, [330, 70]);
      link('start', 'current_iteration_value', 'join', 'image1'); link('drop', 0, 'join', 'image2');
      add('end', 'EndLoop', [1590, 780], null, { accumulate: false }, [330, 100]);
      link('join', 0, 'end', 'output_value'); link('join', 0, 'end', 'next_iteration_value');
      add('vid', 'CreateVideo', [1960, 760], null, { fps: 16 }, [270, 80]);
      link('end', 'outputs', 'vid', 'images');
      add('save', 'SaveVideo', [1960, 880], null, { filename_prefix: 'video/wan22_i2v_loop' }, [420, 420]);
      link('vid', 0, 'save', 'video');
      B.note([
        '## Wan 2.2 image to video, in segments', '',
        "1. **Start image**: any shape. *Fit to Wan's size* scales it to about 832x480's area (0.41 MP) in its own aspect ratio, in steps of 16 px. For 720p set 0.92 (slower).",
        '2. **Prompt**: used for every segment.',
        '3. **Segments**: how many times the prompt runs. Each starts from the last frame of the one before; the result is one video of segments x 80 + 1 frames at 16 fps.',
        '4. **LoRAs**: a chain for each half of the model. The first is the 4-step Lightning LoRA (keep it at 1, or set the samplers to 20 steps, cfg 3.5, split at 10). The two spares are off at strength 0: pick a file and raise the strength to use one. A Wan 2.2 LoRA usually comes as a high-noise and a low-noise file; a Wan 2.1 LoRA goes in both chains.', '',
        'Models: GGUF Q4_K_M (ComfyUI-GGUF), for a 16 GB card.',
      ].join('\n'), [-420, 0], [380, 620]);
      return app.graph.serialize();
    }, NEG);
    fs.writeFileSync(OUT + 'wan22_i2v_loop.json', JSON.stringify(wf, null, 1));
    await p.screenshot({ path: OUT + 'wan22_i2v_loop.png' });
    results.wan = await p.evaluate(() => B.test(() => {
      B.N.img.widgets.find(w => w.name === 'image').value = 'mass84_walk_first.png';
      B.N.start.widgets.find(w => w.name === 'mode.num_iterations').value = 2;
      B.N.wan.widgets.find(w => w.name === 'length').value = 17;
    }, 1500000));
    console.log('wan test:', JSON.stringify(results.wan));
  }
  if (ONLY.includes('h3')) {
    const wf = await p.evaluate(() => {
      app.graph.clear(); B.N = {};
      const { add, link } = { add: B.add.bind(B), link: B.link.bind(B) };
      add('unet', 'UNETLoader', [0, 0], 'MiniMax H3 (first/last frame to video with audio)', { unet_name: 'minimax_h3_fl2va_pruned_int8_convrot.safetensors', weight_dtype: 'default' }, [360, 82]);
      const spare = 'h3\\minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors';
      const m = B.loras('lr', 'unet', 400, 0, 'h3\\minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors', spare, 'MiniMax H3');
      add('clip', 'CLIPLoader', [0, 400], null, { clip_name: 'qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors', type: 'minimax' }, [360, 110]);
      add('vv', 'VAELoader', [0, 560], 'Video VAE', { vae_name: 'minimax_h3_video_vae_fp16.safetensors' }, [360, 60]);
      add('va', 'VAELoader', [0, 660], 'Audio VAE', { vae_name: 'minimax_h3_audio_vae_fp32.safetensors' }, [360, 60]);
      add('prompt', 'PrimitiveStringMultiline', [400, 400], 'Prompt (the same for every segment; describe the sound too)', { value: 'The camera slowly moves forward through the scene, steady and smooth. Audio: quiet ambient sound of the place.' }, [420, 180]);
      add('sched', 'BasicScheduler', [850, 0], 'Steps (8 with the turbo LoRA at 1; 20 without)', { scheduler: 'simple', steps: 8, denoise: 1 }, [330, 110]);
      link(m, 0, 'sched', 'model');
      add('sampler', 'KSamplerSelect', [850, 150], null, { sampler_name: 'res_multistep' }, [330, 60]);
      add('noise', 'RandomNoise', [850, 250], null, { noise_seed: 1, control_after_generate: 'randomize' }, [330, 82]);
      add('img', 'LoadImage', [0, 780], 'Start image', { image: 'example.png' }, [360, 330]);
      add('fit', 'ImageScaleToTotalPixels', [400, 800], "Fit to H3's size, keeping the shape (0.4 MP = 864x480; 0.98 = 1344x768)", { upscale_method: 'lanczos', megapixels: 0.4, resolution_steps: 32 }, [420, 110]);
      add('size', 'GetImageSize', [400, 950], null, {}, [220, 80]);
      link('img', 0, 'fit', 'image'); link('fit', 0, 'size', 'image');
      add('v0', 'CreateVideo', [400, 1060], 'The start image as a one-frame video', { fps: 24 }, [300, 80]);
      link('fit', 0, 'v0', 'images');
      add('start', 'StartLoop', [850, 400], 'Segments: how many times to run the prompt', { mode: 'simple' }, [330, 130]);
      B.N.start.widgets.find(w => w.name === 'mode.num_iterations').value = 3;
      link('v0', 0, 'start', 'initial_iteration_value');
      add('parts', 'GetVideoComponents', [850, 580], 'The video so far', {}, [330, 90]);
      link('start', 'current_iteration_value', 'parts', 'video');
      add('last', 'ImageFromBatch', [850, 720], 'Last frame so far: this segment starts from it', { batch_index: 4095, length: 1 }, [330, 90]);
      link('parts', 'images', 'last', 'image');
      add('i2v', 'MiniMaxH3ImageToVideo', [1220, 400], 'Segment length (frames, 17k+5; 124 = 5.2 s at 24 fps)', { length: 124 }, [380, 220]);
      link('clip', 0, 'i2v', 'clip'); link('vv', 0, 'i2v', 'vae'); link('prompt', 0, 'i2v', 'prompt');
      link('size', 'width', 'i2v', 'width'); link('size', 'height', 'i2v', 'height'); link('last', 0, 'i2v', 'first_frame');
      add('guide', 'BasicGuider', [1220, 0], null, {}, [260, 60]);
      link(m, 0, 'guide', 'model'); link('i2v', 'positive', 'guide', 'conditioning');
      add('samp', 'SamplerCustomAdvanced', [1220, 100], null, {}, [300, 120]);
      link('noise', 0, 'samp', 'noise'); link('guide', 0, 'samp', 'guider'); link('sampler', 0, 'samp', 'sampler'); link('sched', 0, 'samp', 'sigmas'); link('i2v', 1, 'samp', 'latent_image');
      add('dv', 'VAEDecode', [1640, 0], null, {}, [220, 50]); add('da', 'VAEDecodeAudio', [1640, 100], null, {}, [220, 50]);
      link('samp', 0, 'dv', 'samples'); link('vv', 0, 'dv', 'vae'); link('samp', 0, 'da', 'samples'); link('va', 0, 'da', 'vae');
      add('drop', 'ImageFromBatch', [1640, 220], 'The segment without its first frame (the start, already in)', { batch_index: 1, length: 4096 }, [330, 90]);
      link('dv', 0, 'drop', 'image');
      add('trim', 'TrimAudioDuration', [1640, 360], "Its sound without the first frame's 1/24 s", { start_index: 0.0417, duration: 100000 }, [330, 90]);
      link('da', 0, 'trim', 'audio');
      add('jv', 'ImageBatch', [2010, 220], 'All frames so far', {}, [300, 70]);
      link('parts', 'images', 'jv', 'image1'); link('drop', 0, 'jv', 'image2');
      add('ja', 'AudioConcat', [2010, 330], 'All sound so far', { direction: 'after' }, [300, 90]);
      link('parts', 'audio', 'ja', 'audio1'); link('trim', 0, 'ja', 'audio2');
      add('vid', 'CreateVideo', [2010, 460], null, { fps: 24 }, [300, 100]);
      link('jv', 0, 'vid', 'images'); link('ja', 0, 'vid', 'audio');
      add('end', 'EndLoop', [2010, 600], null, { accumulate: false }, [300, 100]);
      link('vid', 0, 'end', 'output_value'); link('vid', 0, 'end', 'next_iteration_value');
      add('save', 'SaveVideo', [2360, 400], null, { filename_prefix: 'video/minimax_h3_i2v_loop' }, [420, 420]);
      link('end', 'outputs', 'save', 'video');
      B.note([
        '## MiniMax H3 image to video with sound, in segments', '',
        "1. **Start image**: any shape. *Fit to H3's size* scales it to 0.4 MP (864x480 for 16:9) in its own aspect ratio, in steps of 32 px. The official size is 0.98 MP (1344x768): sharper, much slower.",
        '2. **Prompt**: used for every segment. H3 makes the sound too, so describe it.',
        '3. **Segments**: how many times the prompt runs. Each starts from the last frame of the one before; frames and sound are joined into one video at 24 fps.',
        '4. **LoRAs**: the first is the 8-step turbo LoRA (keep it at 1 with 8 steps, or set it to 0 and the steps to 20). The two spares are off at strength 0: pick a file and raise the strength to use one.', '',
        'Settings as in ComfyUI\'s own MiniMax H3 image-to-video template (res_multistep, simple schedule).',
      ].join('\n'), [-420, 0], [380, 620]);
      return app.graph.serialize();
    });
    fs.writeFileSync(OUT + 'minimax_h3_i2v_loop.json', JSON.stringify(wf, null, 1));
    await p.screenshot({ path: OUT + 'minimax_h3_i2v_loop.png' });
    results.h3 = await p.evaluate(() => B.test(() => {
      B.N.img.widgets.find(w => w.name === 'image').value = 'mass84_walk_first.png';
      B.N.start.widgets.find(w => w.name === 'mode.num_iterations').value = 2;
      B.N.i2v.widgets.find(w => w.name === 'length').value = 39;
      B.N.fit.widgets.find(w => w.name === 'megapixels').value = 0.25;
    }, 2400000));
    console.log('h3 test:', JSON.stringify(results.h3));
  }
  fs.writeFileSync(OUT + 'build_workflows_result.json', JSON.stringify(results, null, 1));
  await b.close();
})();
