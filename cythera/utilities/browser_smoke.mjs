#!/usr/bin/env node
// End-to-end smoke test in real Chrome.
//
// NOTE: this cannot run on the machine it was written on. Chrome's
// ProcessSingleton binds a unix domain socket at startup and this sandbox
// denies bind() (a plain file write to the same directory succeeds, so it is
// the socket policy, not a path permission). Everything else is solved:
// MAC_CHROMIUM_TMPDIR below is the env var Chromium honours on macOS -- it
// ignores TMPDIR -- and HOME is redirected so it does not touch the real
// Chrome profile. utilities/preview_smoke.mjs covers the same ground in Node.
//
//   node utilities/browser_smoke.mjs resource_fork_browser.html "$TMPDIR/Cythera.rsrc"
//
// The Node snapshot only exercises the decoders. This drives the actual page:
// it feeds a real resource fork through the same entry point the file picker
// uses, then selects every type, previews every single resource, switches to
// gallery view and opens the cursor gallery -- so a broken appendChild, a
// missing element id or a decoder that throws inside a preview branch shows up
// as a failure line instead of an empty pane the user finds later.

import { readFileSync, writeFileSync, mkdtempSync } from 'node:fs';
import { execFileSync } from 'node:child_process';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const CHROME = process.env.CHROME || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const [htmlPath, forkPath] = process.argv.slice(2);
if (!htmlPath || !forkPath) {
  console.error('usage: browser_smoke.mjs <browser.html> <fork.rsrc>');
  process.exit(2);
}

const page = readFileSync(htmlPath, 'utf8');
const forkB64 = readFileSync(forkPath).toString('base64');

const driver = `
<script>
const LOG = [];
const say = s => LOG.push(s);
window.onerror = (m, src, line) => { say('UNCAUGHT ' + m + ' @line ' + line); };
window.addEventListener('unhandledrejection', e => say('UNHANDLED REJECTION ' + e.reason));
const step = (name, fn) => { try { return fn(); } catch (e) { say('FAIL ' + name + ': ' + e.message); } };

const raw = atob(FORK_B64);
const bytes = new Uint8Array(raw.length);
for (let i = 0; i < raw.length; i++) bytes[i] = raw.charCodeAt(i);

step('handleBytes', () => handleBytes({ name: 'test.rsrc', size: bytes.length }, bytes));
say('status: ' + document.getElementById('status').textContent);
say('error: ' + (document.getElementById('error').textContent || '(none)'));
say('browser visible: ' + (document.getElementById('browser').style.display !== 'none'));
say('type options: ' + document.getElementById('typeSelect').options.length);
say('cursor button: ' + document.getElementById('cursorGalleryBtn').style.display);

// Every type through the list renderer, then every resource through preview.
let previewed = 0, empty = 0;
for (const t of typeList.map(t => t.type)) {
  document.getElementById('typeSelect').value = t;
  step('onTypeChange ' + t, onTypeChange);
  const rows = document.querySelectorAll('#resTableBody tr').length;
  const list = resourcesByType[t] || [];
  if (rows !== list.length) say('ROW MISMATCH ' + t + ': ' + rows + ' rows for ' + list.length + ' resources');
  for (const entry of list) {
    step('preview ' + t + '#' + entry.id, () => {
      const data = getResourceData(t, entry);
      previewResource(t, entry, data);
      previewed++;
      const pv = document.getElementById('preview');
      if (!pv.children.length) { empty++; say('EMPTY PREVIEW ' + t + '#' + entry.id); }
    });
  }
}
say('previewed: ' + previewed + ' resources, ' + empty + ' rendered nothing');

// Gallery view over every type, so lazy thumbnails and the char fallback run.
step('toggleView', toggleView);
for (const t of typeList.map(t => t.type)) {
  document.getElementById('typeSelect').value = t;
  step('gallery ' + t, onTypeChange);
}
say('gallery cells on last type: ' + document.querySelectorAll('.galCell').length);
step('toggleView back', toggleView);

step('cursor gallery', showCursorGallery);
say('cursor tiles: ' + document.getElementById('preview').querySelectorAll('button').length);

// Filtering, sorting and the all-types search.
const sb = document.getElementById('searchBox');
sb.value = '1'; step('filter', onTypeChange);
say('filtered rows: ' + document.querySelectorAll('#resTableBody tr').length);
document.getElementById('searchAll').checked = true;
step('search all types', onTypeChange);
say('all-type rows: ' + document.querySelectorAll('#resTableBody tr').length);
document.getElementById('searchAll').checked = false;
sb.value = ''; step('clear filter', onTypeChange);
for (const m of ['id', 'name', 'size', 'fork']) {
  sortMode = m; step('sort ' + m, onTypeChange);
}

// Keyboard navigation.
step('keyboard', () => {
  const first = document.querySelector('#resTableBody tr.resRow');
  if (!first) return say('no focusable rows');
  first.focus();
  document.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true }));
  say('focus moved: ' + (document.activeElement !== document.body));
});

// A deliberately corrupt fork must be reported, not accepted.
step('garbage rejected', () => {
  const junk = new Uint8Array(5000).fill(0x41);
  handleBytes({ name: 'junk.bin', size: junk.length }, junk);
  say('garbage error: ' + (document.getElementById('error').textContent ? 'reported' : 'SILENTLY ACCEPTED'));
});

document.title = 'SMOKE_DONE';
const out = document.createElement('pre');
out.id = 'smokeResults';
out.textContent = LOG.join('\\n');
document.body.appendChild(out);
</script>
`;

const tmp = mkdtempSync(join(tmpdir(), 'rfb-smoke-'));
const testPath = join(tmp, 'smoke.html');
writeFileSync(testPath, page.replace('</body>', driver.replace('FORK_B64', JSON.stringify(forkB64)) + '</body>'));

let dom = '';
try {
  dom = execFileSync(CHROME, [
    '--headless', '--disable-gpu', '--no-sandbox', '--no-first-run',
    '--disable-crash-reporter', '--dump-dom',
    '--virtual-time-budget=30000', `--user-data-dir=${join(tmp, 'profile')}`,
    `file://${testPath}`,
  ], {
    encoding: 'utf8', maxBuffer: 256 * 1024 * 1024, stdio: ['ignore', 'pipe', 'ignore'],
    env: { ...process.env, MAC_CHROMIUM_TMPDIR: tmp, HOME: join(tmp, 'home') },
  });
} catch (e) {
  console.error('Chrome failed to run:', e.message);
  process.exit(2);
}

const m = /<pre id="smokeResults">([\s\S]*?)<\/pre>/.exec(dom);
if (!m) { console.error('the page never finished; no results element was produced'); process.exit(1); }
const text = m[1]
  .replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&amp;/g, '&').replace(/&quot;/g, '"');
console.log(text);
const bad = text.split('\n').filter(l => /^(FAIL|UNCAUGHT|UNHANDLED|EMPTY PREVIEW|ROW MISMATCH)/.test(l));
console.log(bad.length ? `\n=> ${bad.length} problem(s)` : '\n=> clean');
process.exit(bad.length ? 1 : 0);
