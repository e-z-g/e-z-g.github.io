# e-z-g.github.io

A collection of web-based tools and interactive viewers.

## Tools

- **[Cubemap VR Viewer](https://e-z-g.github.io/cube/)** — Interactive 360° parallax cubemap viewer with depth-driven square transitions, gyroscope support, and custom LDI upload.
- **[Cubemap Face Stitcher](https://e-z-g.github.io/cube/stitcher.html)** — Assemble six cube faces into the atlas the viewer's custom LDI mode loads, with per-face rotation and flip.
- **[QR Code Generator](https://e-z-g.github.io/qr.html)** — Generate and download QR codes in the browser.
- **[Wine Tool](https://e-z-g.github.io/wine.html)** — Wine reference/utility tool.
- **[VR Video](https://e-z-g.github.io/vrvid.html)** — VR video player.
- **[Star/Planet Viewer](https://e-z-g.github.io/ev/)** — Generative space scene with star field and planet image, with PNG export.
- **[3D Print Scanimation Generator](https://e-z-g.github.io/scanimation.html)** — Interlace up to six frames into a printable base plate and sliding barrier grid, with SVG and multi-colour 3MF export.
- **[FPQR](https://e-z-g.github.io/fpqr/)** — First-person QR experience.

## Local preview

Everything here is static, but the two cubemap pages load their assets relatively
and share an ES module (`cube/atlas-layout.js`), so they need to be served rather
than opened from disk:

```
python3 -m http.server 8000
```

Then open <http://localhost:8000/cube/>.

`cube/atlas-layout.js` is the single definition of the atlas format the stitcher
writes and the viewer reads. Both layouts (5×3 and the compact 3×2) are described
there; changing one side without the other will misalign the pole faces.
