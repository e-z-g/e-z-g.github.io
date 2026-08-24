# CLAUDE.md

Guidance for AI assistants working in this repository.

## What this is

`e-z-g.github.io` is a **GitHub Pages static site** — a collection of independent,
self-contained web tools and interactive experiments published at
<https://e-z-g.github.io/>.

There is **no build step, no bundler, no package manager, and no CI**. No
`package.json`, no lockfile, no `requirements.txt`, no `.github/workflows`.
`.nojekyll` at the root disables Jekyll processing, so every file is served
exactly as committed.

**Pushing to `main` deploys.** Whatever lands in `main` is live within a minute
or two. There is no staging environment and nothing catches a broken page for
you — verify changes locally before pushing.

## Repository layout

```
index.html            tool directory (the site's front page)
README.md             same directory, in markdown
.nojekyll             disables Jekyll on Pages
*.html                standalone single-file tools (see below)

cube/                 cubemap VR viewer + face stitcher (ES modules, three.js)
  README.md             the viewer's rendering pipeline and its invariants
  index.html            the viewer
  stitcher.html         builds atlases the viewer reads
  atlas-layout.js       the shared contract between the two
  amateria/ edanna/ jnanin/ voltaic/   scene assets (images, audio)

cythera/              retro-Mac / Cythera subsystem — the largest area
  cythera_data_viewer.html    Delver archive viewer (~11k lines)
  resource_fork_browser.html  generic classic-Mac resource fork browser
  mobile.html                 Cythera in an infinite-mac emulator iframe
  colorcyclecanvas.html       colour-cycling paint studio
  js/                         shared classic scripts (see "Cythera" below)
  utilities/                  Node + Python check harnesses and converters
  res/                        game data, fonts, PDFs, extracted assets
  deprecated/                 retired experiments; do not extend

ev/                   star/planet viewer
fpqr/                 Fancy-Pants QR encoder (index.html + css/ + js/)
wine/                 VinoVision inventory/AR tool
```

## The three code regimes

Different areas make deliberately different tradeoffs. Match the regime of the
file you are editing; do not "modernise" across the boundary.

### 1. Standalone single-file tools (root `*.html`)

`pixelator.html`, `scanimation.html`, `gif2sheet.html`, `unpremultiply.html`,
`vidscale.html`, `ez-pw.html`, `check.html`, `frame.html`, `vrvid.html`,
`anachronism.html`, `infj4.html`.

One HTML file each: markup, styles and script inline. Several pull React,
Babel-standalone, Tailwind, or photo-sphere-viewer from a CDN at runtime
(`cdn.tailwindcss.com`, `unpkg.com`, `cdnjs.cloudflare.com`, `jsdelivr`) —
that CDN dependency *is* the build system here. `anachronism.html`,
`unpremultiply.html`, `check.html`, `frame.html` and `vidscale.html` are fully
self-contained with no external scripts.

These open correctly by double-clicking the file. Keep it that way.

### 2. ES modules (`cube/`, and the split-out `fpqr/js/`)

`cube/index.html` and `cube/stitcher.html` use `<script type="module">` and an
import map pointing at `three@0.160.0` on jsDelivr. They import
`./atlas-layout.js` relatively, so **these pages must be served over HTTP** —
`file://` gives an opaque origin and module fetches fail CORS.

`cube/atlas-layout.js` is the *contract* between the stitcher and the viewer:
face indices, face-name-to-material-slot mapping, and atlas layouts. The
stitcher writes cells at particular rotations and the viewer's `sampleAtlas()`
reads them back on that assumption. Change one side without the other and the
cube poles smear silently — read the header comment in that file before
touching either page.

**`cube/README.md` is the map of the viewer itself** — the depth pipeline, the
material kinds, the seam invariant, and how to verify a change in a real
browser. Read it before editing `cube/index.html`. Two rules from it are worth
repeating here, because both fail *silently and only at certain camera angles*:

- **The vertex stage must pick its depth face from the direction, not from
  `uFace`.** A `BoxGeometry` keeps a separate copy of every cube-edge vertex per
  adjoining face. If each copy reads its own face's depth map, the two disagree
  by whatever the maps disagree by at that seam, the copies displace to
  different radii, and the mesh pulls apart — a black tear the length of the
  edge. `faceOfDir()` makes both copies choose the same face, so the seam closes
  by construction. Its `>=` tie-breaks are load-bearing.
- **Depth has to reach the vertex stage as an atlas**, since that is what lets a
  face read its neighbour. Colour stays as six separate images where it can, so
  it keeps mipmaps and anisotropy.

`fpqr/` splits its script into `js/qr-engine.js`, `js/renderer.js`,
`js/app.js` and `js/gif-exporter.js`, loaded as ordinary classic `<script src>`
tags (not modules), with CSS in `css/styles.css`.

### 3. Classic scripts, `file://`-safe (`cythera/`)

