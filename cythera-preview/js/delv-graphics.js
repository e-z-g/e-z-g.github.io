/* delv-graphics.js -- Cythera's palette, its compressed-graphics decoder, and
 * the undither filter, from bytes to pixels and no further.
 *
 * Nothing in here touches the DOM. decompressDCG() and decodeResource() return
 * a plain Uint8Array of palette indices; undither() takes and returns RGBA
 * arrays. Drawing those onto a canvas is the page's job and stays there, which
 * is what makes this file checkable: utilities/delv_graphics_check.mjs runs
 * delvmod's independent decoder over every image in the archive and compares
 * pixel for pixel, and utilities/decoder_snapshot.mjs hashes the output so a
 * refactor that changes a byte is visible. Keep new code here on the same side
 * of that line -- a decoder that needs a canvas cannot be compared against a
 * Python one.
 *
 * See delv-archive.js for why these are classic scripts and why this is
 * organisation rather than a library. LOAD ORDER: after delv-archive.js, whose
 * bit readers decodeResource() uses; before the page.
 *
 * ABOUT THE PALETTE, before anyone corrects it: this table differs from the
 * application's own `clut` 256 at exactly two entries, index 0 and index 247,
 * and both differences are absorbed by the `>> 2` in scale6to8 -- the rendered
 * pixels are identical either way. The comment above scale6to8 explains why
 * the widening is done by scaling rather than the shift the original used.
 *
 * The undither block is the settled result of a long tuning exercise, and
 * mobile.html carries a port of it as three GPU passes because this
 * implementation costs 5.8 s for a 640x480 frame. utilities/
 * mobile_undither_check.mjs reads UD and the detector's constants back out of
 * this file and fails if the two have drifted, so a tuning change made here
 * without touching mobile.html is caught rather than discovered later.
 */

const PALETTE = ["ffffff","0000a8","00a800","00a8a8","a80000","a800a8","a85400","a8a8a8","545454","5454fc","54fc54","54fcfc","fc5454","fc54fc","fcfc54","fcfcfc","fcfcfc","ececec","d8d8d8","c8c8c8","b8b8b8","a8a8a8","989898","848484","747474","646464","545454","444444","343434","202020","101010","080808","fcf400","f8c800","f4a400","ec8000","e86000","e44000","e02000","dc0000","c80000","b40000","a00000","8c0000","7c0000","680000","540000","400000","fcfcfc","fcf4c0","fcec84","fce448","fcdc38","fcd024","fcc814","fcb800","e89000","d07000","bc5400","a83c00","942800","7c1800","680800","540000","e8905c","dc7848","d0603c","c04c2c","b4381c","a82414","9c1008","900000","800000","6c0000","5c0000","480000","380000","240000","100000","000000","f8fcd8","f4fcb8","e8fc9c","e0fc7c","d0fc5c","c4fc40","b4fc20","a0fc00","90e400","80cc00","74b400","609c00","508400","447000","345800","284000","d8fcd8","bcfcb8","9cfc9c","80fc7c","60fc5c","40fc40","20fc20","00fc00","00e400","04cc00","04b400","049c00","088400","047000","045800","044000","d8ecfc","b8dcfc","9cd0fc","7cbcfc","5cacfc","4094fc","2084fc","0070fc","0068e4","005ccc","0058b4","00509c","004484","003c70","003058","002440","fcc87c","f0b870","e8a868","dc9c60","d09058","c88450","bc784c","b46c44","a0643c","906034","80542c","6c4c24","5c401c","483818","382c10","28200c","fcd8fc","fcb8fc","fc9cfc","fc7cfc","fc5cfc","fc40fc","fc20fc","fc00fc","e000e4","c800cc","b400b4","9c009c","840084","6c0070","580058","400040","fce8dc","fce0d0","fcd8c4","fcd4bc","fcccb0","fcc4a4","fcbc9c","fcb890","e8a47c","d0946c","bc8458","a8744c","94643c","805830","684824","543c1c","fce8dc","f4c8b4","e8b090","e09470","d47850","cc6034","c44818","bc3400","a82800","981c00","881400","781000","680800","580400","480000","380000","fcf46c","f0f060","dce454","ccdc48","b8d040","a8c434","94b82c","84b024","749820","64841c","506c14","405810","30400c","202c08","101404","000000","fcfcfc","e8e8f0","d4d4e8","c0c4dc","b4b4d0","a0a0c8","9494bc","8484b4","74749c","646484","505470","404058","303044","20202c","101018","000000","fc0000","fc1c00","fc4000","fc6000","fc7c00","fc9800","fcbc00","fcdc00","0010fc","1028fc","1c44fc","2c5cfc","3874fc","4484fc","5498fc","60a8fc","d02094","dc34c0","ec48e8","ec60fc","704820","84542c","9c6038","b56d45","24a800","1cbc00","10d000","00e400","000000","000000","fcf4c0","000000"];
// The CLUT above is a 6-bit-per-channel Mac clut that was widened to 8 bits
// by a left shift (v6 << 2). That is why 254 of the 256 entries have all three
// channels a multiple of 4, and why the top of every ramp lands 3 short of
// full range: white comes out 0xFC/252 instead of 255.
//
// Shifting is wrong twice over. It compresses the whole gamut to 0-252, and it
// splits one colour into two: index 0 is stored 255,255,255 while indices 15,
// 16 and 48 -- the same intended white -- are stored 252,252,252. An undither
// pass then sees a 3-level step between two whites and treats it as signal.
//
// Scaling instead of shifting maps 63 -> 255 exactly and keeps every
// intermediate step proportional: round(v6 * 255/63). All four whites collapse
// onto 255,255,255 and the 252/255 split disappears. The two entries that are
// not multiples of 4 (index 0, already full range, and index 247) round back
// to within one level of themselves, so nothing else moves meaningfully.
function scale6to8(v8) { return Math.round(((v8 >> 2) * 255) / 63); }
function hexToRgb(h) {
  return [scale6to8(parseInt(h.substr(0,2),16)),
          scale6to8(parseInt(h.substr(2,2),16)),
          scale6to8(parseInt(h.substr(4,2),16))];
}
const PAL_RGB = PALETTE.map(hexToRgb);
const CANONICAL_SIZE = { 135: [64,64], 137: [32,16], 141: [32,512], 131: [288,32], 142: [256,256] };
const HAS_HEADER = { 135:false, 137:false, 141:false, 131:false, 142:true };
const UNCOMPRESSED = { 137:true };
/* Delver Compressed Graphics.
 *
 * VERIFIED against delvmod's DelvImage.decompress (delv/graphics.py), which is
 * an independent implementation of this format by the people who worked it out:
 * all 441 images in the shipped archive decode to identical pixels. Re-run it
 * with utilities/delv_graphics_check.mjs after touching anything in here --
 * decoder_snapshot.mjs only proves this function is *unchanged*, which a
 * decoder that has been wrong since it was written also passes.
 *
 * The two implementations differ deliberately in four places, all opcodes
 * delvmod treats as fatal or undefined (0xD4-0xDF, 0xF1-0xF7, 0xFE, 0xF8-0xFD;
 * each is commented at its branch below). That check walks every opcode stream
 * and confirms this archive reaches none of them -- which is the other half of
 * the argument, because identical pixels would equally be explained by a
 * divergent branch that never fires. */
