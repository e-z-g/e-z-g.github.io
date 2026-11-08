# One COLMAP model of a room or age from solve_nodes.py's poses: the poses written
# as a model on a sparse run's database (build_model.py), points triangulated with
# the poses held, then bundle adjustment with every rotation held and only positions
# and points free, so the distances between nodes come from the 3D points.
#
#     powershell -ExecutionPolicy Bypass -File join_model.ps1 -Work C:\myst3_colmap\Amateria
#         [-Run run1] [-Solved solve_same] [-Tag joined] [-Rounds 1] [-Colmap C:\colmap\4.2.1\COLMAP.bat]
#
# -Rounds above 1 triangulates again from each adjusted model and adjusts again: starting
# positions that are far off triangulate few points, and the points found move the
# positions so that the next round finds more. Rounds go to tri1, ba1, tri2, ...; the
# last round's adjusted model is also copied to ba.
# Writes WORK\<Tag>\{init,tri,ba} (binary models), WORK\runs\<Tag>\sparse_txt\{init,tri,ba}
# (text, for evaluate_model.py WORK <Tag> ba) and logs in WORK\<Tag>\logs. Focal length,
# principal point, extra parameters and the faces' rotations in the rig are never refined.

param(
  [Parameter(Mandatory = $true)][string]$Work,
  [string]$Run = 'run1',
  [string]$Solved = 'solve_same',
  [string]$Tag = 'joined',
  [int]$Rounds = 1,
  [string]$Colmap = 'C:\colmap\4.2.1\COLMAP.bat'
)
$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$J = Join-Path $Work $Tag
$logs = Join-Path $J 'logs'
$db = Join-Path $Work "runs\$Run\database.db"
New-Item -ItemType Directory -Force $logs, "$J\tri", "$J\ba" | Out-Null

function Step([string]$name, [string]$line) {
  $t0 = Get-Date
  cmd /c "$line > `"$logs\$name.log`" 2>&1"
  $code = $LASTEXITCODE
  '{0,-20} exit {1}  {2:n0} s' -f $name, $code, ((Get-Date) - $t0).TotalSeconds
  if ($code -ne 0) { Get-Content "$logs\$name.log" -Tail 20; throw "$name failed" }
}

Step 'build_model' "py -3 `"$here\build_model.py`" `"$db`" `"$Work\$Solved\nodes_solved.json`" `"$J\init`""
$in = "$J\init"
for ($r = 1; $r -le $Rounds; $r++) {
  New-Item -ItemType Directory -Force "$J\tri$r", "$J\ba$r" | Out-Null
  Step "tri$r" "`"$Colmap`" point_triangulator --database_path `"$db`" --image_path `"$Work\images`" --input_path `"$in`" --output_path `"$J\tri$r`" --Mapper.ba_refine_focal_length 0 --Mapper.ba_refine_extra_params 0 --Mapper.ba_refine_sensor_from_rig 0"
  Step "ba$r" "`"$Colmap`" bundle_adjuster --input_path `"$J\tri$r`" --output_path `"$J\ba$r`" --BundleAdjustment.constant_rig_from_world_rotation 1 --BundleAdjustment.refine_focal_length 0 --BundleAdjustment.refine_principal_point 0 --BundleAdjustment.refine_extra_params 0 --BundleAdjustment.refine_sensor_from_rig 0"
  Step "analyzer$r" "`"$Colmap`" model_analyzer --path `"$J\ba$r`""
  Get-Content "$logs\analyzer$r.log" | Select-String 'Points:|reprojection'
  $in = "$J\ba$r"
}
Copy-Item -Force "$J\ba$Rounds\*" "$J\ba"
Copy-Item -Force "$J\tri1\*" "$J\tri"
foreach ($m in 'init', 'tri', 'ba') {
  $txt = Join-Path $Work "runs\$Tag\sparse_txt\$m"
  New-Item -ItemType Directory -Force $txt | Out-Null
  Step "txt-$m" "`"$Colmap`" model_converter --input_path `"$J\$m`" --output_path `"$txt`" --output_type TXT"
}
