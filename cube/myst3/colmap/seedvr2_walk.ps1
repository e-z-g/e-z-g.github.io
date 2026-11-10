$env:PATH = "C:\Users\lloyd\AppData\Local\Microsoft\WinGet\Links;" + $env:PATH
$A = 'C:\myst3_colmap\Amateria'; $F = 'C:\myst3_out\film'; $O = "$F\wan84_eq_seedvr2"
New-Item -ItemType Directory -Force $O | Out-Null
& py -3 C:\myst3_out\colmap\walk_ends.py "$A\images" "$A\runs\joined_floor_map\sparse_txt\ba" "$F\ends84_eq2560" 4084 4089 --size 2560x1280 --equirect 2>&1 | Select-String -NotMatch 'Warning'
& py -3 C:\myst3_out\colmap\seedvr2_run.py "$F\wan84_eq_light\walk_finished.mp4" "$O\up16.mp4" --every 4 --resolution 1280 2>&1
if (Test-Path "$O\up16.mp4") {
  & py -3 C:\myst3_out\colmap\walk_finish.py "$O\up16.mp4" "$F\ends84_eq2560\first.png" "$F\ends84_eq2560\last.png" "$O\walk_finished.mp4" --reverse "$O\walk_finished_back.mp4" 2>&1 | Select-String -NotMatch 'FutureWarning|warnings.warn|jit'
}
