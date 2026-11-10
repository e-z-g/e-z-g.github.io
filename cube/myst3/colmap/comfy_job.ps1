# Any job against this PC's own ComfyUI (C:\ComfyUI): started for it, stopped after it. -Cmd is run with PowerShell once it answers.
# It listens on 8189, never 8188: Comfy Desktop, which Sam uses, listens on 8188, and a job once ran on Desktop's server
# because this one could not take the port and Desktop's answered in its place. COMFY_SERVER tells the scripts the address.
# Only this job's own server is stopped afterwards: matching 'ComfyUI\main.py' also matched Desktop's server.
param([string]$Cmd)
$env:PATH = "C:\Users\lloyd\AppData\Local\Microsoft\WinGet\Links;" + $env:PATH
$env:PYTHONIOENCODING = 'utf-8'; $env:PYTHONUTF8 = '1'   # add-ons that print emoji fail to load when the log is in the old code page
$port = 8189
$env:COMFY_SERVER = "http://127.0.0.1:$port"
$log = "C:\myst3_out\film\comfyui_job.log"
if (Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue) { "Port $port is taken: another server is running there. Not starting."; exit 1 }
$p = Start-Process -FilePath py -ArgumentList '-3','C:\ComfyUI\main.py','--listen','127.0.0.1','--port',"$port" -WorkingDirectory C:\ComfyUI -RedirectStandardOutput $log -RedirectStandardError "$log.err" -PassThru -WindowStyle Hidden
try {
  $up = $false
  foreach ($i in 1..120) {
    if ($p.HasExited) { break }
    try { Invoke-WebRequest -UseBasicParsing "http://127.0.0.1:$port/system_stats" -TimeoutSec 2 | Out-Null; $up = $true; break } catch { Start-Sleep 2 }
  }
  if (-not $up) { "ComfyUI did not start"; Get-Content "$log.err" -Tail 20; exit 1 }
  Invoke-Expression $Cmd
} finally {
  # py.exe starts python.exe as a child: stop that child (C:\ComfyUI\main.py with this port), then py.exe itself
  Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -like '*C:\ComfyUI\main.py*' -and $_.CommandLine -like "*--port $port*" } | % { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
  Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue
}
