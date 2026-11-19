# Second H3 pass over MACA 1-2's seam (seed 2, 190 deg): the walk (with game detail) as one fisheye of -SingleFov
# degrees with the seam a ring inside it, sampled again at -Denoise from itself; the band round the seam taken back
# into the walk as H3 made it, then the game's detail carried on (detail_transfer.py) last; then scored.
param([double]$Denoise = 0.3, [int]$Size = 2304, [double]$Width = 12, [int]$SingleFov = 360,
      [string]$Src = 'h3combo_Amateria_1001_1002_s2', [switch]$NoH3)
$env:PATH = "C:\Users\lloyd\AppData\Local\Microsoft\WinGet\Links;" + $env:PATH
$F = 'C:\myst3_out\film'; $C = 'C:\myst3_out\colmap'; $E = "$F\ends_combo_Amateria_1001_1002"
$T = "d$([int]($Denoise * 100))$(if ($SingleFov -ne 360) { "_f$SingleFov" })"
$D = "$F\$Src"; $S = "$D\seampass_single$(if ($SingleFov -ne 360) { "_f$SingleFov" })"; $H = "$D\seampass_h3_$T"; $O = "$D\seampass_$($T)_raw"; $X = "$D\seampass_$($T)_dt"
$L = @('--dual', '190', '--fill-square', '--squash', '0.35', '--single-fov', "$SingleFov")
if (-not (Test-Path "$S\init.mp4")) { & py -3 $C\seam_pass.py single "$D\dt" $S @L --size $Size 2>&1 | Select-Object -Last 1 }
$view = if ($SingleFov -ge 360) { 'One circular 360-degree fisheye view, black around it: straight ahead in the middle, straight behind all round the rim.' } else { "One circular $SingleFov-degree fisheye view, black around it, looking straight ahead." }
$P = "$view The camera glides perfectly smoothly forward in a straight line, like a dolly on rails, with no walking, no bobbing, no swaying, no shake and no turning: everything grows outward from the centre. A stone tunnel through rock on a sunny island, red painted beams, no cuts, static lighting, one continuous picture. Audio: quiet wind, no footsteps."
if (-not $NoH3) {
  $t0 = Get-Date
  & py -3 $C\h3_flf.py "$S\first.png" "$S\last.png" $H --size "${Size}x${Size}" --frames 22 --steps 4 --init "$S\init.mp4" --denoise $Denoise --turbo 'h3\minimax_h3_fl2v_turbo_4step_v1.0_768p_comfyui_bf16.safetensors' --seeds 2 --timeout 5000 --prompt $P 2>&1 | Select-Object -Last 2
  "h3: $([int]((Get-Date) - $t0).TotalSeconds) s" }
"== h3 done $T " + (Get-Date -Format s)
