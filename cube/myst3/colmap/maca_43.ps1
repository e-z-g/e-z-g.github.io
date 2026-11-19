# MACA 1 to 2 at nearly twice the frame rate: 39 frames (H3 takes 17k + 5) at -Size, upscaled to 3328x1664 and
# drawn again by H3 at -Denoise in two runs of 22 frames (0-21 and 17-38, the second starting from the first's
# frame 17, crossfaded over the 5 frames in both by join_halves.py); then the seam pass (240-degree fisheye, 0.3) in the same two
# halves. ComfyUI only; maca_43_post.ps1 does the rest.
param([int]$Seed = 2, [double]$Denoise = 0.5, [string]$Size = '2560x1280')
$env:PATH = "C:\Users\lloyd\AppData\Local\Microsoft\WinGet\Links;" + $env:PATH
$F = 'C:\myst3_out\film'; $C = 'C:\myst3_out\colmap'; $E = "$F\ends_combo_Amateria_1001_1002"; $D = "$F\h3x39_Amateria_1001_1002_s$Seed"
$turbo = 'h3\minimax_h3_fl2v_turbo_4step_v1.0_768p_comfyui_bf16.safetensors'
$P = "Two square fisheye views side by side, each a round fisheye stretched out to fill its square (straight lines bow outward toward the corners): the left looks straight ahead along the way the camera moves, the right looks straight back. The camera glides perfectly smoothly forward in a straight line into a stone tunnel, like a dolly on rails, with no walking, no bobbing, no swaying, no shake and no turning: in the left view everything grows outward from the centre, in the right everything shrinks into the centre. Ancient stone walls of hexagonal blocks, chains, red lacquered beams, a round lantern, no cuts, static lighting. Audio: a soft echoing breeze, no footsteps."
$P1 = "One circular 240-degree fisheye view, black around it, looking straight ahead. The camera glides perfectly smoothly forward in a straight line, like a dolly on rails, with no walking, no bobbing, no swaying, no shake and no turning: everything grows outward from the centre. A stone tunnel through rock on a sunny island, red painted beams, no cuts, static lighting, one continuous picture. Audio: quiet wind, no footsteps."
function H3($first, $last, $out, $size, $frames, $prompt, $init, $dn) {
  $x = @(); if ($init) { $x = @('--init', $init, '--denoise', "$dn") }
  $t0 = Get-Date
  & py -3 $C\h3_flf.py $first $last $out --size $size --frames $frames --steps 4 --turbo $turbo --seeds $Seed --timeout 5000 --prompt $prompt @x 2>&1 | Select-Object -Last 1
  "  $([int]((Get-Date) - $t0).TotalSeconds) s" }
function Chunks($dir, $tag) {   # frames 0-21 and 17-38 of a folder as two near-lossless videos
  & ffmpeg -loglevel error -y -framerate 24 -start_number 0 -i "$dir\%04d.png" -frames:v 22 -c:v libx264 -crf 6 -pix_fmt yuv444p "$D\${tag}_a.mp4"
  & ffmpeg -loglevel error -y -framerate 24 -start_number 17 -i "$dir\%04d.png" -frames:v 22 -c:v libx264 -crf 6 -pix_fmt yuv444p "$D\${tag}_b.mp4" }
"pass 1, 39 frames at $Size"
if (-not (Test-Path "$D\p1\frames_s$Seed\0038.png")) { H3 "$E\first.png" "$E\last.png" "$D\p1" $Size 39 $P $null 0 }
New-Item -ItemType Directory -Force "$D\up" | Out-Null
& ffmpeg -loglevel error -y -i "$D\p1\frames_s$Seed\%04d.png" -vf scale=3328:1664:flags=lanczos -start_number 0 "$D\up\%04d.png"
Chunks "$D\up" up
"pass 2, first half"
H3 "$E\first.png" "$D\up\0021.png" "$D\p2a" '3328x1664' 22 $P "$D\up_a.mp4" $Denoise
"pass 2, second half"
H3 "$D\p2a\frames_s$Seed\0017.png" "$E\last.png" "$D\p2b" '3328x1664' 22 $P "$D\up_b.mp4" $Denoise
& py -3 $C\join_halves.py "$D\p2a\frames_s$Seed" "$D\p2b\frames_s$Seed" "$D\walk" --start 17
"seam pass"
$L = @('--dual', '190', '--fill-square', '--squash', '0.35', '--single-fov', '240')
& py -3 $C\seam_pass.py single "$D\walk" "$D\single" @L --size 2304 2>&1 | Select-Object -Last 1
Chunks "$D\single\frames" single
H3 "$D\single\first.png" "$D\single\frames\0021.png" "$D\spa" '2304x2304' 22 $P1 "$D\single_a.mp4" 0.3
H3 "$D\spa\frames_s$Seed\0017.png" "$D\single\last.png" "$D\spb" '2304x2304' 22 $P1 "$D\single_b.mp4" 0.3
& py -3 $C\join_halves.py "$D\spa\frames_s$Seed" "$D\spb\frames_s$Seed" "$D\sp" --start 17
"== done h3 x39 " + (Get-Date -Format s)