function decompressDCG(data, width, height) {
  const image = new Uint8Array(width*height);
  let cursor = 0, dcursor = 0; const len = data.length;
  function run(length, color) { const maxc = cursor+length; while (cursor < maxc && cursor < image.length) { image[cursor]=color; cursor++; } }
  function copy(length, origin) {
    const absOrigin = cursor+origin; const copyWidth = -origin;
    for (let n=0; n<length && cursor<image.length; n++) {
      const src = absOrigin + (n % copyWidth);
      image[cursor] = (src>=0 && src<image.length) ? image[src] : 0;
      cursor++;
    }
  }
  function cdata(bytes) { for (let i=0; i<bytes.length && cursor<image.length; i++) { image[cursor]=bytes[i]; cursor++; } }
  let iterations = 0;
  decompressDCG.lastWarning = null;
  while (dcursor < len) {
    if (++iterations > 300000) {
      decompressDCG.lastWarning = 'Stopped after 300000 opcodes; image may be incomplete.';
      break;
    }
    const opcode = data[dcursor];
    if (opcode < 0x80) {
      const op = data.slice(dcursor, dcursor+2); dcursor+=2;
      const index = -(ncbitsOf(op, [[3,8],[7,1]]) + 1);
      const length = bitsOfSingle(op, 3, 13) + 3; const literals = bitsOfSingle(op, 2, 11);
      cdata(data.slice(dcursor, dcursor+literals)); dcursor += literals;
      copy(length, index);
    } else if (opcode < 0xC0) {
      const op = data.slice(dcursor, dcursor+3); dcursor+=3;
      const index = -(ncbitsOf(op, [[6,16],[3,8],[6,2]]) + 1);
      const length = bitsOfSingle(op, 5, 11) + 3; const literals = bitsOfSingle(op, 2, 22);
      cdata(data.slice(dcursor, dcursor+literals)); dcursor += literals;
      copy(length, index);
    } else if (opcode < 0xD0) {
      const op = data.slice(dcursor, dcursor+1); dcursor+=1;
      const size = (bitsOfSingle(op,4,4)+1)*4;
      cdata(data.slice(dcursor, dcursor+size)); dcursor += size;
    } else if (opcode < 0xE0) {
      // 0xD0-0xDF: Short Data. The wiki splits the low nibble as 0b1101 BB CC
      // -- two UNKNOWN bits then two literal bits -- so the literal count is
      // the low 2 bits only, not the whole nibble. The two readings agree for
      // 0xD0-0xD3 and diverge above that; only 0xD1 and 0xD2 appear in the
      // Cythera corpus, so the wiki's split is untested but is what we follow.
      // (Before either reading, this was a 2-byte no-op, which dropped pixels
      // and desynced the stream: 0x8E14, 0x8401 and 0x8F04 failed to decode.)
      const op = data.slice(dcursor, dcursor+1); dcursor += 1;
      const literals = opcode & 0x03;
      if (opcode & 0x0C) {
        decompressDCG.lastWarning = 'Short Data opcode 0x' + opcode.toString(16) +
          ' at 0x' + (dcursor-1).toString(16) + ' sets the two undocumented bits; ' +
          'literal count read as ' + literals + ' (low 2 bits only).';
      }
      cdata(data.slice(dcursor, dcursor+literals)); dcursor += literals;
    } else if (opcode < 0xF0) {
      const op = data.slice(dcursor, dcursor+2); dcursor+=2;
      const length = bitsOfSingle(op,4,4)+3; const color = op[1];
      run(length,color);
    } else if (opcode < 0xF8) {
      // Long Run is the prefix 0b11110***, i.e. the whole range 0xF0-0xF7.
      // Only 0xF0 occurs in the Cythera corpus and the three low bits do not
      // appear to affect anything, but 0xF1 is known to be interpreted as
      // Long Run, so treating 0xF1-0xF7 as fatal was wrong.
      const op = data.slice(dcursor, dcursor+3); dcursor+=3;
      const length = op[1]+3; const color = op[2];
      run(length,color);
    } else if (opcode === 0xFF || opcode === 0xFE) {
      // Terminate is the prefix 0b1111111*: 0xFE terminates as well as 0xFF.
      dcursor += 1; break;
    }
    else {
      // 0xF8-0xFD remain genuinely unknown -- they are not covered by any
      // prefix in the wiki's command table and have not been seen in the
      // corpus, so they may simply be unimplemented.
      // Return what decoded successfully rather than discarding the whole
      // image; a single bad byte used to blank the entire resource.
      decompressDCG.lastWarning = 'Unknown opcode 0x' + opcode.toString(16) +
        ' at 0x' + dcursor.toString(16) + '; showing partial image.';
      break;
    }
  }
  return image;
}

