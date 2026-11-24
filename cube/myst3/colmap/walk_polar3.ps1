# One walk by the method settled on MACA 1 to 2 (19 November 2026), from the node pictures:
#   1. H3 in the polar layout (walk_ends.py --polar 20: equirectangular, poles ahead and behind), -Frames at -Size (2560x1280; 1792x896 for 73 frames on a 16 GB card);
#   2. polar_to_dual.py to two 180-degree fisheyes (fill-square, squash 0.35);
#   3. H3 again in the two-fisheye layout from that walk at -Denoise (0.3; 0.5 until 23 November 2026, which drew
#      things up to 60-120 px from pass 1, and the blend showed them twice), between the clean two-fisheye node pictures;
#   4. pole_blend.py: the third pass kept whole within 55 degrees of straight ahead and behind, faded out by 75;
#   then the two-fisheye frames encoded for the viewer, forward and reversed.
# H3 steps run inside comfy_job.ps1; the rest after. Example (LEIS 62 to 78):
#   walk_polar3.ps1 -Age Jnanin -Model joined2_floor_map -Prefix LE -A 1062 -B 1078 -Tag leis_1062_1078
# -Via "1081 1063 1062": one walk through these nodes on the way, each held at its share of the route's length
# (MiniMaxH3AddGuide), every node drawn with the orientation from A to B; with -Turn each node faces halfway
# between its step in and its step out (walk_ends.py --turn), so the view turns with the walk.
# -Mid 0.5 [-MidDepth "DIR_A DIR_B", default C:\myst3_out\route_depth\<Prefix><A> and <B>]: a picture from halfway, drawn from both nodes moved by their depth (walk_ends.py
# --mid), held at that frame in the first H3 pass only; the third pass is left free to clean up the drawing's faults.
# -Suffix _d03: appended to the walk's folder, so a pass 3 rerun (-Step p3, with p1 copied in) keeps the earlier one.
# -P1Frames 73 -P1Size 1792x896: pass 1 longer and smaller (prompt <Tag>_p<P1Frames>_polar.txt), its frames thinned to
# -Frames (evenly, ends kept) before polar_to_dual.py draws them at -Size for pass 3; more frames for the motion, pass 3 for the size.
# -JoinUp: the first pass's polar layout turned half a turn round the line of travel (walk_ends.py --polar-join up), the
# ground in the middle and the join straight up, so the floor underfoot is drawn in one piece (prompt <tag>_polar_jup.txt).
param([string]$Age, [string]$Model, [string]$Prefix, [string]$A, [string]$B, [string]$Tag, [int]$Frames = 39, [int]$Seed = 2,
      [string]$Denoise = "0.3", [string]$Step = 'all', [string]$Size = "2560x1280", [string]$Via = "", [string]$Sparse = "", [switch]$Turn, [switch]$Eight, [switch]$NoLora, [string]$Mid = "", [string]$MidDepth = "", [string]$Plan = "",
      [int]$P1Frames = 0, [string]$P1Size = "", [string]$Suffix = "", [switch]$JoinUp)
