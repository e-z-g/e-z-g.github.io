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
