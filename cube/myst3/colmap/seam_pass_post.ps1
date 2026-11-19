# After seam_pass.ps1 (ComfyUI stopped): the band taken back into the walk as H3 made it, detail_transfer.py last,
# seam score, web copies.
param([string]$T = 'd30', [double]$Width = 12, [int]$SingleFov = 360, [string]$Src = 'h3combo_Amateria_1001_1002_s2')
$env:PATH = "C:\Users\lloyd\AppData\Local\Microsoft\WinGet\Links;" + $env:PATH
$F = 'C:\myst3_out\film'; $C = 'C:\myst3_out\colmap'; $E = "$F\ends_combo_Amateria_1001_1002"; $D = "$F\$Src"
$H = "$D\seampass_h3_$T"; $O = "$D\seampass_$($T)_raw"; $X = "$D\seampass_$($T)_dt"
$L = @('--dual', '190', '--fill-square', '--squash', '0.35')
& py -3 $C\seam_pass.py back "$D\frames_s2" "$H\frames_s2" $O @L --width $Width --single-fov $SingleFov 2>&1 | Select-Object -Last 1
& py -3 $C\detail_transfer.py $O "$E\first.png" "$E\last.png" $X 2>&1 | Select-String 'frame (0|10|21):'
& py -3 $C\seam_score.py $X @L 2>&1 | Select-Object -Last 1
& ffmpeg -loglevel error -y -framerate 24 -i "$X\%04d.png" -c:v libx264 -preset slow -crf 16 -pix_fmt yuv420p "$X\web_fwd.mp4"
& ffmpeg -loglevel error -y -framerate 24 -i "$X\%04d.png" -vf reverse -c:v libx264 -preset slow -crf 16 -pix_fmt yuv420p "$X\web_back.mp4"
"== done post $T " + (Get-Date -Format s)