$env:PATH = "C:\Users\lloyd\AppData\Local\Microsoft\WinGet\Links;" + $env:PATH
$C = 'C:\myst3_out\colmap'; $F = 'C:\myst3_out\film'; $W = "C:\myst3_colmap\$Age"; $M = "$W\runs\$Model\sparse_txt\ba"; if ($Sparse) { $M = $Sparse }
$D = "$F\walk3_$($Tag)_s$Seed"; if ($Turn) { $D += "_turn" }; if ($Plan) { $D += "_plan" }; if ($Eight) { $D += "_8step" }; if ($NoLora) { $D += "_nolora" }; if ($Mid) { $D += "_mid" }; if ($P1Frames) { $D += "_p$P1Frames" }; if ($JoinUp) { $D += "_jup" }; if ($Suffix) { $D += $Suffix }; $EP = "$D\ends_polar"; $ED = "$D\ends_dual"
$L = @('--dual', '180', '--fill-square', '--squash', '0.35')
$J = @(); $PJ = @(); $PS = ''; if ($JoinUp) { $J = @('--polar-join', 'up'); $PJ = @('--join', 'up'); $PS = '_jup' }
$turbo = 'h3\minimax_h3_fl2v_turbo_4step_v1.0_768p_comfyui_bf16.safetensors'; $NS = 4; $TS = '1'
# -Eight: both H3 passes with the 8-step turbo LoRA at 8 steps
if ($Eight) { $turbo = 'h3\minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors'; $NS = 8 }
# -NoLora: the model alone, as h3_flf.py gives it (LoRA strength 0, 20 steps, no CFG)
if ($NoLora) { $TS = '0'; $NS = 20 }
New-Item -ItemType Directory -Force $D | Out-Null
$V = @(); if ($Via) { $V = @('--via') + $Via.Split(' ') }; if ($Turn) { $V += '--turn' }; if ($Plan) { $V += @('--plan', $Plan) }; if ($Mid) { if (-not $MidDepth) { $MidDepth = "C:\myst3_out\route_depth\$Prefix$A C:\myst3_out\route_depth\$Prefix$B" }; $V += @('--mid', $Mid, '--mid-depth') + $MidDepth.Split(' ') }
$F1 = $Frames; $S1 = $Size; $P1Tag = $Tag; if ($P1Frames) { $F1 = $P1Frames; $P1Tag = "$($Tag)_p$P1Frames" }; if ($P1Size) { $S1 = $P1Size }
function Guides($E, $N = $Frames) {
  if (-not $Via -and -not $Mid) { return @() }
  $r = Get-Content -Raw "$E\route.json" | ConvertFrom-Json; $g = @()
  for ($k = 1; $k -lt $r.share.Count - 1; $k++) { $g += @('--guide', "$E\via$k.png", [string][math]::Round($r.share[$k] * ($N - 1))) }
  return $g
}
if ($Step -eq 'ends') {
  & py -3 $C\walk_ends.py "$W\images" $M $EP $A $B --size $S1 --polar 20 @J --along-motion --prefix $Prefix @V 2>&1 | Select-Object -Last 8
  "guides: " + ((Guides $EP $F1) -join ' ')
}
if ($Step -in 'all', 'h3', 'p3') {                          # p3: pass 1 already in $D\p1, from pass 3 on
  if ($Step -ne 'p3') { & py -3 $C\walk_ends.py "$W\images" $M $EP $A $B --size $S1 --polar 20 @J --along-motion --prefix $Prefix @V 2>&1 | Select-Object -Last 1 }
  & py -3 $C\walk_ends.py "$W\images" $M $ED $A $B --size $Size --dual-fisheye 180 --along-motion --fill-square --squash 0.35 --prefix $Prefix @V 2>&1 | Select-Object -Last 1
  if ($Step -ne 'p3') {
    $P = (Get-Content -Raw -Encoding UTF8 "C:\myst3_out\prompts\$($P1Tag)_polar$PS.txt").Trim()
    & py -3 $C\h3_flf.py "$EP\first.png" "$EP\last.png" "$D\p1" --size $S1 --frames $F1 --steps $NS --turbo $turbo --turbo-strength $TS --seeds $Seed --timeout 5000 @(Guides $EP $F1) --prompt $P 2>&1 | Select-Object -Last 3
  }
  $P1 = "$D\p1\frames_s$Seed"
  if ($F1 -ne $Frames) {                                     # thinned evenly to -Frames, the ends kept
    $all = @(Get-ChildItem "$P1\*.png" | Sort-Object Name); $P1 = "$D\p1thin"; New-Item -ItemType Directory -Force $P1 | Out-Null
    for ($i = 0; $i -lt $Frames; $i++) { Copy-Item $all[[math]::Round($i * ($all.Count - 1) / ($Frames - 1))].FullName ("$P1\{0:D4}.png" -f $i) }
    "pass 1: $($all.Count) frames thinned to $Frames"
  }
  & py -3 $C\polar_to_dual.py $P1 "$D\p1dual" --pad 20 @PJ --size $Size @L
  & ffmpeg -loglevel error -y -framerate 24 -i "$D\p1dual\%04d.png" -c:v libx264 -crf 6 -pix_fmt yuv444p "$D\p1dual.mp4"
  $P = (Get-Content -Raw -Encoding UTF8 "C:\myst3_out\prompts\$($Tag)_dual180.txt").Trim()
  & py -3 $C\h3_flf.py "$ED\first.png" "$ED\last.png" "$D\p3" --size $Size --frames $Frames --steps $NS --turbo $turbo --turbo-strength $TS --seeds $Seed --init "$D\p1dual.mp4" --denoise $Denoise --timeout 5000 @(if ($Mid) { @() } else { Guides $ED }) --prompt $P 2>&1 | Select-Object -Last 3
  "== done h3 " + (Get-Date -Format s)
}
if ($Step -in 'all', 'post', 'p3') {
  & py -3 $C\pole_blend.py "$D\p1dual" "$D\p3\frames_s$Seed" "$D\final" --fade 55 75 @L
  & py -3 $C\seam_score.py "$D\final" @L | Select-Object -Last 1
  & ffmpeg -loglevel error -y -framerate 24 -i "$D\final\%04d.png" -c:v libx264 -preset slow -crf 17 -pix_fmt yuv420p "$D\w_fwd.mp4"
  & ffmpeg -loglevel error -y -framerate 24 -i "$D\final\%04d.png" -vf reverse -c:v libx264 -preset slow -crf 17 -pix_fmt yuv420p "$D\w_back.mp4"
  "== done post " + (Get-Date -Format s)
}
