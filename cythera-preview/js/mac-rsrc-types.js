/* mac-rsrc-types.js -- decoders for the resource types a classic Mac file
 * actually contains: PICT, snd, NFNT, clut, cicn, crsr, ICN#, STR#, vers,
 * DITL, MENU, cfrg, CODE and the rest.
 *
 * These were the whole of resource_fork_browser.html, a separate page that
 * opened any classic Mac resource fork. That page is gone. It was more
 * general-purpose than this repository, and everything in it that Cythera
 * needs is here instead: both of Cythera's files are stuffed with these types
 * -- "Cythera Data" has 18 of them across 113 resources, and the application
 * has 52 across 339 -- so explorer.html reads its own resource fork with the
 * same decoders rather than sending anyone to a second tool.
 *
 * GENERIC TIER. Nothing here knows Cythera exists; this belongs beside the
 * other mac-* modules, not beside delv-*. It is Apple's formats, and the
 * palettes near the middle are Apple's standard 4- and 8-bit tables, which are
 * NOT the same thing as Cythera's own CLUT in delv-graphics.js.
 *
 * These decoders take bytes and return a value: a string, a record, or a
 * canvas already drawn. The canvas ones are the exception to the usual rule
 * that drawing stays in the page, and they earn it -- utilities/
 * rsrc_snapshot.mjs hashes what they draw, pixel for pixel, so they are as
 * checkable as the ones that return text. What is NOT here is the page's own
 * furniture: the panes, the ids, the file input. That is explorer.html's job.
 *
 * TWO RENAMES on the way in, because the two pages were never loaded together
 * and each had a function the other also had. A function declaration in a
 * classic script is a global binding, so the later file would simply have won:
 *
 *   samplesToWav -> pcmToWavBlob   explorer's takes (rate, samples) and
 *                                  returns bytes; this one takes
 *                                  (samples, rate, bits, channels) and returns
 *                                  a Blob. Reversed arguments, silently.
 *   hexDump      -> rsrcHexDump    js/delv-archive.js has one with a different
 *                                  offset width and no length argument.
 *
 * CLASSIC SCRIPT -- no `type="module"`. See js/mac-bytes.js for why.
 * LOAD ORDER: after mac-bytes.js and mac-media.js, whose readers and WAV
 * writer this uses; mac-resfork.js opens the fork these decode the contents of.
 */

// ============================================================
//  Bulk export: every resource, raw and decoded, as one .zip
// ============================================================
// Store-only (method 0). Deflate would need a compressor; the point here is
// getting a whole fork out in one click, and PNG/WAV payloads barely compress.
// crc32 and buildZip are in js/mac-export.js -- the data viewer grew the same
// store-only ZIP writer, field for field.
// Remember the palette indices a canvas was drawn from, so it can be saved as
// a real indexed PNG instead of being re-photographed as truecolour. A canvas
// drawn through a 1-bit mask keeps its alpha and is left alone: PNG's tRNS can
// make one palette slot transparent, not an arbitrary shape.
function tagIndexed(canvas, W, H, indices, palette, maskBits){
  if(maskBits) return canvas;
  canvas.__indexed = {W, H, indices, palette};
  return canvas;
}

// What files can this resource become? One list, so the ZIP export and the
// preview cannot drift apart about which types are decodable.
function exportArtifacts(fork, type, entry, data){
  const out=[], txt=s=>out.push({ext:'txt', text:s}), cvs=(c,tag)=>out.push({ext:'png', canvas:c, tag});
  if(type==='STR#') txt(decodeSTRList(data).map((s,i)=>`[${i}] ${s}`).join('\n'));
  else if(type==='STR ') txt(decodeSTR(data));
  else if(type==='TEXT') txt(decodeTEXT(data));
  else if(type==='vers') txt(decodeVers(data));
  else if(type==='cfrg') txt(decodeCfrg(data));
  else if(CODE_TYPES[type]) txt(decodeCodeResource(type, entry.id, data));
  else if(type==='DITL') txt(decodeDITL(data));
  else if(type==='MENU') txt(decodeMENU(data));
  else if(type==='WIND') txt(decodeWIND(data));
  else if(type==='ALRT') txt(decodeALRT(data));
  else if(type==='DLOG') txt(decodeDLOG(data));
  else if(type==='MBAR') txt(decodeMBAR(data));
  else if(type==='FREF') txt(decodeFREF(data));
  else if(type==='BNDL') txt(decodeBNDL(data));
  else if(type==='SIZE') txt(decodeSIZE(data));
  else if(type==='TMPL') txt(decodeTMPL(data));
  else if(type==='CNTL') txt(decodeCNTL(data));
  else if(type==='nrct') txt(decodeNrct(data));
  else if(type==='styl') txt(decodeStyl(data));
  else if(type==='FOND') txt(decodeFOND(data).text);
  else if(type==='ICN#') cvs(decode1bitIcon(data,32));
  else if(type==='ics#') cvs(decode1bitIcon(data,16));
  else if(type==='ICON') cvs(decodeICON(data));
  else if(type==='icl4') cvs(drawIndexedIcon(data,32,4,MAC_4BIT_PAL,iconMaskFor(fork, 32)(entry.id)));
  else if(type==='icl8') cvs(drawIndexedIcon(data,32,8,MAC_8BIT_PAL,iconMaskFor(fork, 32)(entry.id)));
  else if(type==='ics4') cvs(drawIndexedIcon(data,16,4,MAC_4BIT_PAL,iconMaskFor(fork, 16)(entry.id)));
  else if(type==='ics8') cvs(drawIndexedIcon(data,16,8,MAC_8BIT_PAL,iconMaskFor(fork, 16)(entry.id)));
  else if(type==='SICN') decodeSICN(data).forEach((c,i)=>cvs(c,String(i+1)));
  else if(type==='PAT ') cvs(decodePAT(data));
  else if(type==='PAT#') decodePATList(data).forEach((c,i)=>cvs(c,String(i+1)));
  else if(type==='ppat') cvs(decodePpat(data));
  else if(type==='cicn') cvs(decodeCicn(data));
  else if(type==='CURS') cvs(decodeCURS(data).canvas);
  else if(type==='crsr') cvs(decodeCrsr(data).canvas);
  else if(type==='pltt') cvs(decodePltt(data).canvas);
  else if(COLOR_TABLE_TYPES[type]) cvs(decodeClut(data).canvas);
  else if(type==='NFNT'||type==='FONT'){
    const f=decodeNFNT(data); txt(f.info); cvs(f.canvas,'strike');
    f.glyphs.forEach(g=>cvs(g.canvas, g.missing?'missing':'char'+g.code));
  }
  else if(type==='sfnt') out.push({ext:'ttf', bytes:data});
  else if(type==='snd ') out.push({ext:'wav', blob:decodeSndToWav(data).blob});
  else if(type==='PICT'){
    const r=decodePict(data);
    if(r.kind==='embedded') out.push({ext:r.ext, blob:r.blob});
    else cvs(r.canvas);
  }
  return out;
}

const TEXT_PREVIEW_LIMIT = 4000;
const TYPE_BADGES={
  'STR#':'text','STR ':'text','TEXT':'text','vers':'version info','DITL':'dialog items',
  'MENU':'menu','WIND':'window','ALRT':'alert','DLOG':'dialog','MBAR':'menu bar',
  'CNTL':'control','FREF':'file reference','BNDL':'bundle','SIZE':'memory sizes',
  'TMPL':'template','nrct':'rectangles','styl':'text styles','snd ':'audio',
  'CURS':'cursor','crsr':'colour cursor','acur':'animated cursor control',
  'ICN#':'image','ics#':'image','icl4':'image','icl8':'image','ics4':'image','ics8':'image',
  'ICON':'image','SICN':'small icons','cicn':'colour image','PICT':'image',
  'ppat':'pattern','PAT ':'pattern','PAT#':'patterns','pltt':'palette',
  'sfnt':'font','NFNT':'bitmap font','FONT':'bitmap font','FOND':'font family',
  'cfrg':'code fragments','CODE':'68K code','CDEF':'68K code','WDEF':'68K code',
  'MDEF':'68K code','LDEF':'68K code','PACK':'68K code','INIT':'68K code',
  'DRVR':'68K code','FKEY':'68K code'
};
function decodableBadge(type){
  return TYPE_BADGES[type] || COLOR_TABLE_TYPES[type] || null;
}

// downloadBlob and dlBlob are in js/mac-export.js.

// ---- Decoders ----

function decodeSTRList(data){
  let p=0; if(data.length<2) throw new Error('STR# too short');
  const count = u16be(data,0); p=2;
  const out=[];
  for(let i=0;i<count;i++){
    if(p>=data.length) break;
    const len = data[p]; p+=1;
    if(p+len>data.length) throw new Error('STR# entry overruns resource');
    out.push(decodeMacRoman(data.slice(p,p+len)));
    p+=len;
  }
  return out;
}

function decodeSTR(data){
  if(!data.length) return '';
  const len = data[0];
  if(1+len>data.length) throw new Error('STR resource overruns length');
  return decodeMacRoman(data.slice(1,1+len));
}

function decodeTEXT(data){
  return decodeMacRoman(data);
}

