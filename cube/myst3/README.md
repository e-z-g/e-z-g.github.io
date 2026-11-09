# `cube/myst3/` — Myst III node data and maps

Tools for getting real node data out of *Myst III: Exile*, the game the cube
viewer's ages come from, and maps of how its nodes connect. Nothing here is
served to the viewer; it is groundwork for walking an age node by node and for
3D reconstruction from the nodes' panoramas.

## How to build a layered node

A site node's *Layered* version is two cube maps: the node's faces with holes
cut at every step in the depth, and a backdrop showing what lay behind. Each
built node has a file in `layers/nodes/` holding every setting it was built
with and why it differs from the default; that file, not the notes below, is
the record.

1. **Faces.** `myst3_nodes.py` extracts them. The six go in the age's folder
   (`cube/<age>/`) as `<name>_orig.jpg`, in the order front, bottom, back,
   right, left, top.
2. **A 3D model with the node in it.** `colmap/prepare_age.py`, then
   `colmap/run_colmap.ps1 -Mask` on the PC (sky masked: matches on the sky
   pull nodes together), then `colmap/run_dense.ps1`; for one node of a
   sparse model, `colmap/node_stereo.py`. Check the model with
   `colmap/ghost_points.py` against nodes known to be right.
3. **Measured depth.** `colmap/node_depth.py` fits Depth Anything to the
   model's depths: `<name>_measured-depth.png` and `node_depth.json`.
4. **The node's file.** Copy `layers/nodes/mass84.json`, set the names and
   paths, and leave every setting at its default until a fault shows; when
   one is changed, say why in `why`.
5. **Build**, on the PC: `python layers/build_node.py layers/nodes/<node>.json`
   runs `colmap/sharpen_depth.py` (depth redrawn at 1280 px),
   `colmap/model_backdrop.py` (what other nodes saw behind the near objects)
   and `layers/build_layers.py` (holes, and LaMa for the backdrop no node
   saw), and prints the stitch command.
6. **Stitch** on the Mac with that command (`layers/stitch_layers.js`, through
   `stitcher.html`), copy the four atlases into the age's folder and add a
   `Layered` version with `backdropFullDepth: true` to the node's entry in
   `cube/index.html`.

