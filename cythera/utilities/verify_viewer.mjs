#!/usr/bin/env node
// Static integrity checker for the single-file Cythera viewers.
//
// There is no build step and no test suite, so the cheap regressions to guard
// against are the ones a browser only reports at click time: a JS syntax error,
// an inline handler naming a function that no longer exists, and JS reaching for
// an element id that is not in the markup.
//
//   node utilities/verify_viewer.mjs cythera_data_viewer.html
//   node utilities/verify_viewer.mjs --baseline .backups/x.html cythera_data_viewer.html
//
// Exits non-zero if a hard check fails (syntax, missing handler, missing id).

import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import { collectPageScripts } from './page_scripts.mjs';

const argv = process.argv.slice(2);
let baselinePath = null;
const files = [];
for (let i = 0; i < argv.length; i++) {
  if (argv[i] === '--baseline') baselinePath = argv[++i];
  else files.push(argv[i]);
}
if (!files.length) {
  console.error('usage: verify_viewer.mjs [--baseline old.html] <file.html>');
  process.exit(2);
}

// Browser globals the top-level script body may legitimately touch. Anything
// outside this list that resolves nowhere is worth a look, not an error.
const KNOWN_GLOBALS = new Set([
  'window', 'document', 'console', 'navigator', 'location', 'history', 'screen',
  'fetch', 'Blob', 'URL', 'FileReader', 'Image', 'Audio', 'AudioContext',
  'requestAnimationFrame', 'cancelAnimationFrame', 'setTimeout', 'clearTimeout',
  'setInterval', 'clearInterval', 'localStorage', 'sessionStorage', 'alert',
  'CompressionStream', 'DecompressionStream', 'Response', 'Request', 'TextEncoder',
  'TextDecoder', 'DOMParser', 'performance', 'matchMedia', 'getComputedStyle',
  'OffscreenCanvas', 'createImageBitmap', 'structuredClone', 'queueMicrotask',
  'ResizeObserver', 'IntersectionObserver', 'MutationObserver', 'crypto',
  'CustomEvent', 'Event', 'AbortController', 'globalThis', 'ImageData', 'FontFace',
  // Built-ins. Listed because check 4b asks "does anything declare this?", and
  // the answer for Uint8Array is "the language does".
  'Object', 'Array', 'String', 'Number', 'Boolean', 'Symbol', 'BigInt', 'Function',
  'Math', 'JSON', 'Date', 'RegExp', 'Error', 'TypeError', 'RangeError', 'SyntaxError',
  'Map', 'Set', 'WeakMap', 'WeakSet', 'Promise', 'Proxy', 'Reflect', 'Intl',
  'parseInt', 'parseFloat', 'isNaN', 'isFinite', 'eval',
  'encodeURIComponent', 'decodeURIComponent', 'encodeURI', 'decodeURI',
  'ArrayBuffer', 'SharedArrayBuffer', 'DataView', 'URLSearchParams',
  'Int8Array', 'Uint8Array', 'Uint8ClampedArray', 'Int16Array', 'Uint16Array',
  'Int32Array', 'Uint32Array', 'Float32Array', 'Float64Array', 'BigInt64Array',
]);

// Comments and string literals, gone. Without this, prose inside a comment or a
// message string reads as code: the words in "That is a MacBinary file" become a
// call to MacBinary(). Quotes are replaced rather than deleted so nothing on
// either side of them joins up into a new identifier.
// Is this '/' the start of a regex literal rather than a division? Look at the
// last meaningful character emitted: after a value (identifier, number, closing
// bracket) a slash divides; after an operator, comma, or opening bracket it
// starts a pattern.
function isRegexStart(emitted) {
  const m = /([^\s])\s*$/.exec(emitted);
  if (!m) return true;                       // start of input
  const prev = m[1];
  if (/[)\]}]/.test(prev)) return false;      // (a+b) / 2
  if (/[\w$]/.test(prev)) {
    // `return /x/` and `typeof /x/` are patterns; `count / 2` is division.
    return /\b(return|typeof|case|in|of|instanceof|new|delete|void|do|else|yield|await)\s*$/.test(emitted);
  }
  return true;
}

