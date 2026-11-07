# Sparse reconstruction of one Myst III room laid out by prepare_colmap.py.
#
#     powershell -ExecutionPolicy Bypass -File run_colmap.ps1 -Work C:\myst3_colmap\ENSI [-Tag run1]
#         [-FeatureImages images_feat] [-PeakThreshold 0.00667] [-Mapper mapper|global_mapper]
#         [-MapperArgs '--Mapper.abs_pose_min_num_inliers 15'] [-Colmap C:\colmap\4.2.1\COLMAP.bat]
#
# Each run has its own database and output, <WORK>\runs\<Tag>\ (database.db,
# sparse\<n>\, logs\<n>-<step>.log), so runs can be compared side by side.
# Steps:
#   1. SIFT features on the GPU, from -FeatureImages (a folder of WORK with the same
#      names as images\, e.g. brightened copies; default the images themselves).
#      PINHOLE 320 320 320 320, one camera per face folder (a rig needs a camera per
#      sensor; all six have the same, exact intrinsics).
#   2. rig_config.json: one rig of six faces about one centre, one frame per node.
#   3. Matching only the pairs in pairs.txt (linked nodes, and each node's own faces).
#   4. The mapper (incremental by default, or global) with nothing about the cameras
#      refined: focal length, principal point and the faces' rotations within the rig
#      are all exact. -MapperArgs adds options, as one string split on spaces (an
#      array does not survive powershell -File). The mapper reads images\ itself, so the
#      points take their colours from the original faces.
#   5. model_analyzer on each model.

param(
  [Parameter(Mandatory = $true)][string]$Work,
  [string]$Tag = 'run',
  [string]$FeatureImages = 'images',
  [string]$PeakThreshold = '0.00667',
  [ValidateSet('mapper', 'global_mapper')][string]$Mapper = 'mapper',
  [string]$MapperArgs = '',
  [string]$Colmap = 'C:\colmap\4.2.1\COLMAP.bat'
)
$ErrorActionPreference = 'Stop'
$run = Join-Path $Work "runs\$Tag"
$db = Join-Path $run 'database.db'
$logs = Join-Path $run 'logs'
$sparse = Join-Path $run 'sparse'
if (Test-Path $run) { Remove-Item -Recurse -Force $run }
New-Item -ItemType Directory -Force $logs, $sparse | Out-Null
"tag $Tag  features from $FeatureImages  peak $PeakThreshold  $Mapper $MapperArgs" | Tee-Object (Join-Path $run 'settings.txt')
$extra = @($MapperArgs -split '\s+' | Where-Object { $_ })

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

Step '1-feature_extractor' @('feature_extractor', '--database_path', $db, '--image_path', (Join-Path $Work $FeatureImages),
  '--ImageReader.camera_model', 'PINHOLE', '--ImageReader.camera_params', '320,320,320,320',
  '--ImageReader.single_camera_per_folder', '1', '--FeatureExtraction.use_gpu', '1',
  '--SiftExtraction.peak_threshold', $PeakThreshold)
Step '2-rig_configurator' @('rig_configurator', '--database_path', $db, '--rig_config_path', (Join-Path $Work 'rig_config.json'))
Step '3-matches_importer' @('matches_importer', '--database_path', $db, '--match_list_path', (Join-Path $Work 'pairs.txt'),
  '--match_type', 'pairs', '--FeatureMatching.use_gpu', '1')
if ($Mapper -eq 'mapper') {
  $fixed = @('--Mapper.ba_refine_focal_length', '0', '--Mapper.ba_refine_principal_point', '0',
    '--Mapper.ba_refine_extra_params', '0', '--Mapper.ba_refine_sensor_from_rig', '0')
} else {
  $fixed = @('--GlobalMapper.ba_refine_focal_length', '0', '--GlobalMapper.ba_refine_principal_point', '0',
    '--GlobalMapper.ba_refine_extra_params', '0', '--GlobalMapper.refine_sensor_from_rig', '0')
}
Step '4-mapper' (@($Mapper, '--database_path', $db, '--image_path', (Join-Path $Work 'images'), '--output_path', $sparse) + $fixed + $extra)
foreach ($m in Get-ChildItem $sparse -Directory | Sort-Object Name) {
  Step "5-model_analyzer-$($m.Name)" @('model_analyzer', '--path', $m.FullName)
  Get-Content (Join-Path $logs "5-model_analyzer-$($m.Name).log") | Select-String -Pattern 'Registered frames|Registered images|Points:|reprojection' | ForEach-Object { '    ' + ($_.Line -replace '^.*\] ', '') }
}
