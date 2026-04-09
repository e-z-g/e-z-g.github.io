// Drawing State Globals
let logoShape = 'square';
let globalTime = 0;

let colorMapImage = null;
let densityMapImage = null;
let customLogoImage = null;
let customModuleImage = null;
let animLoopId = null;
let lastAnimTime = 0;

// GIF Tracking Variables
let customLogoIsGif = false;
let colorMapIsGif = false;
let densityMapIsGif = false;
let colorMapGifFrames = null;
let colorMapGifTotalTime = 0;
let densityMapGifFrames = null;
let densityMapGifTotalTime = 0;
let logoGifFrames = null;
let logoGifTotalTime = 0;
let gifTimeMs = 0; 

const offscreenCanvas = document.createElement('canvas');
const offscreenCtx = offscreenCanvas.getContext('2d');

const getHasAnimatedGif = () => customLogoIsGif || colorMapIsGif || densityMapIsGif;

// Math & Drawing Utilities
const smoothNoise = (x, y, seed, time) => {
    const n1 = Math.sin(x * 0.71 + y * 0.53 + time + seed * 1.3);
    const n2 = Math.cos(x * 0.43 - y * 0.89 + time * 2 + seed * 2.7);
    const n3 = Math.sin(x * 1.1 - y * 0.2 - time + seed * 0.9);
    return (n1 + n2 + n3) / 3; 
};

const chaoticNoise = (x, y, seed, time) => {
    const n1 = Math.sin(x * 3.71 + y * 2.53 + time * 2 + seed * 1.3);
    const n2 = Math.cos(x * 2.43 - y * 3.89 + time * 3 + seed * 2.7);
    const n3 = Math.sin(x * 4.11 - y * 2.22 - time * 2 + seed * 0.9);
    return (n1 + n2 + n3) / 3; 
};

function roundRectPath(ctx, x, y, w, h, r) {
    r = Math.min(r, w/2, h/2); 
    ctx.moveTo(x+r, y); ctx.lineTo(x+w-r, y); ctx.quadraticCurveTo(x+w, y, x+w, y+r);
    ctx.lineTo(x+w, y+h-r); ctx.quadraticCurveTo(x+w, y+h, x+w-r, y+h); ctx.lineTo(x+r, y+h);
    ctx.quadraticCurveTo(x, y+h, x, y+h-r); ctx.lineTo(x, y+r); ctx.quadraticCurveTo(x, y, x+r, y);
}

function getCurrentGifFrame(gifData, timeMs) {
    if (!gifData || !gifData.frames || gifData.totalTime === 0) return null;
    let t = timeMs % gifData.totalTime;
    for (let i = 0; i < gifData.frames.length; i++) {
        t -= gifData.frames[i].duration;
        if (t <= 0) return gifData.frames[i].canvas;
    }
    return gifData.frames[gifData.frames.length - 1].canvas;
}

function createEngineGradient(ctx, cSz, c1, c2) {
    const gradStyle = E('grad-style')?.value || 'linear';
    let grad;
    
    if (gradStyle === 'radial') {
        const rScale = parseInt(E('grad-radial')?.value || '100') / 100;
        grad = ctx.createRadialGradient(cSz/2, cSz/2, 0, cSz/2, cSz/2, (cSz/1.414) * rScale);
    } else {
        const angleDeg = parseInt(E('grad-angle')?.value || '135');
        const angleRad = (angleDeg - 90) * Math.PI / 180;
        const cx = cSz/2, cy = cSz/2;
        const extent = (cSz/2) * (Math.abs(Math.cos(angleRad)) + Math.abs(Math.sin(angleRad)));
        
        const x1 = cx - Math.cos(angleRad) * extent;
        const y1 = cy - Math.sin(angleRad) * extent;
        const x2 = cx + Math.cos(angleRad) * extent;
        const y2 = cy + Math.sin(angleRad) * extent;
        
        grad = ctx.createLinearGradient(x1, y1, x2, y2);
    }
    grad.addColorStop(0, c1);
    grad.addColorStop(1, c2);
    return grad;
}

function getMapData(activeImage, gSz, ctx, canvas) {
    if (!activeImage) return null;
    canvas.width = gSz; canvas.height = gSz;
    ctx.clearRect(0, 0, gSz, gSz);
    const scale = Math.max(gSz / activeImage.width, gSz / activeImage.height);
    const nw = activeImage.width * scale;
    const nh = activeImage.height * scale;
    const nx = (gSz - nw)/2;
    const ny = (gSz - nh)/2;
    ctx.drawImage(activeImage, nx, ny, nw, nh);
    return ctx.getImageData(0, 0, gSz, gSz).data;
}

