# J'nanin as one mesh, as Amateria's age_v8 (6M triangles): Marigold material maps for every placed node, MoGe depth
# for every node (ComfyUI, through comfy_job.ps1), then fused with a dense cloud, the vertices' pictures and maps, and
# each node's shell.
#
#   jnanin_mesh.ps1                     the first build (13 November 2026): dense_joined2, into jnanin_v1
#   jnanin_mesh.ps1 -Model C:\myst3_colmap\Jnanin\video_jfly2\ba -Drop f1/LE-1086.jpg,... -DenseOut ...\dense_jfly
#                   -Out C:\myst3_out\scene_mesh\jnanin_v2 -From E:\myst3_archive\myst3_out\scene_mesh\jnanin_v1
#       a dense cloud made first from another model (the flyover's), with some images taken out of it, and the
#       nodes' maps and MoGe depth copied from an earlier build instead of made again
#
# The nodes' places and depth come from joined2_floor_map in every case; -Model must hold its nodes where they are.
param(
  [string]$Model = '',
  [string[]]$Drop = @(),
  [string]$DenseOut = 'C:\myst3_colmap\Jnanin\dense_joined2',
  [string]$Out = 'C:\myst3_out\scene_mesh\jnanin_v1',
  [string]$From = ''
)
# no 'Stop': COLMAP and Python write to stderr, which PowerShell 5.1 turns into errors
$W = 'C:\myst3_colmap\Jnanin'; $SP = "$W\runs\joined2_floor_map\sparse_txt\ba"; $S = $Out; $C = 'C:\myst3_out\colmap'
New-Item -ItemType Directory -Force $S | Out-Null
$nodes = (Get-Content "$SP\images.txt" | Select-String ' f1/LE-(\d+)\.jpg' | ForEach-Object { $_.Matches[0].Groups[1].Value })
"nodes: " + $nodes.Count

if ($Model) {
  $M = $Model
  if ($Drop.Count) {
    $M = "$DenseOut\model_in"; New-Item -ItemType Directory -Force $M | Out-Null
    $list = "$DenseOut\dropped.txt"
    [IO.File]::WriteAllLines($list, [string[]]$Drop)
    "== drop $($Drop.Count) images " + (Get-Date -Format s)
    & C:\colmap\4.2.1\COLMAP.bat image_deleter --input_path $Model --output_path $M --image_names_path $list 2>&1 |
      Select-String 'rror' | Select-Object -Last 3
  }
  "== dense " + (Get-Date -Format s)
  & powershell -ExecutionPolicy Bypass -File "$C\run_dense.ps1" -Images "$W\images" -Sparse $M -Out $DenseOut
  if ($LASTEXITCODE -ne 0) { throw 'dense failed' }
}

if ($From) {
  "== copy maps and moge from $From " + (Get-Date -Format s)
  foreach ($d in 'maps', 'moge') {
    robocopy "$From\$d" "$S\$d" /E /R:1 /W:1 /NP /NFL /NDL /NJH /NJS /MT:8 | Out-Null
    if ($LASTEXITCODE -ge 8) { throw "copy $d failed ($LASTEXITCODE)" }
  }
} else {
  "== materials " + (Get-Date -Format s)
  & py -3 "$C\materials.py" $W "$S\maps" --prefix LE --nodes @nodes 2>&1 | Select-String -NotMatch 'Warning|warn|RemoteException|^\s*$|\[A' | Select-Object -Last 3
  "== moge " + (Get-Date -Format s)
  & powershell -ExecutionPolicy Bypass -File C:\myst3_out\film\comfy_job.ps1 -Cmd "py -3 $C\scene_mesh.py $W $SP $S --prefix LE --nodes 1001 --near 200 --stage moge 2>&1 | Select-String -NotMatch 'Warning|warn' | Select-Object -Last 3"
}
"== fuse " + (Get-Date -Format s)
& py -3 "$C\scene_mesh.py" $W $SP $S --prefix LE --nodes 1001 --near 200 --stage fuse --far 10 --confirm-beyond 3 --dense "$DenseOut\fused.ply" --tile 12 --triangles 6000000 2>&1 | Select-String -NotMatch 'Warning|warn' | Select-String 'nodes:|anchored|triangles after|left out|unit'
"== attrs " + (Get-Date -Format s)
& py -3 "$C\scene_attrs.py" $W $SP $S "$S\maps" --prefix LE 2>&1 | Select-String -NotMatch 'Warning|warn' | Select-Object -Last 3
"== shells " + (Get-Date -Format s)
& py -3 "$C\scene_shells.py" $S --width 256 --prefix LE 2>&1 | Select-Object -Last 1
"== done " + (Get-Date -Format s)
