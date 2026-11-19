# After maca_43.ps1 (ComfyUI stopped): the seam band taken back, the game's detail, seam score, web copies at 24 fps.
param([int]$Seed = 2)
$env:PATH = "C:\Users\lloyd\AppData\Local\Microsoft\WinGet\Links;" + $env:PATH
$F = 'C:\myst3_out\film'; $C = 'C:\myst3_out\colmap'; $E = "$F\ends_combo_Amateria_1001_1002"; $D = "$F\h3x39_Amateria_1001_1002_s$Seed"
$L = @('--dual', '190', '--fill-square', '--squash', '0.35')
& py -3 $C\seam_pass.py back "$D\walk" "$D\sp" "$D\raw" @L --single-fov 240 2>&1 | Select-Object -Last 1
& py -3 $C\detail_transfer.py "$D\raw" "$E\first.png" "$E\last.png" "$D\dt" 2>&1 | Select-String 'frame (0|10|19|29|38):'
& py -3 $C\seam_score.py "$D\dt" @L 2>&1 | Select-Object -Last 1
foreach ($p in 'p1\frames_s2', 'walk', 'dt') {
  $n = $p.Split('\')[0]
  & ffmpeg -loglevel error -y -framerate 24 -i "$D\$p\%04d.png" -c:v libx264 -preset slow -crf 19 -pix_fmt yuv420p "$D\web_$($n)_fwd.mp4"
  & ffmpeg -loglevel error -y -framerate 24 -i "$D\$p\%04d.png" -vf reverse -c:v libx264 -preset slow -crf 19 -pix_fmt yuv420p "$D\web_$($n)_back.mp4" }
"== done post x39 " + (Get-Date -Format s)
