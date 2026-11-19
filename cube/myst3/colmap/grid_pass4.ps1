# A fourth pass for a walk in the two-fisheye layout (-Src: frames, 180, fill-square, squash 0.35): moved to the 5x3
# cube grid (cube_grid.py), H3 at -Denoise in one run of 39 frames between the clean node pictures moved the same
# way, then back to two fisheyes. ComfyUI only for the H3 step; the rest runs after it.
param([string]$Src, [string]$Out, [string]$Denoise = "0.25", [int]$Seed = 2, [string]$Size = '2560x1536', [string]$PromptFile = 'C:\myst3_out\maca_1001_1002_grid.txt')
$env:PATH = "C:\Users\lloyd\AppData\Local\Microsoft\WinGet\Links;" + $env:PATH
$C = 'C:\myst3_out\colmap'; $E = 'C:\myst3_out\film\ends_combo_Amateria_1001_1002_fov180'; $D = $Out
New-Item -ItemType Directory -Force $D | Out-Null
$L = @('--dual', '180', '--fill-square', '--squash', '0.35')
& py -3 $C\cube_grid.py to-grid "$E\first.png" "$D\first.png" --size $Size @L | Select-Object -Last 1
& py -3 $C\cube_grid.py to-grid "$E\last.png" "$D\last.png" --size $Size @L | Select-Object -Last 1
& py -3 $C\cube_grid.py to-grid $Src "$D\grid" --size $Size @L | Select-Object -Last 1
& ffmpeg -loglevel error -y -framerate 24 -i "$D\grid\%04d.png" -c:v libx264 -crf 6 -pix_fmt yuv444p "$D\init.mp4"
$P = (Get-Content -Raw -Encoding UTF8 $PromptFile).Trim()
$turbo = 'h3\minimax_h3_fl2v_turbo_4step_v1.0_768p_comfyui_bf16.safetensors'
& py -3 $C\h3_flf.py "$D\first.png" "$D\last.png" "$D\h3" --size $Size --frames 39 --steps 4 --turbo $turbo --seeds $Seed --init "$D\init.mp4" --denoise $Denoise --timeout 6000 --prompt $P 2>&1 | Select-Object -Last 12
"== done pass4 " + (Get-Date -Format s)