// 'snd ' resource -> WAV. Handles the standard sound header (8-bit unsigned
// mono) and the extended header (encode 0xFF), which is how 16-bit and stereo
// sounds are stored; the original code rejected everything but the former.
function decodeSndToWav(data){
  let p=0;
  const format = u16be(data,p); p+=2;
  if(format===1){
    const numDataFormats = u16be(data,p); p+=2;
    p += numDataFormats*6; // skip data format list
  } else if(format===2){
    p+=2; // refCount
  } else {
    throw new Error('unsupported snd format '+format);
  }
  const numCommands = u16be(data,p); p+=2;
  let soundHeaderOff = null;
  for(let i=0;i<numCommands && p+8<=data.length;i++){
    const cmd = u16be(data,p);
    const param2 = u32be(data,p+4);
    // bufferCmd/soundCmd with the dataOffsetFlag (0x8000) set: param2 is an
    // offset from the start of the resource to the sound header.
    if(cmd===0x8051 || cmd===0x8050){ soundHeaderOff = param2; }
    p+=8;
  }
  if(soundHeaderOff===null) throw new Error('no bufferCmd/soundCmd found in this snd resource');
  if(soundHeaderOff+22 > data.length) throw new Error('sound header offset is past the end of the resource');
  let hp = soundHeaderOff;
  hp+=4;                                   // samplePtr (0 when the samples follow the header)
  const lengthOrChannels = u32be(data,hp); hp+=4;
  const rateFixed = u32be(data,hp); hp+=4;
  hp+=4; hp+=4;                            // loopStart, loopEnd
  const encode = data[hp]; hp+=1;
  hp+=1;                                   // baseFrequency
  const rate = (rateFixed>>>0)/65536;   // 16.16 Fixed

  let samples, bits=8, channels=1, frames;
  if(encode===0x00){
    channels=1; bits=8; frames=lengthOrChannels;
    samples=data.slice(hp, hp+frames);
  } else if(encode===0xFF){
    channels=Math.max(1,lengthOrChannels);
    frames=u32be(data,hp); hp+=4;
    hp+=10;                                // AIFF sample rate (80-bit extended)
    hp+=4+4+4;                             // markerChunk, instrumentChunks, AESRecording
    bits=u16be(data,hp); hp+=2;
    hp+=2+2+2+2;                           // futureUse 1..4
    if(bits!==8 && bits!==16) throw new Error(`unsupported sample size (${bits}-bit)`);
    samples=data.slice(hp, hp+frames*channels*bits/8);
  } else if(encode===0xFE){
    throw new Error('this sound is MACE/IMA compressed (encode 0xFE), which this tool cannot decompress');
  } else {
    throw new Error('unknown sound header encoding 0x'+encode.toString(16));
  }
  if(!samples.length) throw new Error('sound header declares no samples');
  const blob=pcmToWavBlob(samples, Math.round(rate), bits, channels);
  const secs=frames/(rate||1);
  return {blob, rate, bits, channels, frames,
          description:`${bits}-bit ${channels===1?'mono':'stereo'}, ${Math.round(rate).toLocaleString()} Hz, ${frames.toLocaleString()} frames (${secs.toFixed(2)} s)`};
}

// Mac 8-bit samples are unsigned and 16-bit samples are signed big-endian;
// WAV wants unsigned 8-bit and signed little-endian 16-bit.
// The WAV writer is in js/mac-media.js. This wrapper keeps the Blob the
// preview and the download expect.
function pcmToWavBlob(samples, rate, bits, channels){
  return new Blob([wavFromPcmBytes(samples, rate, bits, channels)], {type:'audio/wav'});
}

// 1-bit ICN#/ics# icon -> canvas (32x32 or 16x16), mask ignored for simplicity
function decode1bitIcon(data, size){
  const rowBytes = size/8;
  const canvas = document.createElement('canvas');
  canvas.width=size; canvas.height=size;
  const ctx = canvas.getContext('2d');
  const imgData = ctx.createImageData(size,size);
  for(let y=0;y<size;y++){
    for(let x=0;x<size;x++){
      const byteIdx = y*rowBytes + Math.floor(x/8);
      const bit = 7-(x%8);
      const val = (data[byteIdx]>>bit)&1;
      const idx=(y*size+x)*4;
      const c = val?0:255;
      imgData.data[idx]=c; imgData.data[idx+1]=c; imgData.data[idx+2]=c; imgData.data[idx+3]=255;
    }
  }
  ctx.putImageData(imgData,0,0);
  return canvas;
}



// ---- Cursor decoders ----
function drawCursorBits(imageBits, maskBits, W, H){
  const canvas=document.createElement('canvas');canvas.width=W;canvas.height=H;
  const ctx=canvas.getContext('2d'), im=ctx.createImageData(W,H);
  const rb=Math.ceil(W/8);
  for(let y=0;y<H;y++)for(let x=0;x<W;x++){
    const bit=7-(x&7), off=(y*W+x)*4, by=y*rb+(x>>3);
    const ink=(imageBits[by]>>bit)&1, mask=maskBits?((maskBits[by]>>bit)&1):1;
    const v=ink?0:255; im.data[off]=v;im.data[off+1]=v;im.data[off+2]=v;im.data[off+3]=mask?255:0;
  }
  ctx.putImageData(im,0,0); return canvas;
}
function decodeCURS(data){
  if(data.length<68)throw new Error('CURS resource is shorter than 68 bytes');
  const hotY=u16be(data,64),hotX=u16be(data,66);
  return {canvas:drawCursorBits(data.slice(0,32),data.slice(32,64),16,16),hotX,hotY};
}
function decodeCrsr(data){
  if(data.length<96)throw new Error('crsr resource is too short');
  // CCrsr record, Inside Macintosh: Imaging With QuickDraw p.4-104. This is NOT
  // the cicn layout -- the offsets below are fixed, and the PixMap lives at the
  // offset named by crsrMap rather than at the start of the resource.
  //    0 crsrType 2 | 2 crsrMap 4 | 6 crsrData 4 | 10 crsrXData 4
  //   14 crsrXValid 2 | 16 crsrXHandle 4 | 20 crsr1Data 32 | 52 crsrMask 32
  //   84 crsrHotSpot 4 | 88 crsrXTable 4 | 92 crsrID 4 | then PixMap, pixels, clut
  const crsrType=u16be(data,0);
  if(crsrType!==0x8001&&crsrType!==0x8000) throw new Error('Not a colour cursor (crsrType 0x'+crsrType.toString(16)+')');
  const mapOff=u32be(data,2), pixOff0=u32be(data,6);
  const hotY=s16(data,84), hotX=s16(data,86);
  const mask=data.slice(52,84);
  // PixMap at mapOff: baseAddr 4, rowBytes 2, bounds 8, ... pixelSize at +32, pmTable at +42
  const rowBytes=u16be(data,mapOff+4)&0x3fff;
  const bounds=readRect(data,mapOff+6);
  const pixelSize=u16be(data,mapOff+32);
  const ctOff=u32be(data,mapOff+42);
  const W=bounds.right-bounds.left,H=bounds.bottom-bounds.top;
  if(W<=0||H<=0||rowBytes<=0||pixelSize>8)throw new Error(`Unsupported crsr PixMap (${W}×${H}, ${pixelSize}-bit)`);
  const ct=readColorTable(data,ctOff);
  const c=renderIndexedPixels(data,pixOff0,rowBytes,W,H,pixelSize,ct.palette,mask,2);
  return {canvas:c,hotX,hotY,pixelSize};
}


