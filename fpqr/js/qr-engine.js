// Core DOM Utilities
const E = id => document.getElementById(id);
const safeSetText = (id, txt) => { if(E(id)) E(id).textContent = txt; };
const safeSetHTML = (id, html) => { if(E(id)) E(id).innerHTML = html; };

// Shared QR Constants
const AP_LOCATIONS = [[], [], [6, 18], [6, 22], [6, 26], [6, 30], [6, 34], [6, 22, 38], [6, 24, 42], [6, 26, 46], [6, 28, 50]];
const QR_CAPACITY = { 
    'L': [0, 152, 272, 440, 640, 864, 1088], 
    'M': [0, 128, 224, 352, 512, 688, 864], 
    'Q': [0, 104, 176, 272, 384, 496, 608], 
    'H': [0, 72, 128, 208, 288, 368, 480] 
};

// Global Matrix State
let currentMatrices = null;

// Live Validation Tracker
let lastValidateTime = 0;
let validationTimeout = null;
let scanHistory = [];
const validateCanvas = document.createElement('canvas');
validateCanvas.width = 512; 
validateCanvas.height = 512;
const validateCtx = validateCanvas.getContext('2d', { willReadFrequently: true });

function getBits(s, m) { 
    const l = s.length; 
    if(m === 'numeric') return Math.floor(l/3)*10 + [0,4,7][l%3]; 
    if(m === 'alphanumeric') return Math.floor(l/2)*11 + (l%2===1?6:0); 
    return new TextEncoder().encode(s).length*8; 
}

function extractFormatInfoFromImage(imageData, code) {
    let result = { ec: 'M', mask: -1 };
    try {
        const tl = code.location.topLeftCorner, tr = code.location.topRightCorner, bl = code.location.bottomLeftCorner;
        const dim = code.version * 4 + 17, dist = dim - 1; 
        const dX_col = (tr.x - tl.x) / dist, dY_col = (tr.y - tl.y) / dist;
        const dX_row = (bl.x - tl.x) / dist, dY_row = (bl.y - tl.y) / dist;

        const getPixelDark = (r, c) => {
            const x = Math.floor(tl.x + c * dX_col + r * dX_row);
            const y = Math.floor(tl.y + c * dY_col + r * dY_row);
            if(x < 0 || y < 0 || x >= imageData.width || y >= imageData.height) return 0;
            const idx = (y * imageData.width + x) * 4;
            return (imageData.data[idx] * 0.299 + imageData.data[idx+1] * 0.587 + imageData.data[idx+2] * 0.114) < 128 ? 1 : 0;
        };

        const bit14 = getPixelDark(0.5, 8.5) ^ 1;
        const bit13 = getPixelDark(1.5, 8.5) ^ 0;
        const bit12 = getPixelDark(2.5, 8.5) ^ 1;
        const bit11 = getPixelDark(3.5, 8.5) ^ 0;
        const bit10 = getPixelDark(4.5, 8.5) ^ 1;

        const ecBits = (bit14 << 1) | bit13;
        if (ecBits === 1) result.ec = 'L';
        else if (ecBits === 0) result.ec = 'M';
        else if (ecBits === 3) result.ec = 'Q';
        else if (ecBits === 2) result.ec = 'H';

        result.mask = (bit12 << 2) | (bit11 << 1) | bit10;
    } catch (e) { console.error("Format Info Extraction fail:", e); }
    return result; 
}

function runDP(text, uT, pT) {
    let s = text; 
    let pStart = s.includes('://') ? s.indexOf('://') + 3 : 0;
    let sIdx = -1;
    
    for(let i = pStart; i < s.length; i++) {
        if (s[i] === '/' || s[i] === '?' || s[i] === '#') { sIdx = i; break; }
    }

    if (sIdx !== -1) { 
        s = (uT ? s.substring(0, sIdx).toUpperCase() : s.substring(0, sIdx)) + (pT ? s.substring(sIdx).toUpperCase() : s.substring(sIdx)); 
    } else {
        s = uT ? s.toUpperCase() : s;
    }

    const n = s.length, dp = Array(n+1).fill(Infinity), back = Array(n+1).fill(null); dp[0] = 0;
    for(let i=0; i<n; i++) for(let j=i+1; j<=n; j++) {
        const sub = s.substring(i,j);
        const modes = [{m:'numeric',v:/^[0-9]+$/.test(sub)}, {m:'alphanumeric',v:/^[0-9A-Z $%*+\-./:]+$/.test(sub)}, {m:'byte',v:true}];
        for(const {m,v} of modes) if(v) { 
            const c = (m==='byte'?12:13) + getBits(sub,m); 
            if(dp[i]+c < dp[j]) { dp[j] = dp[i]+c; back[j] = {f:i,m,d:sub,c}; } 
        }
    }
    let segs = [], currIdx = n;
    while(currIdx > 0) { let st = back[currIdx]; segs.unshift({mode:st.m, data:st.d, bits:st.c}); currIdx = st.f; }
    return { segs, dpBits: dp[n], finalString: s };
}