/* One resource in subindex 141 is not a tile sheet at all.
   ---------------------------------------------------------------------------
   0x8EFF -- the wiki's "Tombstone" -- was being decompressed as the fixed
   32x512 strip every other 0x8Exx resource is, which produced a sheared mess:
   its rows are 196 pixels long, so reading them 32 at a time walks diagonally
   through the picture. It is a SIZED resource, the same 4-byte {width, height}
   header subindex 142 uses, and it decodes to a 194x127 tombstone slab -- the
   panel the game lays a gravestone inscription on.

   Two things have to hold before the header reading is used, and across all
   160 tile sheets in the archive only 0x8EFF passes both:

     * the header parses to a plausible picture (every other sheet's first four
       bytes read as sizes like 61693x128 or 20x61185 -- they are compression
       opcodes, not a header; only 0x8E8D at 272x46 and 0x8EFF at 194x127 are
       even arguable), and
     * none of the sixteen tile ids the sheet would occupy carries any tile
       attribute in 0xF002. 0x8E8D's sixteen are all attributed and all named
       ("earthen wall", "small hole", "fine wire"...) and all referenced by
       maps; 0x8EFF's sixteen are attributed nowhere and referenced by nothing.

   Row-to-row self-similarity confirms the reading: 0.58 flat against 0.82 at
   the header's width. */
const _sizedSheetCache = new Map();
function tileSheetIsSized(resid, resData) {
  if (_sizedSheetCache.has(resid)) return _sizedSheetCache.get(resid);
  let ok = false;
  try {
    if (resData && resData.length >= 8) {
      const h = resData.slice(0, 4);
      const w2 = bitsOf(h, 14, 0) << 2, fl = bitsOf(h, 2, 14);
      const h2 = bitsOf(h, 15, 16) << 1, fl2 = bitsOf(h, 1, 31);
      const lw = w2 + (fl ? 4 : 0), lh = h2 + fl2;
      if (lw >= 8 && lw <= 1024 && lh >= 8 && lh <= 1024 && lw * lh >= 1024) {
        const attrs = getTileAttributes();
        const first = (resid & 0xFF) << 4;
        let used = false;
        for (let t = first; t < first + 16; t++) if (attrs[t]) { used = true; break; }
        ok = !used;
      }
    }
  } catch (e) {}
  _sizedSheetCache.set(resid, ok);
  return ok;
}

function decodeResource(resData, subn, resid) {
  let W, H, logW, logH, image;
  if (UNCOMPRESSED[subn]) { [W,H] = CANONICAL_SIZE[subn]; image = resData.slice(0, W*H); return {W,H,image}; }
  if (subn === 141 && resid !== undefined && tileSheetIsSized(resid, resData)) subn = 142;
  if (HAS_HEADER[subn] && resData.length >= 4) {
    const header = resData.slice(0,4);
    let W2 = bitsOf(header, 14, 0) << 2;
    const flags = bitsOf(header, 2, 14);
    let H2 = bitsOf(header, 15, 16) << 1;
    const flags2 = bitsOf(header, 1, 31);
    // logH2 must include flags2. delv computes logical_height = height + flags2
    // BEFORE adding flags2 to height, so the two end up equal and the decode
    // buffer holds every row. Taking logH2 from the pre-adjustment height
    // decoded one row short, and the crop below then read past the end of the
    // buffer and filled the last row with the `|| 0` fallback -- 28 of the 59
    // sized resources have flags2 set and were losing their bottom row.
    let logW2 = W2, logH2 = H2 + flags2;
    if (flags) { logW2 += 4; W2 += flags; }
    if (flags2) { H2 += flags2; }
    resData = resData.slice(4);
    const fullImage = decompressDCG(resData, logW2, logH2);
    let image = fullImage;
    if (W2 !== logW2 || H2 !== logH2) {
      image = new Uint8Array(W2*H2);
      for (let y=0;y<H2;y++) {
        for (let x=0;x<W2;x++) image[y*W2+x] = fullImage[y*logW2+x] || 0;
      }
    }
    return {W:W2, H:H2, image};
  }
  [W,H] = CANONICAL_SIZE[subn];
  image = decompressDCG(resData, W, H);
  return {W,H,image};
}

function reshapeTileSheetGrid(W, H, image) {
  if (W !== 32 || H !== 512) return {W,H,image};
  const gridW = 128, gridH = 128;
  const out = new Uint8Array(gridW*gridH);
  for (let t=0; t<16; t++) {
    const gx = (t % 4) * 32, gy = Math.floor(t / 4) * 32;
    for (let y=0;y<32;y++) for (let x=0;x<32;x++) {
      out[(gy+y)*gridW + (gx+x)] = image[(t*32+y)*32 + x];
    }
  }
  return {W:gridW, H:gridH, image:out};
}

// Palette index 0 is Delver's transparent slot. Portraits are cut-outs on
// index 0, so forcing alpha 255 painted a white box behind every face.
// Cythera animates water, lava and magic by palette cycling rather than by
// swapping frames: the wiki records that "colors 0xE0-0xFB inclusive are
// subject to palette animation", and Glenn Andreas describes the engine
// iterating those indices for "the lava, or waves in the water". The Andreas
// quote and the 0xE0-0xFB range are the wiki's; the five-ramp subdivision
// below is THIS TOOL'S OWN reading of the palette and appears nowhere in the
// wiki. It is a guess that looks right, not documented fact:
//   E0-E7 fire/lava   E8-EF water   F0-F3 magic (the void sparkle)
//   F4-F7 earth       F8-FB nature
const PALETTE_CYCLES = [[0xE0,8],[0xE8,8],[0xF0,4],[0xF4,4],[0xF8,4]];
function cycledPalette(frame) {
  const pal = PAL_RGB.slice();
  for (const [start, len] of PALETTE_CYCLES) {
    for (let i = 0; i < len; i++) pal[start + i] = PAL_RGB[start + ((i + frame) % len)];
  }
  return pal;
}
function imageUsesAnimatedColors(image) {
  for (let i = 0; i < image.length; i++) if (image[i] >= 0xE0 && image[i] <= 0xFB) return true;
  return false;
}

// The in-app dedither is gone. It was a 3x3 box blur that pushed pixels off
// the palette, which meant the canvas no longer matched its palette indices
// and PNG export had to fall back to RGBA. Undithering now happens in the
// separate tool, fed by the indexed PNGs this viewer writes.


