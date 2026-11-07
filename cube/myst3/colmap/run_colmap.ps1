# Sparse reconstruction of one Myst III room laid out by prepare_colmap.py.
#
#     powershell -ExecutionPolicy Bypass -File run_colmap.ps1 C:\myst3_colmap\ENSI [C:\colmap\4.2.1\COLMAP.bat]
#
# Steps, each logged to <ROOM>\logs\<n>-<step>.log:
#   1. SIFT features on the GPU. PINHOLE 320 320 320 320, one camera per face folder
#      (a rig needs a camera per sensor; all six have the same, exact intrinsics).
#   2. rig_config.json: one rig of six faces about one centre, one frame per node.
#   3. Matching only the pairs in pairs.txt (linked nodes, and each node's own faces).
#   4. The incremental mapper with nothing about the cameras refined: focal length,
#      principal point and the faces' rotations within the rig are all exact.
#   5. model_analyzer on each model the mapper writes.
# Starts from an empty database each time.

param(
  [Parameter(Mandatory = $true)][string]$Work,
  [string]$Colmap = 'C:\colmap\4.2.1\COLMAP.bat'
)
$ErrorActionPreference = 'Stop'
$db = Join-Path $Work 'database.db'
$logs = Join-Path $Work 'logs'
$sparse = Join-Path $Work 'sparse'
New-Item -ItemType Directory -Force $logs | Out-Null
foreach ($p in @($db, "$db-shm", "$db-wal")) { if (Test-Path $p) { Remove-Item $p } }
if (Test-Path $sparse) { Remove-Item -Recurse -Force $sparse }
New-Item -ItemType Directory -Force $sparse | Out-Null

function Step([string]$name, [string[]]$colmapArgs) {
  $log = Join-Path $logs "$name.log"
  $t0 = Get-Date
  # COLMAP logs to stderr; cmd's redirection keeps PowerShell from treating that as an error.
  $line = '"' + $Colmap + '" ' + (($colmapArgs | ForEach-Object { if ($_ -match '\s') { '"' + $_ + '"' } else { $_ } }) -join ' ')
  cmd /c "$line > `"$log`" 2>&1"
  $code = $LASTEXITCODE
  '{0,-24} exit {1}  {2:n0} s' -f $name, $code, ((Get-Date) - $t0).TotalSeconds
  if ($code -ne 0) { Get-Content $log -Tail 20; throw "$name failed" }
}

Step '1-feature_extractor' @('feature_extractor', '--database_path', $db, '--image_path', (Join-Path $Work 'images'),
  '--ImageReader.camera_model', 'PINHOLE', '--ImageReader.camera_params', '320,320,320,320',
  '--ImageReader.single_camera_per_folder', '1', '--FeatureExtraction.use_gpu', '1')
Step '2-rig_configurator' @('rig_configurator', '--database_path', $db, '--rig_config_path', (Join-Path $Work 'rig_config.json'))
Step '3-matches_importer' @('matches_importer', '--database_path', $db, '--match_list_path', (Join-Path $Work 'pairs.txt'),
  '--match_type', 'pairs', '--FeatureMatching.use_gpu', '1')
Step '4-mapper' @('mapper', '--database_path', $db, '--image_path', (Join-Path $Work 'images'), '--output_path', $sparse,
  '--Mapper.ba_refine_focal_length', '0', '--Mapper.ba_refine_principal_point', '0',
  '--Mapper.ba_refine_extra_params', '0', '--Mapper.ba_refine_sensor_from_rig', '0')
foreach ($m in Get-ChildItem $sparse -Directory | Sort-Object Name) {
  Step "5-model_analyzer-$($m.Name)" @('model_analyzer', '--path', $m.FullName)
  Get-Content (Join-Path $logs "5-model_analyzer-$($m.Name).log") | Select-String -Pattern 'Rigs|Frames|Cameras|Images|Registered|Points|Observations|track length|reprojection' | ForEach-Object { '    ' + ($_.Line -replace '^.*\] ', '') }
}
