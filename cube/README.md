# `cube/` — the cubemap VR viewer

Notes for anyone editing the viewer or the stitcher. The code carries its own
long *why* comments; this is the map that sits above them — the shape of the
pipeline, the invariants that are easy to break silently, and how to check that
you have not broken them.

## The three files

| File | What it is |
|---|---|
| `index.html` | the viewer. One `<script type="module">`, three.js from a jsDelivr import map. |
| `stitcher.html` | builds atlases the viewer reads, from six face images. |
| `atlas-layout.js` | the **contract** between the two. Face indices, name→slot mapping, cell layouts, and the GLSL `sampleAtlas()` both sides agree on. |

Both pages import `./atlas-layout.js` relatively, so they must be **served over
HTTP** — `file://` gives an opaque origin and the module fetch fails CORS.

The import carries a `?v=` version. **Bump it in both pages whenever
`atlas-layout.js` changes.** Pages lets browsers cache the module for ten
minutes, and a reload refetches the page but not the module, so without a new
URL an updated page runs against the old contract — once already that was a
missing export and a viewer that never started.

Read the header comment in `atlas-layout.js` before touching either page. The
stitcher writes cells at particular rotations and the viewer reads them back on
that assumption; change one side alone and the poles smear without an error.

## The scene

The camera sits at the origin of a **sphereified cube**: six grids, one per
face, with every vertex normalised onto a sphere of radius 50, built by
`buildSphereCube()` straight into typed arrays (positions and indices only), in
material-slot order, facing inward. `CUBE_SEGMENTS` is **512** per face edge
(3.1M triangles), **256** on low-power devices (0.8M); `?mesh=N` overrides it,
and `?debug` reports it with the frame rate. The mesh is what bends, so a depth
edge can only turn where there is a vertex, and detail in the map finer than
the grid is averaged away: at the old phone default of 128, Voltaic's slatted
walkway channels averaged into a trough whose texture slid about under the
beam beside it.

Smoothing the *map* to suit a coarse mesh was tried instead — a morphological
closing to fill the gaps between slats, and growing near things by a quad —
and rejected: it pulled rims of rock forward around every near outline on
Voltaic and threw away detail the map really has. The map is used as drawn;
the mesh is what got finer.

It used to be a `BoxGeometry` scaled by `(-1, 1, 1)`. At 512 that assembles
positions, normals and uvs in plain JS arrays — about 100 MB of garbage for a
mesh that only reads positions. `buildSphereCube()` builds the same point set
(checked identical to the old one at 128 and 256: 6n²+2 distinct points, every
group on its face, every triangle inward) in ~80 ms and 54 MB at 512.

Two meshes:

- `fgCubeMesh` — radius 50, `renderOrder` 1. The picture.
- `bgCubeMesh` — radius 56, `renderOrder` 0. Only visible for dual-layer (LDI)
  custom uploads, where it is the backdrop behind the foreground's tears. Its
  geometry is built the first time one is shown (`ensureBgGeometry()`), not
  at startup.

Camera is 80° FOV, near 0.1, far 500. Pixel ratio is capped at 2 and then driven
by an adaptive supersampling governor (`RENDER_SCALES`, 0.75×–2×) that measures
the display's real frame interval first and climbs only while frames stay on
cadence. What the depth pass needs is supersampling, not MSAA: the displaced
mesh is continuous, so there are no internal silhouettes for multisampling to
find — what steps along an edge is the texture draped over the mesh.

## Face indices

The one table everything else is defined against:

| Slot (`uFace`) | Direction | Name |
|---|---|---|
| 0 | −X | left |
| 1 | +X | right |
| 2 | +Y | top |
| 3 | −Y | bottom |
| 4 | +Z | back |
| 5 | −Z | front |

`getCubemapUrls()` hands its six URLs to the material slots in the order
`[left, right, top, bottom, back, front]`, and that ordering is authoritative —
`atlas-layout.js`'s `FACE_INDEX` is written to match it.

`gnomonicUV(dir, face)` maps a direction to that face's `[0,1]` UV. `u` must
increase with yaw on all four walls, because the render loop sweeps
+X → +Z → −X → −Z as longitude increases.

## Depth: from a grey image to a mesh