// ===================== Undither =========================================
// Tone reconstruction for the quantised photographs behind the portrait and
// graphic resources. Lifted verbatim from cythera_graphics_undither.html and
// checked byte-for-byte against it on eight resources; the only edits were to
// collapse the settings this page does not expose. Those settings are:
//
//   pattern scale 1, sensitivity 0.67, strength 67%, edge threshold 64,
//   3 refinement passes, detail recovery 50%, checkerboard-notch smoother,
//   stray-colour repair at 40 (inside dithered areas only, 0.65),
//   2x structure-guided upscale resampled back to native size.
//
// Specks, denoise and palette requantisation are not offered and their code is
// not carried over. The tuning page remains the place to explore; this is the
// settled result of that exploration.
const UD = {
  radius:1, sens:0.67, lock:true, diagonals:false, strength:0.67, edge:64, passes:3,
  detail:0.5, speck:0, speckPasses:2, speckLiterals:false, stray:40, strayRegion:0.65,
  nlm:0, nlmPatch:2, nlmSearch:4, upscale:2, supersample:true, scaler:"guided",
  filter:"notch", quantise:"off", quantiseK:2, lockAnimated:true, protectCutout:true
};
const LINE_REACH = 3;
const AXES_STRAIGHT = [[1,0],[0,1]];
const AXES_ALL      = [[1,0],[0,1],[1,1],[1,-1]];

function isAnimatedIndex(n){ return n >= 0xE0 && n < 0xFC; }

/* ------------------------------------------------------------
   Protected pixels.

   Two things are never touched by any stage:

     transparency, so the cut-out can never be dragged into the
     artwork or the artwork smeared out past its own silhouette;

     palette-animated indices E0-FB, whose exact values are chosen
     for their position in a runtime colour cycle and so carry
     meaning that averaging would destroy.

   There used to be a third: pixels the encoder emitted as a long
   run or a distant copy were treated as deliberate structure and
   locked. That was wrong, and measurably so. In dithered artwork
   the dither is itself what compresses into long copies — the
   encoder is matching one patch of noise against another — so
   trusting copies pinned the dither in place instead of the
   drawing. It locked 48% of one portrait and 89% of a texture,
   and scored worse on every resource class tried. Removed.
   ------------------------------------------------------------ */
function buildLockedMask(indexPlane, opt, rgba, W, H){
  const N = rgba ? rgba.length/4 : (indexPlane ? indexPlane.length : 0);
  const locked = new Uint8Array(N);
  for(let i=0;i<N;i++){
    if(opt.protectCutout!==false && rgba && rgba[i*4+3]===0){ locked[i]=1; continue; }
    if(opt.lockAnimated && indexPlane && isAnimatedIndex(indexPlane[i])){ locked[i]=1; continue; }
  }
  return locked;
}

function boxMean(src, out, W, H, r, alpha, stride, off){
  const N=W*H;
  const hNum=new Float32Array(N), hDen=new Float32Array(N);
  const pv=new Float64Array(W+1), pm=new Float64Array(W+1);
  for(let y=0;y<H;y++){
    pv[0]=0; pm[0]=0;
    for(let x=0;x<W;x++){
      const i=y*W+x;
      const m=(alpha && alpha[i]===0) ? 0 : 1;
      pv[x+1]=pv[x] + (m ? src[i*stride+off] : 0);
      pm[x+1]=pm[x] + m;
    }
    for(let x=0;x<W;x++){
      const lo=x-r>0?x-r:0, hi=x+r<W-1?x+r:W-1, i=y*W+x;
      hNum[i]=pv[hi+1]-pv[lo];
      hDen[i]=pm[hi+1]-pm[lo];
    }
  }
  const qv=new Float64Array(H+1), qm=new Float64Array(H+1);
  for(let x=0;x<W;x++){
    qv[0]=0; qm[0]=0;
    for(let y=0;y<H;y++){ const i=y*W+x; qv[y+1]=qv[y]+hNum[i]; qm[y+1]=qm[y]+hDen[i]; }
    for(let y=0;y<H;y++){
      const lo=y-r>0?y-r:0, hi=y+r<H-1?y+r:H-1;
      const sm=qm[hi+1]-qm[lo], i=y*W+x;
      out[i*stride+off] = sm>0 ? (qv[hi+1]-qv[lo])/sm : src[i*stride+off];
    }
  }
}

function boxBlur3(src, out, W, H, r, alpha){
  boxMean(src,out,W,H,r,alpha,3,0);
  boxMean(src,out,W,H,r,alpha,3,1);
  boxMean(src,out,W,H,r,alpha,3,2);
}

function boxBlur1(src, out, W, H, r, alpha){ boxMean(src,out,W,H,r,alpha,1,0); }

function smoothstep(a,b,x){
  let t=(x-a)/(b-a); t=t<0?0:t>1?1:t;
  return t*t*(3-2*t);
}

function toFloat3(rgba, N){
  const src=new Float32Array(N*3);
  for(let i=0;i<N;i++){ src[i*3]=rgba[i*4]; src[i*3+1]=rgba[i*4+1]; src[i*3+2]=rgba[i*4+2]; }
  return src;
}

function alphaOf(rgba, N){
  const a=new Uint8Array(N);
  for(let i=0;i<N;i++) a[i] = rgba[i*4+3]===0 ? 0 : 1;
  return a;
}

function detect(src, mean, W, H, thr, diagonals, locked, alpha){
  const N=W*H;
  const res=new Float32Array(N*3), mag=new Float32Array(N), d=new Float32Array(N);
  for(let i=0;i<N*3;i++) res[i]=src[i]-mean[i];
  for(let i=0;i<N;i++){
    const a=res[i*3], b=res[i*3+1], c=res[i*3+2];
    mag[i]=Math.sqrt(a*a+b*b+c*c);
  }
  const AX = diagonals ? AXES_ALL : AXES_STRAIGHT;
  for(let y=0;y<H;y++){
    for(let x=0;x<W;x++){
      const i=y*W+x;
      if(alpha && alpha[i]===0){ d[i]=0; continue; }
      if(locked && locked[i]){ d[i]=0; continue; }
      const m=mag[i];
      if(m<0.5){ d[i]=0; continue; }
      let best=-2;
      for(let a=0;a<AX.length;a++){
        const ax=AX[a][0], ay=AX[a][1];
        let sum=0, cnt=0;
        for(let k=1;k<=LINE_REACH;k++){
          for(let sg=-1; sg<=1; sg+=2){
            const nx=x+ax*k*sg, ny=y+ay*k*sg;
            if(nx<0||ny<0||nx>=W||ny>=H) continue;
            const j=ny*W+nx;
            if(alpha && alpha[j]===0) continue;
            const mj=mag[j];
            cnt++;
            if(mj<0.5) continue;           /* flat neighbour votes neutral */
            sum += (res[i*3]*res[j*3] + res[i*3+1]*res[j*3+1] + res[i*3+2]*res[j*3+2])/(m*mj);
          }
        }
        if(cnt){ const s=sum/cnt; if(s>best) best=s; }
      }
      const coh = best<-1 ? 1 : best;      /* no support at all: treat as coherent */
      let v = (thr-coh)*8;
      v = v<0?0:v>1?1:v;
      d[i] = v * smoothstep(1.5, 5.0, m);  /* ignore imperceptible wobble */
    }
  }
  return {d, mag};
}

