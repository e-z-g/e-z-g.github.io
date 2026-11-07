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
| `colmap/ENSI/` | Those three files for ENSI (no images). |

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

**A warning for the reconstruction:** the southern chain, nodes 27–41, matches
poorly. Its links find 4–18 consistent matches where the rest of the room
finds 30–1,200, so COLMAP may fail to join those nodes to the others; that is
where to look first if the room comes back in pieces.
