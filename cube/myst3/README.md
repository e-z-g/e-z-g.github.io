# `cube/myst3/` — Myst III node data and maps

Tools for getting real node data out of *Myst III: Exile*, the game the cube
viewer's ages come from, and maps of how its nodes connect. Nothing here is
served to the viewer; it is groundwork for walking an age node by node and for
3D reconstruction from the nodes' panoramas.

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
| `colmap/sharpen_depth.py` | A site node's measured depth redrawn at 1280 px from the 4K faces: Depth Anything V2 Large at an input of 1036 px, fitted to the measured depth away from its outlines, seams closed; outlines that follow the picture, for Amateria's *Layered* version. Needs torch, transformers, opencv-python. |
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

