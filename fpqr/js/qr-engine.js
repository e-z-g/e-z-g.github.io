// Core DOM Utilities
const E = id => document.getElementById(id);
const safeSetText = (id, txt) => { if(E(id)) E(id).textContent = txt; };
const safeSetHTML = (id, html) => { if(E(id)) E(id).innerHTML = html; };

// Shared QR Constants
// Both tables are indexed by version and must cover the full 1-40 range: the
// version slider goes to 20 and auto-selection can pick anything up to 40, so a
// short table silently degrades (no alignment styling, "0 B" capacity readout).
const AP_LOCATIONS = [
    [],                             // (unused, versions are 1-based)
    [],                             // v1 has no alignment patterns
    [6, 18],       [6, 22],         [6, 26],         [6, 30],         [6, 34],
    [6, 22, 38],   [6, 24, 42],     [6, 26, 46],     [6, 28, 50],     [6, 30, 54],
    [6, 32, 58],   [6, 34, 62],     [6, 26, 46, 66], [6, 26, 48, 70], [6, 26, 50, 74],
    [6, 30, 54, 78], [6, 30, 56, 82], [6, 30, 58, 86], [6, 34, 62, 90],
    [6, 28, 50, 72, 94],  [6, 26, 50, 74, 98],  [6, 30, 54, 78, 102], [6, 28, 54, 80, 106],
    [6, 32, 58, 84, 110], [6, 30, 58, 86, 114], [6, 34, 62, 90, 118],
    [6, 26, 50, 74, 98, 122],  [6, 30, 54, 78, 102, 126], [6, 26, 52, 78, 104, 130],
    [6, 30, 56, 82, 108, 134], [6, 34, 60, 86, 112, 138], [6, 30, 58, 86, 114, 142],
    [6, 34, 62, 90, 118, 146],
    [6, 30, 54, 78, 102, 126, 150], [6, 24, 50, 76, 102, 128, 154],
    [6, 28, 54, 80, 106, 132, 158], [6, 32, 58, 84, 110, 136, 162],
    [6, 26, 54, 82, 110, 138, 166], [6, 30, 58, 86, 114, 142, 170]
];

// Usable data capacity in bits (total data codewords x 8) per version.
const QR_CAPACITY = {
    'L': [0, 152, 272, 440, 640, 864, 1088, 1248, 1552, 1856, 2192, 2592, 2960, 3424, 3688, 4184,
          4712, 5176, 5768, 6360, 6888, 7456, 8048, 8752, 9392, 10208, 10960, 11744, 12248, 13048,
          13880, 14744, 15640, 16568, 17528, 18448, 19472, 20528, 21616, 22496, 23648],
    'M': [0, 128, 224, 352, 512, 688, 864, 992, 1232, 1456, 1728, 2032, 2320, 2672, 2920, 3320,
          3624, 4056, 4504, 5016, 5352, 5712, 6256, 6880, 7312, 8000, 8496, 9024, 9544, 10136,
          10984, 11640, 12328, 13048, 13800, 14496, 15312, 15936, 16816, 17728, 18672],
    'Q': [0, 104, 176, 272, 384, 496, 608, 704, 880, 1056, 1232, 1440, 1648, 1952, 2088, 2360,
          2600, 2936, 3176, 3560, 3880, 4096, 4544, 4912, 5312, 5744, 6032, 6464, 6968, 7288,
          7880, 8264, 8920, 9368, 9848, 10288, 10832, 11408, 12016, 12656, 13328],
    'H': [0, 72, 128, 208, 288, 368, 480, 528, 688, 800, 976, 1120, 1264, 1440, 1576, 1784,
          2024, 2264, 2504, 2728, 3080, 3248, 3536, 3712, 4112, 4304, 4768, 5024, 5288, 5608,
          5960, 6344, 6760, 7208, 7688, 7888, 8432, 8768, 9136, 9776, 10208]
};

// Global Matrix State
let currentMatrices = null;

// Live Validation Tracker
let scanHistory = [];
const validateCanvas = document.createElement('canvas');
validateCanvas.width = 512; 
validateCanvas.height = 512;
const validateCtx = validateCanvas.getContext('2d', { willReadFrequently: true });

// Readability Accumulator Variables
let animScanAccumulator = 0;
let animScanCount = 0;
let lastAnimScanUpdate = Date.now();

// Per-segment overhead: 4-bit mode indicator + character-count field. The count
// field widens at versions 10 and 27; these are the version 1-9 widths, which is
// the range the DP is actually choosing between.
const SEG_HEADER_BITS = { numeric: 4 + 10, alphanumeric: 4 + 9, byte: 4 + 8 };

