// WebCodecs ImageDecoder approach for native GIF frame extraction
async function decodeGif(file) {
    if (!window.ImageDecoder) return null;
    try {
        const decoder = new ImageDecoder({ type: "image/gif", data: file.stream() });
        // The track list is populated asynchronously from the stream, so
        // selectedTrack is ALWAYS null on the line after the constructor --
        // reading .frameCount off it threw every single time, the catch below
        // swallowed it, and every animated GIF silently loaded as one still
        // frame with no error shown. Await tracks.ready before touching the
        // track, and completed before trusting frameCount, which climbs as the
        // stream arrives.
        await decoder.tracks.ready;
        await decoder.completed;
        const track = decoder.tracks.selectedTrack;
        if (!track || !track.frameCount) return null;
        const frameCount = track.frameCount;
        const frames = [];
        let totalTime = 0;
        for (let i = 0; i < frameCount; i++) {
            const result = await decoder.decode({ frameIndex: i });
            const canvas = document.createElement('canvas');
            canvas.width = result.image.displayWidth;
            canvas.height = result.image.displayHeight;
            const ctx = canvas.getContext('2d');
            ctx.drawImage(result.image, 0, 0);
            const duration = (result.image.duration || 100000) / 1000;
            frames.push({ canvas, duration });
            totalTime += duration;
            result.image.close();
        }
        return { frames, totalTime };
    } catch(e) { 
        console.error("GIF Decode Error:", e); 
        return null; 
    }
}

let lastGifBlobUrl = null;
let gifExportRunning = false;