Four stages, in order. Each exists for a reason that is not obvious from the
code alone.

### 1. Auto-ranging

Depth maps almost never occupy the range they are stored in. Measured off the
shipped assets:

| Map | p0.5 | p99.5 | span |
|---|---|---|---|
| Voltaic (six faces, combined) | 0.055 | 0.529 | 0.47 |
| Edanna (5×3 atlas) | 0.067 | 1.000 | 0.93 |

Voltaic uses barely half the byte; its raw per-face extremes are 0.035 and
0.576. Fed raw to the mesh, the slider's effect
depends entirely on how the map happened to be exported, and Voltaic's whole
scene lands on a shell a few units thick. `measureDepthRange()` therefore
histograms the map at load — **percentiles, so one stray pixel can't set the
scale, and point sampling (`imageSmoothingEnabled = false`) so averaging can't
clip the extremes away** — and the shader stretches the result to `[0, 1]`.

The *raw* value still drives the fragment stage. `depthAt()` is raw;
`depthNorm()` is stretched, and only the vertex stage calls it. This matters:
in a dual-layer LDI foreground a literal zero means "nothing here", and
stretching that floor would break the transparency mask.

### 2. Reciprocal radius

A monocular depth map stores **disparity** — roughly 1/z — so distance has to
be reciprocal in it:

```glsl
vec3 newPos = position / (1.0 + vDepth * uDepthK);
```

`uDepthK` is the far/near radius ratio minus one. The slider maps to it through
`depthRatioFor()`: `(DEPTH_RATIO_MAX - 1) * s^1.6`, ceiling 20.

The previous form was `position * (1.0 - depth * scale)` — linear in the depth
value. On Voltaic at the default slider that produced a spread of about **1.6:1**
(radius 31 to 49): a hard shell with a sky painted on it.

### 3. The vertex low-pass

`smoothedDepth()` averages five taps over roughly one quad
(`uDepthSmooth = 1 / CUBE_SEGMENTS`). A step in the depth map otherwise lands
wherever the vertex grid happens to fall, and the mesh reproduces it as a
staircase along the *grid* rather than as the edge that is in the picture. The
low-pass turns each step into a short ramp: the edge keeps its position and its
contrast but stops snapping to the grid.

### 4. The camera budget

Depth reads as depth because **near things move and far things do not**.
Parallax that lands on everything equally does not read as distance; it reads as
a room being carried around you.

```js
const excursion = Math.min(SPHERE_RADIUS * 0.025, nearRadius * 0.10);
```

Two ceilings, whichever is tighter. The first keeps the backdrop under about
2.5% of parallax, which is where it stops registering as motion and starts
registering as "far". The second keeps the camera from travelling more than a
tenth of the way to the nearest surface — so winding the slider up can never fly
the viewer through the geometry in front of them. Dolly, drift, pointer parallax
and gyro tilt are all fractions of that one budget, so they cannot sum past it.

`nearRadius` is recomputed by `setDisplacement()`, so the budget tracks the
slider live.

How the sideways budget is split depends on the input. With a mouse, pointer
parallax and the idle drift take half each. A phone has no hovering pointer —
a finger is busy turning the view — so when tilt data is live and gyro look is
off, **tilt takes 0.8 and the drift is cut to 0.2**. Tilt is the phone's
rotation since a rest pose that settles over `TILT_SETTLE_S` (4 s), taken as a
quaternion in the screen's frame so landscape works, and treated as a window:
tilt the right edge away and the eye moves left. `TILT_FULL_DEG` (12°) spends
the whole share. Before this, a held 10° tilt moved the camera 0.05 units for a
quarter of a second and nothing after a second; now it is 0.26, and still 0.14
three seconds on.

### Positional tracking: head and AR

Tilt only knows how the phone is turned. Raising or lowering it without turning
reads the same, and nothing a page can reach measures centimetres of travel
(GPS altitude is metres out; the barometer is not exposed). Two opt-in modes
do measure position, both in metres, both mapped through `trackedOffset()`:
linear around rest, `TRACK_FULL_M` (15 cm) spends one budget, easing into a
ceiling of `TRACK_REACH` (1.5) budgets rather than stopping dead.