function decodeDLOG(data){
  if(data.length<18) throw new Error('DLOG too short');
  const r=readRect(data,0), procID=u16be(data,8), visible=!!data[10], goAway=!!data[12], refCon=u32be(data,14);
  let title=''; if(data.length>18){ const len=data[18]||0; if(19+len<=data.length) title=decodeMacRoman(data.slice(19,19+len)); }
  return `Dialog: "${title}"\nBounds: (${r.left},${r.top}) to (${r.right},${r.bottom})\nProc ID: ${procID}  Visible: ${visible}  Close box: ${goAway}  RefCon: ${refCon}`;
}
function decodeMBAR(data){
  if(data.length<2) throw new Error('MBAR too short');
  const count=u16be(data,0); const ids=[]; let p=2; for(let i=0;i<count && p+2<=data.length;i++,p+=2) ids.push(u16be(data,p));
  return `Menu bar with ${ids.length} menu IDs\n` + ids.map((id,i)=>`${i+1}. MENU ${id}`).join('\n');
}
function decodeFREF(data){
  if(data.length<7) throw new Error('FREF too short');
  const type=String.fromCharCode(data[0],data[1],data[2],data[3]), iconListID=u16be(data,4), flags=u16be(data,6);
  return `File reference\nType: ${type}\nIcon list ID: ${iconListID}\nFlags: 0x${flags.toString(16)}`;
}
function decodeBNDL(data){
  if(data.length<8) throw new Error('BNDL too short');
  const sig=String.fromCharCode(data[0],data[1],data[2],data[3]), version=u16be(data,4), arrayCount=u16be(data,6);
  return `Bundle\nSignature: ${sig}\nVersion: ${version}\nMapping arrays: ${arrayCount}`;
}
function decodeSIZE(data){
  if(data.length<10) throw new Error('SIZE too short');
  const flags=u16be(data,0), pref=u32be(data,2), minimum=u32be(data,6);
  return `SIZE resource\nFlags: 0x${flags.toString(16)}\nPreferred memory: ${pref} bytes\nMinimum memory: ${minimum} bytes`;
}
function decodeTMPL(data){
  let p=0, out=[];
  while(p+5<=data.length){
    const labelLen=data[p]; p+=1; if(p+labelLen+4>data.length) break;
    const label=decodeMacRoman(data.slice(p,p+labelLen)); p+=labelLen;
    const kind=String.fromCharCode(data[p],data[p+1],data[p+2],data[p+3]); p+=4;
    out.push(`${label} : ${kind}`);
  }
  return out.join('\n') || 'TMPL resource';
}
function decodePAT(data){
  if(data.length<8) throw new Error('PAT too short');
  const canvas=document.createElement('canvas'); canvas.width=8; canvas.height=8;
  const ctx=canvas.getContext('2d'), im=ctx.createImageData(8,8);
  for(let y=0;y<8;y++) for(let x=0;x<8;x++){
    const b=data[y], bit=(b>>(7-x))&1, o=(y*8+x)*4, c=bit?0:255; im.data[o]=c; im.data[o+1]=c; im.data[o+2]=c; im.data[o+3]=255;
  }
  ctx.putImageData(im,0,0); return canvas;
}
// PixPat record, Inside Macintosh: Imaging With QuickDraw p.4-104:
//   0 patType 2 | 2 patMap 4 | 6 patData 4 | 10 patXData 4 | 14 patXValid 2
//  16 patXMap 4 | 20 pat1Data 8   -> 28 bytes, then PixMap, pixels, ColorTable
// (the same field order as the CCrsr record decoded above it).
// patType 1 is a colour pattern, 2 an RGB pattern, 0 a plain 1-bit one.
// The previous version scanned for a 0x0001 word, threw the result away, and
// always drew data[0..8] -- which is the header, not pattern pixels, so every
// colour ppat rendered as noise.
function decodePpat(data){
  if(data.length===8) return decodePAT(data);        // a bare PAT stored as ppat
  if(data.length<28) throw new Error('ppat resource is shorter than a PixPat record');
  const patType=u16be(data,0), mapOff=u32be(data,2), pixOff=u32be(data,6);
  if((patType===1||patType===2) && mapOff+50<=data.length && pixOff<data.length){
    const rowBytes=u16be(data,mapOff+4)&0x3fff;
    const bounds=readRect(data,mapOff+6);
    const pixelSize=u16be(data,mapOff+32);
    const ctOff=u32be(data,mapOff+42);
    const W=bounds.right-bounds.left, H=bounds.bottom-bounds.top;
    if(W>0&&H>0&&rowBytes>0&&pixelSize>0&&pixelSize<=8&&ctOff+8<=data.length){
      const ct=readColorTable(data,ctOff);
      const c=renderIndexedPixels(data,pixOff,rowBytes,W,H,pixelSize,ct.palette);
      c.info=`${W}×${H} colour pattern, ${pixelSize}-bit, ${ct.palette.filter(Boolean).length} colours`;
      return c;
    }
  }
  // pat1Data: the 1-bit pattern every PixPat carries for black-and-white
  // screens. It is at offset 20, not 0.
  const c=decodePAT(data.slice(20,28));
  c.info = patType===0 ? '8×8 monochrome pattern (patType 0)'
                       : `patType ${patType}: colour pixels unreadable, showing the 1-bit equivalent`;
  return c;
}
// cicn, crsr and ppat all finish with the same loop: indexed pixels through a
// colour table, optionally cut out by a 1-bit mask.
function renderIndexedPixels(data,pixOff,rowBytes,W,H,pixelSize,palette,maskBits,maskRowBytes){
  const ppb=8/pixelSize, pmask=(1<<pixelSize)-1;
  const c=document.createElement('canvas'); c.width=W; c.height=H;
  const ctx=c.getContext('2d'), im=ctx.createImageData(W,H);
  const idx=new Uint8Array(W*H);
  for(let y=0;y<H;y++) for(let x=0;x<W;x++){
    const byte=data[pixOff + y*rowBytes + Math.floor(x/ppb)] || 0;
    const pi = pixelSize===8 ? byte : (byte >> ((ppb-1-(x%ppb))*pixelSize)) & pmask;
    const col=palette[pi]||[255,0,255], o=(y*W+x)*4;
    idx[y*W+x]=pi;
    im.data[o]=col[0]; im.data[o+1]=col[1]; im.data[o+2]=col[2];
    im.data[o+3] = maskBits ? ((((maskBits[y*maskRowBytes+(x>>3)]||0)>>(7-(x&7)))&1)?255:0) : 255;
  }
  ctx.putImageData(im,0,0);
  tagIndexed(c, W, H, idx, palette, maskBits);
  return c;
}
// ---- PICT v2 decoder: indexed PackBitsRect/Rgn AND true-color DirectBitsRect/Rgn ----
// Opcode data-length table derived from Apple's "PICT File Format Notes" (1990).
// Most opcodes carry fixed-size data we don't render (pen state, colors, text,
// shapes, etc); we walk past all of them until we reach the actual image opcode.
// QuickDraw Rect fields are SIGNED 16-bit; reading them unsigned turns any
// negative origin into ~65000 and yields nonsense widths.
function s16(b,i){const v=(b[i]<<8)|b[i+1];return v>32767?v-65536:v;}
function readRect(data,p){return {top:s16(data,p),left:s16(data,p+2),bottom:s16(data,p+4),right:s16(data,p+6)};}
function readColorTable(data,p){
  p+=4; p+=2; const count=u16be(data,p)+1;p+=2; const pal=[];
  for(let i=0;i<count;i++){const val=u16be(data,p);pal[val]=[u16be(data,p+2)>>8,u16be(data,p+4)>>8,u16be(data,p+6)>>8];p+=8;}
  return {palette:pal,p};
}
// hasBaseAddr: DirectBits opcodes (0x9A/0x9B) store a 4-byte placeholder Ptr
// before rowBytes; the indexed opcodes (0x98/0x99) omit it on disk.
function readPictPixmap(data,p,hasBaseAddr){
  if(hasBaseAddr) p+=4;
  const rowWord=u16be(data,p),rowBytes=rowWord&0x3fff; p+=2;
  const bounds=readRect(data,p);p+=8;
  p+=2; const packType=u16be(data,p);p+=2;p+=4;p+=4;p+=4; const pixelType=u16be(data,p);p+=2; const pixelSize=u16be(data,p);p+=2;const cmpCount=u16be(data,p);p+=2;const cmpSize=u16be(data,p);p+=2;p+=4;p+=4;p+=4;
  return {rowBytes,bounds,packType,pixelType,pixelSize,cmpCount,cmpSize,p};
}
function unpackBitsPict(data,p,packedLen,want){
  const src=data.slice(p,p+packedLen),out=new Uint8Array(want);let si=0,oi=0;
  while(si<src.length&&oi<want){let n=i8(src,si++);if(n>=0){let ct=n+1;while(ct--&&si<src.length&&oi<want)out[oi++]=src[si++];}else if(n!==-128){if(si>=src.length)break;let ct=1-n,v=src[si++];while(ct--&&oi<want)out[oi++]=v;}}
  return out;
}
function renderPictIndexed(pm,palette,rows){
  const W=pm.bounds.right-pm.bounds.left,H=pm.bounds.bottom-pm.bounds.top,c=document.createElement('canvas');c.width=W;c.height=H;const ctx=c.getContext('2d'),im=ctx.createImageData(W,H),ppb=8/pm.pixelSize,mask=(1<<pm.pixelSize)-1;
  for(let y=0;y<H;y++){const row=rows[y]||new Uint8Array(pm.rowBytes);for(let x=0;x<W;x++){const b=row[Math.floor(x/ppb)]||0,pi=(b>>((ppb-1-(x%ppb))*pm.pixelSize))&mask,col=palette[pi]||[255,0,255],o=(y*W+x)*4;im.data[o]=col[0];im.data[o+1]=col[1];im.data[o+2]=col[2];im.data[o+3]=255;}}
  ctx.putImageData(im,0,0);return c;
}
function renderPictDirect(pm,rows){
  const W=pm.bounds.right-pm.bounds.left,H=pm.bounds.bottom-pm.bounds.top,c=document.createElement('canvas');c.width=W;c.height=H;const ctx=c.getContext('2d'),im=ctx.createImageData(W,H);
  for(let y=0;y<H;y++){
    const row=rows[y];
    for(let x=0;x<W;x++){
      const o=(y*W+x)*4; let r=255,g=0,b=255;
      if(row){
        if(pm.packType===4 && row.planes){ r=row.planes[0][x]??0; g=row.planes[1][x]??0; b=row.planes[2][x]??0; }
        else if(pm.pixelSize===16){ const w=(row[x*2]<<8)|row[x*2+1]; const r5=(w>>10)&0x1f,g5=(w>>5)&0x1f,b5=w&0x1f; r=Math.round(r5*255/31);g=Math.round(g5*255/31);b=Math.round(b5*255/31); }
        else if(pm.pixelSize===32){ r=row[x*4+1]??0; g=row[x*4+2]??0; b=row[x*4+3]??0; }
      }
      im.data[o]=r;im.data[o+1]=g;im.data[o+2]=b;im.data[o+3]=255;
    }
  }
  ctx.putImageData(im,0,0);return c;
}
function decodeDirectBitsRows(data,p,pm){
  const H=pm.bounds.bottom-pm.bounds.top, rowBytes=pm.rowBytes, cmpCount=pm.cmpCount||3, rows=[];
  for(let y=0;y<H;y++){
    if(rowBytes<8){ rows.push(data.slice(p,p+rowBytes)); p+=rowBytes; }
    else if(pm.packType===4){
      // packType 4 stores ONE PackBits stream per row (one length prefix),
      // which unpacks to cmpCount planes of `width` bytes each -- not one
      // stream per plane, and not rowBytes/cmpCount per plane (rowBytes is
      // width*4 for 32-bit, so that division gives the wrong plane stride).
      const W=pm.bounds.right-pm.bounds.left;
      const plen = rowBytes>250?u16be(data,p):data[p]; p += rowBytes>250?2:1;
      const flat = unpackBitsPict(data,p,plen,W*cmpCount); p+=plen;
      const planes=[];
      const base = cmpCount===4 ? W : 0; // skip alpha plane when present
      for(let c=0;c<3;c++) planes.push(flat.subarray(base+c*W, base+(c+1)*W));
      rows.push({planes});
    } else {
      const plen = rowBytes>250?u16be(data,p):data[p]; p += rowBytes>250?2:1;
      rows.push(unpackBitsPict(data,p,plen,rowBytes)); p+=plen;
    }
  }
  return {rows,p};
}
const PICT_FIXED_LEN = {
  0x0002:8,0x0003:2,0x0004:2,0x0005:2,0x0006:4,0x0007:4,0x0008:2,0x0009:8,
  0x000A:8,0x000B:4,0x000C:4,0x000D:2,0x000E:4,0x000F:4,0x0010:8,
  0x0015:2,0x0016:2,0x0017:0,0x0018:0,0x0019:0,
  0x001A:6,0x001B:6,0x001C:0,0x001D:6,0x001E:0,0x001F:6,
  0x0020:8,0x0021:4,0x0022:6,0x0023:2,
  0x0030:8,0x0031:8,0x0032:8,0x0033:8,0x0034:8,0x0035:8,0x0036:8,0x0037:8,
  0x0038:0,0x0039:0,0x003A:0,0x003B:0,0x003C:0,0x003D:0,0x003E:0,0x003F:0,
  0x0040:8,0x0041:8,0x0042:8,0x0043:8,0x0044:8,0x0045:8,0x0046:8,0x0047:8,
  0x0048:0,0x0049:0,0x004A:0,0x004B:0,0x004C:0,0x004D:0,0x004E:0,0x004F:0,
  0x0050:8,0x0051:8,0x0052:8,0x0053:8,0x0054:8,0x0055:8,0x0056:8,0x0057:8,
  0x0058:0,0x0059:0,0x005A:0,0x005B:0,0x005C:0,0x005D:0,0x005E:0,0x005F:0,
  0x0060:12,0x0061:12,0x0062:12,0x0063:12,0x0064:12,0x0065:12,0x0066:12,0x0067:12,
  0x0068:4,0x0069:4,0x006A:4,0x006B:4,0x006C:4,0x006D:4,0x006E:4,0x006F:4,
  0x0078:0,0x0079:0,0x007A:0,0x007B:0,0x007C:0,0x007D:0,0x007E:0,0x007F:0,
  0x0088:0,0x0089:0,0x008A:0,0x008B:0,0x008C:0,0x008D:0,0x008E:0,0x008F:0,
  0x00A0:2, 0x8000:0
};
const PICT_LEN_PREFIXED_2 = new Set([0x0024,0x0025,0x0026,0x0027,0x002C,0x002D,0x002E,0x002F,0x0092,0x0093,0x0094,0x0095,0x0096,0x0097,0x009C,0x009D,0x009E,0x009F]);
const PICT_REGION_OPS = new Set([0x0001,0x0080,0x0081,0x0082,0x0083,0x0084,0x0085,0x0086,0x0087]);
const PICT_POLY_OPS = new Set([0x0070,0x0071,0x0072,0x0073,0x0074,0x0075,0x0076]);
const PICT_IMAGE_OPS = new Set([0x0098,0x0099,0x009A,0x009B]);
// Walk the opcode stream (skipping every opcode we don't render) until we
// reach a bitmap opcode. This replaces a byte-by-byte signature scan, which
// could false-match inside pixel/text data and silently mis-locate images.
function findPictImageOpcode(data){
  // Version 1 pictures use ONE-byte opcodes; version 2 uses two. The word at
  // offset 10 is 0x0011 for v2 and 0x1101 for v1, so this must be detected
  // before any opcode is read or the whole walk is misaligned.
  let p=2+8;
  const verWord=u16be(data,p);
  const v2 = (verWord===0x0011);
  if(v2){ p+=4; } else { p+=2; }   // v2: 0x0011 0x02FF | v1: 0x11 0x01
  if(v2 && u16be(data,p)===0x0C00){ p+=2+24; }
  let guard=0;
  while(p<data.length && guard++<20000){
    if(v2){ if(p%2) p+=1; if(p+2>data.length) break; }
    let op;
    if(v2){ op=u16be(data,p); p+=2; } else { op=data[p]; p+=1; }
    if(op===0x0000) continue;
    // QuickTime-compressed opcodes carry a 4-byte payload length; the JPEG or
    // PNG lives INSIDE that payload. Return it so the caller can look there
    // instead of scanning the whole resource for a signature.
    if(op===0x8200||op===0x8201){ const size=u32be(data,p); return {op,p:p+4,size,quicktime:true}; }
    if(PICT_REGION_OPS.has(op)||PICT_POLY_OPS.has(op)){ const size=u16be(data,p); p+=size; continue; }
    if(op===0x0028){ p+=4; const len=data[p]; p+=1+len; if(p%2)p+=1; continue; } // LongText
    if(op===0x0029||op===0x002A){ p+=1; const len=data[p]; p+=1+len; if(p%2)p+=1; continue; } // DHText/DVText
    if(op===0x002B){ p+=2; const len=data[p]; p+=1+len; if(p%2)p+=1; continue; } // DHDVText
    if(op===0x0012||op===0x0013||op===0x0014){ // Bk/Pn/FillPixPat, best effort skip
      const patType=u16be(data,p); p+=2; p+=8;
      if(patType===2){ p+=6; }
      else{
        const pm=readPictPixmap(data,p,false); p=pm.p;
        if(pm.pixelType===0){ const ct=readColorTable(data,p); p=ct.p; }
        const H=pm.bounds.bottom-pm.bounds.top;
        if(pm.rowBytes<8){ p+=pm.rowBytes*H; }
        else{ for(let y=0;y<H;y++){ const rl=pm.rowBytes>250?u16be(data,p):data[p]; p+=(pm.rowBytes>250?2:1)+rl; } }
      }
      continue;
    }
    if(op===0x0090||op===0x0091){ // BitsRect/BitsRgn (unpacked 1-bit bitmap, no color table)
      const rowWord=u16be(data,p); const rowBytes=rowWord&0x3fff; p+=2;
      const bounds=readRect(data,p); p+=8; p+=8+8+2;
      if(op===0x0091){ const rs=u16be(data,p); p+=rs; }
      p += rowBytes*(bounds.bottom-bounds.top);
      continue;
    }
    if(PICT_IMAGE_OPS.has(op)) return {op,p};
    if(op===0x00A1){ p+=2; const size=u16be(data,p); p+=2+size; if(p%2)p+=1; continue; } // LongComment
    if(op===0x00FF) return null; // end of picture, nothing to draw
    if(op in PICT_FIXED_LEN){ p+=PICT_FIXED_LEN[op]; continue; }
    if(PICT_LEN_PREFIXED_2.has(op)){ const size=u16be(data,p); p+=2+size; continue; }
    if(op>=0x0100 && op<=0x7FFF){ p+=(op>>8)*2; continue; }
    if(op>=0x8000 && op<=0x80FF){ continue; }
    if(op>=0x8100 && op<=0xFFFF){ const size=u32be(data,p); p+=4+size; continue; }
    // Truly unknown opcode: Apple's own convention for future/reserved
    // opcodes in this range is a 2-byte length prefix, so fall back to that
    // rather than throwing away the whole picture.
    { const size=u16be(data,p); p+=2+size; }
  }
  return null;
}
function decodePictPackBits(data,pre){
  const found = (pre && !pre.quicktime) ? pre : findPictImageOpcode(data);
  if(!found||found.quicktime) throw new Error('No PackBitsRect/PackBitsRgn/DirectBitsRect/DirectBitsRgn image opcode found in this PICT.');
  const foundOp=found.op; let p=found.p;
  if(foundOp===0x0098||foundOp===0x0099){
    // PackBitsRect/Rgn may carry either a PixMap (high bit of rowBytes set) or
    // an old-style 1-bit BitMap. The BitMap header is only rowBytes+bounds and
    // has no colour table, so parsing it as a PixMap reads 36 bytes of garbage.
    if(!(u16be(data,p)&0x8000)){
      const rowBytes=u16be(data,p)&0x3fff; p+=2;
      const bounds=readRect(data,p); p+=8;
      p+=8; const dst=readRect(data,p); p+=8; const mode=u16be(data,p); p+=2;
      if(foundOp===0x0099){ const rgnSize=u16be(data,p); p+=rgnSize; }
      const W=bounds.right-bounds.left, H=bounds.bottom-bounds.top;
      if(W<=0||H<=0||rowBytes<=0) throw new Error(`Unsupported BitMap (${W}×${H})`);
      const rows=[];
      for(let y=0;y<H;y++){
        if(rowBytes<8){ rows.push(data.slice(p,p+rowBytes)); p+=rowBytes; }
        else{ const plen=rowBytes>250?u16be(data,p):data[p]; p+=rowBytes>250?2:1;
              rows.push(unpackBitsPict(data,p,plen,rowBytes)); p+=plen; }
      }
      const pm1={rowBytes,bounds,pixelSize:1};
      // QuickDraw 1-bit: set bit = black.
      const canvas=renderPictIndexed(pm1,[[255,255,255],[0,0,0]],rows);
      return {canvas,width:W,height:H,pixelSize:1,mode,opcode:foundOp,opcodeOffset:found.p-2,colorSpace:'1-bit bitmap'};
    }
    const pm=readPictPixmap(data,p,false); p=pm.p;
    const ct=readColorTable(data,p); p=ct.p;
    const src=readRect(data,p); p+=8; const dst=readRect(data,p); p+=8; const mode=u16be(data,p); p+=2;
    if(foundOp===0x0099){ const rgnSize=u16be(data,p); p+=rgnSize; }
    const W=pm.bounds.right-pm.bounds.left, H=pm.bounds.bottom-pm.bounds.top;
    if(W<=0||H<=0||pm.rowBytes<=0||pm.pixelSize>8) throw new Error(`Unsupported indexed PixMap (${W}×${H}, ${pm.pixelSize}-bit)`);
    const rows=[];
    for(let y=0;y<H;y++){
      let packedLen = pm.rowBytes>250 ? u16be(data,p) : data[p];
      p += pm.rowBytes>250 ? 2 : 1;
      if(p+packedLen>data.length) throw new Error('PICT row data ends unexpectedly');
      rows.push(unpackBitsPict(data,p,packedLen,pm.rowBytes)); p+=packedLen;
    }
    return {canvas:renderPictIndexed(pm,ct.palette,rows),width:W,height:H,pixelSize:pm.pixelSize,mode,opcode:foundOp,opcodeOffset:found.p-2,colorSpace:`${pm.pixelSize}-bit indexed`};
  } else {
    // DirectBitsRect (0x9A) / DirectBitsRgn (0x9B): true-color pixels, no palette.
    const pm=readPictPixmap(data,p,true); p=pm.p;
    const src=readRect(data,p); p+=8; const dst=readRect(data,p); p+=8; const mode=u16be(data,p); p+=2;
    if(foundOp===0x009B){ const rgnSize=u16be(data,p); p+=rgnSize; }
    const W=pm.bounds.right-pm.bounds.left, H=pm.bounds.bottom-pm.bounds.top;
    if(W<=0||H<=0||pm.rowBytes<=0) throw new Error(`Unsupported DirectBits PixMap (${W}×${H})`);
    if(pm.pixelSize!==16 && pm.pixelSize!==32) throw new Error(`Unsupported DirectBits pixel depth (${pm.pixelSize}-bit)`);
    const {rows}=decodeDirectBitsRows(data,p,pm);
    return {canvas:renderPictDirect(pm,rows),width:W,height:H,pixelSize:pm.pixelSize,mode,opcode:foundOp,opcodeOffset:found.p-2,colorSpace:`${pm.pixelSize}-bit direct`};
  }
}

