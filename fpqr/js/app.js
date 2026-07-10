// Utility Functions
function showToast(msg, isError = false) {
    const toast = document.createElement('div');
    toast.className = `fixed top-6 right-6 p-4 px-6 rounded-xl text-xs font-bold text-white shadow-xl z-[9999] transition-all duration-300 transform -translate-y-4 opacity-0 ${isError ? 'bg-rose-500' : 'bg-emerald-500'}`;
    toast.textContent = msg;
    document.body.appendChild(toast);
    requestAnimationFrame(() => {
        toast.classList.remove('-translate-y-4', 'opacity-0');
        toast.classList.add('translate-y-0', 'opacity-100');
    });
    setTimeout(() => {
        toast.classList.remove('translate-y-0', 'opacity-100');
        toast.classList.add('-translate-y-4', 'opacity-0');
        setTimeout(() => toast.remove(), 300);
    }, 3000);
}

// ─── Debug Log Panel ───────────────────────────────────────────────────────────
const _dbgLogs = [];
function dbg(msg, level = 'info') {
    const ts = new Date().toISOString().slice(11, 23);
    const entry = { ts, msg, level };
    _dbgLogs.push(entry);
    if (_dbgLogs.length > 200) _dbgLogs.shift();
    const panel = document.getElementById('debug-log-panel');
    if (panel) {
        const colors = { info: '#94a3b8', warn: '#fbbf24', error: '#f87171', ok: '#34d399' };
        const line = document.createElement('div');
        line.style.cssText = `font-size:10px;font-family:monospace;color:${colors[level]||colors.info};white-space:pre;`;
        line.textContent = `[${ts}] ${msg}`;
        panel.appendChild(line);
        panel.scrollTop = panel.scrollHeight;
    }
    if (level === 'error') console.error('[DBG]', msg);
    else if (level === 'warn') console.warn('[DBG]', msg);
}

function buildDebugPanel() {
    if (document.getElementById('debug-panel-root')) return;

    const root = document.createElement('div');
    root.id = 'debug-panel-root';
    root.style.cssText = [
        'position:fixed', 'bottom:12px', 'right:12px', 'z-index:99999',
        'width:340px', 'background:#0a0c14', 'border:1px solid #334155',
        'border-radius:12px', 'font-family:monospace', 'box-shadow:0 8px 32px #000a',
        'display:flex', 'flex-direction:column', 'overflow:hidden'
    ].join(';');

    root.innerHTML = `
        <div id="debug-panel-header" style="display:flex;align-items:center;justify-content:space-between;padding:8px 12px;background:#13151f;border-bottom:1px solid #1e293b;cursor:move;user-select:none;">
            <span style="font-size:10px;font-weight:700;color:#94a3b8;letter-spacing:.1em;">&#x1F6E0; DEBUG LOG</span>
            <div style="display:flex;gap:8px;align-items:center;">
                <button id="debug-poll-btn" style="font-size:9px;font-weight:700;color:#34d399;background:#14532d44;border:1px solid #34d39933;border-radius:6px;padding:2px 7px;cursor:pointer;">POLL</button>
                <button id="debug-clear-btn" style="font-size:9px;font-weight:700;color:#94a3b8;background:#1e293b;border:none;border-radius:6px;padding:2px 7px;cursor:pointer;">CLEAR</button>
                <button id="debug-close-btn" style="font-size:12px;font-weight:700;color:#64748b;background:none;border:none;cursor:pointer;line-height:1;">&times;</button>
            </div>
        </div>
        <div id="debug-log-panel" style="height:220px;overflow-y:auto;padding:8px 10px;display:flex;flex-direction:column;gap:2px;"></div>
        <div id="debug-status-bar" style="padding:5px 10px;background:#0f111a;border-top:1px solid #1e293b;font-size:9px;color:#475569;font-family:monospace;">Ready</div>
    `;
    document.body.appendChild(root);

    // Close
    document.getElementById('debug-close-btn').onclick = () => root.remove();
    // Clear
    document.getElementById('debug-clear-btn').onclick = () => {
        document.getElementById('debug-log-panel').innerHTML = '';
        _dbgLogs.length = 0;
        dbg('Log cleared');
    };
    // Poll – snapshot current state
    document.getElementById('debug-poll-btn').onclick = pollAnimState;

    // Drag
    const hdr = document.getElementById('debug-panel-header');
    let ox = 0, oy = 0, dragging = false;
    hdr.onmousedown = (e) => {
        dragging = true;
        const r = root.getBoundingClientRect();
        ox = e.clientX - r.left; oy = e.clientY - r.top;
        root.style.right = 'auto';
    };
    document.addEventListener('mousemove', (e) => {
        if (!dragging) return;
        root.style.left = (e.clientX - ox) + 'px';
        root.style.top  = (e.clientY - oy) + 'px';
        root.style.bottom = 'auto';
    });
    document.addEventListener('mouseup', () => { dragging = false; });
}