// Trailing bits for a numeric run whose length is 1 or 2 past a multiple of 3.
// Hoisted so the DP's inner loop is not re-creating it a few million times.
const NUMERIC_TAIL_BITS = [0, 4, 7];

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
        // jsQR's *Corner points are the OUTER corners of the symbol, not the
        // centres of the corner modules -- topLeft/topRight are a full `dim`
        // modules apart, so one module step is the span divided by dim, NOT by
        // dim-1. Dividing by dim-1 stretches every step by dim/(dim-1), which
        // by row 8 has drifted 8.5/(dim-1) of a module: 0.425 at version 1,
        // against a half-module of tolerance. It read the right module on clean
        // renders and had almost nothing left for a photo or a rounded module.
        // With the correct step the `+ 0.5` offsets below land on module centres.
        const dim = code.version * 4 + 17, dist = dim;
        const dX_col = (tr.x - tl.x) / dist, dY_col = (tr.y - tl.y) / dist;
        const dX_row = (bl.x - tl.x) / dist, dY_row = (bl.y - tl.y) / dist;

        const getPixelDark = (r, c) => {
            const x = Math.floor(tl.x + c * dX_col + r * dX_row);
            const y = Math.floor(tl.y + c * dY_col + r * dY_row);
            if(x < 0 || y < 0 || x >= imageData.width || y >= imageData.height) return 0;
            const idx = (y * imageData.width + x) * 4;
            return (imageData.data[idx] * 0.299 + imageData.data[idx+1] * 0.587 + imageData.data[idx+2] * 0.114) < 128 ? 1 : 0;
        };

        // Format bits 14..10 carry the EC level and mask. In the top-left copy they
        // sit along ROW 8, columns 0-4 -- column 8 / rows 0-4 holds bits 0..4, which
        // are BCH parity, not data. Each bit is unmasked against 0x5412 (101010...).
        const bit14 = getPixelDark(8.5, 0.5) ^ 1;
        const bit13 = getPixelDark(8.5, 1.5) ^ 0;
        const bit12 = getPixelDark(8.5, 2.5) ^ 1;
        const bit11 = getPixelDark(8.5, 3.5) ^ 0;
        const bit10 = getPixelDark(8.5, 4.5) ^ 1;

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

    const n = s.length;

    // The DP still considers every (start, end) pair, but it used to do so by
    // cutting a fresh substring for each one and running two regexes and a
    // TextEncoder over it -- O(n^3) work, on the main thread, on every
    // keystroke. A 400-character payload took 400ms and an 800-character one
    // 1.8 SECONDS per edit, which read as the tab hanging. The tables below
    // answer the same three questions in constant time per pair:
    //   numRunEnd[i] / alnRunEnd[i]  how far a segment starting at i may run
    //                                and still be all-numeric / all-alphanumeric
    //   utf8Prefix[i]                UTF-8 bytes in s[0..i), so a byte segment's
    //                                length is one subtraction
    // Same search, same tie-breaks, same answer -- just without the allocation.
    const numRunEnd = new Int32Array(n + 1);
    const alnRunEnd = new Int32Array(n + 1);
    const utf8Prefix = new Int32Array(n + 1);
    numRunEnd[n] = alnRunEnd[n] = n;
    for (let i = n - 1; i >= 0; i--) {
        const ch = s.charCodeAt(i);
        const isNum = ch >= 48 && ch <= 57;
        // 0-9 A-Z space $ % * + - . / :  -- the QR alphanumeric set
        const isAln = isNum || (ch >= 65 && ch <= 90) || ch === 32 || ch === 36 ||
                      ch === 37 || ch === 42 || ch === 43 || ch === 45 ||
                      ch === 46 || ch === 47 || ch === 58;
        numRunEnd[i] = isNum ? numRunEnd[i + 1] : i;
        alnRunEnd[i] = isAln ? alnRunEnd[i + 1] : i;
    }
    for (let i = 0; i < n; i++) {
        const ch = s.charCodeAt(i);
        let bytes;
        if (ch < 0x80) bytes = 1;
        else if (ch < 0x800) bytes = 2;
        // A surrogate pair is 4 UTF-8 bytes, counted as 2 against each half so
        // that any prefix difference still totals correctly.
        else if (ch >= 0xD800 && ch <= 0xDBFF && i + 1 < n) {
            const next = s.charCodeAt(i + 1);
            bytes = (next >= 0xDC00 && next <= 0xDFFF) ? 2 : 3;
        }
        else if (ch >= 0xDC00 && ch <= 0xDFFF && i > 0) {
            const prev = s.charCodeAt(i - 1);
            bytes = (prev >= 0xD800 && prev <= 0xDBFF) ? 2 : 3;
        }
        else bytes = 3;
        utf8Prefix[i + 1] = utf8Prefix[i] + bytes;
    }

    const dp = new Float64Array(n + 1).fill(Infinity);
    const backFrom = new Int32Array(n + 1).fill(-1);
    const backMode = new Array(n + 1).fill(null);
    dp[0] = 0;

    for (let i = 0; i < n; i++) {
        const base = dp[i];
        if (base === Infinity) continue;
        const numEnd = numRunEnd[i], alnEnd = alnRunEnd[i], byteBase = utf8Prefix[i];
        // Modes are tried numeric, then alphanumeric, then byte, and start
        // positions ascend, so a strict < keeps the original tie-breaking.
        for (let j = i + 1; j <= n; j++) {
            const len = j - i;
            if (j <= numEnd) {
                const c = base + SEG_HEADER_BITS.numeric + Math.floor(len/3)*10 + NUMERIC_TAIL_BITS[len%3];
                if (c < dp[j]) { dp[j] = c; backFrom[j] = i; backMode[j] = 'numeric'; }
            }
            if (j <= alnEnd) {
                const c = base + SEG_HEADER_BITS.alphanumeric + Math.floor(len/2)*11 + (len%2===1?6:0);
                if (c < dp[j]) { dp[j] = c; backFrom[j] = i; backMode[j] = 'alphanumeric'; }
            }
            const cb = base + SEG_HEADER_BITS.byte + (utf8Prefix[j] - byteBase)*8;
            if (cb < dp[j]) { dp[j] = cb; backFrom[j] = i; backMode[j] = 'byte'; }
        }
    }

    // Segment text is cut once, here, rather than n^2 times above.
    let segs = [], currIdx = n, dpBits = 0;
    while (currIdx > 0) {
        const from = backFrom[currIdx], mode = backMode[currIdx];
        const data = s.substring(from, currIdx);
        const bits = SEG_HEADER_BITS[mode] + getBits(data, mode);
        segs.unshift({ mode, data, bits });
        dpBits += bits;
        currIdx = from;
    }
    return { segs, dpBits, finalString: s };
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
    const isAnimated = E('anim-toggle')?.checked || (typeof getHasAnimatedGif === 'function' && getHasAnimatedGif());
    let score = 0;
    const s = isAnimated ? 256 : 512;

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
        score += isAnimated ? 70 : 40;
        if (drawAndTest(ctx => { ctx.translate(s/2, s/2); ctx.scale(0.8, 0.8); ctx.translate(-s/2, -s/2); })) score += isAnimated ? 30 : 15;
        if (!isAnimated) {
            if (drawAndTest(ctx => { ctx.translate(s/2, s/2); ctx.scale(0.6, 0.6); ctx.translate(-s/2, -s/2); })) score += 15;
            if (drawAndTest(null, 'blur(0.5px)')) score += 15;
            if (drawAndTest(null, 'blur(1px)')) score += 15;
        }
    } else {
        if (drawAndTest(null, 'contrast(400%) grayscale(100%)')) { score += 20; }
        else if (!isAnimated && drawAndTest(null, 'brightness(200%) contrast(400%) grayscale(100%)')) { score += 20; }
        else if (!isAnimated && drawAndTest(null, 'brightness(50%) contrast(400%) grayscale(100%)')) { score += 20; }
        else if (!isAnimated && drawAndTest(null, 'invert(100%) contrast(400%) grayscale(100%)')) { score += 20; }
    }


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

    const applyScore = (s) => {
        if (s >= 85) { updateBadge(s, 'EXCELLENT', 'bg-emerald-500', 'text-emerald-400'); } 
        else if (s >= 40) { updateBadge(s, 'GOOD', 'bg-blue-500', 'text-blue-400'); } 
        else if (s >= 20) { updateBadge(s, 'FRAGILE', 'bg-amber-500', 'text-amber-400'); } 
        else { updateBadge(s, 'UNREADABLE', 'bg-rose-500', 'text-rose-500'); }
    };

    if (isAnimated) {
        animScanAccumulator += score;
        animScanCount++;
        const now = Date.now();
        if (now - lastAnimScanUpdate >= 5000) {
            const avgScore = Math.round(animScanAccumulator / animScanCount);
            applyScore(avgScore);
            lastAnimScanUpdate = now;
            animScanAccumulator = 0;
            animScanCount = 0;
        } else if (E('scan-status-text')?.textContent === 'ANALYZING...') {
            applyScore(score);
        }
    } else {
        scanHistory.push(score);
        if (scanHistory.length > 5) scanHistory.shift();
        const smoothedScore = Math.round(scanHistory.reduce((a, b) => a + b, 0) / scanHistory.length);
        applyScore(smoothedScore);
        
        animScanAccumulator = 0;
        animScanCount = 0;
        lastAnimScanUpdate = Date.now();
    }
}