function stripJsText(src) {
  let out = '', i = 0;
  while (i < src.length) {
    const c = src[i], d = src[i + 1];
    if (c === '/' && d === '/') { while (i < src.length && src[i] !== '\n') i++; continue; }
    if (c === '/' && d === '*') { i += 2; while (i < src.length && !(src[i] === '*' && src[i + 1] === '/')) i++; i += 2; out += ' '; continue; }
    // A regex literal can contain quotes -- /[\\/:*?"<>|]/ has one -- and
    // without recognising it the scanner enters string mode there and swallows
    // everything up to the next quote, taking real declarations with it. That
    // is what made this check report jumpToResource() as undefined while it was
    // declared thirty lines away.
    if (c === '/' && isRegexStart(out)) {
      i++;
      let inClass = false;
      while (i < src.length) {
        const ch = src[i];
        if (ch === '\\') { i += 2; continue; }
        if (ch === '[') inClass = true;
        else if (ch === ']') inClass = false;
        else if (ch === '/' && !inClass) { i++; break; }
        else if (ch === '\n') break;      // not a regex after all; bail out
        i++;
      }
      out += ' ';
      continue;
    }
    if (c === '"' || c === "'" || c === '`') {
      const q = c; i++;
      while (i < src.length && src[i] !== q) {
        // A template literal's ${...} is real code and has to survive.
        if (q === '`' && src[i] === '$' && src[i + 1] === '{') {
          let depth = 1; i += 2; const start = i;
          while (i < src.length && depth) {
            if (src[i] === '{') depth++;
            else if (src[i] === '}') depth--;
            if (depth) i++;
          }
          // Semicolons, not spaces: `${procID} ... ${(enable>>>0).toString(16)}`
          // emitted side by side reads as a call to procID().
          out += ';' + src.slice(start, i) + ';';
          i++;
          continue;
        }
        if (src[i] === '\\') i++;
        i++;
      }
      i++;
      out += '""';
      continue;
    }
    out += c; i++;
  }
  return out;
}