// Search a BOUNDED slice for a JPEG/PNG signature. Scanning the whole
// resource false-matched inside PackBits pixel data: 5 of the 83 PICTs in
// Cythera/Cythera Data contain a stray FF D8 FF and were silently decoded as
// broken JPEGs instead of QuickDraw bitmaps.
function findEmbeddedImage(data,from,to){
  const lo=from||0, hi=Math.min(to===undefined?data.length:to, data.length);
  for(let i=lo;i<hi-4;i++){
    if(data[i]===0xFF && data[i+1]===0xD8 && data[i+2]===0xFF){
      return {type:'jpeg', bytes:data.slice(i,hi)};
    }
    if(data[i]===0x89 && data[i+1]===0x50 && data[i+2]===0x4E && data[i+3]===0x47){
      return {type:'png', bytes:data.slice(i,hi)};
    }
  }
  return null;
}

function decodePict(data){
  const found=findPictImageOpcode(data);
  if(found && found.quicktime){
    const embedded=findEmbeddedImage(data,found.p,found.p+found.size);
    if(embedded){const blob=new Blob([embedded.bytes],{type:embedded.type==='jpeg'?'image/jpeg':'image/png'});return {kind:'embedded',blob,ext:embedded.type==='jpeg'?'jpg':'png'};}
  }
  const parsed=decodePictPackBits(data,found);return {kind:'canvas',...parsed};
}

