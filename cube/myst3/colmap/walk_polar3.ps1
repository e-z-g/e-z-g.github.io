# One walk by the method settled on MACA 1 to 2 (19 November 2026), from the node pictures:
#   1. H3 in the polar layout (walk_ends.py --polar 20: equirectangular, poles ahead and behind), -Frames at 2560x1280;
#   2. polar_to_dual.py to two 180-degree fisheyes (fill-square, squash 0.35);
#   3. H3 again in the two-fisheye layout from that walk at -Denoise (0.5), between the clean two-fisheye node pictures;
#   4. pole_blend.py: the third pass kept whole within 55 degrees of straight ahead and behind, faded out by 75;
#   then the two-fisheye frames encoded for the viewer, forward and reversed.
# H3 steps run inside comfy_job.ps1; the rest after. Example (LEIS 62 to 78):
#   walk_polar3.ps1 -Age Jnanin -Model joined2_floor_map -Prefix LE -A 1062 -B 1078 -Tag leis_1062_1078
param([string]$Age, [string]$Model, [string]$Prefix, [string]$A, [string]$B, [string]$Tag, [int]$Frames = 39, [int]$Seed = 2,
      [string]$Denoise = "0.5", [string]$Step = 'all')
$env:PATH = "C:\Users\lloyd\AppData\Local\Microsoft\WinGet\Links;" + $env:PATH
$C = 'C:\myst3_out\colmap'; $F = 'C:\myst3_out\film'; $W = "C:\myst3_colmap\$Age"; $M = "$W\runs\$Model\sparse_txt\ba"
$D = "$F\walk3_$($Tag)_s$Seed"; $EP = "$D\ends_polar"; $ED = "$D\ends_dual"
$L = @('--dual', '180', '--fill-square', '--squash', '0.35')
$turbo = 'h3\minimax_h3_fl2v_turbo_4step_v1.0_768p_comfyui_bf16.safetensors'
New-Item -ItemType Directory -Force $D | Out-Null
if ($Step -in 'all', 'h3') {
  & py -3 $C\walk_ends.py "$W\images" $M $EP $A $B --size 2560x1280 --polar 20 --along-motion --prefix $Prefix 2>&1 | Select-Object -Last 1
  & py -3 $C\walk_ends.py "$W\images" $M $ED $A $B --size 2560x1280 --dual-fisheye 180 --along-motion --fill-square --squash 0.35 --prefix $Prefix 2>&1 | Select-Object -Last 1
  $P = (Get-Content -Raw -Encoding UTF8 "C:\myst3_out\prompts\$($Tag)_polar.txt").Trim()
  & py -3 $C\h3_flf.py "$EP\first.png" "$EP\last.png" "$D\p1" --size 2560x1280 --frames $Frames --steps 4 --turbo $turbo --seeds $Seed --timeout 5000 --prompt $P 2>&1 | Select-Object -Last 3
  & py -3 $C\polar_to_dual.py "$D\p1\frames_s$Seed" "$D\p1dual" --pad 20 --size 2560x1280 @L
  & ffmpeg -loglevel error -y -framerate 24 -i "$D\p1dual\%04d.png" -c:v libx264 -crf 6 -pix_fmt yuv444p "$D\p1dual.mp4"
  $P = (Get-Content -Raw -Encoding UTF8 "C:\myst3_out\prompts\$($Tag)_dual180.txt").Trim()
  & py -3 $C\h3_flf.py "$ED\first.png" "$ED\last.png" "$D\p3" --size 2560x1280 --frames $Frames --steps 4 --turbo $turbo --seeds $Seed --init "$D\p1dual.mp4" --denoise $Denoise --timeout 5000 --prompt $P 2>&1 | Select-Object -Last 3
  "== done h3 " + (Get-Date -Format s)
}
if ($Step -in 'all', 'post') {
  & py -3 $C\pole_blend.py "$D\p1dual" "$D\p3\frames_s$Seed" "$D\final" --fade 55 75 @L
  & py -3 $C\seam_score.py "$D\final" @L | Select-Object -Last 1
  & ffmpeg -loglevel error -y -framerate 24 -i "$D\final\%04d.png" -c:v libx264 -preset slow -crf 17 -pix_fmt yuv420p "$D\w_fwd.mp4"
  & ffmpeg -loglevel error -y -framerate 24 -i "$D\final\%04d.png" -vf reverse -c:v libx264 -preset slow -crf 17 -pix_fmt yuv420p "$D\w_back.mp4"
  "== done post " + (Get-Date -Format s)
}
