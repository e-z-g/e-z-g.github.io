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

Read the header comment in `atlas-layout.js` before touching either page. The
stitcher writes cells at particular rotations and the viewer reads them back on
that assumption; change one side alone and the poles smear without an error.

## The scene

The camera sits at the origin of a **sphereified cube**: a `BoxGeometry` scaled
by `(-1, 1, 1)` so we see its inside, with every vertex normalised onto a sphere
of radius 50. `CUBE_SEGMENTS` is 256 per face (128 on low-power devices), which
is ~790k triangles — the mesh is what bends, so a depth edge can only turn where
there is a vertex, and a coarser grid turns every object edge into a staircase.

Two meshes:

- `fgCubeMesh` — radius 50, `renderOrder` 1. The picture.
- `bgCubeMesh` — radius 56, `renderOrder` 0. Only visible for dual-layer (LDI)
  custom uploads, where it is the backdrop behind the foreground's tears.

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

## The seam invariant

**This is the rule most likely to be broken by accident.**

A `BoxGeometry` keeps a **separate copy of every cube-edge vertex** for each of
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

Both copies of an edge vertex share a position bit for bit — `BoxGeometry`
generates the same grid coordinates for both faces, and `normalize()` of equal
inputs gives equal outputs — so both pick the same face, the same UV and the
same depth. `gl_Position` comes out identical and the rasteriser fills the
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

`createMaterials(colorMode, depthMode, seamFill, layoutId)` builds one material
per face; `MAT_KINDS` names the combinations. A material bakes **one** atlas
layout for both its samplers, which is the constraint behind the one gap below.

| Kind | Colour | Depth | Used by |
|---|---|---|---|
| `standard` | six images | none | depthless ages (Amateria, J'nanin) |
| `standardDepth` | six images | 3×2 atlas | ages with six depth faces (Voltaic) |
| `atlasSolo` | atlas | same atlas | pre-stitched ages (Edanna) |
| `atlasFg` | atlas | same atlas | custom LDI foreground; `seamFill` on |
| `atlasBg` | atlas | same atlas | custom LDI backdrop; displaces at a lower rate |
| `atlasStandard` | 5×3 atlas | six images | video panoramas |

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
   `/opt/pw-browsers/chromium-*/chrome-linux/chrome` with
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