function renderCanvas() {
    if (!currentMatrices) return;
    const { nData, oData, oV } = currentMatrices;
    const shape = E('data-shape')?.value || 'solid';
    const colorStyle = E('grad-style')?.value || 'linear';
    const densityMapStyle = E('density-map-style')?.value || 'uniform';
    const needsImageMap = colorStyle === 'image' || densityMapStyle === 'image';
    
    const dB = parseInt(E('data-bevel')?.value || '75');
    const pct = parseInt(E('logo-size')?.value || '25'), padPct = parseInt(E('logo-padding')?.value || '1');
    const omit = E('omit-obscured')?.checked, heatmap = E('heatmap-toggle')?.checked;
    
    const isAnimated = E('anim-toggle')?.checked;
    const animMag = parseInt(E('anim-mag')?.value || '50') / 50;
    const flowType = E('anim-flow')?.value || 'wave';
    const noiseFn = flowType === 'chaos' ? chaoticNoise : smoothNoise;

    const matchFinders = E('match-finders')?.checked;
    const fB = parseInt(E('frame-bevel')?.value || '50');
    const pB = parseInt(E('pupil-bevel')?.value || '50');
    const alignFB = matchFinders ? fB : parseInt(E('align-frame-bevel')?.value || '50');
    const alignPB = matchFinders ? pB : parseInt(E('align-pupil-bevel')?.value || '50');

    const alignSliders = E('align-sliders');
    if(alignSliders) {
        alignSliders.style.opacity = matchFinders ? '0.3' : '1';
        alignSliders.style.pointerEvents = matchFinders ? 'none' : 'auto';
    }

    safeSetText('frame-bevel-val', fB + '%'); 
    safeSetText('pupil-bevel-val', pB + '%');
    safeSetText('align-frame-bevel-val', alignFB + '%'); 
    safeSetText('align-pupil-bevel-val', alignPB + '%');
    safeSetText('data-bevel-val', dB + '%'); 
    safeSetText('logo-size-val', pct + '%'); 
    safeSetText('logo-padding-val', padPct + '%');
    safeSetText('grad-angle-val', (E('grad-angle')?.value || '135') + '°');
    safeSetText('grad-radial-val', (E('grad-radial')?.value || '100') + '%');

    const renderM = (canId, matrix) => {
        const can = E(canId); if (!can) return;
        const cSz = 2048, marg = 2, gSz = matrix.modules.size, cell = cSz / (gSz + marg*2);
        
        if (can.width !== cSz) {
            can.width = can.height = cSz;
        }
        
        const ctx = can.getContext('2d', { willReadFrequently: true });
        ctx.clearRect(0, 0, cSz, cSz);
        
        const bgGrad = createEngineGradient(ctx, cSz, E('color-bg-start')?.value || '#ffffff', E('color-bg-end')?.value || '#ffffff');
        const fgGrad = createEngineGradient(ctx, cSz, E('color-start')?.value || '#000000', E('color-end')?.value || '#000000');

        ctx.fillStyle = heatmap ? '#1a1d27' : bgGrad; 
        ctx.fillRect(0,0,cSz,cSz);
        
        const aps = AP_LOCATIONS[oV] || [];
        const sz = cSz * (pct/100), padPx = cSz * (padPct/100), tSz = sz + (padPx * 2), pXy = (cSz - tSz) / 2, lC = cSz / 2;

        const isModuleObscured = (r, c) => {
            if (logoShape === 'none') return false;
            const cx = (c+marg)*cell, cy = (r+marg)*cell;
            const bleed = cell * 0.7; 
            const mLeft = cx - bleed, mRight = cx + cell + bleed, mTop = cy - bleed, mBottom = cy + cell + bleed;
            if (logoShape === 'square') { return (mRight > pXy && mLeft < pXy+tSz && mBottom > pXy && mTop < pXy+tSz); }
            else { const clX = Math.max(mLeft, Math.min(lC, mRight)), clY = Math.max(mTop, Math.min(lC, mBottom)); return ((lC-clX)**2 + (lC-clY)**2) < (tSz/2)**2; }
        };

        const isFinder = (r, c) => (r<7&&c<7) || (r<7&&c>=gSz-7) || (r>=gSz-7&&c<7);
        const isAlignment = (r, c) => {
            if (isFinder(r, c)) return false;
            for(let ax of aps) for(let ay of aps) {
                if((ax===6&&ay===6)||(ax===6&&ay===gSz-7)||(ax===gSz-7&&ay===6)) continue;
                if(Math.abs(r-ay)<=2 && Math.abs(c-ax)<=2) return true;
            }
            return false;
        };

        const isDarkData = (r, c) => {
            if (r < 0 || r >= gSz || c < 0 || c >= gSz) return false;
            if (!matrix.modules.get(r, c)) return false;
            if (isFinder(r, c) && !E('native-finders')?.checked) return false;
            if (isAlignment(r, c) && !E('native-alignments')?.checked) return false;
            return true;
        };

        const shouldRenderData = (r, c) => { if (!isDarkData(r, c)) return false; if (isModuleObscured(r, c) && omit && !heatmap) return false; return true; };

        const setHeatmapColor = (type) => {
            if(!heatmap) { ctx.fillStyle = fgGrad; ctx.strokeStyle = fgGrad; return; }
            if(type==='finder') { ctx.fillStyle = '#3b82f6'; ctx.strokeStyle = '#3b82f6'; }
            else if(type==='alignment') { ctx.fillStyle = '#06b6d4'; ctx.strokeStyle = '#06b6d4'; }
            else if(type==='data') { ctx.fillStyle = '#10b981'; ctx.strokeStyle = '#10b981'; }
        };
        
        let hMapColor = null, hMapDensity = null;
        
        if (colorStyle === 'image') {
            let activeImage = colorMapImage;
            if (colorMapIsGif && colorMapGifFrames) {
                activeImage = getCurrentGifFrame({frames: colorMapGifFrames, totalTime: colorMapGifTotalTime}, gifTimeMs) || colorMapImage;
            }
            if (activeImage) hMapColor = getMapData(activeImage, gSz, offscreenCtx, offscreenCanvas);
        }

        if (densityMapStyle === 'image') {
            let activeImage = densityMapImage;
            if (densityMapIsGif && densityMapGifFrames) {
                activeImage = getCurrentGifFrame({frames: densityMapGifFrames, totalTime: densityMapGifTotalTime}, gifTimeMs) || densityMapImage;
            }
            if (activeImage) hMapDensity = getMapData(activeImage, gSz, offscreenCtx, offscreenCanvas);
        }

        const drawStruct = (r, c, x, y, size, type) => {
            let obscured = isModuleObscured(type === 'finder' ? r+3 : r, type === 'finder' ? c+3 : c);
            if (heatmap && obscured) { ctx.fillStyle = '#ef4444'; ctx.strokeStyle = '#ef4444'; } 
            else if (heatmap) { setHeatmapColor(type); }
            else {
                let sR = type === 'finder' ? r + 3 : r + 2;
                let sC = type === 'finder' ? c + 3 : c + 2;
                if (colorStyle === 'image' && hMapColor) {
                    const idx = (sR * gSz + sC) * 4;
                    const cFill = `rgb(${hMapColor[idx]}, ${hMapColor[idx+1]}, ${hMapColor[idx+2]})`;
                    ctx.fillStyle = cFill; ctx.strokeStyle = cFill;
                } else {
                    ctx.fillStyle = fgGrad; ctx.strokeStyle = fgGrad;
                }
            }

            if (heatmap) { ctx.fillRect(x, y, (type === 'finder' ? 7 : 5)*size, (type === 'finder' ? 7 : 5)*size); return; }
            
            const structFB = type === 'finder' ? fB : alignFB;
            const structPB = type === 'finder' ? pB : alignPB;

            if (type === 'finder') {
                const s = 7*size, rO = (s/2)*(structFB/100), rG = (5*size/2)*(structFB/100), rI = (3*size/2)*(structPB/100);
                ctx.beginPath(); roundRectPath(ctx, x, y, s, s, rO); roundRectPath(ctx, x+size, y+size, 5*size, 5*size, rG); ctx.fill('evenodd');
                ctx.beginPath(); roundRectPath(ctx, x+2*size, y+2*size, 3*size, 3*size, rI); ctx.fill();
            } else {
                const s = 5*size, rO = (s/2)*(structFB/100), rG = (3*size/2)*(structFB/100), rI = (size/2)*(structPB/100);
                ctx.beginPath(); roundRectPath(ctx, x, y, s, s, rO); roundRectPath(ctx, x+size, y+size, 3*size, 3*size, rG); ctx.fill('evenodd');
                ctx.beginPath(); roundRectPath(ctx, x+2*size, y+2*size, size, size, rI); ctx.fill();
            }
        };

        if (!E('native-finders')?.checked) {
            [[0,0], [gSz-7,0], [0,gSz-7]].forEach(([cx,cy]) => drawStruct(cy, cx, (cx+marg)*cell, (cy+marg)*cell, cell, 'finder'));
        }
        if (!E('native-alignments')?.checked) {
            aps.forEach(ax => aps.forEach(ay => { if ((ax===6&&ay===6) || (ax===6&&ay===gSz-7) || (ax===gSz-7&&ay===6)) return; drawStruct(ay-2, ax-2, (ax-2+marg)*cell, (ay-2+marg)*cell, cell, 'alignment'); }));
        }

        for(let r=0; r<gSz; r++) {
            for(let c=0; c<gSz; c++) {
                if (!shouldRenderData(r, c)) continue;
                const cx = (c+marg)*cell, cy = (r+marg)*cell, obscured = isModuleObscured(r, c);
                if (heatmap) {
                    if (obscured) { ctx.fillStyle = '#ef4444'; ctx.strokeStyle = '#ef4444'; }
                    else if (isFinder(r,c)) setHeatmapColor('finder');
                    else if (isAlignment(r,c)) setHeatmapColor('alignment');
                    else setHeatmapColor('data');
                    ctx.fillRect(cx, cy, cell, cell); continue;
                } 

                let currentFill = fgGrad;
                if (hMapColor && colorStyle === 'image') {
                    const idx = (r * gSz + c) * 4;
                    currentFill = `rgb(${hMapColor[idx]}, ${hMapColor[idx+1]}, ${hMapColor[idx+2]})`;
                }

                ctx.fillStyle = currentFill;
                ctx.strokeStyle = currentFill;
                ctx.beginPath();
                
                let sizeFactor = 1.0;
                if (densityMapStyle === 'radial') {
                    const dist = Math.hypot(cx+cell/2 - lC, cy+cell/2 - lC);
                    sizeFactor = Math.max(0.1, 1 - dist / (cSz/1.4));
                } else if (densityMapStyle === 'image' && hMapDensity) {
                    const idx = (r * gSz + c) * 4;
                    let imgLuma = (hMapDensity[idx]*0.299 + hMapDensity[idx+1]*0.587 + hMapDensity[idx+2]*0.114);
                    if (E('invert-density-map')?.checked) imgLuma = 255 - imgLuma;
                    sizeFactor = imgLuma / 255;
                }

                let dX = 0, dY = 0, dS = sizeFactor;

                if (isAnimated) {
                    if (flowType === 'pulse') {
                        const dist = Math.hypot(c - gSz/2, r - gSz/2);
                        dS += Math.sin(dist * 0.5 - globalTime) * animMag * 0.6;
                    } else {
                        dX = noiseFn(r, c, 1, globalTime) * animMag * cell * 0.5;
                        dY = noiseFn(r, c, 2, globalTime) * animMag * cell * 0.5;
                        dS += noiseFn(r, c, 3, globalTime) * animMag * 0.5;
                    }
                }

                if (dS !== 1.0 || dX !== 0 || dY !== 0) {
                    ctx.save();
                    ctx.translate(cx + cell/2 + dX, cy + cell/2 + dY);
                    const safeScale = Math.max(0.01, dS);
                    ctx.scale(safeScale, safeScale);
                    ctx.translate(-(cx + cell/2), -(cy + cell/2));
                }

                if (shape === 'solid') { 
                    roundRectPath(ctx, cx, cy, cell + 0.5, cell + 0.5, Math.max(0, (cell/2)*(dB/100))); ctx.fill(); 
                } else if (shape === 'organic') {
                    const rad = Math.max(0, (cell/2)*(dB/100)), t = shouldRenderData(r-1,c), b = shouldRenderData(r+1,c), l = shouldRenderData(r,c-1), ri = shouldRenderData(r,c+1);
                    const ov = 0.6; 
                    const cR = cx + cell + (ri ? ov : 0), cB = cy + cell + (b ? ov : 0);
                    const cL = cx - (l ? ov : 0), cT = cy - (t ? ov : 0);
                    ctx.moveTo(cx+cell/2, cT);
                    (!t && !ri) ? ctx.arcTo(cx+cell, cy, cx+cell, cy+cell/2, rad) : (ctx.lineTo(cR, cT), ctx.lineTo(cR, cy+cell/2));
                    (!b && !ri) ? ctx.arcTo(cx+cell, cy+cell, cx+cell/2, cy+cell, rad) : (ctx.lineTo(cR, cB), ctx.lineTo(cx+cell/2, cB));
                    (!b && !l)  ? ctx.arcTo(cx, cy+cell, cx, cy+cell/2, rad) : (ctx.lineTo(cL, cB), ctx.lineTo(cL, cy+cell/2));
                    (!t && !l)  ? ctx.arcTo(cx, cy, cx+cell/2, cy, rad) : (ctx.lineTo(cL, cT), ctx.lineTo(cx+cell/2, cT));
                    ctx.fill();
                } else if (shape === 'halftone' || shape === 'dots') {
                    const baseScale = Math.max(0.2, dB/100);
                    ctx.arc(cx+cell/2, cy+cell/2, Math.max(0.1, (cell/2)*baseScale), 0, Math.PI*2); ctx.fill();
                } else if (shape === 'leaf') {
                    const rad = Math.max(0, (cell/2)*Math.max(0.3, dB/100));
                    ctx.moveTo(cx+rad, cy); ctx.lineTo(cx+cell, cy); ctx.lineTo(cx+cell, cy+cell-rad); ctx.quadraticCurveTo(cx+cell, cy+cell, cx+cell-rad, cy+cell); ctx.lineTo(cx, cy+cell); ctx.lineTo(cx, cy+rad); ctx.quadraticCurveTo(cx, cy, cx+rad, cy); ctx.fill();
                } else if (shape === 'diamond') { 
                    const scale = Math.max(0.1, dB / 100);
                    const dR = (cell / 2) * scale;
                    const cxc = cx + cell / 2, cyc = cy + cell / 2;
                    ctx.moveTo(cxc, cyc - dR); ctx.lineTo(cxc + dR, cyc); ctx.lineTo(cxc, cyc + dR); ctx.lineTo(cxc - dR, cyc); ctx.fill(); 
                } else if (shape === 'plus' || shape === 'x-matrix') {
                    const lw = cell * Math.max(0.2, Math.min(1.5, dB/100));
                    ctx.lineWidth = lw; ctx.lineCap = shape === 'x-matrix' ? 'butt' : 'round';
                    if (shape==='plus') { 
                        ctx.moveTo(cx+cell/2, cy); ctx.lineTo(cx+cell/2, cy+cell); 
                        ctx.moveTo(cx, cy+cell/2); ctx.lineTo(cx+cell, cy+cell/2); 
                    } else { 
                        const ov = lw / 3; 
                        ctx.moveTo(cx - ov, cy - ov); ctx.lineTo(cx+cell + ov, cy+cell + ov); 
                        ctx.moveTo(cx+cell + ov, cy - ov); ctx.lineTo(cx - ov, cy+cell + ov); 
                    }
                    ctx.stroke();
                } else if (shape === 'character') {
                    const char = E('module-char')?.value || '★';
                    const baseScale = Math.max(0.1, dB/100);
                    ctx.font = `800 ${cell * 1.4 * baseScale}px Inter, sans-serif`;
                    ctx.textAlign = 'center';
                    ctx.textBaseline = 'middle';
                    ctx.fillText(char, cx + cell/2, cy + cell/2 + (cell * 0.05));
                } else if (shape === 'image') {
                    const baseScale = Math.max(0.1, dB/100);
                    const drawSize = cell * baseScale;
                    const offset = (cell - drawSize) / 2;
                    if (customModuleImage) {
                        ctx.drawImage(customModuleImage, cx + offset, cy + offset, drawSize, drawSize);
                    } else {
                        ctx.fillRect(cx + offset, cy + offset, drawSize, drawSize);
                    }
                }

                if (dS !== 1.0 || dX !== 0 || dY !== 0) {
                    ctx.restore();
                }
            }
        }

        if (logoShape !== 'none') {
            if (!heatmap) {
                ctx.fillStyle = bgGrad; 
                if(logoShape === 'circle') { 
                    ctx.beginPath(); ctx.arc(lC, lC, tSz/2, 0, Math.PI*2); ctx.fill(); 
                } else { 
                    ctx.fillRect(pXy, pXy, tSz, tSz); 
                }

                let activeLogo = customLogoImage;
                if (customLogoIsGif && logoGifFrames) {
                    activeLogo = getCurrentGifFrame({frames: logoGifFrames, totalTime: logoGifTotalTime}, gifTimeMs) || customLogoImage;
                }

                if (activeLogo) {
                    ctx.save();
                    if(logoShape === 'circle') { ctx.beginPath(); ctx.arc(lC, lC, sz/2, 0, Math.PI*2); ctx.clip(); }
                    else { ctx.beginPath(); roundRectPath(ctx, (cSz-sz)/2, (cSz-sz)/2, sz, sz, sz*0.1); ctx.clip(); }
                    ctx.drawImage(activeLogo, (cSz-sz)/2, (cSz-sz)/2, sz, sz);
                    ctx.restore();
                } else {
                    ctx.fillStyle = E('color-start')?.value || '#000000';
                    if(logoShape === 'circle') { 
                        ctx.beginPath(); ctx.arc(lC, lC, sz/2, 0, Math.PI*2); ctx.fill(); 
                    } else { 
                        ctx.fillRect((cSz-sz)/2, (cSz-sz)/2, sz, sz); 
                    }
                    ctx.fillStyle = E('color-bg-start')?.value || '#ffffff';
                    ctx.font = `bold ${sz/4}px Inter`; ctx.textAlign = 'center'; ctx.textBaseline = 'middle'; ctx.fillText('LOGO', lC, lC);
                }
            } else {
                ctx.fillStyle = 'rgba(255,255,255,0.1)'; ctx.strokeStyle = 'rgba(255,255,255,0.5)'; ctx.lineWidth = 4; ctx.setLineDash([10, 10]);
                if(logoShape === 'circle') { ctx.beginPath(); ctx.arc(lC, lC, tSz/2, 0, Math.PI*2); ctx.fill(); ctx.stroke(); } 
                else { ctx.fillRect(pXy, pXy, tSz, tSz); ctx.strokeRect(pXy, pXy, tSz, tSz); }
                ctx.setLineDash([]);
            }
        }
    };
    
    renderM('qr-naive', nData); 
    renderM('qr-optimal', oData);
    
    const mini = E('qr-mini-mirror');
    if(mini) {
        const mSz = 1024;
        if (mini.width !== mSz) {
            mini.width = mini.height = mSz;
        }
        const miniCtx = mini.getContext('2d', { alpha: false });
        miniCtx.clearRect(0, 0, mSz, mSz);
        miniCtx.drawImage(E('qr-optimal'), 0, 0, mSz, mSz);
    }

    const scanContainer = E('scan-container');
    if (!E('live-scan-toggle')?.checked) {
        if (scanContainer) {
            scanContainer.classList.add('hidden');
            scanContainer.classList.remove('opacity-100');
        }
        return;
    }

    if (scanContainer && scanContainer.classList.contains('hidden')) {
        scanContainer.classList.remove('hidden');
        void scanContainer.offsetWidth; 
        scanContainer.classList.add('opacity-100');
        E('scan-status-text').textContent = 'ANALYZING...';
        E('scan-score-num').textContent = '--%';
        E('scan-score-bar').style.width = '0%';
        E('scan-score-bar').className = 'h-full bg-slate-500 transition-all duration-300 ease-out';
    }

    const now = Date.now();
    if (now - lastValidateTime > 400) {
        lastValidateTime = now;
        setTimeout(checkScannability, 0); 
    } else {
        if (validationTimeout) clearTimeout(validationTimeout);
        validationTimeout = setTimeout(() => {
            lastValidateTime = Date.now();
            checkScannability();
        }, 400);
    }
}

function animLoop(timestamp) {
    const isAnimMeshOn = E('anim-toggle')?.checked;
    
    if (!isAnimMeshOn && !getHasAnimatedGif()) { 
        lastAnimTime = 0; 
        animLoopId = null;
        return; 
    }
    if (!lastAnimTime) lastAnimTime = timestamp;
    const deltaTime = timestamp - lastAnimTime;
    lastAnimTime = timestamp;
    
    gifTimeMs += deltaTime;

    if (isAnimMeshOn) {
        const safeDelta = Math.min(deltaTime, 100);
        const speed = parseInt(E('anim-speed')?.value || '30') / 30;
        globalTime += (safeDelta * 0.003) * speed; 
    }
    
    renderCanvas(); 
    animLoopId = requestAnimationFrame(animLoop);
}

function startAnimIfNeeded() {
    if ((E('anim-toggle')?.checked || getHasAnimatedGif()) && !animLoopId) {
        lastAnimTime = 0;
        animLoopId = requestAnimationFrame(animLoop);
        E('export-gif-btn')?.classList.remove('hidden');
    }
}
