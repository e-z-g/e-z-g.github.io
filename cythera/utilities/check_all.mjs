#!/usr/bin/env node
// Runs every check in this directory and prints one table.
//
//   node utilities/check_all.mjs
//   node utilities/check_all.mjs --quick     (skip the slow ones)
//   node utilities/check_all.mjs viewer      (one page: viewer | browser | mobile)
//
// There are thirteen harnesses across three pages, each with its own argument
// list, spread across three handoff documents. Nobody runs all of them by hand
// every time, and it showed: two coverage gaps in decoder_snapshot.mjs went
// unnoticed because a change was verified with the two checks that seemed
// relevant rather than with everything.
//
// This also does the setup. The forks have to be extracted from the .hqx files
// before most checks can run, and that is the step most likely to be forgotten.

import {execFileSync, execSync} from 'node:child_process';
import {existsSync, mkdirSync} from 'node:fs';
import {dirname, resolve} from 'node:path';
import {fileURLToPath} from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, '..');
const TMP = process.env.TMPDIR ? resolve(process.env.TMPDIR) : '/tmp';
const args = process.argv.slice(2);
const quick = args.includes('--quick');
const only = args.find(a => !a.startsWith('--'));

const DATA = `${TMP}/Cythera Data.data`;
const DATA_RSRC = `${TMP}/Cythera Data.rsrc`;
const APP_RSRC = `${TMP}/Cythera.rsrc`;

// ---- finding the inputs ----------------------------------------------------
// These used to be fixed paths under sources/, a scratch directory that is not
// in the repository, so every fresh checkout had to be told to symlink res/
// into it before anything could run -- and a run that skipped that step
// reported most of its checks as "skip", which reads like a clean result. The
// committed copies in res/ are the same files under slightly different names,
// so look there first and keep sources/ working for anyone who already has it.
function firstExisting(...paths) {
  for (const p of paths) if (p && existsSync(p)) return p;
  return paths[paths.length - 1];   // report the conventional name when nothing is there
}

const HQX = firstExisting('res/Cythera Data.Hqx', 'sources/Cythera Data.hqx');
const APP_HQX = firstExisting('res/Cythera.hqx', 'sources/Cythera.hqx');

// delvmod is the reference implementation this project's knowledge of the
// archive came from, and two checks read its Python to catch the copies here
// drifting from it. It is a submodule at reference/delvmod, so a checkout that
// ran `git submodule update --init` has it; $DELVMOD overrides for a working
// copy kept elsewhere, and the old sources/ location still works.
const DELV = firstExisting(process.env.DELVMOD, 'reference/delvmod',
  'sources/github_delvmod/code', '../delvmod');
// mihaip/infinite-mac, which mobile.html embeds. It is a large checkout and is
// gitignored on purpose, so this check skips more often than not; $INFINITE_MAC
// lets a copy kept outside the repository be used without moving it in.
const INFMAC = firstExisting(process.env.INFINITE_MAC, 'infinite-mac', '../infinite-mac');
const GFX_REF = `${TMP}/gfx_ref.json`;
const EXPORTS = `${TMP}/check_all_exports`;

process.chdir(ROOT);

function say(s) { process.stdout.write(s + '\n'); }

// ---- setup -----------------------------------------------------------------
function ensureForks() {
  const need = [[HQX, DATA], [APP_HQX, APP_RSRC]];
  for (const [src, out] of need) {
    if (existsSync(out)) continue;
    if (!existsSync(src)) { say(`  ! ${src} is missing; some checks will be skipped`); continue; }
    say(`  extracting ${src} …`);
    execFileSync('python3', ['utilities/binhex_decode.py', src, TMP], {stdio: 'ignore'});
  }
}

function ensureGraphicsRef() {
  if (existsSync(GFX_REF) || !existsSync(DELV) || !existsSync(DATA)) return;
  say('  building the delvmod graphics reference …');
  try {
    const json = execFileSync('python3', ['utilities/delv_graphics_ref.py', DELV, DATA],
      {maxBuffer: 64 << 20, stdio: ['ignore', 'pipe', 'ignore']});
    execSync(`cat > "${GFX_REF}"`, {input: json});
  } catch (e) {
    say('  ! could not build it: ' + (e.message || '').split('\n')[0]);
  }
}