function analyze(path) {
  const html = readFileSync(path, 'utf8');
  const r = { path, errors: [], warnings: [], stats: {} };

  // ---- extract the script body -------------------------------------------
  // Both the inline block and every <script src> the page pulls in, in
  // document order. A page whose shared modules failed to load would otherwise
  // pass this check while being completely broken in a browser -- and
  // collectPageScripts is also what refuses a `type="module"`, which would not
  // load at all from file://.
  let collected;
  try {
    collected = collectPageScripts(path);
  } catch (e) {
    r.errors.push(e.message);
    collected = { sources: [] };
  }
  const scripts = collected.sources.map(s => s.code);
  const scriptNames = collected.sources.map(s => s.name);
  if (!scripts.length) r.errors.push('no <script> block found');
  r.stats.scriptFiles = collected.sources
    .filter(s => !s.inline && !s.external)
    .map(s => s.name).join(' ');
  const js = scripts.join('\n;\n');
  r.stats.jsBytes = js.length;
  r.stats.htmlBytes = html.length;
  r.stats.lines = html.split('\n').length;

  // ---- 1. does the JS parse? ---------------------------------------------
  for (let i = 0; i < scripts.length; i++) {
    try {
      new vm.Script(scripts[i], { filename: scriptNames[i] || `${path}#script${i}` });
    } catch (e) {
      r.errors.push(`script #${i} syntax error: ${e.message}`);
    }
  }

  // ---- 2. CSS block balance ----------------------------------------------
  const styles = [...html.matchAll(/<style\b[^>]*>([\s\S]*?)<\/style>/gi)].map(m => m[1]);
  r.stats.styleBlocks = styles.length;
  for (const css of styles) {
    // strip strings and comments before counting braces
    const bare = css.replace(/\/\*[\s\S]*?\*\//g, '').replace(/"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*'/g, '""');
    const open = (bare.match(/\{/g) || []).length;
    const close = (bare.match(/\}/g) || []).length;
    if (open !== close) r.errors.push(`unbalanced CSS braces: ${open} { vs ${close} }`);
  }

  // ---- 3. declared top-level names ---------------------------------------
  const declared = new Set();
  for (const m of js.matchAll(/^\s*(?:async\s+)?function\s+([A-Za-z_$][\w$]*)/gm)) declared.add(m[1]);
  for (const m of js.matchAll(/^\s*(?:const|let|var)\s+([A-Za-z_$][\w$]*)/gm)) declared.add(m[1]);
  // window.foo = ... and window.foo=function
  for (const m of js.matchAll(/\bwindow\.([A-Za-z_$][\w$]*)\s*=/g)) declared.add(m[1]);
  r.stats.declared = declared.size;
  r.stats.functions = [...js.matchAll(/^\s*(?:async\s+)?function\s+([A-Za-z_$][\w$]*)/gm)].length;

  // ---- 4. inline handlers reference real functions ------------------------
  // Pull the identifier being called at the start of each inline handler.
  const handlerAttr = /\son(?:click|change|input|submit|keydown|keyup|mousedown|mouseup|mouseover|mouseout|focus|blur|load|error|wheel|pointerdown|pointerup|pointermove|contextmenu|dblclick)\s*=\s*("([^"]*)"|'([^']*)')/gi;
  const handlers = new Map(); // fnName -> count
  let hm;
  while ((hm = handlerAttr.exec(html))) {
    const body = hm[2] !== undefined ? hm[2] : hm[3];
    // A leading (?<![.\w$]) keeps us off method calls like
    // document.getElementById('x').click() -- only bare calls are ours to check.
    for (const call of body.matchAll(/(?<![.\w$])([A-Za-z_$][\w$]*)\s*\(/g)) {
      const name = call[1];
      if (/^(if|for|while|switch|return|typeof|new|function|catch)$/.test(name)) continue;
      handlers.set(name, (handlers.get(name) || 0) + 1);
    }
  }
  r.stats.inlineHandlerCalls = [...handlers.values()].reduce((a, b) => a + b, 0);
  r.stats.inlineHandlerFns = handlers.size;
  for (const [name] of handlers) {
    if (!declared.has(name) && !KNOWN_GLOBALS.has(name)) {
      r.errors.push(`inline handler calls "${name}()" but no such function is declared`);
    }
  }

  // ---- 4b. functions the JS calls but nothing defines --------------------
  // Check 4 only looks at inline HTML handlers, and that is how setStatus() went
  // missing for several sessions: it is called seven times from the JS and never
  // from markup, so deleting it by accident (it sat inside a block that was cut
  // during the js/ extraction) produced a page that threw on every archive load
  // while every check still passed.
  //
  // Names bound anywhere in the file -- by any syntax -- are treated as fine.
  // That is deliberately conservative: it will not catch a name that exists but
  // is out of scope at the call site, and it does catch the case that actually
  // happened, which is a function that exists nowhere at all.
  {
    const src = stripJsText(js);
    const bound = new Set();
    const add = m => { if (m) bound.add(m); };
    for (const m of src.matchAll(/\bfunction\s*\*?\s*([A-Za-z_$][\w$]*)/g)) add(m[1]);
    // `const a = 1, b = 2` binds both; matching only after the keyword found a.
    for (const m of src.matchAll(/\b(?:const|let|var)\s+([^;\n]*)/g))
      for (const part of m[1].split(',')) add(part.trim().split('=')[0].trim().replace(/[[{(].*/, ''));
    for (const m of src.matchAll(/\bclass\s+([A-Za-z_$][\w$]*)/g)) add(m[1]);
    for (const m of src.matchAll(/\bcatch\s*\(\s*([A-Za-z_$][\w$]*)/g)) add(m[1]);
    // Destructuring, in declarations and in parameter lists.
    for (const m of src.matchAll(/\b(?:const|let|var)\s*[[{]([^\]}]*)[\]}]/g))
      for (const part of m[1].split(',')) add((part.split(':').pop() || '').trim().replace(/^\.\.\./, '').split('=')[0].trim());
    // Parameters: `function f(a, b)`, `(a, b) =>`, `a =>`, and object methods.
    for (const m of src.matchAll(/(?:function\s*\*?\s*[A-Za-z_$][\w$]*\s*|function\s*)\(([^)]*)\)/g))
      for (const part of m[1].split(',')) add(part.trim().replace(/^\.\.\./, '').split('=')[0].trim().replace(/[[{].*/, ''));
    for (const m of src.matchAll(/\(([^()]*)\)\s*=>/g))
      for (const part of m[1].split(',')) add(part.trim().replace(/^\.\.\./, '').split('=')[0].trim().replace(/[[{].*/, ''));
    for (const m of src.matchAll(/([A-Za-z_$][\w$]*)\s*=>/g)) add(m[1]);
    // Object-literal properties, and method shorthand. The second pattern
    // insists on a `{` body: written as `name\s*\(` it matched every call site
    // in the file, so every called name counted as bound and this whole check
    // silently passed on the very bug it was written for.
    for (const m of src.matchAll(/([A-Za-z_$][\w$]*)\s*:/g)) add(m[1]);
    for (const m of src.matchAll(/([A-Za-z_$][\w$]*)\s*\([^)]*\)\s*\{/g)) add(m[1]);

    const KEYWORDS = /^(if|for|while|switch|return|typeof|new|function|catch|do|else|delete|void|in|of|instanceof|await|yield|throw|case|try|super|this)$/;
    const called = new Map();
    for (const m of src.matchAll(/(?<![.\w$])([A-Za-z_$][\w$]*)\s*\(/g)) {
      const name = m[1];
      if (KEYWORDS.test(name)) continue;
      called.set(name, (called.get(name) || 0) + 1);
    }
    const missing = [...called.keys()].filter(n => !bound.has(n) && !KNOWN_GLOBALS.has(n));
    r.stats.jsCalls = called.size;
    for (const name of missing) {
      r.errors.push(`JS calls "${name}()" ${called.get(name)}x but nothing declares it`);
    }
  }

  // ---- 5. getElementById targets exist in the markup ---------------------
  const markupIds = new Set([...html.matchAll(/\bid\s*=\s*(?:"([^"]+)"|'([^']+)')/g)]
    .map(m => m[1] || m[2]));
  r.stats.markupIds = markupIds.size;
  const looked = new Set();
  for (const m of js.matchAll(/getElementById\(\s*['"]([^'"]+)['"]\s*\)/g)) looked.add(m[1]);
  for (const m of js.matchAll(/querySelector(?:All)?\(\s*['"]#([\w-]+)['"]\s*\)/g)) looked.add(m[1]);
  r.stats.idsLookedUp = looked.size;
  // Ids are also built dynamically, including by concatenation
  // (b.id = 'nav_' + g.id), so collect the literal prefixes that JS assigns and
  // treat a lookup as satisfied when it starts with one.
  const idPrefixes = [...js.matchAll(/\.id\s*=\s*['"`]([\w-]+)['"`]\s*\+/g)].map(m => m[1]);
  const esc = s => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  for (const id of looked) {
    if (markupIds.has(id)) continue;
    const dynamic =
      new RegExp(`id\\s*=\\s*[\`'"]?${esc(id)}\\b`).test(js) ||
      new RegExp(`\\.id\\s*=\\s*['"\`]${esc(id)}['"\`]`).test(js) ||
      idPrefixes.some(p => id.startsWith(p));
    if (dynamic) r.warnings.push(`#${id} is created dynamically in JS (not in static markup)`);
    else r.errors.push(`JS looks up #${id} but nothing ever creates it`);
  }

  // ---- 6. soft signals ----------------------------------------------------
  r.stats.inlineStyleAttrs = (html.match(/\sstyle\s*=\s*"/g) || []).length;
  r.stats.consoleLogs = (js.match(/\bconsole\.log\s*\(/g) || []).length;
  r.stats.tryBlocks = (js.match(/\btry\s*\{/g) || []).length;
  r.stats.emptyCatches = (js.match(/catch\s*\([^)]*\)\s*\{\s*\}/g) || []).length;
  r.stats.canvases = (html.match(/<canvas\b/g) || []).length;
  r.stats.addEventListener = (js.match(/addEventListener\(/g) || []).length;
  r.stats.removeEventListener = (js.match(/removeEventListener\(/g) || []).length;

  return r;
}

function report(r) {
  console.log(`\n=== ${r.path} ===`);
  const s = r.stats;
  console.log(`  html ${s.htmlBytes} bytes / ${s.lines} lines, js ${s.jsBytes} bytes`);
  if (s.scriptFiles) console.log(`  shared modules: ${s.scriptFiles}`);
  console.log(`  functions ${s.functions}, top-level names ${s.declared}`);
  console.log(`  inline handlers ${s.inlineHandlerCalls} calls -> ${s.inlineHandlerFns} distinct fns`);
  console.log(`  markup ids ${s.markupIds}, looked up in JS ${s.idsLookedUp}`);
  console.log(`  canvases ${s.canvases}, inline style= ${s.inlineStyleAttrs}`);
  console.log(`  listeners +${s.addEventListener}/-${s.removeEventListener}, try ${s.tryBlocks}, empty catch ${s.emptyCatches}, console.log ${s.consoleLogs}`);
  for (const w of r.warnings) console.log(`  WARN  ${w}`);
  for (const e of r.errors) console.log(`  ERROR ${e}`);
  console.log(`  => ${r.errors.length ? 'FAIL' : 'PASS'} (${r.errors.length} errors, ${r.warnings.length} warnings)`);
  return r.errors.length === 0;
}

let ok = true;
const results = files.map(analyze);
for (const r of results) ok = report(r) && ok;

if (baselinePath) {
  const base = analyze(baselinePath);
  report(base);
  console.log(`\n=== drift vs baseline ===`);
  const keys = new Set([...Object.keys(base.stats), ...Object.keys(results[0].stats)]);
  for (const k of [...keys].sort()) {
    const a = base.stats[k], b = results[0].stats[k];
    if (typeof a === 'number' && typeof b === 'number' && a !== b) {
      const d = b - a;
      console.log(`  ${k}: ${a} -> ${b} (${d > 0 ? '+' : ''}${d})`);
    }
  }
  const newErrors = results[0].errors.filter(e => !base.errors.includes(e));
  if (newErrors.length) {
    console.log(`\n  REGRESSION: ${newErrors.length} error(s) not present in baseline`);
    for (const e of newErrors) console.log(`    ${e}`);
    ok = false;
  } else {
    console.log(`  no new errors vs baseline`);
  }
}

process.exit(ok ? 0 : 1);