- **Head tracking** (face button, <kbd>T</kbd>; anywhere with a camera). The
  front camera through MediaPipe's BlazeFace detector, loaded from the CDN only
  when switched on — its WebAssembly runtime is ~11 MB. The eye midpoint gives
  the head's position across the frame and the eye spacing (~63 mm) gives scale
  and distance, so it yields right, up and toward/away *relative to the
  screen* — what parallax depends on. The raw front-camera stream is not
  mirrored, hence the sign flips. Rest settles over `HEAD_SETTLE_S` (10 s);
  with a face in view it drives the eye alone (no drift, dolly or tilt).
  It also turns the screen into a **window**: an off-axis frustum cut through
  fixed glass at the nearest surface (`HEAD_WINDOW_AT` × `nearRadius`), so the
  frame stays pinned to the glass and the distance slides with the head,
  rather than the distance staying put while near things swing. Near-to-far
  parallax is unchanged; only the anchor moves. Leaning in widens the view.
  `camera.updateProjectionMatrix()` restores the symmetric frustum the frame
  tracking stops.
- **AR** (Android Chrome only; the button appears when
  `isSessionSupported('immersive-ar')`). WebXR tracks the phone's full pose.
  Rotation is used as is; for position, the `world` group holding the meshes
  is moved to the camera's position less the scaled offset, which leaves the
  eye exactly that offset from the panorama's centre. The page's own rAF loop
  stands down while the session's loop draws, and three.js's copy of the
  headset field of view into the camera is undone on exit.

### The motion nudge

Without either mode, a quick move of the phone still registers. The
accelerometer's gravity-free `acceleration` (device axes, rotated into the
screen's) is integrated twice in the `devicemotion` handler, at the sensor's own
rate. Position leaks home over `NUDGE_POS_S`; velocity is cleared by a
zero-velocity update once readings have sat inside `NUDGE_DEADBAND` for
`NUDGE_STILL_S`. A steady velocity leak was tried first and swung the view a
quarter of the peak back past centre a second later. Eye moves opposite to the
phone, the same window as tilt. A simulated 10 cm raise in 0.4 s peaks at 0.19
units at 0.3 s and is back under 0.02 by 1.5 s. Head tracking, when it sees a
face, supersedes it.

### `?debug`

`index.html?debug` puts a readout in the corner: screen angle, the depth
budget, raw orientation and the tilt it becomes, motion permission, the nudge,
head-tracking state (face seen or lost, offset, distance, detection time), AR
state and the phone's position in the session, and the final eye offset. It is
how to test on a phone, which has no console; it moves into the AR overlay
during a session.

## The seam invariant

**This is the rule most likely to be broken by accident.**

The cube mesh keeps a **separate copy of every cube-edge vertex** for each of
the two faces that meet there, and the two copies are drawn in different
material groups with different `uFace`. If each copy reads its own face's depth
map, the two disagree by however much the maps disagree at that seam — across
one of Voltaic's edges that is 0.097 against 0.078, ordinary JPEG noise — the
copies displace to different radii, and the mesh **pulls apart along the edge**.
The gap shows the clear colour: a black tear running the length of the seam.

So the vertex stage picks its depth face from the **direction**, not from the
face being drawn:

```glsl
int dFace = faceOfDir(dir);                              // major axis, with >= tie-breaks
vec2 dUv  = clamp(gnomonicUV(dir, dFace), 0.001, 0.999);
```

Both copies of an edge vertex share a position bit for bit —
`buildSphereCube()` derives every coordinate from the one integer formula
`(2k − n) / n`, never from two expressions that only agree on paper, and
normalising equal inputs gives equal outputs — so both pick the same face, the
same UV and the same depth. (Count the distinct positions: a closed cube of n
segments has exactly 6n² + 2. More means an edge copy drifted.) `gl_Position` comes out identical and the rasteriser fills the
shared edge with no gap. The seam closes **by construction**, not by tuning.

Two consequences to preserve:

- `faceOfDir()`'s `>=` tie-breaks are load-bearing. A vertex sitting exactly on
  a cube edge hits them, and both of its copies have to land on the same side.
  It is the exact mirror of `dirToFaceUv()` in `atlas-layout.js`.