**This is a hard constraint, not a style preference.** `cythera/js/*.js` are
classic scripts — no `type="module"`, no `import`, no `export`. Everything is
declared at top level and shared as globals. The reason: these pages have to
keep working when copied to a USB stick and double-clicked, and a module script
is fetched with CORS which fails from an opaque `file://` origin.

Consequences you must respect when editing `cythera/`:

- Never add `type="module"` to a `<script>` tag in these pages.
- Declare at top level; let things be globals.
- Keep the `<script src>` order in the HTML matching the dependency order.
- `utilities/verify_viewer.mjs` and `utilities/page_scripts.mjs` **fail** if a
  module script appears — that check is the enforcement mechanism.

Load order (both `cythera_data_viewer.html` and `resource_fork_browser.html`
include these five, in this order, before their own inline script):

| File | Purpose |
|---|---|
| `js/mac-bytes.js` | big-endian readers, Mac Roman, CRC-32, `safeFileName`. **First** — everything else needs it. |
| `js/mac-containers.js` | BinHex 4.0 (`.hqx`), MacBinary, AppleSingle/Double unwrapping → `{kind, name, type, creator, data, rsrc}` |
| `js/mac-resfork.js` | `openResourceFork(bytes)` → a fork object (not globals, so two forks can be open at once) |
| `js/mac-media.js` | decoded pixels/samples → WAV and hand-written indexed PNG (colour-type 3 + PLTE/tRNS, so the CLUT survives byte for byte) |
| `js/mac-export.js` | store-only ZIP writer + browser download helpers |

`mobile.html` and `colorcyclecanvas.html` do **not** use `js/` — each is
self-contained with a single inline script.

## Running things locally

Most pages open fine from `file://`. The `cube/` pages and anything loading a
relative module or asset need a server:

```sh
python3 -m http.server 8000     # from the repo root
# then http://localhost:8000/
```

## Looking at a page in a real browser

Most changes here can be judged by reading them. Rendering changes cannot —
`cube/`, `pixelator.html`, `scanimation.html` and `colorcyclecanvas.html`
produce artefacts that only appear at particular angles, zoom levels or frames.

