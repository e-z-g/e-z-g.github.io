# Dense reconstruction from a finished sparse model of a Myst III room.
#
#     powershell -ExecutionPolicy Bypass -File run_dense.ps1 -Images C:\myst3_colmap\ENSI\images
#         -Sparse C:\myst3_colmap\ENSI\joined_1-27\ba -Out C:\myst3_colmap\ENSI\dense_1-27
#         [-Colmap C:\colmap\4.2.1\COLMAP.bat]
#
# Steps, each logged to OUT\logs\:
#   1. image_undistorter: the faces are exact pinhole views, so nothing is undistorted;
#      this only lays out the workspace patch_match_stereo expects.
#   2. patch_match_stereo on the GPU, with geometric consistency: a depth and normal map
#      per face. The original faces, not the brightened copies: the matching is
#      photometric, and the colours of the result come from here.
#   3. stereo_fusion: depths that agree across views fused into one coloured point cloud,
#      OUT\fused.ply.
#   4. poisson_mesher and delaunay_mesher: two meshes from it, for comparison.
# The six faces of a node share one centre, so they never see each other with any
# parallax; patch_match_stereo picks each face's sources from the sparse points, which
# favours faces of neighbouring nodes looking the same way.

param(
  [Parameter(Mandatory = $true)][string]$Images,
  [Parameter(Mandatory = $true)][string]$Sparse,
  [Parameter(Mandatory = $true)][string]$Out,
  [string]$Colmap = 'C:\colmap\4.2.1\COLMAP.bat'
)
$ErrorActionPreference = 'Stop'
$logs = Join-Path $Out 'logs'
New-Item -ItemType Directory -Force $Out, $logs | Out-Null

function Step([string]$name, [string[]]$colmapArgs) {
  $log = Join-Path $logs "$name.log"
  $t0 = Get-Date
  $line = '"' + $Colmap + '" ' + (($colmapArgs | ForEach-Object { if ($_ -match '\s') { '"' + $_ + '"' } else { $_ } }) -join ' ')
  cmd /c "$line > `"$log`" 2>&1"
  $code = $LASTEXITCODE
  '{0,-24} exit {1}  {2:n0} s' -f $name, $code, ((Get-Date) - $t0).TotalSeconds
  if ($code -ne 0) { Get-Content $log -Tail 20; throw "$name failed" }
}

Step '1-image_undistorter' @('image_undistorter', '--image_path', $Images, '--input_path', $Sparse,
  '--output_path', $Out, '--output_type', 'COLMAP')
Step '2-patch_match_stereo' @('patch_match_stereo', '--workspace_path', $Out, '--workspace_format', 'COLMAP',
  '--PatchMatchStereo.geom_consistency', 'true')
Step '3-stereo_fusion' @('stereo_fusion', '--workspace_path', $Out, '--workspace_format', 'COLMAP',
  '--input_type', 'geometric', '--output_path', (Join-Path $Out 'fused.ply'))
Step '4-poisson_mesher' @('poisson_mesher', '--input_path', (Join-Path $Out 'fused.ply'),
  '--output_path', (Join-Path $Out 'meshed-poisson.ply'))
Step '5-delaunay_mesher' @('delaunay_mesher', '--input_path', $Out, '--input_type', 'dense',
  '--output_path', (Join-Path $Out 'meshed-delaunay.ply'))
Get-ChildItem $Out -Filter *.ply | Select-Object Name, Length | Format-Table -AutoSize | Out-String
