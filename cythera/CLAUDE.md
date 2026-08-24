# CLAUDE.md

Guidance for AI assistants working in this repository.

> While this directory still lives inside `e-z-g.github.io`, the root
> `CLAUDE.md` there also applies and overlaps with this file. After the split
> described in `SPLIT.md`, this becomes the only one. See that file for what
> remains to be done.

## What this is

A **GitHub Pages static site** of tools for reading, and eventually editing,
the data of *Cythera* (Ambrosia Software, 1999) and of classic Mac OS files
generally. Published at <https://e-z-g.github.io/cythera/>.

There is **no build step, no bundler, no package manager, and no CI**. No
`package.json`, no lockfile, no `requirements.txt`, no `.github/workflows`.
`.nojekyll` at the root disables Jekyll processing, so every file is served
exactly as committed.

**Pushing to `main` deploys.** Whatever lands in `main` is live within a minute
or two. There is no staging environment and nothing catches a broken page for
you — run the checks below before pushing.

## Layout

```
cythera_data_viewer.html    Delver archive viewer (~11k lines)
resource_fork_browser.html  generic classic-Mac resource fork browser
mobile.html                 Cythera in an infinite-mac emulator iframe
colorcyclecanvas.html       colour-cycling paint studio
js/                         shared classic scripts (see below)
utilities/                  Node + Python check harnesses and converters
res/                        game data, fonts, PDFs, extracted assets
reference/delvmod           submodule: the delvmod reference implementation
deprecated/                 retired experiments; do not extend
```

## The hard constraint: classic scripts, `file://`-safe

**This is not a style preference.** `js/*.js` are classic scripts — no
`type="module"`, no `import`, no `export`. Everything is declared at top level
and shared as globals. The reason: these pages have to keep working when copied
to a USB stick and double-clicked, and a module script is fetched with CORS,
which fails from an opaque `file://` origin.

Consequences you must respect:

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

The pages open fine from `file://`. For a server:

```sh
python3 -m http.server 8000
```

## Checks

`utilities/` holds the test suite. Everything runs on plain Node 18+ (`.mjs`, no
dependencies) or Python 3. Run from the repository root:

```sh
node utilities/check_all.mjs            # everything, one table
node utilities/check_all.mjs --quick    # skip the slow browser-ish smokes
node utilities/check_all.mjs viewer     # one page: viewer | browser | mobile
```

`check_all.mjs` is the entry point: it does the setup (extracting resource forks
from the `.hqx` files in `res/` into `$TMPDIR`), runs the fifteen individual
harnesses, validates exported ZIPs with `unzip -t`, and prints a single
pass/skip/fail table.

### Data setup

Nothing to do: `check_all.mjs` finds its inputs itself, reading the committed
archives straight out of `res/`.

Two further inputs come from outside the repository:

- **delvmod** — the reference implementation, used by `delv_crosscheck.mjs` and
  `delv_graphics_check.mjs` to catch the tables copied into the viewer drifting
  from the original. It is a **submodule**, so a fresh checkout needs one
  command before those two checks can run:

  ```sh
  git submodule update --init reference/delvmod
  ```

  Set `$DELVMOD` instead to point at a working copy kept elsewhere.

- **infinite-mac** — a checkout of `mihaip/infinite-mac`, used by
  `mobile_api_check.mjs`. Large, and **gitignored** on purpose, so this check
  skips by default. Put it at `infinite-mac`, beside the repo as
  `../infinite-mac`, or point `$INFINITE_MAC` at it.

A check whose inputs are genuinely missing is reported as **skip**, not fail.
A clean run is **14 ok, 0 failed, 1 skipped** — the skip being infinite-mac.
Anything else is a regression.

### How the harnesses work

There is no browser automation here. `browser_smoke.mjs` documents why: Chrome's
`ProcessSingleton` binds a unix socket at startup and the author's sandbox
denies `bind()`. Everything else therefore runs the page's real JavaScript
inside a `node:vm` against a hand-written DOM stub.

