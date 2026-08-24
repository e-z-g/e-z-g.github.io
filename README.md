# e-z-g.github.io

Web tools and interactive experiments: <https://e-z-g.github.io/>

## 360° / VR

| | |
|---|---|
| [Cubemap VR Viewer](https://e-z-g.github.io/cube/) | [Cubemap Face Stitcher](https://e-z-g.github.io/cube/stitcher.html) |
| [Video Sphere Viewer](https://e-z-g.github.io/vrvid.html) | |

## Image / video

| | |
|---|---|
| [Pixelator](https://e-z-g.github.io/pixelator.html) | [PNG Alpha Tools](https://e-z-g.github.io/unpremultiply.html) |
| [GIF Sprite Extractor](https://e-z-g.github.io/gif2sheet.html) | [Custom Video Scaler](https://e-z-g.github.io/vidscale.html) |
| [3D Print Scanimation Generator](https://e-z-g.github.io/scanimation.html) | [Star/Planet Viewer](https://e-z-g.github.io/ev/) |
| [Anachronism Machine](https://e-z-g.github.io/anachronism.html) | |

## Utilities

| | |
|---|---|
| [Fancy-Pants QR Encoder](https://e-z-g.github.io/fpqr/) | [Input-Optimized Passwords](https://e-z-g.github.io/ez-pw.html) |
| [Instant Mobile Tester](https://e-z-g.github.io/check.html) | [VinoVision](https://e-z-g.github.io/wine/) |
| [Desktop View](https://e-z-g.github.io/frame.html) | |

## Retro Mac / Cythera

| | |
|---|---|
| [Cythera Data Viewer](https://e-z-g.github.io/cythera/cythera_data_viewer.html) | [Cythera Mobile](https://e-z-g.github.io/cythera/mobile.html) |
| [ColorCycleCanvas](https://e-z-g.github.io/cythera/colorcyclecanvas.html) | [Mac Resource Fork Browser](https://e-z-g.github.io/cythera/resource_fork_browser.html) |
| [JumpStart 4th Grade Player](https://e-z-g.github.io/infj4.html) | |

## Local preview

Most tools are static HTML. The cubemap viewer and stitcher share relative ES-module assets, so serve the repository locally:

```sh
python3 -m http.server 8000
```

Then open <http://localhost:8000/>.

## Repository layout

- `cube/` — cubemap viewer, stitcher, atlas layout, and scene assets
- `ev/` — star/planet viewer assets
- `fpqr/` — QR encoder assets
- `wine/` — VinoVision assets
- `*.html` — standalone tools

The Cythera and retro-Mac tools are their own repository —
<https://github.com/e-z-g/cythera> — served at the same
`e-z-g.github.io/cythera/…` addresses, so the links above are unchanged.

Source: <https://github.com/e-z-g/e-z-g.github.io>
