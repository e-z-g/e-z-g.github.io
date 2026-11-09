# Register more of an age's movies into its model, one after another, each
# continuing the model and database the one before left.
#
#     powershell -ExecutionPolicy Bypass -File add_movies.ps1 -Work C:\myst3_colmap\Amateria
#         -Movies C:\myst3_out\movies\MASS\MASS-11090-0-t8.bik,... -Start video_lemt_nodesky
#         [-Params 455,320,180] [-Every 1] [-Colmap C:\colmap\4.2.1\COLMAP.bat]
#
# For each movie (tag: room and entry, lower case, as mass11090): video_frames.py
# takes its frames into WORK\images\<tag> (every -Every-th), sky_masks.py masks
# their sky, sea and water (WORK\masks\<tag>), and register_video.ps1 adds them
# to the model in WORK\<prev>\ba with the database WORK\<prev>\combined.db,
# the node frames held, the movie camera given by -Params (the flyover's,
# measured on LEMT 10912: 640x360, f 455), writing WORK\video_<tag>_chain.
# The first <prev> is -Start; the last one's model holds every movie. A movie
# whose registration fails is left out and the chain goes on from the one
# before. Prints each movie's frames registered.
param(
  [Parameter(Mandatory = $true)][string]$Work,
  [Parameter(Mandatory = $true)][string]$Movies,          # comma-separated: -File passes a list as one string
  [Parameter(Mandatory = $true)][string]$Start,
  [string]$Params = '455,320,180',
  [int]$Every = 1,
  [string]$Colmap = 'C:\colmap\4.2.1\COLMAP.bat'
)
$ErrorActionPreference = 'Continue'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$prev = $Start
foreach ($m in ($Movies -split ',')) {
  $base = [IO.Path]::GetFileNameWithoutExtension($m)            # MASS-11090-0-t8
  $p = $base.Split('-')
  $tag = ($p[0] + $p[1]).ToLower()
  $t0 = Get-Date
  "== $tag from $prev"
  & py -3 "$here\video_frames.py" $Work $m $tag --every $Every 2>&1 | Select-Object -Last 2
  & py -3 "$here\sky_masks.py" "$Work\images" "$Work\$tag\list.txt" "$Work\masks" 2>&1 | Select-Object -Last 1
  $out = "video_${tag}_chain"
  & powershell -ExecutionPolicy Bypass -File "$here\register_video.ps1" -Work $Work -Tag $tag -Out $out `
      -Database "$prev\combined.db" -Model "$prev\ba" -Mask -Params $Params -Colmap $Colmap 2>&1 |
      Select-String 'registered|Registered|exit [1-9]|failed'
  if (Test-Path "$Work\$out\ba\images.bin") { $prev = $out } else { "  $tag left out" }
  '  {0:n0} s' -f ((Get-Date) - $t0).TotalSeconds
}
"last model: $prev"