window.exportGIF = function(canvasId) {
    if (!gifWorkerUrl) { 
        showToast("GIF Engine loading...", true); 
        return; 
    }
    // Two captures at once would fight over globalTime and produce a pair of
    // scrambled animations.
    if (gifExportRunning) { showToast("A GIF is already being rendered.", true); return; }
    gifExportRunning = true;
    
    const canvas = E(canvasId);
    const progEl = E('gif-progress');
    const progTxt = E('gif-progress-text');
    if(!canvas) return;
    
    progEl?.classList.remove('hidden');
    
    const exportSize = 1024;
    const exportCanvas = document.createElement('canvas');
    exportCanvas.width = exportSize;
    exportCanvas.height = exportSize;
    const eCtx = exportCanvas.getContext('2d', { willReadFrequently: true });

    const gif = new GIF({ 
        workers: 2, 
        quality: 5, 
        workerScript: gifWorkerUrl, 
        width: exportSize, 
        height: exportSize, 
        repeat: 0, 
        dither: 'FloydSteinberg' 
    });
    
    const origTime = globalTime;
    const origGifTime = gifTimeMs;
    
    const fps = 25;
    const speed = parseInt(E('anim-speed')?.value || '30') / 30;
    
    let durationSecs = 2; // Default
    if (E('anim-toggle')?.checked) {
        durationSecs = (2 * Math.PI) / (3.0 * speed);
    } else if (getHasAnimatedGif()) {
        let maxMs = 0;
        if (colorMapIsGif) maxMs = Math.max(maxMs, colorMapGifTotalTime);
        if (densityMapIsGif) maxMs = Math.max(maxMs, densityMapGifTotalTime);
        if (customLogoIsGif) maxMs = Math.max(maxMs, logoGifTotalTime);
        durationSecs = maxMs / 1000;
    }

    // Every captured frame is copied into gif.js at 1024x1024 RGBA -- 4MB each,
    // all held until the encode finishes. Taken straight from a source GIF's
    // length that is a tab-killer: a 10s GIF asks for 250 frames (~1GB), a 20s
    // one for 500 (~2GB). Cap the count and stretch the per-frame delay to keep
    // the loop the right duration, just at a lower frame rate.
    const MAX_EXPORT_FRAMES = 120;
    const frames = Math.min(MAX_EXPORT_FRAMES, Math.max(10, Math.round(durationSecs * fps)));
    const preciseDelta = (2 * Math.PI) / frames;
    const frameDelay = Math.round((durationSecs * 1000) / frames); 
    
    let frame = 0;
    window.isExporting = 'gif';
    const capture = () => {
        if (frame < frames) {
            globalTime = origTime + (frame * preciseDelta); 
            gifTimeMs = origGifTime + (frame * frameDelay); 
            renderCanvas();
            eCtx.drawImage(canvas, 0, 0, exportSize, exportSize);
            
            const imgData = eCtx.getImageData(0, 0, exportSize, exportSize);
            const data = imgData.data;
            
            let isGrayscale = true;
            for (let i = 0; i < data.length; i += 64) {
                if (Math.abs(data[i] - data[i+1]) > 5 || Math.abs(data[i+1] - data[i+2]) > 5) {
                    isGrayscale = false; break;
                }
            }
            
            if (isGrayscale) {
                const step = 255 / 7;
                for (let i = 0; i < data.length; i += 4) {
                    const luma = data[i] * 0.299 + data[i+1] * 0.587 + data[i+2] * 0.114;
                    const val = luma > 248 ? 255 : (luma < 8 ? 0 : Math.round(luma / step) * step);
                    data[i] = data[i+1] = data[i+2] = val;
                }
            } else {
                for (let i = 0; i < data.length; i += 4) {
                    for (let j = 0; j < 3; j++) {
                        let v = data[i+j];
                        if (v > 245) data[i+j] = 255;
                        else if (v < 10) data[i+j] = 0;
                        else data[i+j] = Math.round(v / 8) * 8; 
                    }
                }
            }
            eCtx.putImageData(imgData, 0, 0);

            gif.addFrame(exportCanvas, {copy: true, delay: frameDelay}); 
            if(progTxt) progTxt.textContent = `CAPTURING ${Math.round((frame/frames)*50)}%`;
            frame++; requestAnimationFrame(capture);
        } else {
            if(progTxt) progTxt.textContent = "ENCODING..."; 
            gif.on('progress', p => { if(progTxt) progTxt.textContent = `ENCODING ${Math.round(50 + p*50)}%`; });
            gif.on('abort', () => {
                // Without this a failed encode leaves the guard latched and the
                // button dead until the page is reloaded.
                gifExportRunning = false;
                window.isExporting = false;
                progEl?.classList.add('hidden');
                globalTime = origTime;
                gifTimeMs = origGifTime;
                renderCanvas();
                showToast('GIF encoding failed.', true);
            });
            gif.on('finished', b => { 
                progEl?.classList.add('hidden'); 
                window.isExporting = false;
                globalTime = origTime; 
                gifTimeMs = origGifTime;
                renderCanvas(); 
                
                // Released when the modal closes; a 1024px animation is several
                // megabytes and every export was leaking one for the session.
                if (lastGifBlobUrl) URL.revokeObjectURL(lastGifBlobUrl);
                const blobUrl = URL.createObjectURL(b);
                lastGifBlobUrl = blobUrl;
                const modal = E('isolate-modal');
                const img = E('isolate-img');
                if(img) img.src = blobUrl;
                
                const btnPng = E('modal-download-png');
                if(btnPng) {
                    btnPng.innerHTML = `Download GIF`;
                    btnPng.onclick = () => {
                        const l = document.createElement('a'); 
                        l.download = `Animated-Matrix-${Date.now()}.gif`; 
                        l.href = blobUrl; 
                        l.click(); 
                    };
                }
                
                const btnJpg = E('modal-download-jpg');
                if(btnJpg) btnJpg.classList.add('hidden');

                if(modal) { 
                    modal.classList.remove('hidden'); 
                    void modal.offsetWidth; 
                    modal.classList.add('opacity-100'); 
                }
                gifExportRunning = false;
            });
            gif.render();
        }
    };
    capture();
};
