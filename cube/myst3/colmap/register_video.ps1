# Register a movie's frames (video_frames.py) into a finished model of the same room or age.
#
#     powershell -ExecutionPolicy Bypass -File register_video.ps1 -Work C:\myst3_colmap\Amateria -Tag lemt
#         [-Run run1] [-Model joined_floor_map\ba] [-Out video_lemt] [-Mask] [-Colmap C:\colmap\4.2.1\COLMAP.bat]
#         [-Focal 550] [-CameraModel SIMPLE_PINHOLE] [-AloneOnly] [-FixFocal | -FreeAll]
#         [-Params 455,320,180]   (skip step 1 and use this camera)
#
# -Focal is the starting focal length in pixels for the movie's camera (a mapper
# left to guess from nothing settled on nonsense); the mapper refines it. -AloneOnly
# stops after step 1, to compare starting values. -FixFocal holds the focal length at
# -Focal in step 1 (any curvature term is still refined); -FreeAll also frees the
# principal point.
#
# 1. The movie alone, to measure its camera: features (on the brightened frames, as
#    for the faces), each frame matched with its next few (pairs_seq.txt), the mapper
#    with one camera (-CameraModel) for every frame, started at -Focal and refined.
#    WORK\<Tag>\alone_f<Focal>\, and the camera it found.
# 2. With the room: a copy of the run's database, the frames added with that camera
#    held fixed, matched in sequence and key frames against every node face
#    (pairs_all.txt), the incremental mapper continuing the finished model with its
#    frames held (fix_existing_frames), so it triangulates along the movie as it
#    registers (image_registrator alone only reached the frames that match node
#    faces directly). With -FinalBA, points triangulated again then bundle adjustment with all intrinsics and
#    rotations held (positions and points free), as join_model.ps1 does; on the
#    flyover that diverged (mean error 1e+200 px), so by default the mapper's result,
#    in which the node frames stay where they were, is the result.
# Writes WORK\<Out>\{reg,tri,ba} and text copies in WORK\runs\<Out>\sparse_txt\.