function pollAnimState() {
    const toggle      = document.getElementById('anim-toggle');
    const loopId      = window.animLoopId;
    const hasGif      = typeof getHasAnimatedGif === 'function' ? getHasAnimatedGif() : '?';
    const matrices    = typeof currentMatrices !== 'undefined' ? !!currentMatrices : '?';
    const rendererOk  = typeof renderCanvas === 'function';
    const startFnOk   = typeof startAnimIfNeeded === 'function';

    dbg('─── POLL ───────────────────────────────', 'info');
    dbg(`anim-toggle checked : ${toggle ? toggle.checked : 'NO ELEMENT'}`, toggle?.checked ? 'ok' : 'warn');
    dbg(`window.animLoopId   : ${loopId}`, loopId ? 'ok' : 'warn');
    dbg(`getHasAnimatedGif() : ${hasGif}`, 'info');
    dbg(`currentMatrices set : ${matrices}`, matrices ? 'ok' : 'warn');
    dbg(`renderCanvas exists : ${rendererOk}`, rendererOk ? 'ok' : 'error');
    dbg(`startAnimIfNeeded   : ${startFnOk}`, startFnOk ? 'ok' : 'error');
    dbg(`globalTime          : ${typeof globalTime !== 'undefined' ? globalTime.toFixed(4) : 'N/A'}`, 'info');

    const statusBar = document.getElementById('debug-status-bar');
    if (statusBar) statusBar.textContent = `polled @ ${new Date().toLocaleTimeString()}`;
}

// Attach keyboard shortcut: Ctrl+Shift+D opens debug panel
document.addEventListener('keydown', (e) => {
    if (e.ctrlKey && e.shiftKey && e.key === 'D') {
        if (!document.getElementById('debug-panel-root')) buildDebugPanel();
        else document.getElementById('debug-panel-root')?.remove();
    }
});
// ─── End Debug Log Panel ───────────────────────────────────────────────────────

