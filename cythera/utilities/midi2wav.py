#!/usr/bin/env python3
"""
Minimal software synth: reads a Standard MIDI File and renders it to WAV.
Deliberately parses the .mid from disk (not the QTMA source) so this is an
independent check that the MIDI files themselves contain audible music.
"""
import struct, sys, os, glob, wave
import numpy as np
 
SR = 22050
 
def read_vlq(d, i):
    v = 0
    while True:
        b = d[i]; i += 1
        v = (v << 7) | (b & 0x7F)
        if not (b & 0x80):
            return v, i
 
def parse_midi(path):
    d = open(path, 'rb').read()
    assert d[0:4] == b'MThd'
    _, fmt, ntrk, div = struct.unpack('>IHHH', d[4:14])
    i = 14
    assert d[i:i+4] == b'MTrk'
    tlen = struct.unpack('>I', d[i+4:i+8])[0]
    i += 8
    end = i + tlen
    tempo = 500000
    t = 0
    running = None
    prog = {}          # channel -> program
    chan_vol = {}      # channel -> volume (0..127)
    notes = []         # (start_sec, dur_sec, pitch, vel, ch, program)
    active = {}        # (ch,pitch) -> (start_tick, vel)
    tempo_map = [(0, 500000)]
    while i < end:
        dt, i = read_vlq(d, i)
        t += dt
        b = d[i]
        if b == 0xFF:
            i += 1; mt = d[i]; i += 1
            ln, i = read_vlq(d, i)
            pl = d[i:i+ln]; i += ln
            if mt == 0x51:
                tempo = int.from_bytes(pl, 'big')
                tempo_map.append((t, tempo))
            if mt == 0x2F:
                break
            continue
        if b & 0x80:
            running = b; i += 1
        st = running; hi = st & 0xF0; ch = st & 0x0F
        if hi in (0xC0, 0xD0):
            d1 = d[i]; i += 1
            if hi == 0xC0:
                prog[ch] = d1
        else:
            d1 = d[i]; d2 = d[i+1]; i += 2
            if hi == 0x90 and d2 > 0:
                active[(ch, d1)] = (t, d2)
            elif hi == 0x80 or (hi == 0x90 and d2 == 0):
                if (ch, d1) in active:
                    st_tick, vel = active.pop((ch, d1))
                    notes.append((st_tick, t - st_tick, d1, vel, ch))
            elif hi == 0xB0 and d1 == 7:
                chan_vol[ch] = d2
    # convert ticks -> seconds using tempo map
    def tick_to_sec(tick):
        sec = 0.0; last_t = 0; last_tempo = tempo_map[0][1]
        for tt, tp in tempo_map[1:]:
            if tt >= tick: break
            sec += (tt - last_t) / div * (last_tempo / 1e6)
            last_t = tt; last_tempo = tp
        sec += (tick - last_t) / div * (last_tempo / 1e6)
        return sec
    out = []
    for st_tick, dur_tick, pitch, vel, ch in notes:
        s = tick_to_sec(st_tick)
        e = tick_to_sec(st_tick + dur_tick)
        out.append((s, max(e - s, 0.02), pitch, vel, ch, prog.get(ch, 0)))
    return out, chan_vol
 
# Rough timbre families so different GM programs don't all sound identical.
def harmonics_for(program):
    p = program
    if p < 8:    return [1.0, 0.5, 0.25, 0.12, 0.06], 'pluck'      # piano
    if p < 16:   return [1.0, 0.3, 0.6, 0.2], 'pluck'              # chromatic perc
    if p < 24:   return [1.0, 0.8, 0.6, 0.5, 0.3], 'pad'           # organ
    if p < 32:   return [1.0, 0.6, 0.35, 0.2, 0.1], 'pluck'        # guitar
    if p < 40:   return [1.0, 0.7, 0.2, 0.1], 'pluck'              # bass
    if p < 56:   return [1.0, 0.5, 0.35, 0.25, 0.15], 'pad'        # strings
    if p < 64:   return [1.0, 0.7, 0.5, 0.35, 0.2], 'pad'          # brass
    if p < 80:   return [1.0, 0.35, 0.15, 0.08], 'pad'             # reed/pipe
    if p < 96:   return [1.0, 0.45, 0.3, 0.2], 'pad'               # synth lead/pad
    return [1.0, 0.4, 0.25, 0.15], 'pad'
 
def render(notes, chan_vol, total_sec):
    n = int((total_sec + 2.0) * SR)
    buf = np.zeros(n, dtype=np.float32)
    for (s, dur, pitch, vel, ch, program) in notes:
        f = 440.0 * (2 ** ((pitch - 69) / 12.0))
        if f <= 0 or f > SR / 2:
            continue
        length = int(min(dur + 0.25, 6.0) * SR)
        if length < 8:
            continue
        i0 = int(s * SR)
        if i0 + length > n:
            length = n - i0
            if length < 8:
                continue
        tt = np.arange(length, dtype=np.float32) / SR
        harms, kind = harmonics_for(program)
        wave_ = np.zeros(length, dtype=np.float32)
        for k, amp in enumerate(harms, start=1):
            if f * k > SR / 2:
                break
            wave_ += amp * np.sin(2 * np.pi * f * k * tt).astype(np.float32)
        wave_ /= max(sum(harms), 1e-6)
        # envelope
        sustain_len = int(min(dur, 6.0) * SR)
        env = np.zeros(length, dtype=np.float32)
        atk = max(int(0.008 * SR), 1)
        if kind == 'pluck':
            dec = np.exp(-np.arange(length, dtype=np.float32) / (0.45 * SR))
            env = dec
        else:
            env[:] = 1.0
            rel_start = min(sustain_len, length)
            rel_len = length - rel_start
            if rel_len > 0:
                env[rel_start:] = np.exp(-np.arange(rel_len, dtype=np.float32) / (0.12 * SR))
        env[:atk] *= np.linspace(0, 1, atk, dtype=np.float32)
        cv = chan_vol.get(ch, 100) / 127.0
        gain = (vel / 127.0) * (0.4 + 0.6 * cv) * 0.28
        buf[i0:i0+length] += wave_ * env * gain
    peak = float(np.max(np.abs(buf))) if len(buf) else 0.0
    if peak > 0:
        buf = buf / peak * 0.89
    return buf, peak
 
def write_wav(path, buf):
    pcm = np.clip(buf, -1, 1)
    pcm = (pcm * 32767).astype('<i2')
    with wave.open(path, 'wb') as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes(pcm.tobytes())
 
if __name__ == '__main__':
    os.makedirs('/home/claude/wav_out', exist_ok=True)
    for path in sorted(glob.glob('/home/claude/midi_out/*.mid')):
        notes, chan_vol = parse_midi(path)
        if not notes:
            print(os.path.basename(path), 'NO NOTES'); continue
        total = max(s + d for s, d, *_ in notes)
        buf, peak = render(notes, chan_vol, total)
        rms = float(np.sqrt(np.mean(buf.astype(np.float64) ** 2)))
        out = '/home/claude/wav_out/' + os.path.basename(path).replace('.mid', '.wav')
        write_wav(out, buf)
        size = os.path.getsize(out) / 1e6
        print(f"{os.path.basename(out)}: {len(notes)} notes, {total:.1f}s, "
              f"pre-norm peak={peak:.3f}, RMS={rms:.4f}, {size:.1f}MB")