Headless Chromium **does** work in Claude Code's remote container, driven by
Playwright installed into a scratch directory (never into the repo — see "Do not
add tooling"). Serve the repo with `python3 -m http.server`, then:

- Launch the pre-installed browser at
  `/opt/pw-browsers/chromium-*/chrome-linux/chrome` with
  `--use-gl=angle --use-angle=swiftshader --enable-unsafe-swiftshader`. There is
  no GPU; SwiftShader is the renderer and it is slow.
- **CDN imports fail inside the browser** even though `curl` reaches them, because
  the headless browser does not inherit the agent proxy. Fetch `three.module.js`
  once with `curl` and `page.route()` the jsDelivr URL to the local copy.
- For a WebGL page, force `preserveDrawingBuffer: true` by wrapping
  `HTMLCanvasElement.prototype.getContext`, stop the rAF loop before capturing,
  and call `gl.finish()`. Otherwise the screenshot is a scatter of tiles.

`cube/README.md` has the full recipe, including how to pin an animated camera to
a repeatable frame and two ways to turn "looks better" into a number.

This does **not** apply to `cythera/utilities/` — those harnesses run the page's
real JavaScript inside a `node:vm` against a DOM stub on purpose, and are
documented below. Do not rewrite them to drive a browser.

## Cythera checks

`cythera/utilities/` holds the only test suite in the repository. Everything
runs on plain Node 18+ (`.mjs`, no dependencies) or Python 3. Run from the
`cythera/` directory:

```sh
cd cythera
node utilities/check_all.mjs            # everything, one table
node utilities/check_all.mjs --quick    # skip the slow browser-ish smokes
node utilities/check_all.mjs viewer     # one page: viewer | browser | mobile
```

`check_all.mjs` is the entry point: it does the setup (extracting resource forks
from the `.hqx` files into `$TMPDIR`), runs the fifteen individual harnesses,
validates exported ZIPs with `unzip -t`, and prints a single pass/skip/fail
table. A check whose inputs are missing is reported as **skip**, not fail.

### Data setup: `sources/` vs `res/`

The harnesses expect a `cythera/sources/` directory that **is not in the
repository** — the committed data lives in `cythera/res/` instead, under
slightly different names. Before a full run, bridge the two:

```sh
cd cythera
mkdir -p sources
ln -sf "../res/Cythera Data.Hqx" "sources/Cythera Data.hqx"
ln -sf "../res/Cythera.hqx"      "sources/Cythera.hqx"
```

`sources/` is scratch — do not commit it. Two further inputs are optional and
absent by default, so their checks always skip:

- `sources/github_delvmod/code` — a checkout of the delvmod source, used to
  cross-check the viewer's tables and graphics against the original engine.
- `cythera/infinite-mac` — a checkout of `mihaip/infinite-mac`, used by
  `mobile_api_check.mjs`. It is **gitignored** on purpose.

### How the harnesses work

There is no browser automation here. `browser_smoke.mjs` documents why: Chrome's
`ProcessSingleton` binds a unix socket at startup and the author's sandbox
denies `bind()`. Everything else therefore runs the page's real JavaScript
inside a `node:vm` against a hand-written DOM stub. (A headless browser *can* be
run in Claude Code's remote container — see "Looking at a page in a real
browser" above — but these harnesses are committed, have to run on the author's
machine, and must stay dependency-free.)

- `page_scripts.mjs` — collects the scripts a page actually runs, in document
  order (inline plus `<script src>`), and throws on a module script. Use
  `pageSource(path)` / `describeScripts(path)` rather than re-inventing a
  regex; a harness that only reads the inline block silently tests the page with
  its decoders missing.
- `verify_viewer.mjs` — static integrity: JS syntax, inline handlers naming
  functions that exist, `getElementById` targets present in the markup. Cheap,
  runs on all three pages, catches the regressions a browser only reports at
  click time.
- `*_snapshot.mjs` — hash the decoder output so a refactor that changes bytes is
  visible.
- `viewer_smoke.mjs` / `preview_smoke.mjs` — drive the actual UI (open every
  category, render every gallery, open every resource) through a fuller DOM
  stub that includes a working 2D canvas.
- `mobile_input_check.mjs`, `mobile_undither_check.mjs`, `mobile_api_check.mjs`
  — cover `mobile.html`'s touch handling, its dedither path, and its use of
  infinite-mac's documented embed API.
- Python converters: `binhex_decode.py`, `resource_fork_parser.py`,
  `quickdraw_pict_decoder.py`, `pictscan.py`, `qtma2midi.py`, `midi2wav.py`,
  `delv_graphics_ref.py`.

### Known failing checks

Three viewer harnesses currently fail with
`script body threw while loading: Cannot read properties of null (reading 'createImageData')`:

- `decoder_snapshot.mjs`
- `loader_test.mjs`
- `export_test.mjs`

Cause: these share a minimal DOM stub whose `getContext()` returns `null`, but
`cythera_data_viewer.html` gained an animated colour-cycling footer scene that
asks for a 2D context while the script body is loading. `viewer_smoke.mjs`
passes because its stub implements a real 2D context. The fix is to give the
minimal stub a canvas (as `rsrc_sandbox.mjs` and `viewer_smoke.mjs` do), not to
change the page. Treat this as pre-existing — do not report it as a regression
you caused, and if you touch those harnesses, fixing it is welcome.

## Conventions

**Comments explain *why*, at length.** This codebase's distinguishing habit is
long header comments recording the reasoning, the bug that motivated the design,
and what was tried and rejected — see `cube/atlas-layout.js`,
`cythera/js/mac-bytes.js`, `cythera/utilities/check_all.mjs`. When you make a
non-obvious choice, write down why, in that voice. Do not strip these comments.

**Commit messages are prose, not conventional-commits.** They read like a
sentence describing the change from the user's side:

> `Ring the square, not the sprite; and read the sheet a name at a time`
> `On a phone the canvas comes first and never leaves the screen`
> `Two kinds of back, and a list view for the galleries`

Match that register. No `feat:` / `fix:` prefixes, no scope tags.

**Adding a new tool** means three edits, not one:

1. the tool file itself,
2. a link in `index.html` under the right section (360° / VR · Image / video ·
   Utilities · Retro Mac / Cythera),
3. a matching row in `README.md`'s tables.

`index.html` and `README.md` list the same tools in the same four sections;
they drift easily, so update both.

**Do not add tooling.** No `package.json`, no bundler, no formatter config, no
transpile step. If something needs a dependency, load it from a CDN (as the root
tools do) or write it by hand (as `cythera/` does).

**`cythera/deprecated/`** holds retired work (`documentation_to_pdf/`, a
graphics tone experiment). Read it for context; do not extend it.

## Gotchas

- Editing `cythera/*.html` means editing files of 2k–11k lines. Use targeted
  `grep` + `sed -n` to locate a region rather than reading the whole file.
- `cythera_data_viewer.html` fetches its default archive, font and dialogue
  background from `raw.githubusercontent.com/e-z-g/e-z-g.github.io/main/...`.
  Those URLs are pinned to `main`, so an asset renamed on a branch breaks the
  live page only after merge — and a local edit to `cythera/res/` will not be
  reflected until it is pushed.
- `cube/` assets are loaded *relatively* on purpose (Pages CDN, no cross-origin
  handshake, no raw.githubusercontent throttling). Do not switch them to raw
  URLs.
- Indexed-colour PNGs in `cythera/` are written by hand rather than through
  `canvas.toBlob()`, because `toBlob` drops the palette and adds an iCCP profile
  that colour-manages pixels which are already exactly right.
- `repomix_output.md`, `.DS_Store` and `cythera/infinite-mac` are gitignored.