function genDefaultImageMap(type) {
    if(type === 'color' && colorMapImage) return;
    if(type === 'density' && densityMapImage) return;
    const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="200" height="200" viewBox="0 0 200 200">
        <defs><linearGradient id="sky" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="#FF7B54"/><stop offset="100%" stop-color="#FFD56F"/></linearGradient></defs>
        <rect width="200" height="200" fill="url(#sky)"/>
        <circle cx="100" cy="120" r="60" fill="#FF5E5E"/>
        <path d="M0 200 L50 130 L100 180 L160 110 L200 160 L200 200 Z" fill="#2D4059"/>
        <path d="M-20 200 L40 160 L90 200 Z" fill="#40514E"/>
    </svg>`;
    const img = new Image();
    img.onload = () => {
        if (type === 'color') {
            colorMapImage = img;
            if(E('color-map-name')) E('color-map-name').textContent = "Landscape Vector";
        }
        if (type === 'density') {
            densityMapImage = img;
            if(E('density-map-name')) E('density-map-name').textContent = "Landscape Vector";
        }
        if (typeof startAnimIfNeeded === 'function') startAnimIfNeeded();
        if (typeof renderCanvas === 'function') renderCanvas();
    };
    img.src = 'data:image/svg+xml;base64,' + btoa(svg);
}

window.exportSettings = () => {
    const settings = {};
    const elements = document.querySelectorAll('input[type="range"], input[type="color"], input[type="checkbox"], input[type="text"], select, textarea');
    elements.forEach(el => {
        if (el?.id && !['color-map-input', 'density-map-input', 'logo-upload-input', 'module-image-input', 'import-qr-input', 'import-cfg-input'].includes(el.id)) {
            settings[el.id] = el.type === 'checkbox' ? el.checked : el.value;
        }
    });
    settings['logoShape'] = logoShape;
    const blob = new Blob([JSON.stringify(settings, null, 2)], {type: 'application/json'});
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `QR-Settings-${Date.now()}.json`;
    a.click();
};

function isolateQR(canvasId) {
    window.isExporting = true;
    if (typeof renderCanvas === 'function') renderCanvas();
    const canvas = E(canvasId), modal = E('isolate-modal'), img = E('isolate-img');
    if(!canvas || !modal || !img) { window.isExporting = false; return; }
    img.src = canvas.toDataURL('image/png');
    const btnPng = E('modal-download-png');
    if(btnPng) {
        btnPng.innerHTML = `Download PNG`;
        btnPng.classList.remove('hidden');
        btnPng.onclick = () => { const l = document.createElement('a'); l.download = `HD-Matrix-${Date.now()}.png`; l.href = canvas.toDataURL('image/png'); l.click(); };
    }
    const btnJpg = E('modal-download-jpg');
    if(btnJpg) {
        btnJpg.innerHTML = `Download JPG`;
        btnJpg.classList.remove('hidden');
        btnJpg.onclick = () => { const l = document.createElement('a'); l.download = `HD-Matrix-${Date.now()}.jpg`; l.href = canvas.toDataURL('image/jpeg', 1.0); l.click(); };
    }
    window.isExporting = false;
    if (typeof renderCanvas === 'function') renderCanvas();
    modal.classList.remove('hidden');
    void modal.offsetWidth;
    modal.classList.add('opacity-100');
}

let gifWorkerUrl = null;

const initApp = () => {
    // Open debug panel automatically on load so you can see what happens
    buildDebugPanel();
    dbg('initApp() started', 'info');

    fetch('https://cdnjs.cloudflare.com/ajax/libs/gif.js/0.2.0/gif.worker.js')
        .then(r => r.text())
        .then(t => {
            const b = new Blob([t], {type: 'application/javascript'});
            gifWorkerUrl = URL.createObjectURL(b);
            dbg('GIF worker loaded ok', 'ok');
        })
        .catch(err => { dbg('GIF worker FAILED: ' + err, 'error'); });

    function updateImageMapVisibility() {
        const gs = E('grad-style')?.value;
        const dms = E('density-map-style')?.value;
        E('color-map-upload-container')?.classList.toggle('hidden', gs !== 'image');
        E('density-map-upload-container')?.classList.toggle('hidden', dms !== 'image');
        E('fg-color-container')?.classList.toggle('opacity-30', gs === 'image');
        E('fg-color-container')?.classList.toggle('pointer-events-none', gs === 'image');
        if (gs === 'image' && !colorMapImage) genDefaultImageMap('color');
        if (dms === 'image' && !densityMapImage) genDefaultImageMap('density');
    }

    E('show-naive')?.addEventListener('change', (e) => {
        E('naive-container')?.classList.toggle('hidden', !e.target.checked);
    });

    E('import-cfg-input')?.addEventListener('change', (e) => {
        const file = e.target.files[0];
        if (!file) return;
        const reader = new FileReader();
        reader.onload = (ev) => {
            try {
                const settings = JSON.parse(ev.target.result);
                for (const key in settings) {
                    const el = E(key);
                    if (el) {
                        if (el.type === 'checkbox') el.checked = settings[key];
                        else el.value = settings[key];
                    }
                }
                if (settings['logoShape']) {
                    logoShape = settings['logoShape'];
                    ['none', 'square', 'circle'].forEach(s => E(`shape-${s}`)?.classList.toggle('active', s === logoShape));
                }
                const ds = E('data-shape')?.value;
                const isChar = ds === 'character';
                const isImg = ds === 'image';
                E('custom-module-container')?.classList.toggle('hidden', !isChar && !isImg);
                E('module-char-container')?.classList.toggle('hidden', !isChar);
                E('module-image-container')?.classList.toggle('hidden', !isImg);
                const gs = E('grad-style')?.value;
                E('grad-angle-wrapper')?.classList.toggle('hidden', gs === 'radial' || gs === 'image');
                E('grad-radial-wrapper')?.classList.toggle('hidden', gs !== 'radial');
                updateImageMapVisibility();
                if (E('anim-toggle')?.checked) {
                    E('anim-settings')?.classList.remove('hidden');
                    window.animLoopId = null;
                    dbg('cfg import: anim on, resetting loop', 'info');
                    startAnimIfNeeded();
                } else {
                    E('anim-settings')?.classList.add('hidden');
                    if (!getHasAnimatedGif()) E('export-gif-btn')?.classList.add('hidden');
                }
                if (E('show-naive')) E('naive-container')?.classList.toggle('hidden', !E('show-naive').checked);
                if (typeof analyzeData === 'function') analyzeData();
                showToast('Settings applied successfully!');
            } catch(err) {
                showToast('Failed to parse settings file.', true);
                dbg('cfg import error: ' + err, 'error');
            }
        };
        reader.readAsText(file);
        e.target.value = '';
    });

    async function handleMapUpload(file, type) {
        const isGif = file.type === 'image/gif';
        let gifFrames = null; let gifTotalTime = 0;
        if (isGif && window.ImageDecoder) {
            showToast(`Parsing ${type} GIF Frames...`, false);
            const parsed = await decodeGif(file);
            if (parsed && parsed.frames.length > 0) {
                gifFrames = parsed.frames;
                gifTotalTime = parsed.totalTime;
                showToast(`Animated ${type} Map Loaded!`);
            }
        } else if (isGif) {
            showToast("Animated GIF Support requires Chromium browsers.", true);
        }
        const blobUrl = URL.createObjectURL(file);
        const img = new Image();
        img.onload = () => {
            if (type === 'color') {
                colorMapImage = img; colorMapIsGif = !!gifFrames;
                colorMapGifFrames = gifFrames; colorMapGifTotalTime = gifTotalTime;
                if(E('color-map-name')) E('color-map-name').textContent = file.name;
            } else {
                densityMapImage = img; densityMapIsGif = !!gifFrames;
                densityMapGifFrames = gifFrames; densityMapGifTotalTime = gifTotalTime;
                if(E('density-map-name')) E('density-map-name').textContent = file.name;
            }
            startAnimIfNeeded();
            renderCanvas();
        };
        img.src = blobUrl;
    }

    E('color-map-input')?.addEventListener('change', async (e) => {
        const file = e.target.files[0];
        if (file) await handleMapUpload(file, 'color');
        e.target.value = '';
    });

    E('density-map-input')?.addEventListener('change', async (e) => {
        const file = e.target.files[0];
        if (file) await handleMapUpload(file, 'density');
        e.target.value = '';
    });

    E('module-image-input')?.addEventListener('change', (e) => {
        const file = e.target.files[0];
        if (file) {
            const blobUrl = URL.createObjectURL(file);
            const img = new Image();
            img.onload = () => {
                customModuleImage = img;
                if(E('module-image-name')) E('module-image-name').textContent = file.name;
                renderCanvas();
            };
            img.src = blobUrl;
        }
        e.target.value = '';
    });

    E('data-shape')?.addEventListener('change', (e) => {
        const shape = e.target.value;
        const lbl = E('data-weight-label');
        if(lbl) {
            if(['solid', 'organic'].includes(shape)) lbl.textContent = 'Rounding / Bevel';
            else if(['dots', 'diamond', 'halftone', 'leaf', 'character', 'image'].includes(shape)) lbl.textContent = 'Module Scale';
            else if(['plus', 'x-matrix'].includes(shape)) lbl.textContent = 'Line Thickness';
        }
        const isChar = shape === 'character';
        const isImg = shape === 'image';
        E('custom-module-container')?.classList.toggle('hidden', !isChar && !isImg);
        E('module-char-container')?.classList.toggle('hidden', !isChar);
        E('module-image-container')?.classList.toggle('hidden', !isImg);
        updateImageMapVisibility();
        renderCanvas();
    });

    E('live-scan-toggle')?.addEventListener('change', (e) => {
        if (e.target.checked) {
            lastValidateTime = 0;
            scanHistory = [];
            renderCanvas();
        } else {
            const scanContainer = E('scan-container');
            if (scanContainer) {
                scanContainer.classList.add('hidden');
                scanContainer.classList.remove('opacity-100');
            }
        }
    });

    E('density-map-style')?.addEventListener('change', () => {
        updateImageMapVisibility();
        renderCanvas();
    });

    E('grad-style')?.addEventListener('change', (e) => {
        const val = e.target.value;
        const isRadial = val === 'radial';
        const isImage = val === 'image';
        E('grad-angle-wrapper')?.classList.toggle('hidden', isRadial || isImage);
        E('grad-radial-wrapper')?.classList.toggle('hidden', !isRadial);
        updateImageMapVisibility();
        renderCanvas();
    });

    E('anim-toggle')?.addEventListener('change', (e) => {
        dbg(`anim-toggle change: checked=${e.target.checked} | window.animLoopId=${window.animLoopId}`, 'info');
        E('anim-settings')?.classList.toggle('hidden', !e.target.checked);
        if (e.target.checked) {
            window.animLoopId = null;   // ← clear REAL loop guard
            dbg('Calling startAnimIfNeeded()', 'info');
            startAnimIfNeeded();
            dbg(`after startAnimIfNeeded: window.animLoopId=${window.animLoopId}`, window.animLoopId ? 'ok' : 'error');
        } else if (!getHasAnimatedGif()) {
            E('export-gif-btn')?.classList.add('hidden');
        }
    });

    if(E('shape-none')) E('shape-none').onclick = () => { logoShape = 'none'; E('shape-none')?.classList.add('active'); E('shape-square')?.classList.remove('active'); E('shape-circle')?.classList.remove('active'); renderCanvas(); };
    if(E('shape-square')) E('shape-square').onclick = () => { logoShape = 'square'; E('shape-square')?.classList.add('active'); E('shape-none')?.classList.remove('active'); E('shape-circle')?.classList.remove('active'); renderCanvas(); };
    if(E('shape-circle')) E('shape-circle').onclick = () => { logoShape = 'circle'; E('shape-circle')?.classList.add('active'); E('shape-none')?.classList.remove('active'); E('shape-square')?.classList.remove('active'); renderCanvas(); };

    E('isolate-modal')?.addEventListener('click', (e) => {
        if (e.target.id === 'isolate-modal' || e.target.closest('#close-modal')) {
            E('isolate-modal').classList.remove('opacity-100');
            setTimeout(() => E('isolate-modal')?.classList.add('hidden'), 300);
        }
    });

    document.querySelectorAll('.data-trigger').forEach(el => el?.addEventListener('input', () => {
        if (typeof analyzeData === 'function') analyzeData();
    }));

    document.querySelectorAll('.render-trigger').forEach(el => el?.addEventListener('input', (e) => {
        if (e.target.id === 'anim-toggle' && e.target.checked) {
            window.animLoopId = null;   // ← clear REAL loop guard
            if (typeof startAnimIfNeeded === 'function') startAnimIfNeeded();
        } else if (e.target.id !== 'anim-toggle') {
            if (typeof renderCanvas === 'function') renderCanvas();
        }
    }));

    setTimeout(() => {
        if (typeof analyzeData === 'function') {
            dbg('Initial analyzeData() call', 'info');
            analyzeData();
        }
        dbg('Init complete — toggle Animate Mesh to test', 'ok');
        pollAnimState();
    }, 100);
};

if (document.readyState === 'loading') {
    window.addEventListener('DOMContentLoaded', initApp);
} else {
    initApp();
}
