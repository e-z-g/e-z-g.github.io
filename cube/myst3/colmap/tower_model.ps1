# A sparse model of Amateria's tower (MATO) with MAIS 32 and 33 outside its door, so it can be
# set into the joined model by three shared nodes (MATO 2, MAIS 32, MAIS 33).
$W = 'C:\myst3_colmap\MATO'
$loose = '--Mapper.abs_pose_min_num_inliers 12 --Mapper.abs_pose_min_inlier_ratio 0.1 --Mapper.init_min_num_inliers 50 --Mapper.init_min_tri_angle 8 --Mapper.filter_min_tri_angle 0.5 --Mapper.ba_local_min_tri_angle 2 --Mapper.max_reg_trials 6'
Set-Location C:\myst3_out\colmap
py -3 prepare_colmap.py C:\myst3_out\faces C:\myst3_out\maps_repo\MATO.json C:\myst3_out\maps_repo\Amateria.json $W 2>&1 | Select-Object -Last 3
"pairs before: " + (Get-Content "$W\pairs.txt").Count
Get-Content "$W\pairs.txt" -TotalCount 2
foreach ($n in '0032', '0033') {
  foreach ($k in 1..6) { Copy-Item "C:\myst3_out\faces\MAIS\MAIS-$n-f$k.jpg" "$W\images\f$k\MAIS-$n.jpg" }
}
$extra = @()
foreach ($a in 1..6) { foreach ($b in 1..6) {
  $extra += "f$a/MATO-0002.jpg f$b/MAIS-0033.jpg"
  $extra += "f$a/MAIS-0033.jpg f$b/MAIS-0032.jpg"
} }
foreach ($n in 'MAIS-0032', 'MAIS-0033') { foreach ($a in 1..6) { foreach ($b in ($a + 1)..6) { if ($b -le 6) { $extra += "f$a/$n.jpg f$b/$n.jpg" } } } }
Add-Content "$W\pairs.txt" $extra
"pairs after: " + (Get-Content "$W\pairs.txt").Count
py -3 brighten_faces.py "$W\images" "$W\images_feat" 2>&1 | Select-Object -Last 1
powershell -ExecutionPolicy Bypass -File run_colmap.ps1 -Work $W -Tag run1 -FeatureImages images_feat -PeakThreshold 0.002 -MapperArgs $loose 2>&1 | Select-Object -Last 12
py -3 inspect_run.py $W run1 2>&1 | Select-Object -First 25
