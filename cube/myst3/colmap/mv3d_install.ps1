# MapAnything (Meta) and Depth Anything 3 (ByteDance Seed) in their own Python 3.12 environment, C:\myst3_out\mv3d\env,
# apart from ComfyUI's and the system Python's packages. torch is the same build as the system Python's (cu126).
#
#   powershell -ExecutionPolicy Bypass -File mv3d_install.ps1
#
# The weights come from Hugging Face on first use (facebook/map-anything, depth-anything/DA3-*), into the usual cache.
$R = 'C:\myst3_out\mv3d'; $E = "$R\env"; $P = "$E\Scripts\python.exe"
New-Item -ItemType Directory -Force "$R\src" | Out-Null
if (-not (Test-Path $P)) { & py -3.12 -m venv $E }
& $P -m pip install -q --upgrade pip 2>&1 | Select-Object -Last 2
"== torch " + (Get-Date -Format s)
# torch, torchvision and xformers as one matching set from the cu126 index: DA3 needs xformers, and xformers from PyPI
# would bring its own torch
& $P -m pip install -q torch torchvision xformers --index-url https://download.pytorch.org/whl/cu126 2>&1 | Select-Object -Last 3
foreach ($x in @(@('map-anything', 'https://github.com/facebookresearch/map-anything'),
                 @('Depth-Anything-3', 'https://github.com/ByteDance-Seed/Depth-Anything-3'))) {
  $d = "$R\src\$($x[0])"
  if (-not (Test-Path $d)) { git clone -q --depth 1 $x[1] $d 2>&1 | Select-Object -Last 2 }
  "== $($x[0]) at " + (git -C $d rev-parse --short HEAD) + ' ' + (Get-Date -Format s)
}
& $P -m pip install -q -e "$R\src\Depth-Anything-3" 2>&1 | Select-String -NotMatch 'WARNING|notice' | Select-Object -Last 5
& $P -m pip install -q -e "$R\src\map-anything" 2>&1 | Select-String -NotMatch 'WARNING|notice' | Select-Object -Last 5
"== check " + (Get-Date -Format s)
& $P -c "import torch, mapanything, depth_anything_3; print('torch', torch.__version__, 'cuda', torch.cuda.is_available()); from mapanything.models import MapAnything; from depth_anything_3.api import DepthAnything3; print('imports ok')" 2>&1 | Select-Object -Last 5
& $P -m pip list 2>$null | Select-String '^(torch|torchvision|xformers|mapanything|depth.anything|huggingface)'
"== done " + (Get-Date -Format s)