function analyzeData() {
    const isStrictByte = E('strict-byte') ? E('strict-byte').checked : false;
    let res;
    if (isStrictByte) {
        let s = E('input-text')?.value || ""; 
        let pStart = s.includes('://') ? s.indexOf('://') + 3 : 0;
        let sIdx = -1;
        
        for(let i = pStart; i < s.length; i++) {
            if (s[i] === '/' || s[i] === '?' || s[i] === '#') { sIdx = i; break; }
        }

        if (sIdx !== -1) { 
            s = ((E('url-tricks')?.checked) ? s.substring(0,sIdx).toUpperCase() : s.substring(0,sIdx)) + ((E('path-tricks')?.checked) ? s.substring(sIdx).toUpperCase() : s.substring(sIdx)); 
        } else {
            s = (E('url-tricks')?.checked) ? s.toUpperCase() : s;
        }

        const bits = new TextEncoder().encode(s).length * 8;
        res = { segs: [{mode: 'byte', data: s, bits}], dpBits: bits, finalString: s };
    } else {
        res = runDP(E('input-text')?.value || "", E('url-tricks')?.checked, E('path-tricks')?.checked);
    }
    
    const ec = E('ec-level')?.value || "M";
    const overrideV = parseInt(E('version-override')?.value || "0");
    const overrideM = parseInt(E('mask-override')?.value || "-1");

    safeSetText('version-override-val', overrideV === 0 ? 'Auto' : `V${overrideV}`);
    safeSetText('mask-override-val', overrideM === -1 ? 'Auto' : `M${overrideM}`);

    if(E('timeline')) E('timeline').innerHTML = ''; 
    if(E('segment-details')) E('segment-details').innerHTML = '';
    
    res.segs.forEach(s => {
        if(E('timeline')) E('timeline').innerHTML += `<div class="timeline-segment seg-${s.mode==='alphanumeric'?'alpha':s.mode}" style="width:${(s.data.length/res.finalString.length)*100}%">${s.mode[0].toUpperCase()}</div>`;
        if(E('segment-details')) E('segment-details').innerHTML += `<div><span class="text-${s.mode==='alphanumeric'?'yellow':(s.mode==='byte'?'blue':'emerald')}-400 font-bold uppercase">${s.mode}</span> "${s.data}" <span class="float-right">${s.bits}b</span></div>`;
    });

    try {
        let nOpts = { errorCorrectionLevel: ec }; if(overrideM >= 0) nOpts.maskPattern = overrideM;
        let oOpts = { errorCorrectionLevel: ec }; if(overrideM >= 0) oOpts.maskPattern = overrideM;
        let nData = QRCode.create([{ data: res.finalString, mode: 'byte' }], nOpts);
        let oData = QRCode.create(res.segs, oOpts);
        let minNV = (nData.modules.size-17)/4, minOV = (oData.modules.size-17)/4;
        let nV = minNV, oV = minOV;
        
        if (overrideV > 0) {
            if (overrideV >= minNV) { try { nData = QRCode.create([{ data: res.finalString, mode: 'byte' }], { ...nOpts, version: overrideV }); nV = overrideV; } catch(e) {} }
            if (overrideV >= minOV) { try { oData = QRCode.create(res.segs, { ...oOpts, version: overrideV }); oV = overrideV; } catch(e) {} }
        } else {
            if (oV < nV) { try { oData = QRCode.create(res.segs, { ...oOpts, version: nV }); oV = nV; } catch(e) {} }
        }
        
        currentMatrices = { nData, oData, nV, oV, ec, res };
        safeSetText('naive-version', `VERSION ${nV} (${nData.modules.size}x${nData.modules.size})`);
        safeSetHTML('optimal-version', `VERSION ${oV} OPTIMIZED`);
        E('version-drop-badge')?.classList.toggle('hidden', oV >= nV);
        
        const cM = (QR_CAPACITY[ec] || [])[oV] || 0;
        const capacityBytes = Math.floor(cM / 8);
        const bytesUsed = Math.ceil(res.dpBits / 8);

        safeSetText('capacity-title', `VERSION ${oV} CAPACITY`); 
        safeSetText('capacity-text', `${bytesUsed} / ${capacityBytes} B`);
        
        if(E('capacity-bar') && capacityBytes > 0) {
            E('capacity-bar').style.width = `${Math.min(100, (bytesUsed/capacityBytes)*100)}%`;
        }

        // Trigger global render if renderer is loaded
        if (typeof renderCanvas === 'function') {
            renderCanvas();
        }
    } catch(e) { console.error("DP Error:", e); }
}

