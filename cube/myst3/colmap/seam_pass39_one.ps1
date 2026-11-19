# The seam pass for a 39-frame two-fisheye walk in ONE H3 run (no halves, no crossfade), at -Size (1792) square:
# one 240-degree fisheye from the walk (-Src, fisheyes of -Fov degrees), H3 at -Denoise. ComfyUI only; then
# seam_pass.py back runs outside it (it takes the redraw at any size).
param([string]$Src, [string]$Out, [int]$Fov = 180, [int]$Seed = 2, [string]$Denoise = "0.8", [int]$Size = 1792, [string]$PromptFile = 'C:\myst3_out\maca_1001_1002_single240.txt')
$env:PATH = "C:\Users\lloyd\AppData\Local\Microsoft\WinGet\Links;" + $env:PATH
$C = 'C:\myst3_out\colmap'; $D = $Out; New-Item -ItemType Directory -Force $D | Out-Null
$P = (Get-Content -Raw -Encoding UTF8 $PromptFile).Trim()
$L = @('--dual', "$Fov", '--fill-square', '--squash', '0.35', '--single-fov', '240')
& py -3 $C\seam_pass.py single $Src "$D\single" @L --size $Size 2>&1 | Select-Object -Last 1
& ffmpeg -loglevel error -y -framerate 24 -start_number 0 -i "$D\single\frames\%04d.png" -c:v libx264 -crf 6 -pix_fmt yuv444p "$D\a.mp4"
$turbo = 'h3\minimax_h3_fl2v_turbo_4step_v1.0_768p_comfyui_bf16.safetensors'
& py -3 $C\h3_flf.py "$D\single\first.png" "$D\single\last.png" "$D\sp1" --size "$($Size)x$($Size)" --frames 39 --steps 4 --turbo $turbo --seeds $Seed --init "$D\a.mp4" --denoise $Denoise --timeout 7000 --prompt $P 2>&1 | Select-Object -Last 12
"== done seam pass 39 one run " + (Get-Date -Format s)