/* ------------------------------------------------------------
   Checkerboard notch.

   Where this artwork is dithered, the dither is usually a checkerboard — but
   not in brightness, which is why it hides from a luminance analysis. It is a
   checkerboard in WHICH RAMP each pixel is taken from: neutral greys
   interleaved with warm browns to make a desaturated skin tone. The two are
   close in lightness and far apart in hue, so the pattern is loud to the eye
   and nearly invisible to any measurement of luma.

   Measured on the choice itself, as a grey-or-brown indicator, 56% of the
   mixed patches in 0x8809 and 45% in Pelagon peak at exactly the checkerboard
   frequency. Others, like 0x8801, have almost none — it varies by resource.

   A checkerboard is the single frequency (pi,pi), so it can be removed by a
   filter that is zero there and one at DC instead of by a blur that attenuates
   everything. Half the centre plus half the mean of the four orthogonal
   neighbours does exactly that: the neighbours are all of opposite phase, so
   they cancel the pattern precisely, while a flat area passes through
   untouched. Diagonal neighbours are deliberately excluded — they share the
   centre's phase and would reinforce what we are trying to null.

   On its own it removes a third of the local variation on every portrait
   tried. It cannot tell a one-pixel pupil from one square of a checkerboard,
   so like the other smoothers it is applied through the dither detector rather
   than everywhere.
   ------------------------------------------------------------ */
function checkerNotch(src, guide, out, W, H, r, edge, alpha){
  for(let y=0;y<H;y++){
    for(let x=0;x<W;x++){
      const i=y*W+x, o=i*3;
      if(alpha && alpha[i]===0){ out[o]=src[o]; out[o+1]=src[o+1]; out[o+2]=src[o+2]; continue; }
      let s0=0,s1=0,s2=0,n=0;
      for(let k=0;k<4;k++){
        const nx=x+(k===0?1:k===1?-1:0), ny=y+(k===2?1:k===3?-1:0);
        if(nx<0||ny<0||nx>=W||ny>=H) continue;
        const j=ny*W+nx;
        if(alpha && alpha[j]===0) continue;
        const jo=j*3; s0+=src[jo]; s1+=src[jo+1]; s2+=src[jo+2]; n++;
      }
      if(!n){ out[o]=src[o]; out[o+1]=src[o+1]; out[o+2]=src[o+2]; continue; }
      out[o]  =0.5*src[o]  +0.5*(s0/n);
      out[o+1]=0.5*src[o+1]+0.5*(s1/n);
      out[o+2]=0.5*src[o+2]+0.5*(s2/n);
    }
  }
}

/* ------------------------------------------------------------
   Stray colour repair.

   Some resources carry isolated pixels in a wildly wrong hue — Erechtheus has
   69 magenta ones scattered over his face, from palette index 5 and the far
   end of the magenta ramp. They are quantisation accidents, not paint, and
   they are the most visually offensive thing left in the output because the
   eye finds an out-of-gamut dot instantly.

   Despeckle above will not do the job. It flags a pixel that is isolated and
   far from its neighbours in FULL COLOUR, and that is also an exact
   description of a pupil, which is why it takes the detail you wanted with it.

   The distinction that actually holds is hue. A pupil is extreme in
   brightness but its chroma matches its surroundings — it is a neutral dot in
   a neutral socket. A stray is extreme in chroma: it points somewhere in
   colour space that nothing near it points. Measured on Erechtheus, the
   magenta pixels sit 40 to 160 from their neighbourhood's median chroma;
   Pelagon's and Magpie's pupils sit at 0 to 15. The two populations do not
   overlap anywhere, so a threshold between them separates them completely.

   The isolation test is kept as a second condition so that a small but
   deliberate patch of colour — a gem, a coloured highlight — survives: only a
   pixel with no neighbour of its own hue is treated as an accident.
   ------------------------------------------------------------ */
function fixStrayColours(src, W, H, rgba, T, locked, dLocal, dMin){
  const N=W*H, out=new Float32Array(src), fixed=new Uint8Array(N);
  const cr=new Float32Array(N), cb=new Float32Array(N);
  for(let i=0;i<N;i++){
    const Y=0.299*src[i*3]+0.587*src[i*3+1]+0.114*src[i*3+2];
    cr[i]=src[i*3]-Y; cb[i]=src[i*3+2]-Y;
  }
  const nr=[], nb=[], nbi=[];
  for(let y=0;y<H;y++){
    for(let x=0;x<W;x++){
      const i=y*W+x;
      if(rgba[i*4+3]===0) continue;
      if(locked && locked[i]) continue;
      /* Only inside dithered content. A stray reads as incoherent wherever it
         sits, so the pixel's own detector value cannot tell a magenta accident
         on a cheek from an odd pixel in a drawn frame — both score about 1.
         What separates them is the company they keep: averaged over a
         neighbourhood, a face runs 0.67-0.89 and a drawn frame 0.24-0.59. */
      if(dLocal && dLocal[i] < dMin) continue;
      nr.length=0; nb.length=0; nbi.length=0;
      for(let dy=-1;dy<=1;dy++) for(let dx=-1;dx<=1;dx++){
        if(!dx && !dy) continue;
        const nx=x+dx, ny=y+dy;
        if(nx<0||ny<0||nx>=W||ny>=H) continue;
        const j=ny*W+nx;
        if(rgba[j*4+3]===0) continue;
        nr.push(cr[j]); nb.push(cb[j]); nbi.push(j);
      }
      if(nbi.length<4) continue;
      const sr=nr.slice().sort((a,b)=>a-b), sb=nb.slice().sort((a,b)=>a-b);
      const mr=sr[sr.length>>1], mb=sb[sb.length>>1];
      if(Math.hypot(cr[i]-mr, cb[i]-mb) <= T) continue;      /* hue fits: leave it */
      let kin=false;
      for(let k=0;k<nbi.length;k++)
        if(Math.hypot(cr[i]-nr[k], cb[i]-nb[k]) <= T){ kin=true; break; }
      if(kin) continue;                                      /* part of a coloured patch */
      /* vector median of the neighbours, so the replacement is a colour that
         actually occurs next door rather than an average of several */
      let best=nbi[0], bs=Infinity;
      for(const a of nbi){
        let t=0;
        for(const b of nbi){
          if(a===b) continue;
          t+=Math.hypot(src[a*3]-src[b*3], src[a*3+1]-src[b*3+1], src[a*3+2]-src[b*3+2]);
        }
        if(t<bs){ bs=t; best=a; }
      }
      out[i*3]=src[best*3]; out[i*3+1]=src[best*3+1]; out[i*3+2]=src[best*3+2];
      fixed[i]=1;
    }
  }
  let n=0; for(let i=0;i<N;i++) n+=fixed[i];
  return {out, count:n};
}