// ---- the checks ------------------------------------------------------------
// `want` lists the files that must exist for a check to be meaningful; if one
// is missing the check is skipped and said to be skipped, rather than failing
// in a way that looks like a real problem.
const CHECKS = [
  {page: 'viewer', name: 'static', cmd: ['utilities/verify_viewer.mjs', 'cythera_data_viewer.html']},
  {page: 'viewer', name: 'decoder snapshot', want: [DATA],
   cmd: ['utilities/decoder_snapshot.mjs', 'cythera_data_viewer.html', DATA], grep: /SNAPSHOT \w+/},
  {page: 'viewer', name: 'delvmod tables', want: [DATA, DELV],
   cmd: ['utilities/delv_crosscheck.mjs', 'cythera_data_viewer.html', DELV, DATA]},
  {page: 'viewer', name: 'delvmod graphics', want: [DATA, GFX_REF],
   cmd: ['utilities/delv_graphics_check.mjs', 'cythera_data_viewer.html', DATA, GFX_REF],
   grep: /identical pixels : \d+/},
  {page: 'viewer', name: 'archive loading', want: [HQX, DATA, DATA_RSRC, APP_HQX],
   cmd: ['utilities/loader_test.mjs', 'cythera_data_viewer.html', HQX, DATA, DATA_RSRC, APP_HQX]},
  {page: 'viewer', name: 'ui smoke', want: [DATA], slow: true,
   cmd: ['utilities/viewer_smoke.mjs', 'cythera_data_viewer.html', DATA],
   grep: /\d+ galleries, [\d,]+ tiles/},
  {page: 'viewer', name: 'zip export', want: [DATA], slow: true,
   cmd: ['utilities/export_test.mjs', 'cythera_data_viewer.html', DATA, EXPORTS], zips: EXPORTS},

  {page: 'browser', name: 'static', cmd: ['utilities/verify_viewer.mjs', 'resource_fork_browser.html']},
  {page: 'browser', name: 'resource snapshot', want: [APP_RSRC, DATA_RSRC],
   cmd: ['utilities/rsrc_snapshot.mjs', 'resource_fork_browser.html', APP_RSRC, DATA_RSRC],
   grep: /SNAPSHOT \w+/},
  {page: 'browser', name: 'preview smoke', want: [APP_RSRC, DATA_RSRC, APP_HQX, HQX], slow: true,
   cmd: ['utilities/preview_smoke.mjs', 'resource_fork_browser.html', APP_RSRC, DATA_RSRC, APP_HQX, HQX]},
  {page: 'browser', name: 'zip export', want: [APP_RSRC],
   cmd: ['utilities/zip_export_test.mjs', 'resource_fork_browser.html', APP_RSRC, `${TMP}/check_all.zip`],
   grep: /PNG payloads: .*/},

  {page: 'mobile', name: 'static', cmd: ['utilities/verify_viewer.mjs', 'mobile.html']},
  {page: 'mobile', name: 'input', cmd: ['utilities/mobile_input_check.mjs', 'mobile.html']},
  {page: 'mobile', name: 'undither', cmd: ['utilities/mobile_undither_check.mjs', 'mobile.html', 'cythera_data_viewer.html']},
  {page: 'mobile', name: 'infinite-mac api', want: [INFMAC],
   cmd: ['utilities/mobile_api_check.mjs', 'mobile.html', INFMAC]},
];

// ---- run -------------------------------------------------------------------
say(`\n  Cythera checks — ${new Date().toISOString().slice(0, 16).replace('T', ' ')}`);
ensureForks();
if (!only || only === 'viewer') ensureGraphicsRef();
mkdirSync(EXPORTS, {recursive: true});

const rows = [];
let failed = 0, skipped = 0;
for (const check of CHECKS) {
  if (only && check.page !== only) continue;
  if (quick && check.slow) { rows.push([check.page, check.name, 'skip', '--quick']); skipped++; continue; }
  const missing = (check.want || []).filter(p => !existsSync(p));
  if (missing.length) {
    rows.push([check.page, check.name, 'skip', 'needs ' + missing.map(m => m.replace(TMP + '/', '')).join(', ')]);
    skipped++;
    continue;
  }
  const t0 = Date.now();
  let out = '', ok = true;
  try {
    out = execFileSync('node', check.cmd, {maxBuffer: 64 << 20, encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe']});
  } catch (e) {
    ok = false;
    out = (e.stdout || '') + (e.stderr || '');
  }
  // A hand-written zip is exactly the sort of thing that looks fine and
  // unpacks to nothing, so the archives get validated rather than trusted.
  if (ok && check.zips) {
    try { execSync(`for z in "${check.zips}"/*.zip; do unzip -t "$z" > /dev/null || exit 1; done`, {stdio: 'ignore'}); }
    catch (e) { ok = false; out += '\nunzip -t rejected an archive'; }
  }
  const secs = ((Date.now() - t0) / 1000).toFixed(1);
  let note = '';
  if (check.grep) { const m = check.grep.exec(out); if (m) note = m[0].trim(); }
  if (!ok) {
    failed++;
    const lines = out.trim().split('\n').filter(l => /FAIL|Error|error/.test(l));
    note = (lines[0] || out.trim().split('\n').pop() || 'failed').slice(0, 96);
  }
  rows.push([check.page, check.name, ok ? 'ok' : 'FAIL', `${note}${note ? '  ' : ''}(${secs}s)`]);
}

const w0 = Math.max(...rows.map(r => r[0].length));
const w1 = Math.max(...rows.map(r => r[1].length));
say('');
for (const [page, name, status, note] of rows) {
  const mark = status === 'ok' ? '  ok  ' : status === 'skip' ? ' skip ' : ' FAIL ';
  say(`  ${page.padEnd(w0)}  ${name.padEnd(w1)}  ${mark}  ${note}`);
}

const ran = rows.length - skipped;
say(`\n  ${ran} checks run, ${failed} failed, ${skipped} skipped`);
if (failed) say('  Re-run a failing one on its own to see its full output.');
process.exit(failed ? 1 : 0);
