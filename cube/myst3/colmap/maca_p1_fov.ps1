# MACA 1 to 2, the first pass alone (39 frames at -Size) with two fisheyes of -Fov degrees: 180 leaves no overlap, the
# two circles meeting exactly at their rims. Then the seam score and web copies.
param([int]$Seed = 2, [int]$Fov = 180, [string]$Size = '2560x1280')
$env:PATH = "C:\Users\lloyd\AppData\Local\Microsoft\WinGet\Links;" + $env:PATH
$F = 'C:\myst3_out\film'; $A = 'C:\myst3_colmap\Amateria'; $M = "$A\runs\joined_floor_map\sparse_txt\ba"; $C = 'C:\myst3_out\colmap'
$E = "$F\ends_combo_Amateria_1001_1002_fov$Fov"; $D = "$F\h3x39_Amateria_1001_1002_s$($Seed)_fov$Fov"
$o = @('--dual-fisheye', "$Fov", '--along-motion', '--fill-square', '--squash', '0.35')
& py -3 $C\walk_ends.py "$A\images" $M $E 1001 1002 --size 3328x1664 @o --prefix MA 2>&1 | Select-Object -Last 1
$P = "Two square fisheye views side by side, each a round fisheye stretched out to fill its square (straight lines bow outward toward the corners): the left looks straight ahead along the way the camera moves, the right looks straight back. The camera glides perfectly smoothly forward in a straight line into a stone tunnel, like a dolly on rails, with no walking, no bobbing, no swaying, no shake and no turning: in the left view everything grows outward from the centre, in the right everything shrinks into the centre. Ancient stone walls of hexagonal blocks, chains, red lacquered beams, a round lantern, no cuts, static lighting. Audio: a soft echoing breeze, no footsteps."
$t0 = Get-Date
& py -3 $C\h3_flf.py "$E\first.png" "$E\last.png" "$D\p1" --size $Size --frames 39 --steps 4 --turbo 'h3\minimax_h3_fl2v_turbo_4step_v1.0_768p_comfyui_bf16.safetensors' --seeds $Seed --timeout 5000 --prompt $P 2>&1 | Select-Object -Last 1
"h3: $([int]((Get-Date) - $t0).TotalSeconds) s"
"== done p1 fov$Fov " + (Get-Date -Format s)