| node | file | how its settings differ |
|---|---|---|
| Amateria MAWW 101 | `maww101.json` | not in the model; floor face keeps the nearest step |
| Amateria MASS 84 | `mass84.json` | backdrop from 20 nodes within 45°; nearest step throughout |
| Voltaic ENSI 16 | `ensi16.json` | backdrop colour test at 4, not 1.6 |
| J'nanin LEIS 77 | `leis77.json` | defaults; captured faces only |
| Voltaic ENCH grate | `ench-grate.json` | its own method, `grate_layers.py` (holes from the wire mesh's colour) |

**Known limits.** Depth Anything runs on each face alone, so neighbouring
faces disagree at their seams and are blended together over 48–96 px; the
seams are patched, not solved. Predicting each face padded with 20% of its
neighbours (`sharpen_depth.py --pad 0.2`, a wider perspective view) did not
settle them: the median step across the seams before blending went from 11.1%
to 9.5% on MAWW 101, 7.7% to 6.0% on ENSI 16 and 19.0% to 16.2% on LEIS 77, but
from 6.1% to 14.4% on MASS 84, and the fit to the measured depth got worse on
most faces. The default stays unpadded; a model made for panoramas is the next
thing to try. Laid out as one 5x3 grid instead (the walls in a row, the top
and bottom above and below each wall turned to meet it, as the stitcher's
atlas; `colmap/grid_depth_test.py`), Depth Anything V2 Large at 364 px a cell
did worse on MASS 84 than each face alone at the same size: seams before
blending 14.4% median and 35.8% at the 90th percentile against 6.9% and
19.6%, and 7.8% from the measured depth against 4.0%. The grid is no one
camera's picture; across it the network's scale drifts. The per-node settings are each a patch for one
node's fault; more neighbouring views in the model, which let
`model_backdrop.py` show what is really behind, are the way to fewer of them.

Everything below is the lab notebook, in the order the work was done.

## Where the data comes from

- **Faces** live in the game's `<ROOM>nodes.m3a` archives: one directory entry
  per node, listing its resources by face number (1–6) and type. Cube faces
  are stored as JPEG, so they come out byte for byte. The directory is
  XOR-obfuscated; `myst3_nodes.py` decodes it the way ScummVM's Myst III
  engine does (`engines/myst3/archive.cpp`). Faces 1–6 run front, bottom,
  back, right, left, top (confirmed on ENSI node 1: face 6 is the sky with
  the sun, face 2 the platforms seen from above).
- **Links** come from ScummVM's `myst3.dat`, its copy of the game's node
  scripts (`engines/myst3/database.cpp`). It is not in this repository; the
  scripts download it from `github.com/scummvm/scummvm`
  (`dists/engine-data/myst3.dat`). Every movement hotspot records the heading
  it sits at in its node.

**All nodes share one world orientation.** Over Voltaic's 186 two-way walks, a
walk A→B and its walk back differ by 180° ± 4° (median). ScummVM relies on
this too: entering a node, it keeps exactly the heading you clicked at. So a
hotspot's heading is the compass bearing from one node to the next, and for
reconstruction every node's rotation is already known.

## The scripts

| File | What it does |
|---|---|
| `myst3_nodes.py` | Extracts every node's faces from an installed game, named `<ROOM>-<node>-f<face>.jpg`, with an index CSV (room, node, face, size). Also writes each room's links (`maps/rooms/<ROOM>.json`) and a sketch map (`.svg`, every step drawn the same length). Standard library only. |
| `age_maps.py` | Lays out each whole age (`maps/ages/<Age>.json`). Needs numpy. |
| `draw_maps.py` | Draws both kinds of map as PNGs. Needs Pillow. |

```sh
python myst3_nodes.py "C:\GOG Games\Myst 3 Exile" out          # faces + room maps
python myst3_nodes.py maps/x --maps-only ENSI,ENCH --dat myst3.dat   # room maps only
python age_maps.py myst3.dat maps/ages
python draw_maps.py rooms maps/rooms maps
python draw_maps.py ages  maps/ages  maps
```

## What the first real extraction found

Run on the GOG release (7 November 2026): 27 room archives, **904 nodes,
every one with exactly faces 1–6, all 5,424 valid JPEGs**. `faces_index.csv`
is that run's index — metadata only; the images themselves stay out of this
repository.

- **The faces are the shipped files, byte for byte.** Faces extracted earlier
  with Riveal match entries here to the byte, which is also how the site's
  three nodes were identified:
  - Voltaic `ENCHnodes-277…282` is **ENCH node 93**, faces 1–6 in order;
  - Amateria `MAWWnodes-8…13` is **MAWW node 101** (faces 3–6 are
    byte-identical to node 1's: 101 is node 1 in another state);
  - J'nanin `LEIS661…666` is **LEIS node 77** (three faces shared with 177).
- **Nodes 100 and up are the same place in another state**, sharing every
  face that does not show the change.
- **Riveal's file numbers are not this CSV's running number** (ENCH 277 is
  running number 345, node 93's first face is the archive's 247th; MAWW 8 is
  68 and 7; LEIS 661 is 976 and 469). Riveal counts some resource types
  besides cube faces but not all. A Riveal file is mapped to its node by its
  byte size instead, or simply re-extracted with `myst3_nodes.py`.
- Archives and scripts list different node counts (ENSI 41 in the archive, 43
  scripted; LEIS 93 and 141): the scripts also cover close-ups and puzzle
  screens, which are not cube nodes.

## How the whole-age layout is solved

Positions are least-squares fits to the hotspot bearings, in two stages.

1. **Each room alone.** Walks pull towards one-unit steps along their bearing.
   Zips (clicking on a distant spot you can see) are bearings to farther
   nodes, and set how long the steps between them really are. A bearing alone
   can't tell ahead from behind, so a zip that comes out pointing backwards is
   required to point forwards and the room is solved again. A node and its
   ±100 variant (the same place in another state, linked by `changeNode`) are
   pinned together.
2. **Rooms as rigid blocks.** A move into another room is not always a bearing
   to where you arrive: its hotspot can be a door, a lift or a cart. Fitted
   all at once, such links contradicted each other (Voltaic's ENSI 35 → ENPP 1
   at 232°, the way back at 99°) and folded whole areas — ENSI's southern
   chain shrank from ~14 units to 2. So only cross-room links whose way there
   and way back agree within 20° of opposite place one room against another,
   and they move a room without reshaping it. A room with none is drawn apart.

The result fits the bearings to a median of 2–5° (90% within 9–16°).
Distances are in typical steps, not metres; there are no heights.

## The maps

- `maps/age-<Age>.png` — the whole-age maps: colour per room, black for the
  room-to-room links used, pink for zips.
- `maps/rooms-<Age>.png` — every room of an age as its own panel.
- `maps/rooms/index.html` — the room sketches as SVG.
- `maps/ages/*.json`, `maps/rooms/*.json` — the data, for later use (e.g. as
  starting positions for COLMAP).

## Preparing a room for COLMAP (`colmap/`)

The aim is a true 3D reconstruction of an age from its node panoramas, starting
with Voltaic's ENSI room. This part only lays the room out as COLMAP input and
checks the geometry; nothing has been reconstructed yet.

| File | What it does |
|---|---|
| `colmap/face_geometry.py` | Each face pixel's direction, each face's camera rotation, and a seam check that stitches a node's six faces (`check`, one node, optionally writing an equirectangular panorama; `room`, every node of a room). Needs numpy and Pillow for the checks. |
| `colmap/prepare_colmap.py` | Copies a room's faces into COLMAP's layout and writes `pairs.txt`, `rig_config.json` and `nodes.json`. Standard library only. |
| `colmap/heading_check.py` | Measures each link's direction of travel from the pictures (below). Needs opencv-python. |
| `colmap/run_colmap.ps1` | Runs the sparse reconstruction on the PC: features, rig, matching from `pairs.txt`, mapper, model statistics; logs in `<room>\logs\`. |
| `colmap/inspect_run.py` | After a run: which nodes each model holds, features per node, verified matches per linked pair. |
| `colmap/brighten_faces.py` | CLAHE-brightened copies of every face, for feature extraction only. Needs opencv-python. |
| `colmap/evaluate_model.py` | Checks a model against what it was never told: one shared rotation, the hotspot bearings, the age map; and, with `--compare`, against other models. Needs numpy. |
| `colmap/solve_nodes.py` | Every node's rotation and position from its links alone: a relative pose per link, rotation averaging, then positions from the directions. Modes: free rotation (default), `--upright` (yaw only), `--same-rotation`. Needs numpy, opencv-python. |
| `colmap/run_dense.ps1` | Dense reconstruction from a sparse model: workspace, depth maps (`patch_match_stereo`, geometric consistency), fused coloured points, Poisson and Delaunay meshes. |
| `colmap/render_cloud.py` | A fused cloud seen from above and from a node's own faces, beside the real faces, with the share of each face it covers. Needs numpy, Pillow. |
| `colmap/build_model.py` | Writes solved poses as a COLMAP text model on an existing database's frames, for `point_triangulator` and `bundle_adjuster`. |
| `colmap/prepare_age.py` | As `prepare_colmap.py` for a whole age: every room's nodes, numbered 1000 × (room's place in the age) + node, with the walks between rooms. |
| `colmap/turn_scan.py` | For each link, how many matches fit at every turn from −180° to +179°: whether two nodes face the same way. Needs numpy, opencv-python. |
| `colmap/join_model.ps1` | Solved poses to one COLMAP model: `build_model.py`, `point_triangulator`, `bundle_adjuster` with rotations held, text copies for `evaluate_model.py`. |
| `colmap/link_scales.py` | Step lengths from points that one node sees on two of its links, then positions (for nodes that face one way). Needs numpy, opencv-python. |
| `colmap/depth_fill.py` | Fills a dense cloud's gaps with Depth Anything V2's depth, fitted face by face to COLMAP's depth maps, sky masked (SegFormer), kept only where nearby nodes agree. Needs torch, transformers. |
| `m3a_list.py` | Lists every resource of a `<ROOM>nodes.m3a` (types, sizes, magic) and extracts any, such as the Bink movies. |
| `colmap/video_frames.py` | A movie's frames as extra views of a laid-out room or age: frames, brightened copies, sequential and key-frame x face pairs. Needs opencv-python and ffmpeg. |
| `colmap/register_video.ps1` | Measures a movie's camera from the movie alone, then continues a finished model with the frames (the mapper with the model's frames held). |
| `colmap/sharpen_depth.py` | A site node's measured depth redrawn at 1280 px from the node's faces (the game's 640 px ones, enlarged): Depth Anything V2 Large at an input of 1036 px, fitted to the measured depth away from its outlines, seams closed; outlines that follow the picture, for Amateria's *Layered* version. Needs torch, transformers, opencv-python. |
| `layers/build_node.py` | Builds a site node's Layered version from its file in `layers/nodes/` (every setting, and why it differs from the default): `colmap/sharpen_depth.py`, `colmap/model_backdrop.py`, `layers/build_layers.py`, then prints the `layers/stitch_layers.js` command. |
| `layers/build_layers.py` | The four slots' face images of a Layered version: holes on the far side of every depth step, the backdrop from `model_backdrop.py` where other nodes saw it and LaMa elsewhere. `--light` gives a lamp against the sky, which the measured depth calls sky, the depth of what holds it. Needs numpy, Pillow, opencv-python, torch. |
| `layers/grate_layers.py` | Voltaic's ENCH grate node, the one built its own way: holes from the wire mesh's colour, floor by push-pull. |
| `layers/stitch_layers.js` | The face images into four 3×2 atlases through `stitcher.html` (Playwright). |
| `colmap/node_consistency.py` | Which nodes of a model disagree with their neighbours: each node's depth-map points projected into its nearest nodes' depth maps, the share a neighbour sees past (or, with `--masks`, sky). Finds single misplaced nodes; misses runs of them, which agree with one another. Needs numpy, Pillow. |
| `colmap/node_resect.py` | Places nodes again from matches to a trusted model's points with their turns held (a line per match). Works where a node shares near scenery with the trusted nodes; Amateria's misplaced runs share almost none (matched with `runs/rematch`'s 154,008 extra pairs, they get 2–30 agreeing lines from one or two trusted nodes). Only near points count: far scenery puts every node on the trusted camera that saw it. |
| `colmap/node_align.py` | Fits a node's, or a run of nodes', own dense points onto the trusted nodes' (ICP, then the trusted faces' see-through test). Per node the search games the score by shrinking nodes; with `--runs` a run moves as one, with runs already in place as controls; a move is kept only if inliers rise and the scale is off its bound. |
| `colmap/apply_moves.py` | A copy of a dense workspace with nodes moved (from `node_resect.py`, or turned and scaled by `node_align.py --runs`) and their depth maps scaled, for `stereo_fusion` without stereo again. Made `dense_moved`. |
| `splat/splat_dataset.py` | A COLMAP text dataset for a Gaussian splat trainer (Brush): the faces of chosen nodes and movie frames, their poses, a ghost-free cloud as starting points. |
| `splat/pad_small.py` | Pads JPEGs under 20 KB with zero bytes after their end marker, which Brush 0.3.0 needs. |
| `splat/splat_render.py` | Renders a 3DGS `.ply` from COLMAP cameras beside the real images, with PSNR (torch, CUDA). |
| `splat/sky_dome.py` | Gives a splat trained with the sky masked its sky back: the masked pixels of every image as an all-round map, sampled as a shell of splats far away. |
| `splat/sky_floaters.py` | Takes out of a sky-masked splat the splats deep in the sky of several views above their horizon. |
| `splat/splat_reduce.py` | A display copy of a splat for a device that cannot load the whole: the splats that show most, without view-dependent colour. |
| `splat/serve_splat.py` | Serves splat files with the cross-origin and byte-range headers a web splat viewer needs, for a tunnel. |
| `colmap/tower_model.ps1` | A sparse model of Amateria's tower (MATO) with MAIS 32 and 33 beside its door, for setting it into the joined model. |
| `colmap/pano_depth.py` | A node's depth from one panoramic prediction (Depth Any Panoramas) over its six faces sewn together, fitted to the measured depth with one factor, beside the site's. |
| `colmap/seam_band_error.py` | A depth map's distance from the measured depth near the cube's edges and inside. |
| `colmap/ghost_points.py` | The points of a fused cloud that a set of trusted nodes see straight through (a farther depth, or sky), written out as a cloud, and for each node or movie the share of the points it helped make that are such ghosts (from `fused.ply.vis`). Needs numpy, Pillow. |
| `colmap/model_backdrop.py` | What is really behind a site node's near objects: the nearest nodes' dense depth maps projected into its faces, each pixel keeping the nearest point behind the foreground, for `build_layers.py --model-bg`; `--masks` leaves out what the neighbours' sky masks black out (sky, sea, water). Needs numpy, Pillow, opencv-python. |
| `colmap/filter_sky.py` | Takes sky out of a database and model whose node faces were matched before there were masks: drops verified matches with an end on `sky_masks.py`'s black, and model points seen mostly there. Needs numpy, Pillow. |
| `colmap/sky_masks.py` | Feature masks that leave out sky, sea and water (SegFormer, ADE20K), for movie frames: matches on the sky fix which way a picture looks but not where. Needs torch, transformers. |
| `colmap/node_stereo.py` | `patch_match_stereo` for one node's six faces and the images they share most points with, instead of every image. |
| `colmap/pair_points.py` | Depths in one face, up to scale, from its verified matches with one other face (essential matrix, triangulation): for a node no model places. Needs opencv-python. |
| `colmap/node_depth.py` | A node's six depth faces for the site's cube viewer: Depth Anything per face, scaled by one joint fit to what was measured (sparse points, stereo, a projected cloud or `pair_points.py`), the seams and the sky at infinity, seams blended, written as the viewer's disparity. Needs torch, transformers. |
| `colmap/static_mask.py` | A mask of what moves with the camera in a movie (pixels that barely change); empty for the ride. |
| `colmap/video_match_stats.py`, `seq_match_stats.py`, `node_points.py`, `set_camera.py` | Small checks: frame-to-face matches, frame-to-frame matches along a movie, points per node face, a fixed camera for trials. |
| `colmap/viewer/` | A browser viewer for a dense cloud and mesh (`index.html`, three.js), `export_viewer_data.py` to pack the data, `serve_viewer.py` to serve it locally or through a tunnel. No data is committed. |
| `colmap/ENSI/`, `colmap/Amateria/` | Pair lists, rig files, `nodes.json`, run summaries (no images). |

```sh
python colmap/prepare_colmap.py C:\myst3_out\faces maps\rooms\ENSI.json maps\ages\Voltaic.json C:\myst3_colmap\ENSI
python colmap/face_geometry.py room C:\myst3_out\faces\ENSI
```

### Where each face points, and the proof

ScummVM draws a node as a cube with face *i* (0–5) textured from the archive's
cube face *i*+1 (`engines/myst3/nodecube.cpp`) at the corners in
`Renderer::cubeVertices` (`engines/myst3/gfx.cpp`). Read from that table, with
*s*, *t* the image column and row as fractions (*t* down), a pixel looks along

| face | | direction (x right, y up, z back) |
|---|---|---|
| 1 | front | (2s−1, 1−2t, −1) |
| 2 | bottom | (1−2s, −1, 1−2t) |
| 3 | back | (1−2s, 1−2t, 1) |
| 4 | right | (1, 1−2t, 2s−1) |
| 5 | left | (−1, 1−2t, 1−2s) |
| 6 | top | (1−2s, 1, 2t−1) |

With *u* = *s* and *v* = 1 − *t* this is `faceUvToDir()` in `../atlas-layout.js`
term for term (viewer slots front 5, bottom 3, back 4, right 1, left 0, top 2).
The viewer's (−1, 1, 1) scale on its cube is undone inside its own
`gnomonicUV`, so `faceUvToDir` is in the game's frame and not mirrored. Two
checks back this up:

- **Every face's rotation has determinant +1.** A COLMAP camera's rotation has
  rows (right, down, forward); a mirrored mapping would make right × down point
  backwards, determinant −1. Seams alone could not show this, since a cube
  mirrored as a whole still joins up.
- **Every seam joins up.** For each of a node's 24 face edges, the check
  compares the colour step across the seam (edge pixel against the pixel one
  step beyond it, on the neighbouring face) with the step one pixel inside
  the face. Over all 41 ENSI nodes the seam adds at most 4.2 grey levels
  (median per node 0.0–0.9; no edge over 5). Swapping and mirroring left and
  right, as a test that the check can fail, gives up to 75. An
  equirectangular panorama of node 1 built this way is seamless, with a
  level horizon (checked by eye; not committed, being made from game images).

Each face is a 640×640 gnomonic view of exactly 90°, so the camera is
`PINHOLE 320 320 320 320` with no distortion, and the six faces of a node share
one centre. As `cam_from_rig` rotations with face 1 as the rig's reference
(quaternions w, x, y, z, as COLMAP's `rig_config.json` reads them): front
(1, 0, 0, 0), bottom (0, 0, ½√2, ½√2), back (0, 0, 1, 0), right
(½√2, 0, −½√2, 0), left (½√2, 0, ½√2, 0), top (0, 0, −½√2, ½√2).

### ENSI's input (7 November 2026)

- **41 nodes, 246 images.** Every node with faces is a base node (1–41); 107 is
  scripted but has no faces of its own.
- **Layout:** `images/f<face>/ENSI-<node>.jpg`. One folder per face because
  COLMAP's rig takes each sensor's images by folder prefix and groups a frame
  by the file name after it, so a node's six faces are its six files with the
  same name. COLMAP gives each sensor of a rig its own camera, so there are six
  cameras with identical PINHOLE settings rather than one shared camera.
- **48 linked node pairs** from 91 walk and 8 zip hotspots within the room
  (7 → 107 dropped as a node to its own variant; moves into other rooms left
  out). Every node is linked to at least one other.
- **2,343 image pairs:** 1,728 between linked nodes (all 36 face pairings of
  each) and 615 within nodes (15 each). The within-node pairs share a centre
  and barely overlap, so they can add no geometry; they are listed as asked and
  cost little.

### The plan (not run)

On the maintainer's PC (Windows 11, RTX 4060 Ti 16 GB): COLMAP 4.2.1 with CUDA
in `C:\colmap\4.2.1`, numpy and Pillow for Python 3.13.

1. `feature_extractor` with `ImageReader.camera_model PINHOLE`,
   `camera_params 320,320,320,320`, `single_camera_per_folder 1`, SIFT on the
   GPU (default 8,192 features).
2. `rig_configurator` with `rig_config.json`: one rig of six sensors, 41 frames.
3. `matches_importer --match_type pairs` with `pairs.txt` (GPU matching).
4. `mapper` with focal length, principal point and extra parameters fixed and
   `ba_refine_sensor_from_rig 0`, so the faces keep their exact rotations about
   one centre; the global mapper is the alternative to try if the incremental
   one breaks the room into pieces.

At this size the first three steps take a minute or two and mapping a few
minutes. The mapper still estimates each node's rotation; since every node in
fact shares one world orientation, the spread of the recovered rotations is a
check on the result, and they can be held equal afterwards.

### Which way headings turn (`colmap/heading_check.py`)

Settled both ways, 7 November 2026. **Heading *h* looks along (−sin *h*, 0,
cos *h*) in the cube frame above: 0 back, 90 left, 180 front, 270 right,
increasing clockwise seen from above** (turning right raises the heading).

- **From the code:** ScummVM's camera is the rotation 180 − heading about y
  (`Renderer::setupCameraPerspective`, `Matrix4(180 - heading, pitch, 0,
  EO_YXZ)`); ScummVM's matrices are stored row by row and `glLoadMatrixf`
  reads column by column, so OpenGL gets the transpose, and the camera's
  −z then points along (−sin *h*, 0, cos *h*).
- **From the pictures:** `heading_check.py` matches SIFT features between the
  two nodes of every walk and zip, and solves for the direction of travel
  with the rotation held at the identity (every node shares one orientation,
  so each match only has to satisfy t · (a × b) = 0). Over ENSI's 99 links the
  measured direction agrees with the hotspot heading to a median of 5.3° (90%
  within 40.5°) read this way, and 89.7° (169.9°) read mirrored.
  `colmap/ENSI/heading_check.txt` is the table.

The same table gives each step's climb, which the age maps lack: 1 → 10 drops
31°, 12 → 13 and 15 → 17 about 25°, 19 → 20 18°, and most walks are within
1° of level. The large misses are zips (distant views, few matches, and
12 ↔ 16 measures as nearly vertical) and links with only a handful of matches.

**A warning for the reconstruction:** nodes 27–41 match poorly. Their walks
find 4–18 consistent matches where the walks among nodes 1–26 find 33–1,240, so COLMAP may fail to join those nodes to the others; that is
where to look first if the room comes back in pieces.

## First sparse run on ENSI (7 November 2026)

`run_colmap.ps1` as written, on the PC: 4 s for features, 1 s matching, 2 s
mapping. `colmap/ENSI/run1.txt` has the details.

- **Two models, 24 of 41 nodes.** Model 0 holds nodes 1–18 (108 images,
  3,751 points), model 1 nodes 21–26 (36 images, 848 points); mean
  reprojection error 0.30 and 0.32 px. Not placed: 19, 20 and 27–41.
- **Nodes 27–41 are in a dark cave passage.** SIFT finds 1,000–5,000 features
  over their six faces against about 15,000 at the sunlit nodes, and seven of
  their links have no verified matches at all. That is the image content,
  not the layout.
- **Nodes 19 and 20 are not that case:** 374–412 verified matches with their
  neighbours, yet the mapper registered neither, and with them missing the
  two models have no shared node. The tail of the mapper's log is failed
  attempts to start further models ("bad initial pair", "no initial pair").

## Runs 2-4 on ENSI (7 November 2026)

Each run in `<room>\runs\<tag>\` on the PC; `colmap/ENSI/run2.txt` … `run4.txt`
have the settings, the models, matches per link and the evaluation.

| run | features | mapper | nodes placed | models |
|---|---|---|---|---|
| 1 | originals, default SIFT | incremental | 24 | 1–18; 21–26 |
| 2 | brightened, SIFT peak 0.002 | incremental | 25 | 1–18; 20–26 |
| 3 | as 2 | incremental, looser thresholds | 30 | 1–19; 19–27; 38–40 |
| 4 | as 2 | global | 40 | one model, all but 36 |

- **Brightening worked.** `brighten_faces.py` (CLAHE on every face) with the
  peak threshold at 0.002 gives 6,000–49,000 features per node instead of
  1,000–15,000, and every cave link now has verified matches (19–220; seven
  had none).
- **Run 3's looser thresholds** (`abs_pose_min_num_inliers 12`,
  `abs_pose_min_inlier_ratio 0.1`, `init_min_num_inliers 50`,
  `init_min_tri_angle 8`, `filter_min_tri_angle 0.5`, `ba_local_min_tri_angle 2`,
  `max_reg_trials 6`) bring in 19 and 27 and start a cave piece; node 19 is now
  in both large models, so they can be merged.
- **Run 4's single model is wrong, though its reprojection error is as low
  (0.34 px).** `evaluate_model.py` finds node rotations up to 67° apart where
  all should be equal, cave walks pointing up to 176° from their hotspots, a
  median 3.7 steps off the age map, and nodes 1–26 all at one height. The
  global mapper averages rotations from the matches and does not know they
  are equal; with the cave's few matches that goes wrong and drags the rest.
- **Run 3's models are right by every check:** rotations equal to 0.01° (model
  0) and 2.4° at worst (model 1), bearings within a median 5.0° and 4.2° of the
  hotspots, and the age map matched to a median 0.43 and 0.12 steps. They also
  give heights: nodes 1–9 and 16 level, 10–12 0.4 steps lower, 13–15 0.75,
  17–19 about 1.2 steps below the start (in map steps, one step being a typical
  walk).

The cave (28–41 except 38–40) is still out. What is left to try: merging
run 3's two large models through node 19 (`model_merger`); holding every
node's rotation at the known one, which COLMAP's mappers have no option for
but which makes the positions a linear problem given each link's direction
(as `heading_check.py` already measures); and the age map's positions as pose
priors.

## One model of nodes 1–27 (7 November 2026)

Run 3's two models could not be merged by COLMAP (`model_merger`: "Merge
failed"; they share one node). The cave was set aside for now (the
maintainer's call): its links are too poorly matched to measure.

**Do the nodes face the same way?** The maintainer's caution was that a node's
"forward" can differ from the next, sometimes by a lot, so this was measured
rather than assumed. For nodes 1–27 the turn between linked nodes is zero by
every measure: the five-unknown pose per link (`solve_nodes.py`) gives
0.0–1.6°, COLMAP's run 3 0.01°, and the two-way hotspot headings agree within
±18° (all of ENSI, except the zip 30–35 at −42°). In the cave, per-link turns
of 8–24° and two of 110° and 158° came from 12–23 matches each, too few to say
whether any cave node is really turned. The tools keep the question open per
room: `solve_nodes.py` solves rotations unless told not to, and
`evaluate_model.py` reports each node's departure from the common rotation.

Two things that did not work, for the record:

- **`--upright`** (each node a yaw alone, three unknowns per link) chose
  between a turn and the same turn plus 180° wrongly on several links
  (10–11, 15–17, 18–19, 21–22 came out at 176–180°). Counting points in front
  only where the two views differ by over 1° of parallax helped but did not
  settle it. Not used.
- **Positions from directions alone** (`--same-rotation`, which reuses
  `heading_check.py`'s solver and gets every link's sign right, in front 0.94–1.00)
  fit the hotspots (median 4.6°) and the age map (0.28 steps) well, but
  differ from COLMAP's models by 0.56 walk lengths. A direction says nothing of
  distance: around a loop the lengths are fixed, along a chain each step is
  set to the minimum. The weak zip 12 → 21 (22 matches, 0.59 in front) also
  had to be dropped (`--min-front 0.8`): kept, it outvoted the strong
  15 → 17 and bent the loop 12–21.

**What worked:** those solved poses written as a COLMAP model
(`build_model.py`) on run 3's database, `point_triangulator` with the poses
held, then `bundle_adjuster` with every rotation held
(`constant_rig_from_world_rotation 1`) and only positions and points free, so
the lengths come from the 3D points:

- **27 nodes in one model**, 9,422 points, 0.30 px mean reprojection error;
- rotations identical (held), hotspot bearings within a median 4.8°, the age
  map within a median 0.35 steps;
- **it agrees with run 3's two models to a median 0.015 and 0.018 walk lengths**
  (at most 0.03 and 0.07), which neither it nor they were fitted to;
- heights, in map steps above the lowest node: 1–9 and 16 at 1.75, 10–12 at
  1.39, 13–15 at 1.05, 17–19 0.6–0.7, 20–22 0.2–0.4, 23–26 at 0, 27 at 0.44.

`colmap/ENSI/joined_1-27_frames.txt` (with `_rigs.txt`) holds the final poses
in COLMAP's frame format; `solved_1-27_nodes.json` and `_relposes.json` the
solve before bundle adjustment; `joined_1-27.txt` the reports. The model itself,
with its points, stays on the PC (`C:\myst3_colmap\ENSI\joined_1-27\ba`), being
made from game images.

```powershell
py solve_nodes.py C:\myst3_colmap\ENSI --same-rotation --nodes 1-27 --out C:\myst3_colmap\ENSI\solve_same_1-27
py build_model.py C:\myst3_colmap\ENSI\runs\run3\database.db C:\myst3_colmap\ENSI\solve_same_1-27\nodes_solved.json J\init
COLMAP.bat point_triangulator --database_path ...\run3\database.db --image_path ...\images --input_path J\init --output_path J\tri
COLMAP.bat bundle_adjuster --input_path J\tri --output_path J\ba --BundleAdjustment.constant_rig_from_world_rotation 1
    (with focal length, principal point, extra parameters and sensor_from_rig not refined)
```

## Dense reconstruction of nodes 1–27 (7 November 2026)

`run_dense.ps1` on the joined model, with the original faces: about 20 minutes
on the RTX 4060 Ti, nearly all of it `patch_match_stereo` (149 of the 162
faces have sparse points to work from, about 3 s per face per pass, two
passes). Fusion gives **430,752 coloured points**; the Poisson mesh is 56 MB,
the Delaunay mesh 4 MB. All of it stays on the PC
(`C:\myst3_colmap\ENSI\dense_1-27\`), being made from game images;
`colmap/ENSI/dense_1-27.txt` has the numbers.

`render_cloud.py` draws the cloud from five nodes' own cameras (1, 8, 13, 19,
24) beside the real faces. It lines up: rocks, the stone tower, the water and
the far cliffs fall where they are in the pictures, in their colours (mean
difference 5–15 grey levels on walls facing the node). The cloud covers
20–58% of the side faces. What is missing is what should be: the sky, and each
node's own platform and the thin walkways and railings (bottom faces 1–10%
covered); a node's floor is seen from straight above only by that node, and
from its neighbours at a grazing angle. Not yet looked at: the two meshes.

A phone-sized viewer for it is in `colmap/viewer/` (orbit, the Delaunay mesh
coloured from the nearest points, and a button per node that puts the camera at
the node's centre). The packed data stays out of the repository, in
`e-z-g-disassembly/reference/myst3/dense_1-27/viewer_data/`; it was shown on the
maintainer's phone through a temporary `cloudflared` tunnel.

## Amateria as one age (7 November 2026)

`prepare_age.py` lays out all six rooms together: **147 nodes, 882 faces, 177
linked pairs**, 12 of them walks from one room into another (every one also in
the age map's `cross_used`). Every room's seams check out (median excess 0–1
grey level per node; the worst single edges, 5–19 levels, are one to three of a
node's twelve, where a wrong layout spoils most).

**Do Amateria's nodes face one way?** Not assumed this time; measured three ways:

- the free solve (`solve_nodes.py`): every link with hundreds to thousands of
  inliers turns 0.0–0.4°; the links that claim 4–180° all have 12–96 inliers
  among several hundred matches, and four of them have almost no points in
  front (the twisted pair);
- `turn_scan.py` on all 177 links: **168 peak at a turn of 0° (±2°)**; of the
  other nine, two are ties between 0° and ±180° and seven fit only 12–34
  matches anywhere, with no clear peak;
- held to one rotation, the hotspot headings agree with the solved directions to
  a median 4.6° (the free solve: 8.0°, 90% within 76°). A node turned by 180°
  would be 180° off on every hotspot.

A turn of exactly 180° often scores nearly as well as 0° in the scan (MALL
8–15: 1,015 against 1,007): points near the horizon fit any level turn. The
hotspots settle those.

**Positions are the hard part.** COLMAP's incremental mapper splits the age into
12 models (62 nodes in the largest). The zero-turn solve joined by
`join_model.ps1` holds 131 nodes, 8,376 points, 0.26 px, hotspots within a median
4.5°, and agrees with COLMAP's largest model to a median 0.10 walk lengths (at
most 0.67), but is 2.6 walk lengths off COLMAP's 13-node MACA model, and fits the
age map to a median 3.2 steps (room by room: MACA 0.36, MALL 0.22, MAIS 0.85 with
its steps 2.7 times longer, MASS 1.76). Repeating triangulation and adjustment
(`-Rounds 5`) diverged at the third round: nodes held by few points drift.

The cause is the scenery: nodes stand far apart over open water, so most matches
are distant (in MALL about 93% have under 1° of parallax), and few near points
are seen from three nodes in a row (MALL 4, 5 and 15 share 0–2 with their
neighbours). Nothing then ties one step's length to the next. `link_scales.py`
measures those ratios where points allow: 79 of 157 links join into one part;
the rest fall into 35 smaller ones.

### Step lengths from shared points, floors and the map

`link_scales.py` now takes each link's length from up to three sources at once:
**shared** points (above), the **floor** (a node stands at eye height above the
floor under it: the link's points that lie under a node give that node's height
in the link's units), and the **age map**'s distance between the two nodes as a
weak pull (log sigma 0.7) where nothing else measures.

The floor was tested first on Voltaic's ENSI, whose joined model is known to be
right. In its dense cloud, flat-platform nodes stand 0.546–0.565 steps above the
floor (within 2%), stairs and walkways 0.42–0.53. Measured from SIFT points
alone, 15 of 16 floor readings fall within 5% of the true height (median 1.01;
the walkway under node 20 at 0.74). On ENSI's 27 nodes, against the joined model:

| lengths from | nodes | median gap |
|---|---|---|
| shared points | 27 | 0.070 steps |
| floor only | 3 (only one chain of floor-measured links) | 0.005 |
| map only | 27 | 0.356 |
| shared + floor | 27 | 0.084 |

On Amateria, shared + floor + map places **131 nodes**; joined by
`join_model.ps1` (one round): 7,908 points, 0.30 px, hotspot bearings within a
median 4.9°, and **against COLMAP's own models that pass the checks**: the
62-node model (spanning MACA, MAIS and MASS) to a median 0.004 walk lengths (at
most 0.023) and MALL's 8-node model to 0.005. The first joined model had 0.098
against the 62-node one. COLMAP's models 3 (MACA), 4 (MAIS 6–11) and 2 are
themselves wrong: their nodes turn 20–49°, 22–25° and up to 23° from each other,
and their hotspot bearings are a median 110° and 107° off.

Room by room against the age map: MACA 0.35 steps, MALL 0.29, MAIS 0.78 (its
steps 2.7 times the others' per map step), MASS 1.68, turned 36° from the map.
The whole-age fit stays at 3.3 steps; as COLMAP's own three-room model agrees
with this one, the age map's layout between rooms (every walk one step) is
the likely cause. Three links still point the wrong way (MAIS 10→11, MACA
4→5, MAIS 19→3), in weakly measured loops.

`colmap/Amateria/` has the layout files, the turn scan, the solve reports and
`solved_floor_map_nodes.json`.

## Filling the gaps (7 November 2026)

Two ways, both alongside the dense runs.

**The pictures themselves, in the viewer.** What has no parallax (sky, sea, far
scenery) is exactly a node's six faces at infinity: standing at a node, the
viewer puts them round the camera behind the cloud (Backdrop). On Voltaic's
node 13 the rock's outline runs on from cloud into picture, and the tower and
water sit behind it in place. The floor right under a node is in its bottom face:
Floors lays each node's bottom face (its middle 60%) flat at the node's floor
height, measured from the dense points under it (21 of 27 Voltaic nodes, 43 of 62
in Amateria's 62-node model; the median for the rest). Some nodes stand on
platforms a lift has raised (the maintainer's reading: their floor patches
came out huge): the cloud lacks the platform, and the points below are the
ground far down. Where those lie more than 1.3 times the median eye height down,
the floor is laid at the median eye height instead: Voltaic's node 10 (3.0
times), and in Amateria MASS 5, 21, 22, 25, 43 and 46 (2.1–3.4 times), MAIS 31
(3.3), MATO 2 (2.8), and MAIS 7 and 18 just over the line (1.4, 1.3).

**Learned depth, scaled to COLMAP's (`depth_fill.py`).** Depth Anything V2 (Base)
on every face, its inverse depth fitted to COLMAP's geometric depth map for that
face, and used where COLMAP has none. Three things keep it honest:

- the fit is checked on half of COLMAP's depths it was not fitted to: Voltaic
  median 6.8% off, 90% within 36.5%; Amateria 9.9% and 51.3%;
- no fill beyond the depth range COLMAP measured on the face, and none on sky
  (SegFormer's ADE20K sky class; Amateria's dusk clouds otherwise get depths);
- each fill point is looked at from the faces of the 8 nearest other nodes and
  kept only if two of them see something at the same depth (within 10%), each
  from more than 3° away from the source node's ray, and no more of them see
  past it than support it. Without this the sky became flat sheets; with one
  supporting node and no angle rule, 53% of Voltaic's 3.4 million candidates
  were kept, 45% of Amateria's 6.2 million; with the rule as it now stands, 48%
  of Voltaic's and 28% of the 131-node Amateria model's 13.9 million.

Voltaic seen from its own nodes: side faces covered 45–80% instead of 20–45%,
colour differences mostly 6–18 as for COLMAP's own points (`render_cloud.py`).
The rocks, the sea and the tower fill in; each node's own platform stays poor
(its neighbours barely see it), which the floor patches cover. In Amateria the
pavilions, paths and walls fill in; nodes standing among near tracks and beams
(MASS 30) stay poor, as nothing near is reconstructed there. The viewer loads
the fill (thinned to about 550,000 points) behind its Fill button.
`colmap/ENSI/fill_1-27.txt` and `colmap/Amateria/fill_run1_0.txt` are the
per-face reports.

### Amateria's 131 nodes, dense (7 November 2026)

`run_dense.ps1` on the joined model (shared + floor + map lengths): 65 minutes
(541 of the 786 faces have sparse points to work from), **586,055 points**, a 9 MB
Delaunay and a 66 MB Poisson mesh. `depth_fill.py` adds 3.85 million points
(held-out error median 8.1%, 90% within 48.7%; `colmap/Amateria/fill_joined.txt`).
The viewer has the whole age and cuts of MACA, MAIS, MALL and MASS (each point
goes to the room of its nearest node). A broad band of points beside MALL that
looks like fill gone wrong is in COLMAP's own points too: a large surface seen
at a grazing angle.

## Movies as extra views (7 November 2026)

Every movie is inside the room archives (`m3a_list.py`; type 8 movie, 72
multitrack, all Bink `BIKi`, decoded with ffmpeg 9 on the PC). The flyovers
shown when an age's book is opened in J'nanin are in the J'nanin rooms that hold
the books: **LEMT 10912 is Amateria's** (15.3 s, 640×360, 15 fps, 229 frames),
LEET 10302 Voltaic's, LELT 10302 Edanna's. MATO 24007 is Amateria's ride seen
from inside the glass ball (143 s), not yet used.

**The flyover's camera** was measured from the movie alone (`register_video.ps1
-AloneOnly`): started at 600 px the mapper settles on a focal length of 455 px
(a 70° horizontal field of view); left free from 455 it ends at 457. **No lens
distortion**: with one radial term free it comes out at k = 0.003 (about 1 px at
the corners) and the error does not change (0.635 against 0.637 px). Left to
guess a focal length from nothing, the mapper started on nonsense and placed
3 frames; started too far off (300, 450, 800) it fails the same way.

**Into the 131-node model.** image_registrator alone placed only the 3 frames that
match node faces directly (the movie looks down from above; many of its matches
are the sun, sea and horizon, which say which way a frame looks but not where).
The incremental mapper continuing the model with its frames held
(`--Mapper.fix_existing_frames`) triangulates along the movie as it goes. With
every other frame, 85 of 115 registered; with **every frame, 227 of 229**, mean
error 0.61 px, 24,562 points instead of 8,248, about 4 minutes on the PC. The
path is smooth (median 0.24, at most 0.36 node spacings from frame to frame),
55 node spacings long, mostly 0.6 spacings above the nodes.

**It confirms the layout.** A bundle adjustment with the flyover in and every node
position free moves the nodes hardly at all: against COLMAP's sound 62-node
model the centres differ by a median 0.007 walk lengths (0.004 held), against
MALL's 0.006. Four more nodes were placed (MALL 17, MASS 57, MATO 7, MAWW 1)
but three of them see only 4–5 points, so their poses (MAWW 1 tilted 27°, MATO 7
turned 16°) are noise; MASS 57 sees 29 and comes out level and unturned.

### The ride (MATO 24007)

143 s, 2,145 frames at 640×360, from inside the glass ball. Nothing in the
picture is fixed to the camera (`static_mask.py` finds no still pixels: the cage
turns as the ball rolls, the scratches on the glass move), so no mask; matches
on the cage do not move like the scenery and fall out as outliers. Frame to frame
the ride matches well (median 225 verified matches to the next frame, over 400 in
long stretches) but breaks about 195 times in motion blur. Alone it falls into
31–42 pieces whatever the focal length (300–700 px all place 1,300–1,770 frames
at about 1 px): the ball spins more than it travels, which does not fix the focal
length. With the flyover's 455 px and the 131-node model continued (nodes held),
**1,316 frames registered** in 19 minutes; 229 of them, placed far outside the
age or off their neighbours in time by over a node spacing, were taken out
(`image_deleter`), leaving **1,087** on a smooth path (median 0.03, at most 0.93
node spacings a frame).

The ride also took in 11 more nodes (70–1,565 points each): MACA 26 and 36,
MALL 17, MASS 57, MAWW 1, 2 and 3, MATO 7, 10, 11 and 12, every one facing the
age's one orientation within 0.2°. The cleaned model (`video_ride\clean` on the
PC): 142 nodes, 44,936 points, 0.81 px; the original nodes as before (0.004 and
0.006 walk lengths from COLMAP's sound models).

**Their positions are wrong** (found the same day, making MAWW 1's depth). Eight
of the 11 lie within 0.15 node spacings of one another (MAWW 1, 2 and 3, MASS
57, MACA 26 and 36, MALL 17, MATO 7), though their faces show a pier, rock
columns, a lift cage and a tower: different places. Their points are on the
clouds (15–20 units away, the median node spacing being 1.59) and on the
horizon (3,600–5,600). The sky looks the same from everywhere in the age, so
matches on it fix which way a picture looks (hence the 0.2°) but not where it
was taken; the mapper put each node by the ride frames it matched, near ride
frame 190. MALL 17's 12 map steps from the age map came from this, not from the
map. The ride frames' own path is suspect for the same reason.

The fix tried: `sky_masks.py` (SegFormer's sky, sea and water, grown by 6
pixels) as feature masks for the ride's frames, so that no feature of theirs is
on the sky; the node faces keep their features, but a match needs both ends.
Of the ride's 2,145 frames the masks take a median 2.2% (10–90%: 0–49%); the
dark sea is mostly not recognised as water, so its reflections stay in.

With the masks the ride registers **226 of its 2,145 frames** (17,474 points,
0.58 px; `video_ride_nosky` on the PC) and places **none** of the 11 nodes: what
held them, and most of the 1,316 frames, was the sky. The movie frames are
640×360 and much of the ride is blurred or inside the cage, so with the sky gone
little matches the node faces.

### The flyover with the sky masked (MATO's lemt)

The flyover registered into that masked model with its frames masked the same
way: **191 of its 229 frames** on a smooth path (a median 0.25 node spacings a
frame, never over 0.37), and four more nodes, MAWW 1, MASS 57, MATO 7 and
MATO 10. Each of the four stood on 17–27 points of its face 4, all in the band
of cloud above the horizon, in two pairs 0.17 and 0.49 apart whose pictures
show a cockpit, rails over water, a rock island and a dome. The masks covered
only the movie frames; the node faces had been matched with one another long
before, and those matches still held cloud points.

`filter_sky.py` takes them out: sky masks for the 852 node faces too (a median
32.5% of a face, 44 faces over 95%), and in a copy of the database every
verified match with an end on the sky dropped (356,226 of 2,996,505), a pair
left under 15 deleted, and the model's 1,097 cloud points of 17,474 dropped.
An image of the model left with no pair at all crashed the mapper (exit
0xC0000409, nothing in the log), so such an image keeps its best pair
unfiltered (135 images, nearly all whole faces of sky; keeping only pairs
between two images of the model left 13 with none, and it crashed again).

Registered again (`video_lemt_nodesky`): **191 of 229 frames** (29,948
points, 0.66 px) and one node, **MASS 57**, now on 17 points of the rock
island on its face 4, 13 units away, seen at a median 28.5°: not sky, but all
in one patch about 100 px across, so its place is weakly held. It lies 7.3
units (4.3 spacings) from the nearest node.

### Dense with the movie frames (`dense_movies`)

`run_dense.ps1` on `video_lemt_nodesky`'s model (the 131 nodes, MASS 57, 226 ride
frames and 191 flyover frames, sky taken out): 1,209 images, `patch_match_stereo`
2 hours 0 minutes on the RTX 4060 Ti, fusion 39 s. **1,146,050 points**, against
586,055 from the nodes alone (`dense_joined`); a 12 MB Delaunay and a 148 MB
Poisson mesh. Packed for `colmap/viewer/` as `amateria-movies`; not yet compared
with `dense_joined` region by region.

A ghost of a tower's top stood beside the tower in this cloud and in
`dense_joined`, both on the 131-node model, but not in COLMAP's own 62-node
model. Fused from the node faces alone (468 k points) it stayed, so it is not
the movie frames. `node_consistency.py` projects each node's depth-map points
into its five nearest nodes' depth maps and counts the points a neighbour sees
past: a median 2.2% over the 131 nodes, but MACA 5 60%, MAIS 10 49% (few
points), MAIS 11 36%, MACA 6 35%, MACA 1 33% and MALL 18 32%, misplaced or
turned in the joined model. Fused without those six nodes' depth maps:
1,141,506 points (`amateria-movies-clean`).

The ghost stayed, smaller. The 62 nodes the two models share sit in the same
places in both (within 0.05 units, 1% of a node spacing, after a similarity
fit), so the ghosts come from the other 69 nodes. A run of misplaced nodes
agrees with itself, so the nearest-neighbour test misses it. `ghost_points.py`
tests each fused point against all 372 faces of the 62 nodes instead: a point
two or more of those faces see past (or see sky at, more than 8 px inside
`sky_masks.py`'s mask) and none agrees with is a ghost. In `dense_joined`,
12,389 of the 475,623 points those faces see are ghosts, and they come in
runs:

| nodes | share of the points they made that are ghosts |
|---|---|
| MALL 5–13 | 38–55% |
| MAIS 1–5 | 29–43% |
| MAIS 30–33, MATO 2 | 29–38% |
| MASS 7–12, 44 | 4–13% |
| MASS 82–90, MACA 37 | 3–6% |

against 0.0% for the 62 nodes themselves. These runs are in the rooms the
joined model fits worst (MAIS's steps 2.7 times the others', above). Fused
from the movie workspace without MALL 5–13, MAIS 1–5 and 30–33, MATO 2 and the
six nodes above: 1,074,211 points, of which 73,791 are still ghosts, 63,546 of
them made by the ride's frames (28.5% of the ride's points; the flyover's
2.0%). With those dropped: 1,000,420 points (`amateria-movies-noghost`). The
filter only reaches what the 62 nodes see; the runs themselves still need
placing again, not just leaving out.

Moving the runs. `node_resect.py` matched the 69 other nodes' faces against all
372 trusted faces (154,008 more pairs in a copy of the database) and placed each
node from the matches' rays through trusted 3D points. Far points only give a
direction (every ray passes through the trusted camera), and with near points
alone the runs have little support: only MASS 83, 89 and 90 were placed with
confidence (moved 0.4–0.65, depth x1.09). `node_align.py --runs` instead fits
each run's own dense points onto the trusted nodes' cloud by one similarity, and
scores it by the trusted faces' see-through test. Two runs already in place went
in as controls:

| run | inliers | seen past | shift, turn, scale | |
|---|---|---|---|---|
| MASS 82–90 | 16% → 53% | 39% → 6% | 0.64, 0.8°, 1.089 | moved |
| MAIS 30–33, MATO 2 | 6% → 29% | 59% → 9% | 2.72, 1.8°, 0.853 | moved |
| MAIS 1–5 | 4% → 15% | 65% → 11% | 2.22, 3.0°, 0.848 | moved |
| MAIS 6–10 | 2% → 1% | 62% → 14% | 6.40, 9.2°, 0.500 | left |
| MACA 1–13 | 0.3% → 1.3% | 45% → 7% | 5.34, 8.7°, 0.500 | left |
| MALL 4–16 | 0.9% → 0.0% | 87% → 71% | 8.69, 7.0°, 0.502 | left |
| MASS 7–12 (control) | 55% → 54% | 40% → 40% | 0.04, 0.4°, 0.997 | stays |
| MACA 14, 15, 38 (control) | 6% → 2% | 3% → 8% | 4.47, 8.7°, 0.502 | stays |

The second control shows how the score is gamed: a run shrunk to half puts more
of its points in front of what the trusted faces saw, so more "agree", while
fewer land on anything. A move is now kept only if the inliers rise too and the
scale is off its 0.5–2 bound; that leaves the first three. MASS 82–90's fit
agrees with `node_resect.py`'s separate estimate. `apply_moves.py` wrote
`dense_joined` with those 15 nodes moved (cameras turned by the run's turn,
depth maps multiplied by its scale) as `dense_moved`; fused, 573,790 points, and
the ghosts fall from 12,389 to 4,808. The moved runs' own share falls to under
1% (MAIS 30–33 from 30–38%, MAIS 1–5 from 29–43%, MASS 82–90 from 3–6%). The
tower's diagonal ghost is gone. What is left is MALL 4–13 (38–55%, unchanged),
MASS 7–12 and 44 (4–13%) and MAIS 6–8 (4%). Packed for `colmap/viewer/` as
`amateria-moved`.

The same moves applied to the movie workspace (`dense_movies_moved`), fused
without the nodes still misplaced (MACA 1, 5 and 6, MAIS 10 and 11, MALL 5–13
and 18): 1,095,589 points, of which 77,225 are ghosts, 68,582 of them made by
the ride's frames (30.4% of the ride's points). The moved runs' own share is
under 1.1%. With the ghosts dropped: 1,018,364 points
(`amateria-movies-moved`), against 1,000,420 without the three runs. The
ride's frames are now the main source of ghosts.

## A Gaussian splat of Amateria (8 November 2026)

`splat/splat_dataset.py` writes a COLMAP text dataset for a splat trainer from
`dense_movies_moved`: the six faces of the 62 trusted and 15 moved nodes and
the flyover's 191 frames (653 images; the ride's frames and the nodes still
misplaced left out), poses from the moved model, and as starting points the
ghost-free cloud thinned to one per 0.04-unit cell (549,082). Trained with
Brush 0.3.0 on the PC (its Windows build; WebGPU, no CUDA build needed), 30,000
steps, every 30th image held out. Brush 0.3.0 reads the first 16,387 bytes of
each image with an exact-length read, so smaller JPEGs (14 sky faces) fail with
"early eof"; `splat/pad_small.py` pads them past their end marker. The first run
stopped without an error at step 10,000 while the GPU was shared with
`node_align.py` and a render; it was resumed from that export (as `init.ply`,
`--start-iter 10000`) with the GPU to itself, 40 minutes to step 30,000:
7,042,375 splats, spherical harmonics to degree 3, a 1.6 GB `.ply` (on the PC,
`C:\myst3_out\splat\amateria_final.ply`).

`splat/splat_render.py` renders a splat from the dataset's cameras beside the
real image. Five held-out images and one trained one, PSNR at step 5,000 and
30,000 (512 px; the numbers first given were from a renderer that summed the
log transparency in single precision, which spoiled the lower rows of a render,
by up to a dB here; these are from the corrected one):

| image | 5,000 | 30,000 |
|---|---|---|
| MASS 35 face 1 (held out) | 22.1 | 22.9 |
| MASS 31 face 3 (held out) | 16.6 | 17.9 |
| MACA 41 face 4 (held out) | 18.6 | 19.5 |
| MAIS 29 face 1 (held out) | 16.2 | 16.9 |
| flyover frame 145 (held out) | 23.2 | 23.9 |
| MASS 84 face 1 (trained) | 19.7 | 21.3 |

The structure holds in every view (the poses agree): the MASS 84 door, the
MACA 41 tower, the MAIS 29 floor tiles and pillars. The sky is wrong in all of
them, blotchy or tinted, and most of the error: it has no depth, so the splat
puts it at a finite distance that only the trained views agree with. Things
under roofs that few views see (MASS 31, 35) stay soft.

### The sky

Three ways were tried, with the same 30,000 steps and the same six views (PSNR,
dB; MASS 35, MASS 31, MACA 41, MAIS 29, flyover frame 145, MASS 84):

| sky | 35 | 31 | 41 | 29 | 145 | 84 | mean |
|---|---|---|---|---|---|---|---|
| trained in, as above | 22.9 | 17.9 | 19.5 | 16.9 | 23.9 | 21.3 | 20.4 |
| masked (`--masks`), a sky shell added | 19.6 | 18.0 | 23.1 | 18.9 | 24.4 | 23.4 | 21.2 |
| transparent (`--alpha`), a sky shell added | 18.0 | 17.0 | 22.6 | 23.0 | 24.3 | 21.7 | 21.1 |
| masked, shell, floaters taken out | 18.7 | 18.0 | 21.6 | 22.9 | 26.4 | 22.9 | 21.8 |

`splat/sky_dome.py` gives a splat trained without the sky its sky back: every
image's masked pixels, as world directions, averaged into an equirectangular
map, and 400,000 opaque splats on a sphere 1,000 units out sampled from it, so
any 3DGS viewer shows the sky. The masks (`sky_masks.py`: SegFormer's sky, sea
and water) also take in the sea next to the nodes, which reflects the towers,
so only directions down to 15 degrees below the horizon are used and the rest
filled from the horizon down (y is up in the joined model). With the sky
masked, nothing in training keeps splats out of it, and some float in front of
it as haze from untrained views (MAIS 29). Training with the sky transparent
instead kept the sky clear at MAIS 29 but grew opaque black blobs (MASS 35, 31,
84). `splat/sky_floaters.py` takes out of the masked splat the splats whose
centre falls more than 8 px inside the sky of at least 8 views and more than 2
degrees above their horizon (below it the masks hold sea, whose splats must
stay): 286,374 of 3,195,184. At 2 views it took the whole roof of MASS 35's
pavilion as well (12.5 dB there), at 4 most of it; 8 keeps it. The best splat
so far is that one with the shell: 3,308,810 splats, 745 MB
(`C:\myst3_out\splat\amateria_best.ply`), and `splat/splat_reduce.py` makes a
copy for phones of the 1.5 million that show most, without view-dependent
colour (84 MB). Under roofs that few views see (MASS 31, 35) every version is
soft.

### With MASS 11090's frames (9 November 2026)

The same recipe from `dense_movies3_moved` (MALL's turret frames left out of
the cloud; ghosts by `ghost_points.py` against the 62 trusted nodes): the
nodes' faces, the flyover and MASS 11090's 81 frames (734 images; MASS
10157's and MACA's frames left out, as they lie by nodes neither trusted nor
moved), 735,895 starting points. Brush took 25 minutes for the 30,000 steps;
312,038 floaters out, the shell added: 3,344,314 splats, `amateria_v2_best.ply`.
On the six views it scores 18.9, 17.4, 21.1, 22.3, 26.9 and 22.6 dB (mean
21.5, against 21.8). `splat/walk_dataset.py` writes cameras walking from one
node to another; rendered from MASS 84 to MASS 89, both splats are soft
halfway, and the new one smears the arches beside the walk more: MASS 11090's
frames do not help there, likely as their places are not quite right. Both are
served beside each other (`?file=amateria_v2_phone_1m.ply`).

### A node's depth from the splat (MASS 84)

Whether the splat could give a site node better depth was tried on MASS 84:
its six faces rendered from the best splat at 1280 px with `splat_render.py
--depth` (where each pixel becomes half covered), and set beside the measured
and the redrawn depth by `splat/node_depth_compare.py`, one scale fitted (the
node's run was rescaled by 1.089). The splat's faces agree at their seams
unblended (median step 1.3%, 90% within 11.7%, where Depth Anything's step 6.1%
before blending), and the walls and the house are right; but it is a median
15.5% from the measured depth (90% within 96%) against 4.1% for the redrawn
depth, with splats just in front of the camera and holes on the floor and
round the node: what only the node itself saw, the splat fits in colour with
splats at any depth. So the redrawn depth stays. A splat held to the measured
depth in training (a depth loss; Brush has none) might do better.

### The tower (MATO)

Of the tower's 10 nodes only MATO 2, outside its door, is in the joined model.
`colmap/tower_model.ps1` makes a model of the tower alone (prepare_colmap.py
with MATO.json, faces brightened, the loose mapper settings) with MAIS 32 and
33 added beside MATO 2, so that three nodes would be shared with the joined
model. It comes out in three pieces: MATO 2 with MAIS 32 and 33; MATO 4, 5, 6
and 9; MATO 10, 11 and 12; MATO 3 and 7 unplaced. The links between the pieces
have no matches to speak of (MATO 2-3: 0 verified, 3-4: 40, 6-7: 17, against
230-2,203 within them): the tower is rooms joined by a door and lift rides
(MATO 2 outside, 3 behind a curtain inside, 4-6 a dark chamber and a hub, 7 an
open lookout over the sea), and no room sees into the next. Joining them needs
the age map's steps and headings (no heights), or, for the lookout, the outside
it sees.

### One depth prediction for the whole panorama (MASS 84)

`colmap/pano_depth.py` sews a node's six faces into one equirectangular picture
and has Depth Any Panoramas (Insta360, December 2025: Depth Anything V2 with a
DINOv3 encoder, trained on panoramas; repository and weights from Hugging Face,
`Insta360-Research/DAP-weights`, on the PC in `C:\myst3_out\dap`) predict the
distance along every ray, then samples it back onto the faces with one factor
fitted to the measured depth. (DAP imports einops without using it, and
DINOv3's hub entry pulls in its evaluation code; the script stubs the one and
builds the backbone directly instead of the other.) On MASS 84:

| depth | seams: median, 90% | from the measured: median, 90% |
|---|---|---|
| measured (node_depth.py) | 0.0%, 2.8% | — |
| redrawn per face, blended (the site's) | 0.0%, 2.0% | 4.1%, 12.8% |
| DAP, 512 x 1024 | 0.2%, 0.6% (unblended) | 9.8%, 41.5% |
| DAP, 1024 x 2048 | 0.2%, 0.4% (unblended) | 8.9%, 39.7% |

The panoramic depth is seamless with no blending, but coarse: the walkway's
slats merge into one slab and the rails thicken. And the blending costs the
redrawn depth nothing measurable here: `colmap/seam_band_error.py` puts it a
median 3.8% from the measured depth within 96 px of a face's edge and 4.2%
inside. So MASS 84 keeps its redrawn depth. Where DAP could count is at nodes
with no measured depth, most of the game's, where nothing but blending holds
Depth Anything's six faces together; not yet tried.

### MASS 84's backdrop from the moved model

MASS 84 is in the MASS 82-90 run moved back on 8 November 2026, so its
backdrop, projected from its neighbours in `dense_movies`, had them from the
wrong place. `build_layers.py` now says, per face, how much of the hidden area
inside near objects other nodes saw. With `model_backdrop.py` on
`dense_movies_moved` (r_far scaled by the run's 1.089, `node_depth_moved.json`):

| face | 1 | 2 | 3 | 4 | 5 | 6 |
|---|---|---|---|---|---|---|
| seen by other nodes, old model | 0.6% | 0.0% | 5.5% | 0.6% | 14.1% | 6.1% |
| seen by other nodes, moved model | 4.1% | 0.0% | 9.8% | 3.5% | 19.2% | 18.3% |

About 8% of the hidden area instead of 4%, and on face 5 a red figure the old
model put behind the arches is gone. LaMa still paints the rest: what is
hidden from MASS 84 is mostly behind the house, which no node sees. Rebuilt
from `layers/nodes/mass84.json` and shipped; the foreground atlases are
unchanged.

On a phone, looking along face 1 at the lamp post and the track overhead,
three faults showed:

- **Clouds:** the neighbours' stereo gave the lit clouds depths a little
  behind the post and the track. The backdrop kept them there as a dark and
  orange speckle in the sky.
- **A second post:** stereo puts the post's reflection below the water, about
  as far down as the post is high. Projected into MASS 84 it landed just
  behind the post, and showed as a second post when the eye moved.
- **The lamp glass:** the glass hangs pale in front of the sunset, and the
  measured depth called it sky. The shade moved with the post, the glass
  stayed on the sky, and the backdrop kept a copy of the glass where the lamp
  had been taken out.

`model_backdrop.py --masks` now leaves out every neighbour pixel its sky mask
blacks out (`sky_masks.py`'s sky, sea and water), and LaMa paints those parts
of the backdrop from MASS 84's own picture. `build_layers.py --light
1:142,280,180,315` gives the glass the shade's depth. Within that box, the
glass is the sky-depth pixels paler than the sky on the box's border, 2,247 px
at 1280. The foreground's colour is unchanged, and its depth changed only at
the glass.

| face | 1 | 2 | 3 | 4 | 5 | 6 |
|---|---|---|---|---|---|---|
| seen by other nodes, moved model, sky and water masked | 2.7% | 0.0% | 9.5% | 2.6% | 17.3% | 14.5% |

Less of the hidden area is real content now, but none of it is cloud or
reflection. Rebuilt and shipped on 8 November 2026.

In the next look from the phone, the blue flame on the far post slid off its
post as the eye moved. The measured depth has the post and the flame at sky
depth, but `sharpen_depth.py`'s lamp rule (`light_fill`) took the flame for a
light. SegFormer's piece for it also took in the rails crossing it, so 2,148 px
of the flame between the rails were pulled forward to the rails' depth. The
rule had never placed the lamp glass it was written for. MASS 84 is now built
with `sharpen_depth.py --no-lights`, and the glass is placed by
`build_layers.py --light` alone. The glass takes the 90th percentile of the
solid pixels round it (q 3.16, the shade 3.01). Without the lamp rule the
shade's soft rim was among those pixels, and their median put the glass
behind its shade (2.12).

Next came the floor (face 2), where slat wood was missing even at depth 0.
The foreground's holes are placed from the depth's outlines, and the slats'
outlines there are notched and up to about 10 px off the picture's straight
edges, so many holes fell on wood. The gaps between the slats are narrower
than the cut, so `build_layers.py` took them for slits and painted them, and
the backdrop under the whole floor was plain dark: every hole on wood showed
dark paint. Two changes:

- The viewer now cuts holes only when depth is on. At zero nothing moves, so
  the picture is drawn whole (`cube/index.html`).
- `build_layers.py --keep-gaps 2` keeps the picture in the floor's gaps, which
  look at the sea far below. That paints 53.4% of face 2 instead of 59.0%, and
  a hole on a slat now shows that slat's wood, at the backdrop's depth.

The holes were on the wood for a reason other than the outlines. The
sharpened depth's slat outlines follow the picture, but it has a ridge a
pixel or two wide along each slat's edge, about 0.8 (in r_far / r) nearer than
the slat. `build_layers.py` finds steps of over 0.8 between pixels 2 apart, so
a strip of every slat read as the far side of a step. The near objects broke
into half-disc blobs, and the holes cut round them fell on the wood. The steps
are now found on the depth after a 5 px median, which takes thin ridges away
and leaves steps where they are; the depth itself is unchanged. The slats were
then whole, but the gaps had holes only in pieces. A pixel joined a near
object when it read t/2 (0.4) nearer than the far side's least q. Down the
gaps the sea's depth varies by about that much, so stretches of gap passed
the test and joined the slat through the steep pixel between. They got no
hole. Pixels on the far side of a step are now never part of the near
object; a middle layer that belongs to it is still added, for ENSI 16's pod
frame. The floor's holes are now full strips down every gap: 20.4% of the
face, against 10.9% in the build before these changes. On the other faces
the holes change by about a point or less.

ENSI 16, LEIS 77 and MAWW 101 were rebuilt with both changes from their
files in `layers/nodes/` the same day. Their holes cover 11.1%, 7.3% and 9.1%
of the atlases, against 9.8%, 7.1% and 7.0%, and their foreground colour is
unchanged. On MAWW 101 the ring of holes round the console is whole where it
was dashed, and on ENSI 16 the walkway's railing is outlined along its whole
length. Voltaic's grate has its own builder (`grate_layers.py`) and is not
affected.

### MASS 84's rock wall: slabs the network draws (8 November 2026)

On faces 3 and 4 the rock wall's columns slid against each other in the
original, and in the layered version tore into strips at the smallest depth.
The cube's seams are not the cause: both depth maps meet across every edge
within 1–4% (90th percentile). Depth Anything V2 draws the wall as a slab per
column. Along row 200 of face 4 it jumps between 2.4 and 3.6 (r_far / r),
where COLMAP's stereo for the node's own face measures 3.1 to 3.3. The
network reads lit columns as near and shaded ones as far.
`node_depth.py` fits the network with one scale and offset per face, so the
slabs stay. Tried:

| what | result |
|---|---|
| MoGe-2 (`colmap/depth_nets.py`, Ruicheng/moge-2-vitl-normal, 90-degree field of view) in place of Depth Anything | the same slabs, deeper: 1.6 to 4.3 along the same row; 8.1% from the stereo on face 4 against Depth Anything's 4.0% |
| `node_depth.py --follow-stereo`: the network's depth plus a correction, smooth within each surface the network drew, held to the stereo (`follow_stereo`, a sparse solve), with the sky and water masks | face 4's wall smooth and on the stereo; but the stereo is wrong on thin things (rails turned to blobs on faces 1 and 3) and on face 3 has slabs of its own |
| the same, without stereo within 6 px of the network's steps (`--edge-px`) | the rails kept, but most slabs are narrower than 12 px and kept no stereo: the wall unchanged |
| the same, without stereo only on thin near things (an 11 px opening) | parts of the lit slabs caught as thin; the wall's spread halved (3.1 to 4.1), the rails blurred again |
| `follow_stereo` only to scale each of the network's steps by the stereo's step across it | the slabs softened a little, slat and rail edges blurred |

None is used; the options are left in, off by default. The stereo on this
dark, repeating rock is no more reliable than the network, only wrong in
other places.

Halving the fine relief (`node_depth.py` and `sharpen_depth.py --relief 0.5`,
`compress_relief`) does what the stereo could not. The log of the depth is
split into a base, two passes of a bilateral filter that keeps steps of more
than about 1.6 times, and the detail above it, which is halved. Along row 200
of face 4 the wall runs 2.6 to 3.0, against 2.4 to 3.6; the rails, the house
and the floor keep their outlines. At the default depth and tear settings,
2.1% of face 4's wall tears (3.9% before) and 1.7% of face 3's (2.1%). It is a
rule, not a measurement: every fine relief is halved, the real with the drawn.
It was on the site as its own location to compare, and was taken off on
8 November 2026 after the maintainer looked at it and did not prefer it.

The depth can instead be held to the model's fused point cloud
(`colmap/cloud_depth.py`), the points that several views agree on, rather
than to COLMAP's single-view depth map. Projected into MASS 84's faces
(`dense_movies_moved/fused_ridefilter.ply`, distances divided by the run's
1.089189), the cloud lands on 17–23% of the side faces' pixels. Along row 260
of face 4 it has the wall receding smoothly from 1.6 to 2.5. It is filtered
in three ways:

- the sky and water masks;
- a point under 0.6 times (in r_far / r) the nearest point within 5 px is
  dropped; with 15 px, wall points beside the rails and the track went too;
- a point more than 2.5 times nearer or farther than the old depth is
  dropped: points seen through the house, where the house wall has none of
  its own.

The depth is then held to what is left by `follow_stereo` with a weak pull
(0.01) and an almost free step between surfaces (0.0001), so each surface the
network drew takes the mean of the points on it. Held at 1, every point's
noise showed as blotches; with the step at 0.01, a slab's long edge outweighed
the points on it and the slabs stayed. The floor and the sky face, with too
few points (under 5%), are held at their edges to their neighbours, and r_far
is set again from the new depth, so the track and floor, nearer than before,
no longer clip. Face 3's wall comes out about twice as far as Depth Anything
had it (3 to 4 against 6.3 along row 350), which was that face's poorest fit
(12.5% median, 59% at the 90th percentile from the stereo). The layered
version's depth is held to it with `sharpen_depth.py --follow-measured 1`.
It was on the site as its own location to compare, and was taken off when
`view_check.py` (below) scored it no better than the live depth on the other
nodes' faces.

**Depth from a mesh** (`colmap/mesh_depth.py`): COLMAP's Delaunay mesh of the
earlier model (`dense_joined/meshed-delaunay.ply`), a ray cast through each
face pixel. It is within 0.1–0.5% of the stereo at the median on faces 1, 3,
4 and 5 (the site's depth 1.7–9.2%). The walls are smooth and face 3's wall is
twice as far, but it has no rails, lamp post or slats (too few views saw
them), and big flat triangles close what no node saw. The Poisson mesh covers
less (45–77% of a side face against 70–99%).

**Scoring a depth by other cameras' pictures** (`colmap/view_check.py`). The
node's faces are moved by a depth to another camera's position and compared
with that camera's picture: every face of the nodes within 3 units, and movie
frames as close. The score is the mean absolute difference (0–255) over the
pixels every version covers. For MASS 84 (18 node faces and 17 movie frames;
11 node faces and 14 frames cover enough):

| depth | 11 node faces | 6 flyover frames | 8 ride frames | all 25 |
|---|---|---|---|---|
| everything at infinity (the turn alone) | 21.6 | 29.7 | 30.1 | 26.3 |
| live (Depth Anything, fitted) | 13.6 | 20.9 | 27.9 | 19.9 |
| live, the layered version's sharper depth | 13.5 | 19.2 | 28.3 | 19.6 |
| fine relief halved | 13.7 | 20.6 | 27.7 | 19.8 |
| held to the fused cloud | 14.1 | 18.8 | 29.2 | 20.1 |
| Delaunay mesh | **12.3** | 20.7 | 30.0 | 20.0 |

Every depth beats the turn alone by a wide margin. On the other nodes' faces
the mesh is best (9% under the live depth) for all it lacks; on the flyover's
frames the cloud is. The ride's frames are poor references: even those 0.4–0.8
units from the node score 31–42 for every version, the turn alone included,
as the ride's path was already suspect (above).

**The mesh with the network's detail** (`cloud_depth.py --mesh`): the live
depth held to the Delaunay mesh's depth (`follow_stereo`, weight 1), except
where the hit triangle spans more than `--max-span` radians from the node (a
surface the mesher made up between far-apart points: median span 0.07–0.14 on
the side faces, 0.6–2.4 on the floor and sky faces), on thin near things the
network draws (`--thin`: nearer than round them by 10%, gone after an opening
11 px across: the rails and post the mesh lost) and under the sky and water
masks. What lies beyond the new r_far is written as the farthest level, not as
sky: set again nearer (15.1 against 21.7), it had turned the far pier and sea to
sky. On the 10 node faces the check covers in the moved model:

| depth | node faces |
|---|---|
| everything at infinity | 21.3 |
| live | 12.9 |
| the mesh alone | 11.5 |
| mesh + network, span under 0.3, no thin rule, weight 1 | 11.3 |
| mesh + network, span under 0.3, thin 11, weight 1 | 11.4 |
| mesh + network, span under 0.3, thin 11, weight 0.01 | 11.2 |
| mesh + network, span under 0.6, thin 11, weight 1 | **11.2** |

The settings barely matter. Over every view the check reaches in the model
before the run moves (with MASS 11090's frames, below; the turn alone judged
on what it covers of the pixels the real depths share), live, the layered
version's depth and mesh + network score 15.8, 15.9 and 15.8: the mesh's gain
is on the nearby nodes' faces, and on the six nearest MASS 11090 frames it is
slightly worse (13.8 against 13.3).

**More movies** (`colmap/add_movies.ps1`): of Amateria's 230 movies (all
extracted with frame sheets in `movies/<ROOM>/` on the PC), 47 are full frame
(640x360), and 8 are the camera moving through the open age. Registered one
after another into `video_lemt_nodesky`'s model, with sky masks and the
flyover's camera (f 455):

| movie | frames registered |
|---|---|
| MASS 11090 (along the pier by MASS 90) | 81 of 81 |
| MASS 10157 (the glass ball leaving) | 16 of 91 |
| MAWW 10300, 10301, 10303, 10304, 11002 (round MAWW's platform) | 0 |
| MATO 10112 (a flight past the rocks) | 0 of 315 |

MAWW's platform has almost no nodes in the model to match, and the flight
sees what no node does. MASS 11090's first frames are 1.65 units from MASS 84,
the nearest views of it there are. `run_dense.ps1` on the model with them
(`dense_movies2`) was started for a mesh with more views.

**The dense run with the movies** (`dense_movies2`, on the model with MASS
11090 and 16 frames of MASS 10157 added): `patch_match_stereo` 2 hours 9
minutes for 1,026 views. The three runs were moved as in `dense_movies_moved`
(`moves_to_runs.py` regroups that workspace's `moves.json`; MASS 11090's 81
frames, registered among the misplaced MASS 82-90, moved with that run by the
similarity fitted to its nodes, scale 1.0892) and fused without the 90 images
left out before: `dense_movies2_moved`, a 283,433-vertex Delaunay mesh. MASS
84 held to it as above, scored in that model:

| depth | 10 nearby node faces | 7 flyover frames | all 26 views |
|---|---|---|---|
| live | 13.8 | 22.5 | 21.1 |
| mesh of `dense_joined` + network | **11.6** | 22.4 | 21.0 |
| mesh of `dense_movies2_moved` + network | 13.3 | **20.5** | 20.9 |

The new mesh does better on the flyover's frames and loses the old one's gain
on the nearby nodes' faces; over every view the three are within 1%. The
extra movie frames did not settle it.

**The rest of the moving-camera movies** (`add_movies.ps1 -Measure`: each
movie's own camera first, mapped alone from f 455), chained on from MASS 10157:

| movies | camera found (f, px) | frames registered |
|---|---|---|
| MALL 14017–25017, the 11 turret views | 380–416 (one 815, one 333) | all 1,321 |
| MACA 10035, 10036, the lift shafts | 381, 387 | 58 of 101, 35 of 96 |
| MAWW 10300, 10301, 10303, 11002 | 58–401 | 0 |
| MATO 10112, 14006, 27007, MAIS 10102 | 320–556 | 0 |
| MAWW 10304, MALL 10008–12008 and 26017, MATO 10002, 10003, 10103 | none: the movie alone gave no model | — |

The flyover's f 455, given to all at first, was wrong for these (they come
out near 390), and with it MAWW's and MATO's movies registered nothing; with
their own cameras they still do not, as MAWW's platform and the flight see
what no node does. The model (`video_mato27007_chain`) holds 2,726 images.
Its dense run reuses `dense_movies2`'s depth maps and computes only the 1,414
new frames' (`dense_movies3`); `dense_movies2` had computed every view again,
2 hours 9 minutes where its 97 new frames needed about 12.

`dense_movies3` (2,726 images): the 1,026 old views' depth maps copied
from `dense_movies2`, the other 1,700 computed in 185 minutes; moved as before
(MASS 11090's frames with their run) and fused from 2,636 images
(`dense_movies3_moved`, 161 MB of points, a 347,640-vertex Delaunay mesh). Its
mesh reaches 100% of MASS 84's faces 3 and 4. MASS 84 held to it scores 13.6
on the 10 nearby node faces and 20.6 on the flyover's 7 frames (live 13.9 and
22.6; the first model's mesh 11.8 and 22.4), better than live on 8 faces and
all 7 frames. It was built for the site and not shipped: the mesh is made of
flat patches, and held to them the depth steps where two patches meet. Face
3's wall and face 4's house wall came out blotchy, the track's slats and gaps
one flat wedge, and the layered version cut holes along the patch edges in
the middle of walls and the walkway floor. The score, an average over the
pixels, does not see a few sharp new steps; the viewer shows them as tears.

MALL's turret frames do not belong in the cloud yet. Of `dense_movies3_moved`'s
5,967,390 points, 3,030,136 were made by those frames alone, lying a median
4.0 units (2.4 node spacings) from the nearest node: a spray in the air. MACA's
lift frames made 236,981, a median 1.0 from MACA's nodes. Three causes: MALL
4-16 is the run left misplaced (the trusted faces see through 71% of its
points) and the turret frames were registered against it; the turret's barrel
and seat move with the camera in every frame, as the ride's glass ball did,
and need a mask; and MALL 14017's camera came out at f 815 against about 390
for the rest. Fused without them (1,315 images): 1,636,011 points, in the
viewer as `amateria-movies3-moved` (the cloud with them kept as
`fused_withmall.ply`). They can come back once MALL is placed and the turret
masked.

**A score that counts stretching** (`view_check.py --connected`): the faces
drawn as the viewer draws them, a surface through every pixel and its
neighbours, so a false step smears across what it covers in another camera's
view, the sky at r_far as the viewer puts it. With it the ranking matches what
the eye saw: over 52 views, live 24.7, the first model's mesh with the network
25.0, the mesh with every movie 25.3 (the one that looked blotchy).

**Steps the network and the model agree on** (`colmap/agree_depth.py`): the
live depth rebuilt from its own gradients, except where it steps by more than
10% and neither the mesh (reliable there) nor the fused cloud (something near
within a few px of the step's near side) bears the step out; there the mesh's
gradient is used. Steps over half the value stay whatever the mesh says.

| version | over 52 views |
|---|---|
| live | 25.30 |
| network steps the mesh lacks flattened, levels held to the mesh | 25.5–25.9 |
| the same, levels left as the network's | 24.72 |
| the same, steps beside thin near things (11 or 17 px) kept | 24.69 |
| the same, steps the fused cloud bears out kept | **24.57** |

Holding the levels to the mesh is what spoiled the first try. The thin-thing
rule did not save the lamp post on face 4, 24 px wide at 640, as wide as the
rock wall's made-up slabs; the cloud has the post (near) and the slabs (a
smooth wall), so its vote tells them apart. With it about half as many steps
are flattened (face 4: 4,355 pairs against 9,187), the rails and slats keep
their holes in the layered build, and the post stays in front of the wall at
a shallower step (2.7 against 2.2, where it was 3.8 against 2.7), too small
now to cut a hole round. MASS 84 is shipped with it (Original, Layered and the
walk, MASS 89 made the same way); the depth before is `site_live_backup/` on
the PC.

The tears at small depth are the viewer's: its tear test weighed only the
step in the stored depth, so at a tiny depth it cut where it cuts at full
depth. How far a step stretches is the step times the depth setting, so the
test now weighs it by the depth (`uDepthK`) against the default (70%, K =
10.7). There it tears as before, below it less, and at zero not at all.

This applies to every node built from now on; ENSI 16, LEIS 77 and MAWW 101
have not been rebuilt with it.

Snapping the outlines to the picture with GrabCut was tried first and dropped:
it dropped face 1's rails from the near objects and made the slats' outlines
wobble.

## Depth for the site's Amateria node (MAWW 101)

The site's Amateria location is MAWW node 101, node 1 with the console closed
and glass balls on the track (faces 3–6 are node 1's; faces 1 and 2 differ in
14% and 36% of their pixels). No model places node 1 (above), and stereo from
the ride's frames measured nothing but clouds (`node_stereo.py`: 0.3–0.5% of the
side faces kept, at 10–20 units). What it does share is its platform: MAWW 2's
floor face shows the same deck and console (144 verified matches with node 1's
floor face, with the sky masked on all 18 faces of MAWW 1–3), with rock columns
round it instead of open sea: the platform moves. `pair_points.py` triangulates
133 points on it from the two floor faces (0.26 px; MAWW 2's eye a little lower,
along the floor face's axis; depths 4.5–10 times the baseline). On node 1's floor
face Depth Anything's inverse depth fits those points within a median 6.3% (one
scale and offset; correlation 0.94).

`node_depth.py` then fits all six faces of node 1 at once (12 unknowns, a scale and
offset per face): the 133 platform points; every face's edges equal to the
neighbouring face's across the seam; and the sky at zero inverse depth, which is
how Depth Anything is trained and fixes each face's offset. Without the sky the
fit made every face a constant distance, a sphere, which satisfies the seams
trivially. Held-out platform points come out a median 16.0% off (90% within 37.1%):
the seams pull the floor face, since each face's network depth is predicted on its
own. Node 101's two changed faces get their own network depth, fitted to node 1's
distances over the pixels they share (5.0% and 0.8% off), so the closed console
and the balls have the depth their own picture shows. The steps left at the
seams (median 16.7%, 90% within 63%) are blended out over 48 pixels each side
(1.2%, 10%), so the viewer draws no crease at the cube's edges.

So for this node only the platform is measured; the rest is the network's depth
held to the platform's scale through the seams, with the sky at infinity. The
overall scale is the two eyes' separation, unknown in the age's units, which
the viewer does not need: it draws proportions. The six maps are
`../amateria/MAWWnodes-8…13_measured-depth.png` (8-bit, d = (r_far / r − 1) /
(r_far / r_near − 1), r_near the 0.5th percentile of distance, r_far 20 times
it), so the slider at its top (K = 19) is true proportion, and the default (70%,
K = 10.7) is flatter.

### Sharper outlines (`colmap/sharpen_depth.py`)

The *Layered* version redraws that depth at 1280 px: Depth Anything V2 Large
run on the site's 4K faces (reduced to 1280) at an input of 1036 px, fitted per
face to the measured depth (1/z = a p + b, Cauchy-weighted, away from the
measured map's outlines, the measured sky held at zero), seams closed over 96
px. At its own input size of 518 px the network drew the spire roof as a
rounded blob whose eaves reached ~10 px past it; at 1036 the outline follows
the eaves. The redrawn maps stay a median 2–7% from the measured ones (90%
within 6–16%).

On 8 November 2026 MAWW 101 was rebuilt from the game's 640 px faces
(`_orig.jpeg`, enlarged to 1280) instead of the 4K faces, which are an AI
upscale, at the maintainer's request (`layers/nodes/maww101.json`). The fit is
a little looser on two faces (median 9.3% and 6.2% on faces 10 and 11, from
7.0% and 3.1%; the others within 0.4 points), the seams before blending the
same (median 12.6%, 90% within 40.4%), and the painted share of each face
within a point of before. The colour layers are softer: the upscaler's
invented detail is gone.

## Depth for a node the model places (MASS 84)

The site also has MASS node 84 (`Amateria (MASS 84)`), one of the 131 nodes
the joined model places, chosen for the best dense coverage of its side faces
(37% of their pixels have a COLMAP geometric depth in `dense_joined`; no node
has more) and near structure: a building with a porthole, the track, a rock
wall. `node_depth.py 4084 --dense dense_joined --sparse
joined_floor_map/sparse_txt/ba` fits Depth Anything to the model's own depths
(3,000 stereo depths a side face, 31–295 sparse points) and the seams: on
held-out measurements a median 2.2% off on faces 1 and 5, 4.5% on face 4, 12.5%
on face 3 (90% within 12–59%); the floor, which no other node saw, takes its
scale from the seams. So here the scale and the shape where points exist are
the model's, and the network fills what no other node saw. Report:
`colmap/Amateria/mass84_depth.json`. Its *Layered* version is built as MAWW
101's, from the 640 px faces (no 4K copies) enlarged to 1280; the redrawn depth
stays a median 2.6–5.1% from the measured.

## Depth for a Voltaic node the model places (ENSI 16)

The same for Voltaic: ENSI node 16 (`Voltaic (ENSI 16)` on the site), beside
the stone tower, from the 27-node model's dense run (`dense_1-27`; 48% of its
side faces and 22% of its floor have a geometric depth, about the most of any
ENSI node). `node_depth.py 0016 --dense dense_1-27 --sparse
joined_1-27/sparse_txt/ba` fits less tightly than for MASS 84: on held-out
measurements a median 4.3–4.8% off on faces 3 and 4 and 1.2% on the sky face,
but 10.9% and 14.6% on faces 1 and 5 (90% within 29–72%) and 26.8% on the
floor. On faces 1 and 5 the sky rule (pixels predicted as far as SegFormer's
sky) also takes in the far sea: 45% and 25% sky against SegFormer's 25% and
18%. Report: `colmap/ENSI/ensi16_depth.json`. node_depth.py read the node
number as an integer, which turned ENSI's `0016` into 16 and found no faces; it
now takes it as written.

## The other ages' rooms, and J'nanin's site node (LEIS 77)

One room per age through `run_colmap.ps1` with ENSI run 3's settings
(brightened faces, SIFT peak 0.002, the looser incremental mapper), on the
CPU (`-Cpu`) while a dense run had the GPU:

| age | room | nodes laid out | largest model |
|---|---|---|---|
| Tomahna | TOHO | 8 | 4 (two models of 4) |
| Narayan | NACH | 26 | 10 (models of 7, 10, 10, 3) |
| Edanna | LISP | 36 | 7; 22 nodes not placed, links of 140-350 matches |
| J'nanin | LEIS | 79 | 77, at 0.34 px |

J'nanin's one model was the sky's doing. With `sky_masks.py`'s masks for its
474 faces (a median 35% of a face) and `run_colmap.ps1 -Mask masks`
(`run2_nosky`) it comes apart into models of 38, 24 and 13 nodes. The site's
J'nanin location is node 77 (LEIS661 is node 77's face 1, pixel for pixel),
in the 13-node model with nodes 23-33 and 76. `node_stereo.py` for node 77 and
its eight nearest found only 9 source images beyond them, and `node_depth.py`
fits loosely: on held-out measurements a median 6% off on face 4 and 19% on
the sky face, but 39%, 80% and 235% on faces 1, 5 and 3. The maps' shapes are
Depth Anything's and look right (the hut near, the cliffs far); on the floor a
few spots of water reflecting the sky are taken for sky. Report:
`colmap/LEIS/leis77_depth.json`. The site now has J'nanin's depth and a
*Layered* version built as ENSI 16's, from the 640 px captures enlarged to
1280 (the site's 6K faces are AI upscales and are not used as input); the model's
neighbours supply 0-9% of its backdrop. `node_stereo.py` read node numbers
as integers too, and now takes them as written.

