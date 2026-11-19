# The seam pass for a 39-frame two-fisheye walk (-Src: a folder of its frames, fisheyes of -Fov degrees): one
# 240-degree fisheye, H3 at 0.3 in two runs of 22 frames (0-21, 17-38; the second from the first's frame 17,
# crossfaded by join_halves.py). ComfyUI only; then seam_pass.py back runs outside it.
param([string]$Src, [string]$Out, [int]$Fov = 180, [int]$Seed = 2, [string]$PromptFile = 'C:\myst3_out\maca_1001_1002_single240.txt')
$env:PATH = "C:\Users\lloyd\AppData\Local\Microsoft\WinGet\Links;" + $env:PATH
$C = 'C:\myst3_out\colmap'; $D = $Out; New-Item -ItemType Directory -Force $D | Out-Null
$P = (Get-Content -Raw -Encoding UTF8 $PromptFile).Trim()
$L = @('--dual', "$Fov", '--fill-square', '--squash', '0.35', '--single-fov', '240')
& py -3 $C\seam_pass.py single $Src "$D\single" @L --size 2304 2>&1 | Select-Object -Last 1
& ffmpeg -loglevel error -y -framerate 24 -start_number 0 -i "$D\single\frames\%04d.png" -frames:v 22 -c:v libx264 -crf 6 -pix_fmt yuv444p "$D\a.mp4"
& ffmpeg -loglevel error -y -framerate 24 -start_number 17 -i "$D\single\frames\%04d.png" -frames:v 22 -c:v libx264 -crf 6 -pix_fmt yuv444p "$D\b.mp4"
$turbo = 'h3\minimax_h3_fl2v_turbo_4step_v1.0_768p_comfyui_bf16.safetensors'
& py -3 $C\h3_flf.py "$D\single\first.png" "$D\single\frames\0021.png" "$D\spa" --size 2304x2304 --frames 22 --steps 4 --turbo $turbo --seeds $Seed --init "$D\a.mp4" --denoise 0.3 --timeout 5000 --prompt $P 2>&1 | Select-Object -Last 1
& py -3 $C\h3_flf.py "$D\spa\frames_s$Seed\0017.png" "$D\single\last.png" "$D\spb" --size 2304x2304 --frames 22 --steps 4 --turbo $turbo --seeds $Seed --init "$D\b.mp4" --denoise 0.3 --timeout 5000 --prompt $P 2>&1 | Select-Object -Last 1
& py -3 $C\join_halves.py "$D\spa\frames_s$Seed" "$D\spb\frames_s$Seed" "$D\sp" --start 17
"== done seam pass 39 " + (Get-Date -Format s)