// ---- clut (color table) — same on-disk layout as a PICT's embedded color table ----
function decodeClut(data){
  const ct=readColorTable(data,0);
  const n=ct.palette.length, perRow=16, cell=20;
  const canvas=document.createElement('canvas');
  canvas.width=perRow*cell; canvas.height=Math.ceil(n/perRow)*cell;
  const ctx=canvas.getContext('2d');
  for(let i=0;i<n;i++){
    const col=ct.palette[i]||[0,0,0];
    ctx.fillStyle=`rgb(${col[0]},${col[1]},${col[2]})`;
    ctx.fillRect((i%perRow)*cell,Math.floor(i/perRow)*cell,cell,cell);
  }
  return {canvas,count:n};
}

// ---- sfnt (raw TrueType/OpenType font data) ----
// Code Fragment Manager resource: what PowerPC (and CFM-68K) code this file
// carries, where each fragment lives and what it is called. One `cfrg` says
// more about a fat binary than nine `CODE` resources do.
const CFRG_ARCH={'pwpc':'PowerPC','m68k':'CFM-68K'};
const CFRG_USAGE=['import library','application','drop-in addition','stub library','weak stub library'];
const CFRG_WHERE=['in this file','in a data fork','in memory','(reserved)','in a named fragment'];
function decodeCfrg(data){
  // CFragResource: 30 bytes of reserved fields, then a UInt16 member count at
  // 30, then the members. Every member is a CFragResourceMember, whose own
  // memberSize at offset 42 says where the next one starts -- the name is a
  // Pascal string at 44 and the record is padded to an even length, so walking
  // by a fixed size does not work.
  if(data.length<32) throw new Error(`cfrg needs 32 bytes of header, got ${data.length}`);
  const version=u16be(data,10), count=u16be(data,30);
  if(count>4096) throw new Error(`implausible fragment count (${count})`);
  const lines=[`${count} fragment${count===1?'':'s'}` + (version!==1?` (resource version ${version})`:'')];
  let p=32;
  for(let i=0;i<count;i++){
    if(p+43>data.length){ lines.push(`  [truncated after ${i} of ${count}]`); break; }
    const arch=fourcc(data,p);
    const updateLevel=data[p+7];
    const currentVersion=u32be(data,p+8), oldestVersion=u32be(data,p+12);
    const stackSize=u32be(data,p+16);
    const usage=data[p+22], where=data[p+23];
    const offset=u32be(data,p+24), length=u32be(data,p+28);
    // memberSize at 40 and the name at 42, which is what the bytes in a real
    // cfrg say: "Cythera" is a 7-character Pascal string ending at 50, and the
    // member size of 52 is that rounded up to an even boundary. Reading the
    // name four bytes later gave "ythera  pwpc..." -- garbage that still
    // looked like a name, which is the sort of wrong that survives review.
    const memberSize=u16be(data,p+40);
    const nameLen=data[p+42];
    const name=decodeMacRoman(data.slice(p+43,p+43+nameLen));
    const ver=v=>`${(v>>>24)&255}.${(v>>>16)&255}.${(v>>>8)&255}`;
    lines.push('');
    lines.push(`  ${name||'(unnamed)'}`);
    lines.push(`    architecture : ${CFRG_ARCH[arch]||arch}`);
    lines.push(`    kind         : ${CFRG_USAGE[usage]||('usage '+usage)}, ${CFRG_WHERE[where]||('location '+where)}`);
    lines.push(`    version      : ${ver(currentVersion)} (oldest definition ${ver(oldestVersion)}, update level ${updateLevel})`);
    lines.push(`    extent       : offset ${offset===0?'0':'0x'+offset.toString(16)}, ` +
               (length===0?'to the end of the fork':`${length.toLocaleString()} bytes`));
    if(stackSize) lines.push(`    stack        : ${stackSize.toLocaleString()} bytes`);
    if(memberSize<44||p+memberSize>data.length){ lines.push('    [member size is out of range; stopping]'); break; }
    p+=memberSize;
  }
  return lines.join('\n');
}

// 68K executable code: CODE, and the definition procedures that are the same
// thing under a different name. There is no disassembler here and there should
// not be one, but "9 resources, no decoder" told you nothing at all -- these
// have real headers, and CODE 0 in particular is the jump table that says how
// many entry points the application has.
const CODE_TYPES={'CODE':'code segment','CDEF':'control definition','WDEF':'window definition',
  'MDEF':'menu definition','LDEF':'list definition','PACK':'package','INIT':'init',
  'DRVR':'driver','FKEY':'function key'};
function decodeCodeResource(type, id, data){
  const lines=[`${CODE_TYPES[type]||'68K code'} — ${data.length.toLocaleString()} bytes of Motorola 68000 machine code`];
  if(type==='CODE' && id===0){
    // The jump table header: above/below A5 sizes, then 8 bytes per entry.
    if(data.length<16) throw new Error(`CODE 0 needs a 16-byte header, got ${data.length}`);
    const aboveA5=u32be(data,0), belowA5=u32be(data,4), tableSize=u32be(data,8), tableOffset=u32be(data,12);
    lines.length=0;
    lines.push('CODE 0 — the jump table, not code');
    lines.push('');
    lines.push(`  above A5      : ${aboveA5.toLocaleString()} bytes (application globals and the jump table)`);
    lines.push(`  below A5      : ${belowA5.toLocaleString()} bytes (QuickDraw globals and parameters)`);
    lines.push(`  jump table    : ${tableSize.toLocaleString()} bytes at offset ${tableOffset}, ` +
               `${Math.floor(tableSize/8).toLocaleString()} entries`);
    const n=Math.min(Math.floor(tableSize/8), Math.floor((data.length-16)/8));
    let unloaded=0;
    for(let i=0;i<n;i++){
      // An unloaded entry is `MOVE.W #segment,-(SP); _LoadSeg`, which is the
      // 0x3F3C / 0xA9F0 pair; a loaded one has been patched to a JMP.
      if(u16be(data,16+i*8+2)===0x3F3C && u16be(data,16+i*8+6)===0xA9F0) unloaded++;
    }
    lines.push(`  entry points  : ${n.toLocaleString()} readable, ${unloaded.toLocaleString()} in the unloaded _LoadSeg form`);
    return lines.join('\n');
  }
  if(data.length>=4){
    const first=u16be(data,0);
    // A near-model segment starts with the jump table offset and entry count;
    // a far-model one is flagged by 0xFFFF in that first word.
    if(first===0xFFFF) lines.push('  far model segment header (32-bit references)');
    else lines.push(`  jump table offset ${first}, ${u16be(data,2)} entr${u16be(data,2)===1?'y':'ies'}`);
  }
  lines.push('');
  lines.push('  This browser does not disassemble 68K. The bytes are below, and');
  lines.push('  "Save raw" writes them out for something that does.');
  return lines.join('\n');
}