- `page_scripts.mjs` — collects the scripts a page actually runs, in document
  order (inline plus `<script src>`), and throws on a module script. Use
  `pageSource(path)` / `describeScripts(path)` rather than re-inventing a
  regex; a harness that only reads the inline block silently tests the page with
  its decoders missing.
- `dom_stub.mjs` — the minimal DOM the non-UI harnesses evaluate a page in, and
  the one 2D canvas implementation. Five harnesses each carried their own copy
  of this; when the viewer gained its animated footer, which asks for a context
  while the script body is still loading, three of them broke at once and two
  more were skipping and so did not show it. Import `makeSandbox()` rather than
  pasting a sixth copy.
- `verify_viewer.mjs` — static integrity: JS syntax, inline handlers naming
  functions that exist, `getElementById` targets present in the markup. Cheap,
  runs on all three pages, catches the regressions a browser only reports at
  click time.
- `*_snapshot.mjs` — hash the decoder output so a refactor that changes bytes is
  visible.
- `viewer_smoke.mjs` / `preview_smoke.mjs` — drive the actual UI (open every
  category, render every gallery, open every resource) through a fuller DOM
  stub, which shares its canvas with `dom_stub.mjs`.
- `delv_crosscheck.mjs` / `delv_graphics_check.mjs` — read delvmod's Python and
  compare it against the tables and the graphics decoder copied into the viewer.
  A copy drifts silently; nothing in a browser complains that a syscall is
  labelled with the wrong name. This is the closest thing here to a correctness
  oracle, and it is worth keeping green.
- `mobile_input_check.mjs`, `mobile_undither_check.mjs`, `mobile_api_check.mjs`
  — cover `mobile.html`'s touch handling, its dedither path, and its use of
  infinite-mac's documented embed API.
- Python converters: `binhex_decode.py`, `resource_fork_parser.py`,
  `quickdraw_pict_decoder.py`, `pictscan.py`, `qtma2midi.py`, `midi2wav.py`,
  `delv_graphics_ref.py`.

## Conventions

**Comments explain *why*, at length.** This codebase's distinguishing habit is
long header comments recording the reasoning, the bug that motivated the design,
and what was tried and rejected — see `js/mac-bytes.js`,
`utilities/check_all.mjs`, `utilities/dom_stub.mjs`. When you make a non-obvious
choice, write down why, in that voice. Do not strip these comments.

**Commit messages are prose, not conventional-commits.** They read like a
sentence describing the change from the user's side:

> `Ring the square, not the sprite; and read the sheet a name at a time`
> `On a phone the canvas comes first and never leaves the screen`
> `Two kinds of back, and a list view for the galleries`

Match that register. No `feat:` / `fix:` prefixes, no scope tags.

**Do not add tooling.** No `package.json`, no bundler, no formatter config, no
transpile step. If something needs a dependency, write it by hand — as
everything here does.

**`deprecated/`** holds retired work (`documentation_to_pdf/`, a graphics tone
experiment). Read it for context; do not extend it.

## Gotchas

- Editing `*.html` here means editing files of 2k–11k lines. Use targeted
  `grep` + `sed -n` to locate a region rather than reading the whole file.
- `cythera_data_viewer.html` fetches its default archive, font and dialogue
  background from `raw.githubusercontent.com/e-z-g/cythera/main/res/...`.
  Those URLs are pinned to `main`, so an asset renamed on a branch breaks the
  live page only after merge — and a local edit to `res/` will not be reflected
  until it is pushed.
- Indexed-colour PNGs are written by hand rather than through
  `canvas.toBlob()`, because `toBlob` drops the palette and adds an iCCP profile
  that colour-manages pixels which are already exactly right.
- `repomix_output.md`, `.DS_Store`, `sources/` and `infinite-mac` are
  gitignored.
