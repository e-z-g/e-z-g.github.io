$env:PATH = "C:\Users\lloyd\AppData\Local\Microsoft\WinGet\Links;" + $env:PATH
$F = 'C:\myst3_out\film'; $O = "$F\wan84_flat720"
$p = 'The camera walking slowly and steadily forward along a wooden pier at dusk among strange fantasy buildings, smooth steady motion, the whole scene moving consistently, sharp detailed textures, no cuts, static lighting'
& py -3 C:\myst3_out\colmap\wan_flf.py "$F\ends84\first.png" "$F\ends84\last.png" $O --size 1280x720 --frames 81 --lightning --prompt $p --timeout 5000 2>&1 | Select-String -NotMatch 'WanFirstLastFrameToVideo inputs'
if (Test-Path "$O\walk.mp4") {
  & py -3 C:\myst3_out\colmap\walk_finish.py "$O\walk.mp4" "$F\ends84\first.png" "$F\ends84\last.png" "$O\walk_finished.mp4" --reverse "$O\walk_finished_back.mp4" 2>&1 | Select-String -NotMatch 'FutureWarning|warnings.warn|jit'
}
