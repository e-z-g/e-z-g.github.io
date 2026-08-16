# e-z-g.github.io

A collection of web-based tools and interactive viewers, live at
<https://e-z-g.github.io/>. Everything is static and runs client-side in the
browser — no build step, no server, no uploads.

## 360° & VR

- **[Cubemap VR Viewer](https://e-z-g.github.io/cube/)** — Interactive 360° parallax cubemap viewer with depth-driven square transitions, gyroscope support, and custom LDI upload.
- **[Cubemap Face Stitcher](https://e-z-g.github.io/cube/stitcher.html)** — Assemble six cube faces into the atlas the viewer's custom LDI mode loads, with per-face rotation and flip.
- **[Video Sphere Viewer](https://e-z-g.github.io/vrvid.html)** — Play any equirectangular 360° video on a sphere; pass one in with `?video=`, with gyroscope and fullscreen.

## Image & video

- **[Pixelator](https://e-z-g.github.io/pixelator.html)** — Nearest-neighbour image downscaler for clean pixel art.
- **[PNG Alpha Tools](https://e-z-g.github.io/unpremultiply.html)** — Remove premultiplied alpha from PNG images, from a file or a URL.
- **[GIF Sprite Extractor](https://e-z-g.github.io/gif2sheet.html)** — Split an animated GIF into its frames and export them as a sprite sheet.
- **[Custom Video Scaler](https://e-z-g.github.io/vidscale.html)** — Rescale a video to arbitrary dimensions with smooth or pixelated sampling, and re-export it.
- **[3D Print Scanimation Generator](https://e-z-g.github.io/scanimation.html)** — Interlace up to six frames into a printable base plate and sliding barrier grid, with SVG and multi-colour 3MF export.
- **[Star/Planet Viewer](https://e-z-g.github.io/ev/)** — Generative space scene with star field and planet image, with PNG export.
- **[Anachronism Machine](https://e-z-g.github.io/anachronism.html)** — Reimagine a modern object as a period advertisement from any of 13 eras, with era-matched typography and palette, optional Claude-written copy and AI illustration, and PNG export.

## Codes & utilities

- **[Fancy-Pants QR Encoder](https://e-z-g.github.io/fpqr/)** — QR generator with custom module geometry, halftone and emoji fills, gradients, and an anatomy view of the finder, alignment, and data blocks.
- **[Input-Optimized Passwords](https://e-z-g.github.io/ez-pw.html)** — Generate strong passwords that are quick to type on an on-screen keyboard, tuned to the keyboard layout and starting focus position.
- **[Instant Mobile Tester](https://e-z-g.github.io/check.html)** — Paste, drop, or upload an HTML file on your phone and run it immediately in a preview.
- **[VinoVision](https://e-z-g.github.io/wine/)** — Photograph a wine shelf to extract every visible bottle into a filterable database, with an AR finder for locating a pick back on the shelf.

## Retro Mac

- **[Cythera Graphics Browser](https://e-z-g.github.io/cythera/databrowser.html)** — Browse the sprites, portraits, skill icons, and tile sheets inside a Cythera Data archive.
- **[Cythera Data Viewer](https://e-z-g.github.io/cythera/cythera_data_viewer.html)** — Expanded Cythera browser with decoded scripts, character and creature records, and full-text search across the archive.
- **[Cythera Mobile](https://e-z-g.github.io/cythera/infinite.html)** — Cythera running on an emulated Mac OS 7.6 with touch-friendly display and speed controls.
- **[Mac Resource Fork Browser](https://e-z-g.github.io/cythera/resource_fork_browser.html)** — Decode raw resource forks, MacBinary (`.bin`), and BinHex (`.hqx`) locally, with text, summary, and ZIP export.
- **[JumpStart 4th Grade Player](https://e-z-g.github.io/infj4.html)** — JumpStart 4th Grade: Haunted Island, booted in an emulated Power Macintosh G3.

## Local preview

Most pages are single self-contained HTML files you can open straight from
disk. The two cubemap pages load their assets relatively and share an ES
module (`cube/atlas-layout.js`), so they need to be served:

```
python3 -m http.server 8000
```

Then open <http://localhost:8000/>.

## Repository layout

| Path | Contents |
| --- | --- |
| `index.html` | Landing page linking every tool — update it alongside this README when adding one. |
| `cube/` | Cubemap viewer, stitcher, `atlas-layout.js`, and the scene image sets. |
| `cythera/` | Cythera browsers, the emulator page, and the `res/` data archive. |
| `ev/` | Star/planet scene and its planet image. |
| `fpqr/` | QR encoder with its own `css/` and `js/`. |
| `wine/` | VinoVision and its sample photo. |
| `*.html` | Standalone single-file tools. |

`cube/atlas-layout.js` is the single definition of the atlas format the
stitcher writes and the viewer reads. Both layouts (5×3 and the compact 3×2)
are described there; changing one side without the other will misalign the
pole faces.
