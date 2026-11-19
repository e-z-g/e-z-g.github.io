# Looser detail transfer on MACA 1-2 (seed 2, seam pass 240 deg at 0.3): more of the mid-walk frames get game detail.
param([string]$Opts = '--nearest --soft --fb 3', [string]$Tag = 'loose')
$env:PATH = "C:\Users\lloyd\AppData\Local\Microsoft\WinGet\Links;" + $env:PATH
$F = 'C:\myst3_out\film'; $C = 'C:\myst3_out\colmap'; $E = "$F\ends_combo_Amateria_1001_1002"
$D = "$F\h3combo_Amateria_1001_1002_s2"; $O = "$D\seampass_d30_f240_raw"; $X = "$D\seampass_d30_f240_$Tag"
& py -3 $C\detail_transfer.py $O "$E\first.png" "$E\last.png" $X $Opts.Split(' ') 2>&1 | Select-String 'trusted'
& py -3 $C\seam_score.py $X --dual 190 --fill-square --squash 0.35 2>&1 | Select-Object -Last 1
& ffmpeg -loglevel error -y -framerate 24 -i "$X\%04d.png" -c:v libx264 -preset slow -crf 16 -pix_fmt yuv420p "$X\web_fwd.mp4"
& ffmpeg -loglevel error -y -framerate 24 -i "$X\%04d.png" -vf reverse -c:v libx264 -preset slow -crf 16 -pix_fmt yuv420p "$X\web_back.mp4"
"== done dt $Tag " + (Get-Date -Format s)
