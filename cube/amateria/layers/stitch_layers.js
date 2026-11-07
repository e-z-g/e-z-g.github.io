// Stitch the face images build_layers.py writes into the four 3x2 atlases
// of Amateria's Layered version (MAWW node 101), with stitcher.html itself, so the layout and
// gutters are exactly what the viewer reads.
//
//   python3 -m http.server 8000                       (from the repo root)
//   node stitch_layers.js http://localhost:8000/cube/stitcher.html layer_faces [out_dir]
//
// Needs Playwright (npm i playwright in a scratch folder, not in this repo).
// 656px cells are 640px of picture inside the 8px gutters: the captures'
// own size, so nothing is resampled. The green see-through mask in fg-depth
// survives the stitcher bit for bit (checked for Voltaic's version).
const { chromium } = require('playwright');
const path = require('path');

const [stitcherUrl, facesDir, outDir = facesDir] = process.argv.slice(2);
if (!stitcherUrl || !facesDir) {
  console.error('usage: node stitch_layers.js <stitcher.html URL> <faces dir> [out dir]');
  process.exit(1);
}
const faces = { left: 12, front: 8, right: 11, back: 10, top: 13, bottom: 9 };
const names = { 'fg-color': 'amateria-layered-fg-color', 'fg-depth': 'amateria-layered-fg-depth',
                'bg-color': 'amateria-layered-bg-color', 'bg-depth': 'amateria-layered-bg-depth' };

(async () => {
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ acceptDownloads: true });
  const page = await ctx.newPage();
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  await page.goto(stitcherUrl);
  for (const slot of Object.keys(names)) {
    for (const [face, k] of Object.entries(faces)) {
      await page.setInputFiles('#file-' + face, path.join(facesDir, `${slot}-${k}.png`));
    }
    await page.selectOption('#slot-select', slot);
    await page.fill('#face-size', '656');
    if (slot.endsWith('color')) {
      await page.selectOption('#fmt-select', 'image/webp');
      await page.fill('#quality', '92');
    }
    await page.click('#stitch-btn');
    await page.waitForFunction(() => document.getElementById('status').textContent.startsWith('Done'), null, { timeout: 60000 });
    const [download] = await Promise.all([page.waitForEvent('download'), page.click('#dl-btn')]);
    const ext = path.extname(download.suggestedFilename());
    await download.saveAs(path.join(outDir, names[slot] + ext));
    console.log(slot, '->', names[slot] + ext, '|', await page.textContent('#align-report'));
  }
  if (errors.length) console.log('page errors:', errors.join(' | '));
  await browser.close();
})();