/* ------------------------------------------------------------
   Structure-guided upscale.

   Ordinary interpolation has no idea which neighbours belong
   together, so it rounds off exactly the edges the artist drew.
   Here the lock mask is available, and it already knows: a pixel
   the encoder wrote as a long run is on one side of a boundary,
   its unlocked neighbour is on the other. Refusing to mix across
   that boundary keeps silhouettes crisp at 4x while flat interiors
   still interpolate smoothly.
   ------------------------------------------------------------ */
function guidedUpscale(src, W, H, S, locked, alpha, edgeThr){
  const oW=W*S, oH=H*S, N2=oW*oH;
  const out=new Float32Array(N2*3), outAlpha=new Uint8Array(N2);
  const invSr = 1/(2*edgeThr*edgeThr);
  for(let y=0;y<oH;y++){
    for(let x=0;x<oW;x++){
      const lx=(x+0.5)/S-0.5, ly=(y+0.5)/S-0.5;
      const bx=Math.round(lx), by=Math.round(ly);
      const cIdx = Math.max(0,Math.min(H-1,by))*W + Math.max(0,Math.min(W-1,bx));
      const baseLocked = locked ? locked[cIdx] : 0;
      const oIdx = y*oW+x;
      outAlpha[oIdx] = alpha ? alpha[cIdx] : 1;
      if(outAlpha[oIdx]===0) continue;
      let r=0,g=0,b=0,wsum=0;
      for(let dy=-1;dy<=1;dy++){
        for(let dx=-1;dx<=1;dx++){
          const nx=bx+dx, ny=by+dy;
          if(nx<0||ny<0||nx>=W||ny>=H) continue;
          const nIdx=ny*W+nx;
          if(alpha && alpha[nIdx]===0) continue;
          if(locked && locked[nIdx]!==baseLocked) continue;   /* never blend across structure */
          const sdx=nx-lx, sdy=ny-ly;
          const spatial=Math.exp(-(sdx*sdx+sdy*sdy)*2.0);
          const n3=nIdx*3, c3=cIdx*3;
          const c0=src[n3]-src[c3], c1=src[n3+1]-src[c3+1], c2=src[n3+2]-src[c3+2];
          const w = spatial*Math.exp(-(c0*c0+c1*c1+c2*c2)*invSr);
          r+=src[n3]*w; g+=src[n3+1]*w; b+=src[n3+2]*w; wsum+=w;
        }
      }
      const o3=oIdx*3;
      if(wsum>0){ out[o3]=r/wsum; out[o3+1]=g/wsum; out[o3+2]=b/wsum; }
      else { const c3=cIdx*3; out[o3]=src[c3]; out[o3+1]=src[c3+1]; out[o3+2]=src[c3+2]; }
    }
  }
  return {out, outAlpha};
}