function decodeSfntInfo(data){
  if(data.length<12) throw new Error('sfnt resource too short');
  const numTables=u16be(data,4); const tables=[];
  let p=12;
  for(let i=0;i<numTables && p+16<=data.length;i++){
    tables.push(String.fromCharCode(data[p],data[p+1],data[p+2],data[p+3])); p+=16;
  }
  return {numTables,tables};
}


// ============================================================
//  Classic Mac system palettes + indexed icon families
// ============================================================
// Standard Mac OS 16-colour palette (icl4 / ics4).
const MAC_4BIT_PAL = [
  [255,255,255],[252,243,5],[255,100,3],[221,9,7],[242,8,132],[71,0,165],
  [0,0,211],[2,171,234],[31,183,20],[0,100,18],[86,44,5],[144,113,58],
  [192,192,192],[128,128,128],[64,64,64],[0,0,0]
];
// Standard Mac OS 256-colour system palette (icl8 / ics8). Indices 0-214 are
// the 6x6x6 colour cube with black removed, 215-254 are the pure red, green,
// blue and grey ramps, and 255 is black.
const MAC_8BIT_PAL = (function(){
  const p=[], lv=[255,204,153,102,51,0];
  for(const r of lv) for(const g of lv) for(const b of lv){
    if(r===0&&g===0&&b===0) continue;   // black is reserved for index 255
    p.push([r,g,b]);
  }
  const ramp=[238,221,187,170,136,119,85,68,34,17];
  for(const v of ramp) p.push([v,0,0]);
  for(const v of ramp) p.push([0,v,0]);
  for(const v of ramp) p.push([0,0,v]);
  for(const v of ramp) p.push([v,v,v]);
  p.push([0,0,0]);
  return p;
})();
// Kept for the older call sites that used the "approximate" name.
const MAC_8BIT_PAL_APPROX = MAC_8BIT_PAL;

// icl4/icl8/ics4/ics8 are bare pixel arrays: no header, no mask, no colour
// table. The mask lives in the matching ICN#/ics# resource, so if one is
// present in the same fork we use it for transparency.
function drawIndexedIcon(data, size, depth, palette, maskBits){
  const need = size*size*depth/8;
  if(data.length < need) throw new Error(`${size}\u00d7${size} ${depth}-bit icon needs ${need} bytes, got ${data.length}`);
  const ppb = 8/depth, mask=(1<<depth)-1, rowBytes=size*depth/8, mRow=size/8;
  const c=document.createElement('canvas'); c.width=size; c.height=size;
  const ctx=c.getContext('2d'), im=ctx.createImageData(size,size);
  const idx=new Uint8Array(size*size);
  for(let y=0;y<size;y++) for(let x=0;x<size;x++){
    const byte = data[y*rowBytes + Math.floor(x/ppb)] || 0;
    const pi = depth===8 ? byte : (byte >> ((ppb-1-(x%ppb))*depth)) & mask;
    const col = palette[pi] || [255,0,255];
    const o=(y*size+x)*4;
    let a=255;
    if(maskBits){ const mb=maskBits[y*mRow+(x>>3)]||0; a=((mb>>(7-(x&7)))&1)?255:0; }
    idx[y*size+x]=pi;
    im.data[o]=col[0]; im.data[o+1]=col[1]; im.data[o+2]=col[2]; im.data[o+3]=a;
  }
  ctx.putImageData(im,0,0);
  tagIndexed(c, size, size, idx, palette, maskBits);
  return c;
}
// ICN#/ics# hold a 1-bit image followed by a 1-bit mask of the same size.
function iconMaskFor(fork, size){
  const t = size===32 ? 'ICN#' : 'ics#';
  return id=>{
    const list=(fork.resourcesByType[t])||null;
    if(!list) return null;
    const e=list.find(r=>r.id===id); if(!e) return null;
    const d=fork.dataOf(t,e), half=size*size/8;
    return d.length>=half*2 ? d.slice(half, half*2) : null;
  };
}

// ============================================================
//  cicn (colour icon)
// ============================================================
// PixMap(50) | mask BitMap(14) | icon BitMap(14) | iconData handle(4) |
// mask bits | icon bits | ColorTable | pixel data
function decodeCicn(data){
  let p=0;
  p+=4;                                     // baseAddr placeholder
  const pmRowBytes=u16be(data,p)&0x3fff; p+=2;
  const pmBounds=readRect(data,p); p+=8;
  p+=2+2+4+4+4;                             // version, packType, packSize, hRes, vRes
  p+=2;                                     // pixelType
  const pixelSize=u16be(data,p); p+=2;
  p+=2+2+4+4+4;                             // cmpCount, cmpSize, planeBytes, pmTable, pmReserved
  const maskRowBytes=u16be(data,p+4)&0x3fff, maskBounds=readRect(data,p+6); p+=14;
  const iconRowBytes=u16be(data,p+4)&0x3fff, iconBounds=readRect(data,p+6); p+=14;
  p+=4;                                     // iconData handle
  const mH=maskBounds.bottom-maskBounds.top, iH=iconBounds.bottom-iconBounds.top;
  const maskBits=data.slice(p, p+maskRowBytes*mH); p+=maskRowBytes*mH;
  p+=iconRowBytes*iH;                       // 1-bit icon bits (unused when colour data exists)
  const ct=readColorTable(data,p); p=ct.p;
  const W=pmBounds.right-pmBounds.left, H=pmBounds.bottom-pmBounds.top;
  if(W<=0||H<=0||pixelSize>8) throw new Error(`Unsupported cicn (${W}\u00d7${H}, ${pixelSize}-bit)`);
  return renderIndexedPixels(data,p,pmRowBytes,W,H,pixelSize,ct.palette,maskBits,maskRowBytes);
}

// ============================================================
//  Structured text resources
// ============================================================
function pstr(data,p){ const n=data[p]||0; return {s:decodeMacRoman(data.slice(p+1,p+1+n)), p:p+1+n}; }

function decodeVers(data){
  if(data.length<6) throw new Error('vers too short');
  const maj=data[0].toString(16), min=(data[1]>>4)&0xf, bug=data[1]&0xf;
  const stageCode=data[2], nonRel=data[3], region=u16be(data,4);
  const stage={0x20:'development',0x40:'alpha',0x60:'beta',0x80:'released'}[stageCode]||('0x'+stageCode.toString(16));
  const a=pstr(data,6), b=pstr(data,a.p);
  return `Version: ${maj}.${min}${bug?'.'+bug:''}\nStage: ${stage}${stageCode!==0x80?' (build '+nonRel+')':''}\nRegion code: ${region}\nShort: ${a.s}\nLong: ${b.s}`;
}

const DITL_TYPES={0:'user item',1:'help item',4:'button',5:'check box',6:'radio button',7:'control',8:'static text',16:'edit text',32:'icon',64:'picture'};
function decodeDITL(data){
  const n=u16be(data,0)+1; let p=2, out=[`${n} item${n===1?'':'s'}`,''];
  for(let i=0;i<n && p+13<=data.length;i++){
    p+=4;
    const r=readRect(data,p); p+=8;
    const raw=data[p++], enabled=!(raw&0x80), kind=raw&0x7f;
    const len=data[p++]; let text='';
    if(kind===32||kind===64){ text='resource #'+u16be(data,p); }
    else text=decodeMacRoman(data.slice(p,p+len));
    p+=len; if(p%2)p++;
    out.push(`[${i+1}] ${DITL_TYPES[kind]||('type '+kind)}${enabled?'':' (disabled)'}`);
    out.push(`     (${r.left},${r.top})-(${r.right},${r.bottom})  ${text?'"'+text+'"':''}`);
  }
  return out.join('\n');
}

function decodeMENU(data){
  if(data.length<14) throw new Error('MENU too short');
  const id=u16be(data,0), procID=u32be(data,6), enable=u32be(data,10);
  let p=14; const t=pstr(data,p); p=t.p;
  const out=[`Menu #${id}  "${t.s}"`, `Proc ID: ${procID}   Enable flags: 0x${(enable>>>0).toString(16)}`, ''];
  let i=1;
  while(p<data.length && data[p]!==0){
    const it=pstr(data,p); p=it.p;
    if(p+4>data.length) break;
    const icon=data[p], key=data[p+1], mark=data[p+2], style=data[p+3]; p+=4;
    const bits=[]; if(style&1)bits.push('bold'); if(style&2)bits.push('italic');
    if(style&4)bits.push('underline'); if(style&8)bits.push('outline'); if(style&16)bits.push('shadow');
    let extra=[];
    if(key>0x1f) extra.push('Cmd-'+String.fromCharCode(key));
    if(mark) extra.push('mark '+String.fromCharCode(mark));
    if(icon) extra.push('icon '+(icon+256));
    if(bits.length) extra.push(bits.join('+'));
    out.push(it.s==='-' ? `[${i}] ---- separator ----`
                        : `[${i}] ${it.s}${extra.length?'   ('+extra.join(', ')+')':''}`);
    i++;
  }
  return out.join('\n');
}