function checkScannability() {
    const container = E('scan-container');
    if (!currentMatrices || !E('live-scan-toggle')?.checked) {
        if (container) container.classList.add('hidden');
        return;
    }

    const optCan = E('qr-optimal');
    if (!optCan || !container) return;

    const targetStr = currentMatrices.res.finalString;
    let score = 0;
    const s = 512;

    const drawAndTest = (transformFn, filterStr = 'none') => {
        validateCtx.fillStyle = '#ffffff';
        validateCtx.fillRect(0, 0, s, s);
        validateCtx.save();
        
        if (transformFn) transformFn(validateCtx);
        
        validateCtx.filter = filterStr;
        const pad = 32;
        validateCtx.drawImage(optCan, pad, pad, s - pad*2, s - pad*2);
        validateCtx.restore();

        const imgData = validateCtx.getImageData(0, 0, s, s);
        const code = jsQR(imgData.data, s, s, { inversionAttempts: "attemptBoth" });
        return (code && code.data === targetStr);
    };

    if (drawAndTest()) {
        score += 40; 
        if (drawAndTest(ctx => { ctx.translate(s/2, s/2); ctx.scale(0.8, 0.8); ctx.translate(-s/2, -s/2); })) score += 15;
        if (drawAndTest(ctx => { ctx.translate(s/2, s/2); ctx.scale(0.6, 0.6); ctx.translate(-s/2, -s/2); })) score += 15;
        if (drawAndTest(null, 'blur(0.5px)')) score += 15;
        if (drawAndTest(null, 'blur(1px)')) score += 15;
    } else {
        if (drawAndTest(null, 'contrast(400%) grayscale(100%)')) { score += 20; } 
        else if (drawAndTest(null, 'brightness(200%) contrast(400%) grayscale(100%)')) { score += 20; } 
        else if (drawAndTest(null, 'brightness(50%) contrast(400%) grayscale(100%)')) { score += 20; }
        else if (drawAndTest(null, 'invert(100%) contrast(400%) grayscale(100%)')) { score += 20; }
    }

    scanHistory.push(score);
    if (scanHistory.length > 5) scanHistory.shift();
    const smoothedScore = Math.round(scanHistory.reduce((a, b) => a + b, 0) / scanHistory.length);

    const updateBadge = (scoreNum, text, barColorClass, textColorClass) => {
        const bar = E('scan-score-bar');
        const status = E('scan-status-text');
        const numText = E('scan-score-num');
        
        if (bar) {
            bar.style.width = `${Math.max(5, scoreNum)}%`;
            bar.className = `h-full ${barColorClass} transition-all duration-300 ease-out`;
        }
        if (status) {
            status.textContent = text;
            status.className = `text-[10px] font-bold uppercase tracking-widest ${textColorClass}`;
        }
        if (numText) {
            numText.textContent = `${scoreNum}%`;
            numText.className = `text-xs font-mono ${textColorClass}`;
        }
    };

    if (smoothedScore >= 85) { updateBadge(smoothedScore, 'EXCELLENT', 'bg-emerald-500', 'text-emerald-400'); } 
    else if (smoothedScore >= 40) { updateBadge(smoothedScore, 'GOOD', 'bg-blue-500', 'text-blue-400'); } 
    else if (smoothedScore >= 20) { updateBadge(smoothedScore, 'FRAGILE', 'bg-amber-500', 'text-amber-400'); } 
    else { updateBadge(smoothedScore, 'UNREADABLE', 'bg-rose-500', 'text-rose-500'); }
}