function undither(rgba, W, H, p, locked, cls){
  const N=W*H;
  let src=toFloat3(rgba,N);
  const alpha=alphaOf(rgba,N);

  const speck=null, speckCount=0;   /* despeckle is not offered here */

  let strayCount=0;


  const mean=new Float32Array(N*3);
  boxBlur3(src, mean, W, H, p.radius, alpha);

  const d = detect(src, mean, W, H, p.sens, p.diagonals, locked, alpha).d;

  /* How dithered is the NEIGHBOURHOOD, as opposed to the pixel. Drawn artwork
     — a frame, a border pattern, hard linework — is coherent, so this stays
     low across it; a quantised photograph does not, so it runs high. */
  const dLocal=new Float32Array(N);
  boxBlur1(d, dLocal, W, H, 3, alpha);

  if(p.stray>0){
    const sf=fixStrayColours(src, W, H, rgba, p.stray, locked, dLocal, p.strayRegion);
    src=sf.out; strayCount=sf.count;
  }

  if(p.lock){
    for(let y=0;y<H;y++) for(let x=0;x<W;x++){
      const i=y*W+x;
      if(d[i]===0) continue;
      let same=true;
      for(let dy=-1;dy<=1 && same;dy++) for(let dx=-1;dx<=1;dx++){
        if(!dx && !dy) continue;
        const nx=x+dx, ny=y+dy;
        if(nx<0||ny<0||nx>=W||ny>=H) continue;
        const nj=ny*W+nx;
        if(alpha[nj]===0) continue;
        const j=nj*3, o=i*3;
        if(src[j]!==src[o]||src[j+1]!==src[o+1]||src[j+2]!==src[o+2]){ same=false; break; }
      }
      if(same) d[i]=0;
    }
  }

  /* Ping-pong the guide and the output buffer so no pass ever reads
     the array it is writing. `mean` must survive as pass 0's guide,
     which is why the first swap allocates a spare instead of reusing
     it as scratch. */
  /* Only one smoother runs. Combining them was tried and does not pay.

     In sequence, the notch's whole virtue — that it touches exactly one
     frequency and leaves the rest alone — is discarded by whatever general
     filter runs after it: notch-then-guided cleaned 13.3% against guided's
     12.8% and cost proportionally more detail, which is the same point on the
     same curve, slightly further along.

     Mixing them per region does no better. The idea was sound — the local size
     of what the notch removes IS the local checkerboard energy, so you can
     measure which tool suits where — but the blend never rose above the line
     joining the two. Where the detector wants smoothing at all, the
     checkerboard is present, so there is no territory for the general filter
     to win that the notch was losing.

     Cleaning per unit of detail lost, over six portraits: notch 0.56,
     guided 0.40, bilateral 0.37, chained 0.38, mixed 0.38-0.54. The notch is
     the efficient choice and the guided filter the thorough one, and that is a
     real either/or rather than a missing feature. */
  const smooth = checkerNotch;   /* fixed here: the viewer offers no choice */
  let guide=mean, filt=new Float32Array(N*3), spare=null;
  for(let pass=0; pass<p.passes; pass++){
    smooth(src, guide, filt, W, H, p.radius, p.edge, alpha);
    if(pass < p.passes-1){
      if(guide===mean){ spare=spare||new Float32Array(N*3); guide=filt; filt=spare; }
      else { const t=guide; guide=filt; filt=t; }
    }
  }

  let res=new Float32Array(N*3);
  for(let i=0;i<N;i++){
    const isLocked = (locked && locked[i]) || alpha[i]===0;
    const w = isLocked ? 0 : d[i]*p.strength;
    const o=i*3;
    res[o]  =src[o]  +w*(filt[o]  -src[o]);
    res[o+1]=src[o+1]+w*(filt[o+1]-src[o+1]);
    res[o+2]=src[o+2]+w*(filt[o+2]-src[o+2]);
  }

  /* Detail recovery re-sharpens what averaging softened. It only
     makes sense when the dither pattern carried reconstruction
     information (error diffusion). For random-threshold dither
     the pattern is pure noise, so this just re-amplifies what
     was removed — hence the default of zero. */
  if(p.detail>0){
    const b1=new Float32Array(N*3);
    boxBlur3(res, b1, W, H, 1, alpha);
    for(let i=0;i<N;i++){
      if((locked && locked[i]) || alpha[i]===0) continue;
      const w=d[i]*p.strength*p.detail, o=i*3;
      res[o]  +=w*(res[o]  -b1[o]);
      res[o+1]+=w*(res[o+1]-b1[o+1]);
      res[o+2]+=w*(res[o+2]-b1[o+2]);
    }
  }

  /* Dither coverage is a property of the source, so measure it in
     source space before any upscale changes the pixel count. */
  let dsum=0, dcount=0;
  for(let i=0;i<N;i++) if(alpha[i]){ dsum+=d[i]; dcount++; }

  /* Captured before any resampling touches it: the restore below pulls
     undithered pixels back to exactly this. */
  const resNative = res;
  let outW=W, outH=H, outAlpha=alpha, S=p.upscale|0 || 1;
  if(S>1){
    /* Unlike the smoothers, these two are estimators of the same unknown — the
       colour of a sub-pixel that was never recorded — so averaging them has a
       reason to work, and it half does.

       Tested against known truth (take a reconstruction as the answer,
       halve it, upscale back, measure the error) xBR is the most accurate at
       32.62 RMSE, the average second at 32.82 and the guided upscale third at
       33.30. The average won on three of the six resources and was never the
       worst on any, so it is a fair hedge — but it never beat simply picking
       xBR, so it is not free accuracy.

       The guided upscale stays the default despite coming third, because that
       ranking is about edges and gradients and this artwork's hardest content
       is one-pixel features. At the shipped settings xBR lifts Magpie's pupils
       to 25 and 29 where the guided upscale holds them at 16: a lone pupil has
       no edge direction for xBR to commit to, so it gets averaged along a
       direction that is not there. */
    const up = guidedUpscale(res, W, H, S, locked, alpha, p.edge);
    res=up.out; outAlpha=up.outAlpha; outW=W*S; outH=H*S;

    /* Supersampling. Interpolate with the structure guide, then average each
       SxS block back down to one pixel. The point is not resolution — you end
       up the size you started — it is tonal depth. The guided upscale invents
       intermediate samples along each edge, and averaging them produces
       colours that were not in the palette at all, so a two-tone dithered
       ramp comes back as a genuine gradient instead of two flat steps.
       Transparency is decided by majority so the silhouette stays hard. */
    if(p.supersample){
      const down=new Float32Array(W*H*3), downA=new Uint8Array(W*H);
      const n=S*S;
      for(let y=0;y<H;y++){
        for(let x=0;x<W;x++){
          let s0=0,s1=0,s2=0,cnt=0;
          for(let dy=0;dy<S;dy++) for(let dx=0;dx<S;dx++){
            const j=(y*S+dy)*outW + (x*S+dx);
            if(!up.outAlpha[j]) continue;
            const o=j*3; s0+=res[o]; s1+=res[o+1]; s2+=res[o+2]; cnt++;
          }
          const i=y*W+x, o=i*3;
          downA[i] = cnt*2 >= n ? 1 : 0;
          if(cnt){ down[o]=s0/cnt; down[o+1]=s1/cnt; down[o+2]=s2/cnt; }
        }
      }
      res=down; outAlpha=downA; outW=W; outH=H; S=1;
    }
  }

  /* Undo the drift that resampling adds to pixels the filter deliberately
     left alone.

     Zero blend weight is not enough by itself. A pixel the detector scored at
     zero comes out of the filter untouched, but the upscaler still resamples
     it and the downsample averages it with its neighbours, so it moves anyway.
     That is what was softening the Greek key on Erechtheus and turning the
     cream mat black on Pelagon.

     The weight to undo it by is the one already in hand: w = d * strength is
     exactly how much of this pixel was meant to change, so pulling the output
     back toward the pre-upscale result by (1 - w) restores an undithered pixel
     exactly, leaves a fully dithered one entirely alone, and slides smoothly
     between. No geometry, no threshold, and it follows the frame's real shape
     rather than a rectangle that would eat the face wherever the face reaches
     the edge. */
  const M=outW*outH;
  const out=new Uint8ClampedArray(M*4), map=new Uint8ClampedArray(M*4);
  const seen=new Set();
  for(let y=0;y<outH;y++){
    for(let x=0;x<outW;x++){
      const i=y*outW+x, o=i*3;
      /* Nearest source pixel — the map and the restore below both need it. */
      const sx = S===1 ? x : (x/S)|0, sy = S===1 ? y : (y/S)|0;
      const sIdx = sy*W + sx;

      let r0=res[o], r1=res[o+1], r2=res[o+2];
      if(res !== resNative){
        const w = Math.min(1, d[sIdx]*p.strength);
        if(w < 1){
          const n3=sIdx*3, kk=1-w;
          r0 += kk*(resNative[n3]  -r0);
          r1 += kk*(resNative[n3+1]-r1);
          r2 += kk*(resNative[n3+2]-r2);
        }
      }
      out[i*4]=r0; out[i*4+1]=r1; out[i*4+2]=r2;
      const a = out[i*4+3] = outAlpha[i] ? 255 : 0;
      if(a>0 && seen.size<300000) seen.add((out[i*4]<<16)|(out[i*4+1]<<8)|out[i*4+2]);

      const lum=(rgba[sIdx*4]*0.299+rgba[sIdx*4+1]*0.587+rgba[sIdx*4+2]*0.114)*0.22;
      if(speck && speck[sIdx]){ map[i*4]=lum; map[i*4+1]=lum+220; map[i*4+2]=lum+90; }
      else { map[i*4]=lum+208*d[sIdx]; map[i*4+1]=lum; map[i*4+2]=lum+212*d[sIdx]; }
      map[i*4+3]=alpha[sIdx]?255:0;
    }
  }
  return {out, map, pct: dcount?dsum/dcount:0, colors: seen.size, specks: speckCount, strays: strayCount, outW, outH};
}

