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
    const canvas = E(canvasId), modal = E('isolate-modal'), img = E('isolate-img');
    if(!canvas || !modal || !img) return;
    img.src = canvas.toDataURL('image/png');
    
    const btnPng = E('modal-download-png');
    if(btnPng) {
        btnPng.innerHTML = `Download PNG`;
        btnPng.classList.remove('hidden');
        btnPng.onclick = () => { 
            const l = document.createElement('a'); 
            l.download = `HD-Matrix-${Date.now()}.png`; 
            l.href = canvas.toDataURL('image/png'); 
            l.click(); 
        };
    }

    const btnJpg = E('modal-download-jpg');
    if(btnJpg) {
        btnJpg.innerHTML = `Download JPG`;
        btnJpg.classList.remove('hidden');
        btnJpg.onclick = () => { 
            const l = document.createElement('a'); 
            l.download = `HD-Matrix-${Date.now()}.jpg`; 
            l.href = canvas.toDataURL('image/jpeg', 1.0); 
            l.click(); 
        };
    }
    
    modal.classList.remove('hidden'); 
    void modal.offsetWidth; 
    modal.classList.add('opacity-100');
}

// Global variable for GIF Worker initialized here
let gifWorkerUrl = null;

const initApp = () => {
    // Fetch and initialize GIF.js worker locally to prevent CDN CORS issues
    fetch('https://cdnjs.cloudflare.com/ajax/libs/gif.js/0.2.0/gif.worker.js')
        .then(r => r.text())
        .then(t => { 
            const b = new Blob([t], {type: 'application/javascript'}); 
            gifWorkerUrl = URL.createObjectURL(b); 
        })
        .catch(err => console.error("GIF Worker Load Error:", err));
        
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
                    startAnimIfNeeded();
                } else {
                    E('anim-settings')?.classList.add('hidden'); 
                    if (!getHasAnimatedGif()) E('export-gif-btn')?.classList.add('hidden');
                }

                if (E('show-naive')) {
                    E('naive-container')?.classList.toggle('hidden', !E('show-naive').checked);
                }

                if (typeof analyzeData === 'function') analyzeData();
                showToast('Settings applied successfully!');
            } catch(err) {
                showToast('Failed to parse settings file.', true);
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
            lastValidateTime = 0; // Force immediate check
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
        E('anim-settings')?.classList.toggle('hidden', !e.target.checked);
        if (e.target.checked) {
            startAnimIfNeeded();
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
        if(e.target.id === 'anim-toggle' && e.target.checked) {
            if (typeof startAnimIfNeeded === 'function') startAnimIfNeeded();
        } else {
            if (typeof renderCanvas === 'function') renderCanvas(); 
        }
    }));

    // Initial Trigger
    setTimeout(() => {
        if (typeof analyzeData === 'function') analyzeData();
    }, 100);
};

// Bootstrap
if (document.readyState === 'loading') {
    window.addEventListener('DOMContentLoaded', initApp);
} else {
    initApp();
}