function decodeWIND(data){
  if(data.length<18) throw new Error('WIND too short');
  const r=readRect(data,0), procID=u16be(data,8), visible=!!data[11], goAway=!!data[13], refCon=u32be(data,14);
  const t=data.length>18?pstr(data,18).s:'';
  return `Window: "${t}"\nBounds: (${r.left},${r.top})-(${r.right},${r.bottom})  ${r.right-r.left}\u00d7${r.bottom-r.top}\nProc ID: ${procID}   Visible: ${visible}   Close box: ${goAway}\nRefCon: ${refCon}`;
}

function decodeALRT(data){
  if(data.length<12) throw new Error('ALRT too short');
  const r=readRect(data,0), itemsID=u16be(data,8), stages=u16be(data,10);
  return `Alert\nBounds: (${r.left},${r.top})-(${r.right},${r.bottom})  ${r.right-r.left}\u00d7${r.bottom-r.top}\nDITL resource: #${itemsID}\nStages word: 0x${stages.toString(16).padStart(4,'0')}`;
}

function decodeCNTL(data){
  if(data.length<22) throw new Error('CNTL too short');
  const r=readRect(data,0), value=s16(data,8), visible=!!data[10],
        max=s16(data,12), min=s16(data,14), procID=s16(data,16), refCon=u32be(data,18);
  const title=pstr(data,22).s;
  // procID is CDEF resource id * 16 + variant code.
  return `Control: "${title}"\nBounds: (${r.left},${r.top})-(${r.right},${r.bottom})  ${r.right-r.left}×${r.bottom-r.top}\n`+
         `Value: ${value}   Range: ${min}–${max}   Visible: ${visible}\n`+
         `Proc ID: ${procID}  (CDEF ${procID>>4}, variant ${procID&15})\nRefCon: ${refCon}`;
}

// A bare list of QuickDraw rectangles; ResEdit calls it "rectangle list".
function decodeNrct(data){
  if(data.length<2) throw new Error('nrct too short');
  const n=u16be(data,0), out=[`${n} rectangle${n===1?'':'s'}`,''];
  for(let i=0;i<n && 2+i*8+8<=data.length;i++){
    const r=readRect(data,2+i*8);
    out.push(`[${i+1}] (${r.left},${r.top})-(${r.right},${r.bottom})   ${r.right-r.left}×${r.bottom-r.top}`);
  }
  return out.join('\n');
}

// TextEdit style scrap: numRuns, then 20-byte ScrpSTElement records.
const FACE_BITS=[[1,'bold'],[2,'italic'],[4,'underline'],[8,'outline'],[16,'shadow'],[32,'condensed'],[64,'extended']];
function decodeStyl(data){
  if(data.length<2) throw new Error('styl too short');
  const n=u16be(data,0), out=[`${n} style run${n===1?'':'s'}`,''];
  for(let i=0;i<n && 2+i*20+20<=data.length;i++){
    const p=2+i*20;
    const start=u32be(data,p), height=s16(data,p+4), ascent=s16(data,p+6),
          font=u16be(data,p+8), face=data[p+10], size=u16be(data,p+12);
    const rgb=[u16be(data,p+14)>>8,u16be(data,p+16)>>8,u16be(data,p+18)>>8];
    const faces=FACE_BITS.filter(([b])=>face&b).map(([,n])=>n);
    out.push(`[${i+1}] from character ${start}: font ${font}, ${size} pt${faces.length?', '+faces.join('+'):''}`);
    out.push(`     height ${height}, ascent ${ascent}, colour rgb(${rgb.join(',')})`);
  }
  return out.join('\n');
}

// Palette resource. The header is 16 bytes (pmEntries plus seven reserved
// words), then one 16-byte ColorInfo per entry -- verified against a 4,112
// byte / 256-entry pltt, which only adds up with a 16-byte header.
const PLTT_USAGE={0x0000:'courteous',0x0001:'tolerant',0x0002:'animated',0x0004:'explicit'};
function decodePltt(data){
  if(data.length<16) throw new Error('pltt too short');
  const n=u16be(data,0);
  if(16+n*16>data.length) throw new Error(`pltt declares ${n} entries but is only ${data.length} bytes`);
  const pal=[], usage=[];
  for(let i=0;i<n;i++){
    const p=16+i*16;
    pal.push([u16be(data,p)>>8,u16be(data,p+2)>>8,u16be(data,p+4)>>8]);
    usage.push(u16be(data,p+6));
  }
  const kinds=[...new Set(usage.map(u=>PLTT_USAGE[u&7]||'0x'+u.toString(16)))];
  return {canvas:swatchGrid(pal), count:n, usage:kinds.join(', ')};
}
function swatchGrid(pal){
  const perRow=16, cell=20;
  const canvas=document.createElement('canvas');
  canvas.width=perRow*cell; canvas.height=Math.max(1,Math.ceil(pal.length/perRow))*cell;
  const ctx=canvas.getContext('2d');
  for(let i=0;i<pal.length;i++){
    const col=pal[i]||[0,0,0];
    ctx.fillStyle=`rgb(${col[0]},${col[1]},${col[2]})`;
    ctx.fillRect((i%perRow)*cell,Math.floor(i/perRow)*cell,cell,cell);
  }
  return canvas;
}

// ICON is a bare 32x32 1-bit image (no mask); SICN is a run of 16x16 ones.
function decodeICON(data){
  if(data.length<128) throw new Error(`ICON needs 128 bytes, got ${data.length}`);
  return decode1bitIcon(data,32);
}
function decodeSICN(data){
  const n=Math.floor(data.length/32);
  if(!n) throw new Error('SICN is shorter than one 16×16 icon');
  const out=[];
  for(let i=0;i<n;i++) out.push(decode1bitIcon(data.slice(i*32,(i+1)*32),16));
  return out;
}
// PAT# is a count followed by that many 8-byte patterns.
function decodePATList(data){
  if(data.length<2) throw new Error('PAT# too short');
  const n=u16be(data,0), out=[];
  for(let i=0;i<n && 2+i*8+8<=data.length;i++) out.push(decodePAT(data.slice(2+i*8,10+i*8)));
  if(!out.length) throw new Error('PAT# contains no patterns');
  return out;
}

// ============================================================
//  Bitmap fonts (NFNT/FONT) and font families (FOND)
// ============================================================
// FontRec: a single wide bitmap holding every glyph side by side, plus a
// location table giving each glyph's left edge in that strip.
function decodeNFNT(data){
  if(data.length<26) throw new Error('NFNT too short');
  const fontType=u16be(data,0), firstChar=u16be(data,2), lastChar=u16be(data,4),
        widMax=u16be(data,6), kernMax=s16(data,8), nDescent=s16(data,10),
        fRectWidth=u16be(data,12), fRectHeight=u16be(data,14), owTLoc=u16be(data,16),
        ascent=u16be(data,18), descent=u16be(data,20), leading=u16be(data,22), rowWords=u16be(data,24);
  if(lastChar<firstChar || lastChar>255) throw new Error(`implausible character range ${firstChar}–${lastChar}`);
  if(!rowWords || !fRectHeight) throw new Error('font has an empty bit image');
  const strikeBytes=rowWords*2*fRectHeight;
  if(26+strikeBytes>data.length) throw new Error('bit image runs past the end of the resource');
  const strike=data.slice(26,26+strikeBytes);
  const strikeW=rowWords*16;
  const canvas=drawBits(strike,strikeW,fRectHeight,rowWords*2);
  // Location table: one entry per glyph plus the missing-symbol and a final
  // sentinel, so glyph i occupies columns loc[i]..loc[i+1].
  const nGlyphs=lastChar-firstChar+2;          // includes the missing symbol
  const locOff=26+strikeBytes;
  const loc=[];
  for(let i=0;i<=nGlyphs && locOff+i*2+2<=data.length;i++) loc.push(u16be(data,locOff+i*2));
  const glyphs=[];
  for(let i=0;i<nGlyphs && i+1<loc.length;i++){
    const w=loc[i+1]-loc[i];
    if(w<=0) continue;                          // no image: this code is unmapped
    glyphs.push({code:firstChar+i, width:w, canvas:cropBits(strike,rowWords*2,fRectHeight,loc[i],w),
                 missing:i===nGlyphs-1});
  }
  return {canvas, glyphs, firstChar, lastChar, ascent, descent, leading, widMax,
          fRectWidth, fRectHeight, strikeW, kernMax, nDescent, fontType, owTLoc,
          info:`chars ${firstChar}–${lastChar} · ${glyphs.length} glyphs · ${fRectWidth}×${fRectHeight} cell · `+
               `ascent ${ascent}, descent ${descent}, leading ${leading} · strike ${strikeW}×${fRectHeight}`};
}
// 1-bit rows, set bit = black, transparent background.
function drawBits(bits,W,H,rowBytes){
  const c=document.createElement('canvas'); c.width=W; c.height=H;
  const ctx=c.getContext('2d'), im=ctx.createImageData(W,H);
  for(let y=0;y<H;y++) for(let x=0;x<W;x++){
    const on=((bits[y*rowBytes+(x>>3)]||0)>>(7-(x&7)))&1, o=(y*W+x)*4;
    im.data[o]=im.data[o+1]=im.data[o+2]=on?0:255;
    im.data[o+3]=on?255:0;
  }
  ctx.putImageData(im,0,0); return c;
}
function cropBits(bits,rowBytes,H,x0,W){
  const c=document.createElement('canvas'); c.width=W; c.height=H;
  const ctx=c.getContext('2d'), im=ctx.createImageData(W,H);
  for(let y=0;y<H;y++) for(let x=0;x<W;x++){
    const sx=x0+x, on=((bits[y*rowBytes+(sx>>3)]||0)>>(7-(sx&7)))&1, o=(y*W+x)*4;
    im.data[o]=im.data[o+1]=im.data[o+2]=on?0:255;
    im.data[o+3]=on?255:0;
  }
  ctx.putImageData(im,0,0); return c;
}
// FOND: 52-byte family record, then the font association table that says
// which NFNT resource holds which size and style.
const FOND_STYLES=[[1,'bold'],[2,'italic'],[4,'underline'],[8,'outline'],[16,'shadow'],[32,'condensed'],[64,'extended']];
function decodeFOND(data){
  if(data.length<54) throw new Error('FOND too short');
  const famID=u16be(data,2), first=u16be(data,4), last=u16be(data,6);
  // ascent/descent/leading/widMax are fractions of an em in 1/4096 units.
  const em=v=>(s16(data,v)/4096).toFixed(3);
  const n=u16be(data,52)+1, entries=[];
  for(let i=0;i<n && 54+i*6+6<=data.length;i++){
    const size=u16be(data,54+i*6), style=u16be(data,56+i*6), id=u16be(data,58+i*6);
    const names=FOND_STYLES.filter(([b])=>style&b).map(([,s])=>s);
    entries.push({size,style,id,label:`${size?size+' pt':'scalable'}${names.length?' '+names.join('+'):''} → ${size?'NFNT':'sfnt'} ${id}`});
  }
  return {famID, first, last, entries,
    text:`Font family #${famID}\nCharacters ${first}–${last}\n`+
         `Ascent ${em(8)} em, descent ${em(10)} em, leading ${em(12)} em, widest ${em(14)} em\n\n`+
         `${n} font${n===1?'':'s'} in this family:\n`+entries.map(e=>'  '+e.label).join('\n')};
}

