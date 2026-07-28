// WebCodecs ImageDecoder approach for native GIF frame extraction
async function decodeGif(file) {
    if (!window.ImageDecoder) return null;
    try {
        const decoder = new ImageDecoder({ type: "image/gif", data: file.stream() });
        const track = decoder.tracks.selectedTrack;
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

window.exportGIF = function(canvasId) {
    if (!gifWorkerUrl) { 
        showToast("GIF Engine loading...", true); 
        return; 
    }
    
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

    const frames = Math.max(10, Math.round(durationSecs * fps));
    const preciseDelta = (2 * Math.PI) / frames;
    const frameDelay = Math.round((durationSecs * 1000) / frames); 
    
    let frame = 0;
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
            gif.on('finished', b => { 
                progEl?.classList.add('hidden'); 
                globalTime = origTime; 
                gifTimeMs = origGifTime;
                renderCanvas(); 
                
                const blobUrl = URL.createObjectURL(b);
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
            });
            gif.render();
        }
    };
    capture();
};