// Indexed resource in, undithered ImageData out. Cached: a gallery redraws
// constantly (hover, palette cycling, mode changes) and this is far too much
// work to repeat for a picture that has not changed.
const UNDITHER_CACHE = new Map();
function unditherIndexed(W, H, image, transparentIndex, palette, key) {
  if (key && UNDITHER_CACHE.has(key)) return UNDITHER_CACHE.get(key);
  const P = palette || PAL_RGB;
  const t = (transparentIndex === undefined || transparentIndex === null) ? -1 : transparentIndex;
  const N = W * H;
  const rgba = new Uint8ClampedArray(N * 4);
  for (let i = 0; i < N; i++) {
    const v = image[i];
    if (v === t) continue;
    const c = P[v] || [0,0,0];
    rgba[i*4]=c[0]; rgba[i*4+1]=c[1]; rgba[i*4+2]=c[2]; rgba[i*4+3]=255;
  }
  const locked = buildLockedMask(image, UD, rgba, W, H);
  const r = undither(rgba, W, H, UD, locked, null);
  const out = new ImageData(new Uint8ClampedArray(r.out), r.outW, r.outH);
  if (key) {
    if (UNDITHER_CACHE.size > 400) UNDITHER_CACHE.clear();
    UNDITHER_CACHE.set(key, out);
  }
  return out;
}
function hashIndices(image) {
  let h = 2166136261;
  for (let i = 0; i < image.length; i++) { h ^= image[i]; h = Math.imul(h, 16777619); }
  return (h >>> 0).toString(36);
}
// Categories drawn as cut-outs rather than full-bleed images.
// Palette index 0 is Delver's transparent slot across the board, not just for
// portraits: skill icons, tile sheets and general graphics are all cut-outs
// drawn over a background. Maps and landscapes are full-bleed and keep it.
// Skill icons (137) are full-bleed 32x16 buttons, not cut-outs: index 0 is a
// real colour in them, and treating it as the void punched holes through the
// middle of every icon.
const TRANSPARENT_SUBN = new Set([135, 141, 142, 143]);
function transparentIndexFor(subn) { return TRANSPARENT_SUBN.has(subn) ? 0 : null; }

// Renders the currently-selected Map resource (subindex 127) plus its
// matching Prop List (subindex 128, same low byte, resid+0x0100) onto
// a canvas, showing an actual top-down picture instead of a data table.
// --- Tile attributes (resource 0xF002) -----------------------------------
// 8192 4-byte big-endian records: the first 0x1000 describe simple tiles,
// the last 0x1000 describe composed tiles. Bits 0xC0 encode how many map
// squares a prop's sprite spans, which is how large creatures and big
// objects (beds, tables, trees) are drawn across more than one tile.
let tileAttrCache = null;
function getTileAttributes() {
  if (tileAttrCache !== null) return tileAttrCache;
  const data = getResourceBytes(0xF002);
  if (!data) { tileAttrCache = []; return tileAttrCache; }
  const n = Math.floor(data.length / 4);
  const arr = new Uint32Array(n);
  for (let i = 0; i < n; i++) {
    arr[i] = u32be(data, i*4);
  }
  tileAttrCache = arr;
  return arr;
}
function isCompletelyWhite(image) {
  let nonwhite=0;
  for (let i=0; i<image.length; i++) { const v=image[i]; if (v!==0 && v!==15 && v!==16 && v!==48 && v!==255) { nonwhite++; if(nonwhite>2) return false; } }
  return image.length > 0;
}

/* The other shapes a 16-tile sheet can be shown in. reshapeTileSheetGrid
 * above is the 4x4 the gallery always drew; these are the native column the
 * archive actually stores (identity), the transposed single row, and the
 * 4x4 with gutters so each tile reads separately. All return indexed pixels
 * like every decoder here, so they stay checkable; the gutters are palette
 * index 0, the transparent slot. */
function reshapeTileSheetRow(W, H, image) {
  if (W !== 32 || H !== 512) return {W, H, image};
  const out = new Uint8Array(512 * 32);
  for (let t = 0; t < 16; t++)
    for (let y = 0; y < 32; y++)
      for (let x = 0; x < 32; x++)
        out[y * 512 + t * 32 + x] = image[(t * 32 + y) * 32 + x];
  return {W: 512, H: 32, image: out};
}
function reshapeTileSheetTiles(W, H, image, gap) {
  if (W !== 32 || H !== 512) return {W, H, image};
  const g = gap || 3;
  const side = 4 * 32 + 3 * g;
  const out = new Uint8Array(side * side);
  for (let t = 0; t < 16; t++) {
    const gx = (t % 4) * (32 + g), gy = Math.floor(t / 4) * (32 + g);
    for (let y = 0; y < 32; y++)
      for (let x = 0; x < 32; x++)
        out[(gy + y) * side + (gx + x)] = image[(t * 32 + y) * 32 + x];
  }
  return {W: side, H: side, image: out};
}
function reshapeTileSheet(W, H, image, mode) {
  if (mode === 'column') return {W, H, image};
  if (mode === 'row') return reshapeTileSheetRow(W, H, image);
  if (mode === 'tiles') return reshapeTileSheetTiles(W, H, image);
  return reshapeTileSheetGrid(W, H, image);
}
