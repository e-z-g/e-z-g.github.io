# A third pass for a walk drawn as walk_ends.py --polar and converted by polar_to_dual.py (-Dir\dual): H3 again in the
# two-circle layout (180, fill-square, squash 0.35) from that walk at -Denoise, between the clean two-circle ends, in
# one run of 39 frames; pole_blend.py then keeps it only round the circles' centres. ComfyUI only for the H3 step.
param([string]$Dir, [string]$Denoise = "0.5", [int]$Seed = 2, [string]$PromptFile = 'C:\myst3_out\maca_1001_1002_dual180.txt')
$env:PATH = "C:\Users\lloyd\AppData\Local\Microsoft\WinGet\Links;" + $env:PATH
$C = 'C:\myst3_out\colmap'; $E = 'C:\myst3_out\film\ends_combo_Amateria_1001_1002_fov180'; $D = "$Dir\pass3_d$($Denoise -replace '\.','')"
New-Item -ItemType Directory -Force $D | Out-Null
$P = (Get-Content -Raw -Encoding UTF8 $PromptFile).Trim()
& ffmpeg -loglevel error -y -framerate 24 -i "$Dir\dual\%04d.png" -c:v libx264 -crf 6 -pix_fmt yuv444p "$D\init.mp4"
$turbo = 'h3\minimax_h3_fl2v_turbo_4step_v1.0_768p_comfyui_bf16.safetensors'
& py -3 $C\h3_flf.py "$E\first.png" "$E\last.png" "$D\h3" --size 2560x1280 --frames 39 --steps 4 --turbo $turbo --seeds $Seed --init "$D\init.mp4" --denoise $Denoise --timeout 5000 --prompt $P 2>&1 | Select-Object -Last 12
"== done pass3 " + (Get-Date -Format s)
