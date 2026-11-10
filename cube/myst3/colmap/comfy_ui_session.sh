#!/bin/bash
# Runs a headless-browser script against this PC's own ComfyUI (C:\ComfyUI, port 8189) through an ssh tunnel on
# the Mac's port 8191: ComfyUI is started by comfy_job.ps1 and kept up until the script ends, then stopped.
# usage: comfy_ui_session.sh SCRIPT.js [SECONDS]
S="$1"; T="${2:-900}"; P=~/e-z-g-disassembly/reference/myst3/pc_scripts
K="-i $HOME/.ssh/cybear_ed25519 -o BatchMode=yes -o ConnectTimeout=10"
ssh $K lloyd@192.168.4.24 "Remove-Item C:\myst3_out\film\ui_done.flag -ErrorAction SilentlyContinue" 2>/dev/null
~/e-z-g-disassembly/tools/pc/pc_run.sh -t $((T + 120)) "powershell -ExecutionPolicy Bypass -File C:\myst3_out\film\comfy_job.ps1 -Cmd 'while (-not (Test-Path C:\myst3_out\film\ui_done.flag)) { Start-Sleep 3 }'" > $P/comfy_ui_session.log 2>&1 &
JOB=$!
for i in $(seq 1 60); do ssh $K lloyd@192.168.4.24 "try { (Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8189/system_stats -TimeoutSec 2).StatusCode } catch { 0 }" 2>/dev/null | grep -q 200 && break; sleep 3; done
ssh $K -N -L 8191:127.0.0.1:8189 lloyd@192.168.4.24 2>/dev/null &
TUN=$!
sleep 2
~/e-z-g-disassembly/tools/headless/run_page_test.sh -t $T "$S"; RC=$?
kill $TUN 2>/dev/null
ssh $K lloyd@192.168.4.24 "New-Item -ItemType File C:\myst3_out\film\ui_done.flag -Force | Out-Null" 2>/dev/null
wait $JOB
exit $RC