- The vertex stage must be able to read **any** face's depth, which means depth
  has to be an atlas. Paths that load six separate depth images stitch them
  into a 3×2 atlas at load (`buildDepthAtlas()`) and release the originals.
  Colour stays as six images — separate faces keep their mipmaps and anisotropy,
  which an atlas cannot have.

`DEPTH_CELL_OF_FACE = [0, 2, 4, 5, 3, 1]` maps face index → 3×2 cell index and
must match `sampleAtlas()` in `atlas-layout.js`. Cells are 512–1024px square:
512 minimum because the shader clamps its UVs a thousandth of a cell in from the
border, and at 512 that is over half a texel — far enough that bilinear
filtering never reaches into the next cell, so the atlas needs no gutter. 1024
maximum because the mesh has 257 vertices along a face edge, and four depth
texels per quad is already more than the geometry can express.

## Material kinds

`createMaterials(colorMode, depthMode, layoutId)` builds one material
per face; `MAT_KINDS` names the combinations. A material bakes **one** atlas
layout for both its samplers, which is the constraint behind the one gap below.

| Kind | Colour | Depth | Used by |
|---|---|---|---|
| `standard` | six images | none | depthless ages (Amateria, J'nanin) |
| `standardDepth` | six images | 3×2 atlas | ages with six depth faces (Voltaic) |
| `atlasSolo` | atlas | same atlas | pre-stitched ages (Edanna) |
| `atlasFg` | atlas | same atlas | LDI foreground (custom uploads, Voltaic and Amateria *Layered*) |
| `atlasBg` | atlas | same atlas | LDI backdrop; displaces at half the slider unless the version has `backdropFullDepth` |
| `atlasStandard` | 5×3 atlas | six images | video panoramas |

Every atlas bound to one material must therefore be in the same layout, and
`agreedLayout()` refuses a mismatch by name rather than rendering it scrambled.
Within a layout, each atlas carries **its own gutter fraction**
(`uColorGutter`, `uDepthGutter`, passed into
`sampleAtlas()` per call): the 3×2 gutter is 8px at the face size the atlas was
stitched at, so a colour atlas stitched at 1024 and a depth atlas at 512 inset
by different fractions. `gutterFracFor()` takes the width *as stitched* —
`fitToGpu()` records it in `userData.sourceWidth` before shrinking an atlas to
the GPU limit, since the shrunk width overstates the fraction.

### Two layers: holes and tears

A two-layer scene (custom upload with BG colour, or a version with `layers`)
draws the backdrop sphere first and the foreground over it. The foreground
says where it is see-through in its depth image's **green** channel (`maskAt()`
< 0.03); red stays the depth that shapes the mesh. A greyscale map has green
equal to red, so for it this is the old rule, "depth near zero is nothing".

- A **hole** is discarded, so the backdrop mesh shows through at its own depth
  and parallax. It used to be painted with the backdrop's colour at the same
  UV on the foreground (`seamFill`), which glued whatever was seen through a
  hole to the hole.
- Keeping holes out of red means marking one need not move the mesh. With one
  channel a hole was depth 0, which also sank the foreground into a pit there,
  and the pit's walls stretched across the view.
- A **tear** (`uTearThreshold`, at steep depth gradients) is discarded in the
  same way, so the backdrop shows there at its own depth. It used to take the
  backdrop's colour at the same UV (`seamFill`, removed): the foreground's
  stretched wall across the step stayed where it was, painted with what was
  behind, and a near object still smeared across what it hid. In Voltaic's
  *Layered* version that changed only the walkway's edge over the floor (about
  1% of a view), where a sawtooth of backdrop colour became a dark band: its
  backdrop there is the original picture of the edge.
- A version with `backdropFullDepth: true` measured its backdrop's depth on
  the foreground's scale. Its backdrop then displaces at the full slider rate
  (`bgDepthRate`) from 1% outside the foreground (`bgScaleFor()`), not at half
  the rate from radius 56, so what a tear reveals lies where the hidden surface
  is; the depth test keeps it behind wherever the two layers agree.