param(
  [Parameter(Mandatory = $true)][string]$Work,
  [Parameter(Mandatory = $true)][string]$Tag,
  [string]$Run = 'run1',
  [string]$Model = 'joined_floor_map\ba',
  [string]$Out = '',
  [switch]$Mask,
  [double]$Focal = 550,
  [string]$CameraModel = 'SIMPLE_PINHOLE',
  [switch]$AloneOnly,
  [switch]$FixFocal,
  [switch]$FreeAll,
  [switch]$FinalBA,
  [string]$Params = '',
  [string]$Colmap = 'C:\colmap\4.2.1\COLMAP.bat'
)
$ErrorActionPreference = 'Stop'
if (-not $Out) { $Out = "video_$Tag" }
$T = Join-Path $Work $Tag
$O = Join-Path $Work $Out
$logs = Join-Path $O 'logs'
New-Item -ItemType Directory -Force $logs, "$T\alone\sparse", "$O\reg", "$O\tri", "$O\ba" | Out-Null
function Step([string]$name, [string]$line) {
  $t0 = Get-Date
  cmd /c "$line > `"$logs\$name.log`" 2>&1"
  $code = $LASTEXITCODE
  '{0,-22} exit {1}  {2:n0} s' -f $name, $code, ((Get-Date) - $t0).TotalSeconds
  if ($code -ne 0) { Get-Content "$logs\$name.log" -Tail 20; throw "$name failed" }
}
$maskArg = if ($Mask) { "--ImageReader.mask_path `"$Work\masks`"" } else { '' }
$fixed = '--Mapper.ba_refine_focal_length 0 --Mapper.ba_refine_principal_point 0 --Mapper.ba_refine_extra_params 0 --Mapper.ba_refine_sensor_from_rig 0'

if ($Params) {
  $params = $Params; $cam = @('', $CameraModel)
  "movie camera given: $CameraModel $params"
} else {
  # 1. the movie alone
  $A = "$T\alone_$($CameraModel.ToLower())_f$([int]$Focal)$(if ($FixFocal) { '_fixed' } else { '' })"
  New-Item -ItemType Directory -Force "$A\sparse", "$A\txt" | Out-Null
  $vdb = "$A\video.db"
  if (Test-Path $vdb) { Remove-Item $vdb }
  $size = (Get-Content "$T\list.txt" -TotalCount 1)
  Add-Type -AssemblyName System.Drawing
  $im = [System.Drawing.Image]::FromFile((Join-Path "$Work\images" $size)); $cx = $im.Width / 2; $cy = $im.Height / 2; $im.Dispose()
  $start = if ($CameraModel -eq 'SIMPLE_RADIAL') { "$Focal,$cx,$cy,0" } elseif ($CameraModel -eq 'SIMPLE_PINHOLE') { "$Focal,$cx,$cy" } else { "$Focal,$Focal,$cx,$cy" }
  Step 'a1-features' "`"$Colmap`" feature_extractor --database_path `"$vdb`" --image_path `"$Work\images_feat`" --image_list_path `"$T\list.txt`" --ImageReader.camera_model $CameraModel --ImageReader.single_camera 1 --ImageReader.camera_params $start $maskArg --FeatureExtraction.use_gpu 1 --SiftExtraction.peak_threshold 0.002"
  Step 'a2-match' "`"$Colmap`" matches_importer --database_path `"$vdb`" --match_list_path `"$T\pairs_seq.txt`" --match_type pairs --FeatureMatching.use_gpu 1"
  $aloneOpts = if ($FixFocal) { '--Mapper.ba_refine_focal_length 0' } elseif ($FreeAll) { '--Mapper.ba_refine_principal_point 1' } else { '' }
  Step 'a3-mapper' "`"$Colmap`" mapper --database_path `"$vdb`" --image_path `"$Work\images`" --output_path `"$A\sparse`" --Mapper.multiple_models 0 $aloneOpts"
  Step 'a4-txt' "`"$Colmap`" model_converter --input_path `"$A\sparse\0`" --output_path `"$A\txt`" --output_type TXT"
  Step 'a5-analyzer' "`"$Colmap`" model_analyzer --path `"$A\sparse\0`""
  Get-Content "$logs\a5-analyzer.log" | Select-String 'Registered images|Points:|reprojection'
  $cam = (Get-Content "$A\txt\cameras.txt" | Where-Object { $_ -notmatch '^#' } | Select-Object -First 1).Split(' ')
  $params = ($cam[4..($cam.Length - 1)]) -join ','
  "movie camera: $($cam[1]) $($cam[2])x$($cam[3]) params $params"
  if ($AloneOnly) { return }

}
# 2. with the room
$db = "$O\combined.db"
Copy-Item -Force (Join-Path $Work "runs\$Run\database.db") $db
Step 'b1-features' "`"$Colmap`" feature_extractor --database_path `"$db`" --image_path `"$Work\images_feat`" --image_list_path `"$T\list.txt`" --ImageReader.camera_model $($cam[1]) --ImageReader.single_camera 1 --ImageReader.camera_params $params $maskArg --FeatureExtraction.use_gpu 1 --SiftExtraction.peak_threshold 0.002"
Step 'b2-match' "`"$Colmap`" matches_importer --database_path `"$db`" --match_list_path `"$T\pairs_all.txt`" --match_type pairs --FeatureMatching.use_gpu 1"
New-Item -ItemType Directory -Force "$O\reg" | Out-Null
Step 'b3-register' "`"$Colmap`" mapper --database_path `"$db`" --image_path `"$Work\images`" --input_path `"$Work\$Model`" --output_path `"$O\reg`" --Mapper.fix_existing_frames 1 $fixed --Mapper.abs_pose_min_num_inliers 15 --Mapper.multiple_models 0"
if ($FinalBA) {
  Step 'b4-tri' "`"$Colmap`" point_triangulator --database_path `"$db`" --image_path `"$Work\images`" --input_path `"$O\reg`" --output_path `"$O\tri`" $fixed"
  Step 'b5-ba' "`"$Colmap`" bundle_adjuster --input_path `"$O\tri`" --output_path `"$O\ba`" --BundleAdjustment.constant_rig_from_world_rotation 1 --BundleAdjustment.refine_focal_length 0 --BundleAdjustment.refine_principal_point 0 --BundleAdjustment.refine_extra_params 0 --BundleAdjustment.refine_sensor_from_rig 0"
} else {
  Copy-Item -Force "$O\reg\*" "$O\ba"                # the mapper's own result, nodes as they were
}
foreach ($m in 'reg', 'ba') {
  $txt = Join-Path $Work "runs\$Out\sparse_txt\$m"
  New-Item -ItemType Directory -Force $txt | Out-Null
  Step "txt-$m" "`"$Colmap`" model_converter --input_path `"$O\$m`" --output_path `"$txt`" --output_type TXT"
}
Step 'analyzer' "`"$Colmap`" model_analyzer --path `"$O\ba`""
Get-Content "$logs\analyzer.log" | Select-String 'Registered frames|Registered images|Points:|reprojection'
$n = (Get-Content "$Work\runs\$Out\sparse_txt\ba\images.txt" | Select-String " $Tag/").Count
"movie frames registered: $n of $((Get-Content "$T\list.txt").Count)"
