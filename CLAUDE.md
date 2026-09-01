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

The Cythera and retro-Mac tools used to live here in `cythera/`. They are their
own repository now — <https://github.com/e-z-g/cythera> — served at the same
URLs, `e-z-g.github.io/cythera/…`, because a project repo of that name occupies
that path. `index.html` and `README.md` still link to them and should keep
doing so — but **the filenames on the other side do change, and nothing here
notices**. Three of the four links were 404 for a while: the viewer is
`explorer.html` now, not `cythera_data_viewer.html`; the paint tool is
`canvas.html`, not `colorcyclecanvas.html`; and the Mac Resource Fork Browser
was retired outright, its decoders folded into the viewer's Resource Fork
gallery. Check them against that repository when it moves.

```
index.html            tool directory (the site's front page)
README.md             same directory, in markdown
.nojekyll             disables Jekyll on Pages
*.html                standalone single-file tools (see below)

cube/                 cubemap VR viewer + face stitcher (ES modules, three.js)
  index.html            the viewer
  stitcher.html         builds atlases the viewer reads
  atlas-layout.js       the shared contract between the two
  amateria/ edanna/ jnanin/ voltaic/   scene assets (images, audio)

ev/                   star/planet viewer
fpqr/                 Fancy-Pants QR encoder (index.html + css/ + js/)
wine/                 VinoVision inventory/AR tool
```

## The two code regimes

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

`fpqr/` splits its script into `js/qr-engine.js`, `js/renderer.js`,
`js/app.js` and `js/gif-exporter.js`, loaded as ordinary classic `<script src>`
tags (not modules), with CSS in `css/styles.css`.

## Running things locally

Most pages open fine from `file://`. The `cube/` pages and anything loading a
relative module or asset need a server:

```sh
python3 -m http.server 8000     # from the repo root
# then http://localhost:8000/
```

## Conventions

**Comments explain *why*, at length.** This codebase's distinguishing habit is
long header comments recording the reasoning, the bug that motivated the design,
and what was tried and rejected — see `cube/atlas-layout.js`. When you make a
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
transpile step. If something needs a dependency, load it from a CDN, as the
root tools do, or write it by hand.

## Gotchas

- `cube/` assets are loaded *relatively* on purpose (Pages CDN, no cross-origin
  handshake, no raw.githubusercontent throttling). Do not switch them to raw
  URLs.
- `repomix_output.md` and `.DS_Store` are gitignored.