Voltaic's *Layered* version is built this way, from the same capture: the
estimated depth could not see through the walkway's slat gaps or the floor
grate's panels, putting the canyon floor just behind the mesh. Its foreground
is the original faces with depth filled flat across the holes (from the metal
around, so no slope to stretch) and green 0 where floor shows between the
wires; wires are kept solid only where they are dark lines over lit floor —
over dark floor they are fainter than it, and a dark-line test only caught
spoke edges. Its backdrop is that floor, reconstructed under the metal by a
pyramid (push-pull) fill ~64 px around every hole — about as far as the floor
slides at full head-tracking range — at the open floor's depth (~20 by the
walkway, 30 straight down), blending back to the estimate over 64 px more so
the backdrop has no step of its own (`voltaic/layers/build_layers.py`). Built as face images, stitched 3×2 with
`stitcher.html` at 656 px (640 of picture), exactly — the green mask survives
the stitcher bit for bit.

Amateria's *Layered* version (MAWW node 101) is the general case: every
step in the depth is cut. Its depth is redrawn at 1280 px from the 4K faces
(`myst3/colmap/sharpen_depth.py`: Depth Anything V2 Large at an input of 1036
px, fitted to the measured depth), because the measured map's outlines, made
at 518 px, were rounder than the picture: the spire roof's eaves reached ~10
px past them, sat at sky depth and were left behind in blocks. Its foreground
is those faces with a 6 px hole (green 0) on the far side of every step and
the near depth carried 3 px under it, Voltaic's way: the mesh has a vertex
every 2.5 px of a 640 px face and smooths depth over as much, so a step is a
ramp of stretched triangles, and the tear test, reaching about a pixel from
the step, left the rest of the ramp as jagged teeth. Its backdrop is the near side of every step
(two pixels 2 apart whose inverse distance differs by more than 0.8 in units
of the farthest kept distance; the tear slider's middle tears at 1 to 2)
within 160 px of it (at 640 px a face, 320 at 1280), painted by LaMa with the whole near object hidden from
it (shown part of one, LaMa carries it on into the gap: with a 64 px band a
ghost of the machinery's box came back beside it), each face padded
with 128 px of its neighbours and faces done earlier lending their finished
backdrop, at the depth of the step's far side, with `backdropFullDepth`
(`amateria/layers/build_layers.py`, stitched at 1296 px by `stitch_layers.js`).
What it leaves: small bites out of the glass balls on the front face, where
the depth steps between a ball and the rings around it. With steps inside a near object (Voltaic ENSI 16's pod: a ball in
front of its frame in front of the sky) the far side of the nearest step is
the frame, which then stayed out of the region, and LaMa painted a dark
pod-shaped blob at the frame's depth that streaked as the eye moved;
`--reach 48` lets a middle layer go with the near object when it belongs to
it: when its gap to the near side is under half (`--belong 0.5`) its gap to
the farthest far side within 48 px (96 at 1280), as the frame does (a little
behind the ball, far in front of the sky). Taking every middle layer took the
rocks round ENSI 16's walkway too, painted as sea at sea depth, which showed
as a grey outline round the walkway; the rocks lie far behind the walkway
next to how far the sea lies behind them, so they stay. Two layers cannot hold three, though: under
MAWW 101's floor it took the beams below the slats for part of them and the
gaps showed flat grey. The choice is per face: ENSI 16 and MAWW 101 are
built with `--reach 48`, MAWW 101 with `--nearest-faces 2` so its floor keeps
the nearest step (cleaner spire and machinery on the other faces); MASS 84
keeps the nearest step throughout (`--reach 0`; reach made no visible
difference). Moving the measured
depth's edges onto the picture's by colour was tried first (pixels within
14–18 px of a jump relabelled near or far) and dropped: in these dark faces
the labels came out speckled, each speckle tore, and the rings and arcs broke
apart.

**Known gap:** the video path's colour is a 5×3 atlas, so it cannot borrow the
3×2 depth stitch and keeps its six per-face depth textures — which means the
vertex stage there can still only see the face it is drawing, and the seam
invariant above does not hold for it. It is unreachable from the shipped
locations (no version declares `video-5x3`). Fixing it properly means letting a
material carry two independent atlas layouts, or teaching `buildDepthAtlas()` to
write 5×3 cells with their rotations.

## Verifying a change in a real browser

The cube is one of the few places in this repository where you cannot read the
diff and know it works — the artefacts are geometric and only appear at
particular angles. Headless Chromium **does** work in Claude Code's remote
container. Serve the repo root with
`python3 -m http.server`, drive it with Playwright installed into a scratch
directory — never into the repo — and expect five non-obvious things:

1. **Software GL.** Launch the pre-installed browser at
   `/opt/pw-browsers/chromium-*/chrome-linux64/chrome` with
   `--use-gl=angle --use-angle=swiftshader --enable-unsafe-swiftshader`. There
   is no GPU here, and SwiftShader renders this mesh at roughly one frame per
   second.
2. **The jsDelivr import fails inside the browser**, even though `curl` reaches
   it — the headless browser does not inherit the agent proxy. Fetch
   `three.module.js` once with `curl` and `page.route()` the CDN URL to the
   local copy, or the page stays black with `ERR_CONNECTION_RESET`.
3. **Force `preserveDrawingBuffer: true`** by wrapping
   `HTMLCanvasElement.prototype.getContext`. Three.js does not set it, and
   without it a screenshot of the WebGL canvas is not the frame you rendered.
4. **Stop the rAF loop before capturing**, then call `gl.finish()`. SwiftShader
   is far slower than the rAF cadence, so a live capture lands mid-raster.
5. **Give the synthetic clock and `performance.now()` the same origin.** Freeze
   `performance.now` to pin the camera drift so frames are repeatable, and feed
   rAF `frozen + n * step`. The load tween reads its start time from
   `performance.now()` and its progress from the rAF stamp; give those two
   different origins and the transition never finishes.

**If the screenshot comes back as a scatter of ~20px tiles**, it is one of
points 3–5, in that order of likelihood — not a rendering bug. `FRAG_BLOCK` is a
50-column block wipe, so a transition caught mid-reveal looks exactly like a
partial raster.

**Testing tilt.** Emulate a phone, step rAF by hand, and dispatch
`new DeviceOrientationEvent('deviceorientation', {alpha, beta, gamma})`. Four
traps: this Chromium has `DeviceOrientationEvent.requestPermission()` and
answers `prompt` unless the context calls
`grantPermissions(['accelerometer', 'gyroscope', 'magnetometer'])`; the grant
resolves asynchronously, so wait after the first tap or your "rest" pose is
recorded before the page is listening; Playwright's landscape devices leave
`screen.orientation.angle` at 0, so set it with CDP
`Emulation.setDeviceMetricsOverride({ screenOrientation: { type:
'landscapePrimary', angle: 90 } })`; and to measure the camera rather than
pixels, serve a copy of three.js whose `render()` records the camera and can
skip drawing — SwiftShader cannot draw hundreds of stepped frames in time.

**Testing head tracking.** Chromium plays a file as the webcam:
`--use-fake-ui-for-media-stream --use-fake-device-for-media-stream
--use-file-for-fake-video-capture=face.y4m`. Build the `.y4m` from a portrait
cropped so the face moves by known amounts in phases (MediaPipe's own test
image at `storage.googleapis.com/mediapipe-assets/portrait.jpg` works), route
the jsDelivr and `storage.googleapis.com` URLs to local copies, and read the
phase from the video element's `currentTime`.

**Testing AR.** Meta's IWER emulates a WebXR device in the page: inject
`iwer@2.2.1/build/iwer.min.js` with `addInitScript`, then
`new IWER.XRDevice(IWER.metaQuest3).installRuntime()` and move it with
`device.position.set()`. Its canvas covers the page, so click the exit button
with `element.click()`.

Two measurements worth reusing, because they turn "looks better" into a number:

- **Tears.** Count pixels with `max(rgb) < 8` and label connected components; a
  tear is a long, thin one. A view along the top-face seam at full depth went
  from a 436px black streak to zero black pixels. Dark scenery (Edanna's forest
  is ~3.5% near-black) shows as many small blobs with no thin streaks — check
  the shape, not the count.
- **Parallax.** Capture two frames at different frozen clock values and
  phase-correlate 128px tiles. A good result is a smooth gradient from small
  shifts on distant tiles to large ones on near tiles. An incoherent field means
  the camera is moving the whole scene rigidly — the "small box".
