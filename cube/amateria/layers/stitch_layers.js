// Stitch the face images build_layers.py writes into the four 3x2 atlases
// of Amateria's Layered version (MAWW node 101), with stitcher.html itself, so the layout and
// gutters are exactly what the viewer reads.
//
//   python3 -m http.server 8000                       (from the repo root)
//   node stitch_layers.js http://localhost:8000/cube/stitcher.html layer_faces [out_dir]
//
// Needs Playwright (npm i playwright in a scratch folder, not in this repo).
// 656px cells are 640px of picture inside the 8px gutters: the captures'
// own size, so nothing is resampled; 1296 for faces of 1280 (sharpen_depth.py).
// The green see-through mask in fg-depth survives the stitcher bit for bit.
const { chromium } = require('playwright');
const path = require('path');

const [stitcherUrl, facesDir, outDir = facesDir, cell = '656', prefix = 'amateria-layered',
       nameList = 'MAWWnodes-8,MAWWnodes-9,MAWWnodes-10,MAWWnodes-11,MAWWnodes-12,MAWWnodes-13'] = process.argv.slice(2);
if (!stitcherUrl || !facesDir) {
  console.error('usage: node stitch_layers.js <stitcher.html URL> <faces dir> [out dir] [cell px, 656 or 1296]\n'
    + '         [atlas name prefix] [six face names in node_depth.py\'s order: front,bottom,back,right,left,top]');
  process.exit(1);
}
const [front, bottom, back, right, left, top] = nameList.split(',');
const faces = { left, front, right, back, top, bottom };
const names = Object.fromEntries(['fg-color', 'fg-depth', 'bg-color', 'bg-depth'].map(sl => [sl, `${prefix}-${sl}`]));

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
    await page.fill('#face-size', cell);
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