// ============================================================
//  Character interpretation for resources we can't decode
// ============================================================
// Show what the bytes spell as Mac Roman text rather than a wall of hex:
// resource forks are full of embedded names, paths and messages, and those
// are what you actually want to see when there's no decoder.
// (the table is MACROMAN_HIGH in js/mac-bytes.js, as code points)
function charDump(bytes, limit){
  const n=Math.min(bytes.length, limit);
  let s='';
  for(let i=0;i<n;i++){
    const b=bytes[i];
    if(b===9||b===10||b===13) s+=' ';
    else if(b<32||b===127) s+='\u00b7';       // control bytes -> middle dot
    else if(b<128) s+=String.fromCharCode(b);
    else s+=String.fromCodePoint(MACROMAN_HIGH[b-128]);
  }
  return s;
}
function rsrcHexDump(bytes, limit){
  const n=Math.min(bytes.length,limit); let out=[];
  for(let i=0;i<n;i+=16){
    const row=Array.from(bytes.slice(i,i+16));
    out.push(i.toString(16).padStart(6,'0')+'  '+
      row.map(b=>b.toString(16).padStart(2,'0')).join(' ').padEnd(47)+'  '+
      charDump(new Uint8Array(row),16));
  }
  return out.join('\n');
}

// dctb/actb/mctb/cctb/wctb/fctb are all plain ColorTables on disk, the same
// layout clut uses, so one decoder covers the family.
const COLOR_TABLE_TYPES={'clut':'colour table','dctb':'dialog colour table','actb':'alert colour table',
  'mctb':'menu colour table','cctb':'control colour table','wctb':'window colour table',
  'fctb':'finder icon colour table'};

// ============================================================
//  Cursor gallery: one tile per cursor, PNG 1x/4x, animated GIF
// ============================================================

// ---- nearest-neighbour upscale -----------------------------
function scaleCanvas(src, mult){
  if(mult===1) return src;
  const c=document.createElement('canvas');
  c.width=src.width*mult; c.height=src.height*mult;
  const x=c.getContext('2d');
  x.imageSmoothingEnabled=false;
  x.drawImage(src,0,0,c.width,c.height);
  return c;
}
// ---- minimal GIF89a encoder (LZW), with transparency -------
function encodeGIF(canvases, delayMs){
  const W=canvases[0].width, H=canvases[0].height;
  // Build a shared palette. Index 0 is reserved for fully transparent pixels.
  const key=(r,g,b)=>(r<<16)|(g<<8)|b;
  const seen=new Map(); const pal=[[0,0,0]];
  const framesIdx=[];
  for(const cv of canvases){
    const d=cv.getContext('2d').getImageData(0,0,W,H).data;
    const idx=new Uint8Array(W*H);
    for(let i=0;i<W*H;i++){
      if(d[i*4+3]<128){ idx[i]=0; continue; }
      const k=key(d[i*4],d[i*4+1],d[i*4+2]);
      let v=seen.get(k);
      if(v===undefined){
        if(pal.length>=256){ v=1; }
        else { v=pal.length; pal.push([d[i*4],d[i*4+1],d[i*4+2]]); seen.set(k,v); }
      }
      idx[i]=v;
    }
    framesIdx.push(idx);
  }
  let bits=1; while((1<<bits)<pal.length) bits++;
  if(bits<2) bits=2;
  const palSize=1<<bits;

  const buf=[];
  const byte=b=>buf.push(b&255);
  const short=v=>{byte(v);byte(v>>8);};
  const str=t=>{for(let i=0;i<t.length;i++) byte(t.charCodeAt(i));};

  str('GIF89a'); short(W); short(H);
  byte(0x80 | ((bits-1)&7));   // global colour table, size
  byte(0); byte(0);
  for(let i=0;i<palSize;i++){const c=pal[i]||[0,0,0]; byte(c[0]);byte(c[1]);byte(c[2]);}
  // Netscape loop-forever extension
  byte(0x21); byte(0xFF); byte(11); str('NETSCAPE2.0'); byte(3); byte(1); short(0); byte(0);

  const delayCs=Math.max(1,Math.round(delayMs/10));
  for(const idx of framesIdx){
    byte(0x21); byte(0xF9); byte(4);
    byte(0x08 | 0x01);          // disposal = restore to background, transparency on
    short(delayCs); byte(0); byte(0);
    byte(0x2C); short(0); short(0); short(W); short(H); byte(0);
    lzw(idx, bits, buf);
  }
  byte(0x3B);
  return new Blob([new Uint8Array(buf)],{type:'image/gif'});
}
function lzw(pixels, minBits, buf){
  const clearCode=1<<minBits, eoi=clearCode+1;
  let codeSize=minBits+1, next=eoi+1;
  let dict=new Map();
  const reset=()=>{dict=new Map(); next=eoi+1; codeSize=minBits+1;};
  let acc=0, accBits=0; const block=[];
  const flushBlock=()=>{ if(!block.length) return; buf.push(block.length); for(const b of block) buf.push(b); block.length=0; };
  const emit=code=>{
    acc |= code<<accBits; accBits+=codeSize;
    while(accBits>=8){ block.push(acc&255); acc>>=8; accBits-=8; if(block.length===255) flushBlock(); }
  };
  buf.push(minBits);
  emit(clearCode);
  let prev=pixels[0];
  for(let i=1;i<pixels.length;i++){
    const c=pixels[i], k=prev*4096+c;
    if(dict.has(k)){ prev=dict.get(k); }
    else{
      emit(prev);
      if(next<4096){ dict.set(k,next++); if(next>(1<<codeSize) && codeSize<12) codeSize++; }
      else { emit(clearCode); reset(); }
      prev=c;
    }
  }
  emit(prev); emit(eoi);
  while(accBits>0){ block.push(acc&255); acc>>=8; accBits-=8; if(block.length===255) flushBlock(); }
  flushBlock();
  buf.push(0);
}

// ---- acur ---------------------------------------------------
// acur is 4-byte header (count, current index) then one 4-byte entry per
// frame: cursor resource ID + a reserved word. It carries NO timing data --
// the advance rate lived in the application's event loop, so any frame
// duration here is our choice, not the resource's.
function decodeAcur(data){
  const n=u16be(data,0), ids=[];
  for(let i=0;i<n && 4+i*4+2<=data.length;i++) ids.push(u16be(data,4+i*4));
  return {count:n, ids};
}
// A crsr and a CURS can share one resource ID (Cythera has both as 138), so
// callers must be able to pin the type; otherwise the CURS tile renders the
// crsr's artwork.
function lookupCursor(fork, id, preferType){
  for(const t of (preferType?[preferType]:['crsr','CURS'])){
    const list=fork.resourcesByType[t]; if(!list) continue;
    const e=list.find(r=>r.id===id); if(!e) continue;
    const data=fork.dataOf(t,e);
    try{ return {type:t, entry:e, ...(t==='crsr'?decodeCrsr(data):decodeCURS(data))}; }catch(_){ }
  }
  return null;
}

function cursorGalleryItems(fork){
  const inAnim=new Set(), anims=[];
  for(const e of (fork.resourcesByType['acur']||[])){
    const a=decodeAcur(fork.dataOf('acur',e));
    // .map(lookupCursor) passed the array index as preferType, so every frame
    // after the first looked up resource type 1, found nothing, and was
    // dropped: animated cursors silently played a single frame.
    const frames=a.ids.map(id=>lookupCursor(fork, id)).filter(Boolean);
    if(frames.length){ a.ids.forEach(i=>inAnim.add(i)); anims.push({anim:true, id:e.id, ids:a.ids, frames}); }
  }
  const singles=[];
  for(const t of ['crsr','CURS']){
    for(const e of (fork.resourcesByType[t]||[])){
      if(inAnim.has(e.id)) continue;
      const c=lookupCursor(fork, e.id, t);
      if(c) singles.push({anim:false, id:e.id, type:t, cur:c});
    }
  }
  singles.sort((a,b)=>a.id-b.id);
  return [...anims, ...singles];
}
