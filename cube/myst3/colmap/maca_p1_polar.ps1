# MACA 1 to 2, the first pass (39 frames at -Size) drawn as walk_ends.py --polar: equirectangular with poles straight
# ahead (top) and behind (bottom), -Pad degrees repeated at each side; then polar_to_dual.py for the viewer.
param([int]$Seed = 2, [int]$Pad = 20, [string]$Size = '2560x1280', [string]$PromptFile = 'C:\myst3_out\maca_1001_1002_polar.txt')
$env:PATH = "C:\Users\lloyd\AppData\Local\Microsoft\WinGet\Links;" + $env:PATH
$F = 'C:\myst3_out\film'; $A = 'C:\myst3_colmap\Amateria'; $M = "$A\runs\joined_floor_map\sparse_txt\ba"; $C = 'C:\myst3_out\colmap'
$E = "$F\ends_polar$($Pad)_Amateria_1001_1002"; $D = "$F\h3x39_Amateria_1001_1002_s$($Seed)_polar$Pad"
& py -3 $C\walk_ends.py "$A\images" $M $E 1001 1002 --size $Size --polar $Pad --along-motion --prefix MA 2>&1 | Select-Object -Last 1
$P = (Get-Content -Raw -Encoding UTF8 $PromptFile).Trim()
$t0 = Get-Date
& py -3 $C\h3_flf.py "$E\first.png" "$E\last.png" "$D\p1" --size $Size --frames 39 --steps 4 --turbo 'h3\minimax_h3_fl2v_turbo_4step_v1.0_768p_comfyui_bf16.safetensors' --seeds $Seed --timeout 5000 --prompt $P 2>&1 | Select-Object -Last 12
"h3: $([int]((Get-Date) - $t0).TotalSeconds) s"
"== done p1 polar$Pad " + (Get-Date -Format s)
