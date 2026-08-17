#!/usr/bin/env python3
"""
QTMA (QuickTime Music Architecture) -> Standard MIDI File converter.
 
Bit-field layout taken verbatim from Apple's QuickTimeMusic.h (Universal
Interfaces 3.3.1), not guessed:
 
  kEventLengthFieldPos        = 30, width 2   (0/1 => 1 long, 2 => 2 longs, 3 => variable)
  kEventTypeFieldPos          = 29, width 3   (short type)
  kXEventTypeFieldPos         = 28, width 4   (extended type, when short type > 3)
  kEventPartFieldPos          = 24, width 5
  kXEventPartFieldPos         = 16, width 12  (1st long word)
 
  Rest:     duration  pos 0,  width 24
  Note:     pitch     pos 18, width 6,  +kNoteEventPitchOffset (32)
            volume    pos 11, width 7
            duration  pos 0,  width 11
  XNote:    pitch     pos 0,  width 16 (1st long)
            duration  pos 0,  width 22 (2nd long)
            volume    pos 22, width 7  (2nd long)
  Control:  controller pos 16, width 8
            value      pos 0,  width 16
  Marker:   subtype   pos 16, width 8
            value     pos 0,  width 16
  General:  subtype   pos 16, width 14 (last long)
            length    pos 0,  width 16 (1st & last long; in LONGS, incl. both)
 
Durations are in MILLISECONDS. Pitch maps directly to MIDI key numbers.
kEndMarkerValue = 0x60000000.
"""
import struct, sys, os
 
# ---- field constants (from QuickTimeMusic.h) ----
kRestEventType, kNoteEventType, kControlEventType, kMarkerEventType = 0, 1, 2, 3
kXNoteEventType, kXControlEventType, kKnobEventType, kGeneralEventType = 0x9, 0xA, 0xB, 0xF
 
kEventLengthFieldPos, kEventLengthFieldWidth = 30, 2
kEventTypeFieldPos, kEventTypeFieldWidth = 29, 3
kXEventTypeFieldPos, kXEventTypeFieldWidth = 28, 4
kEventPartFieldPos, kEventPartFieldWidth = 24, 5
kXEventPartFieldPos, kXEventPartFieldWidth = 16, 12
 
kRestEventDurationFieldPos, kRestEventDurationFieldWidth = 0, 24
kNoteEventPitchFieldPos, kNoteEventPitchFieldWidth, kNoteEventPitchOffset = 18, 6, 32
kNoteEventVolumeFieldPos, kNoteEventVolumeFieldWidth = 11, 7
kNoteEventDurationFieldPos, kNoteEventDurationFieldWidth = 0, 11
kXNoteEventPitchFieldPos, kXNoteEventPitchFieldWidth = 0, 16
kXNoteEventDurationFieldPos, kXNoteEventDurationFieldWidth = 0, 22
kXNoteEventVolumeFieldPos, kXNoteEventVolumeFieldWidth = 22, 7
kControlEventControllerFieldPos, kControlEventControllerFieldWidth = 16, 8
kControlEventValueFieldPos, kControlEventValueFieldWidth = 0, 16
kMarkerEventSubtypeFieldPos, kMarkerEventSubtypeFieldWidth = 16, 8
kMarkerEventValueFieldPos, kMarkerEventValueFieldWidth = 0, 16
kGeneralEventSubtypeFieldPos, kGeneralEventSubtypeFieldWidth = 16, 14
kGeneralEventLengthFieldPos, kGeneralEventLengthFieldWidth = 0, 16
 
kGeneralEventNoteRequest = 1
kMarkerEventEnd, kMarkerEventBeat, kMarkerEventTempo = 0, 1, 2
kEndMarkerValue = 0x60000000
 
# QTMA controller numbers (NOT the same as MIDI CC numbers!)
kControllerModulationWheel = 1
kControllerBreath = 2
kControllerFoot = 4
kControllerPortamentoTime = 5
kControllerVolume = 7
kControllerBalance = 8
kControllerPan = 10
kControllerExpression = 11
kControllerPitchBend = 32      # MIDI CC 32 is Bank Select LSB - must NOT pass through
kControllerAfterTouch = 33     # channel pressure
kControllerPartTranspose = 40
kControllerTuneTranspose = 41
kControllerPartVolume = 42
kControllerTuneVolume = 43
kControllerSustain = 64
kControllerPortamento = 65
kControllerSostenuto = 66
kControllerSoftPedal = 67
kControllerReverb = 91
kControllerTremolo = 92
 
 
def EXT(val, pos, width):
    return (val >> pos) & ((1 << width) - 1)
 
 
def event_type(x):
    t = EXT(x, kEventTypeFieldPos, kEventTypeFieldWidth)
    return EXT(x, kXEventTypeFieldPos, kXEventTypeFieldWidth) if t > 3 else t
 
 
def event_len_longs(words, i):
    """Number of long words this event occupies."""
    x = words[i]
    ext = EXT(x, kEventLengthFieldPos, kEventLengthFieldWidth)
    if ext != 3:
        return 2 if ext == 2 else 1
    # variable length: length field in 1st long word, counted in longs
    return EXT(x, kGeneralEventLengthFieldPos, kGeneralEventLengthFieldWidth)
 
 
def parse_tune(words, verbose=False):
    """Walk the tune sequence, returning (events, parts_from_noterequest)."""
    events = []       # (time_ms, kind, ...)
    note_requests = {}  # part -> gm program
    t = 0
    i = 0
    n = len(words)
    while i < n:
        x = words[i]
        if x == kEndMarkerValue:
            break
        ln = event_len_longs(words, i)
        if ln <= 0 or i + ln > n:
            break
        et = event_type(x)
        if et == kRestEventType:
            dur = EXT(x, kRestEventDurationFieldPos, kRestEventDurationFieldWidth)
            t += dur
        elif et == kNoteEventType:
            part = EXT(x, kEventPartFieldPos, kEventPartFieldWidth)
            pitch = EXT(x, kNoteEventPitchFieldPos, kNoteEventPitchFieldWidth) + kNoteEventPitchOffset
            vol = EXT(x, kNoteEventVolumeFieldPos, kNoteEventVolumeFieldWidth)
            dur = EXT(x, kNoteEventDurationFieldPos, kNoteEventDurationFieldWidth)
            events.append((t, 'note', part, pitch, vol, dur))
        elif et == kXNoteEventType:
            w1, w2 = words[i], words[i + 1]
            part = EXT(w1, kXEventPartFieldPos, kXEventPartFieldWidth)
            pitch = EXT(w1, kXNoteEventPitchFieldPos, kXNoteEventPitchFieldWidth)
            dur = EXT(w2, kXNoteEventDurationFieldPos, kXNoteEventDurationFieldWidth)
            vol = EXT(w2, kXNoteEventVolumeFieldPos, kXNoteEventVolumeFieldWidth)
            events.append((t, 'note', part, pitch, vol, dur))
        elif et == kControlEventType:
            part = EXT(x, kEventPartFieldPos, kEventPartFieldWidth)
            ctl = EXT(x, kControlEventControllerFieldPos, kControlEventControllerFieldWidth)
            val = EXT(x, kControlEventValueFieldPos, kControlEventValueFieldWidth)
            events.append((t, 'ctl', part, ctl, val))
        elif et == kMarkerEventType:
            sub = EXT(x, kMarkerEventSubtypeFieldPos, kMarkerEventSubtypeFieldWidth)
            val = EXT(x, kMarkerEventValueFieldPos, kMarkerEventValueFieldWidth)
            if sub == kMarkerEventEnd and val == 0:
                break
            events.append((t, 'marker', sub, val))
        elif et == kGeneralEventType:
            w1 = words[i]
            wlast = words[i + ln - 1]
            part = EXT(w1, kXEventPartFieldPos, kXEventPartFieldWidth)
            sub = EXT(wlast, kGeneralEventSubtypeFieldPos, kGeneralEventSubtypeFieldWidth)
            if sub == kGeneralEventNoteRequest and ln >= 4:
                # NoteRequest: flags(1 long) then ToneDescription (synthesizerType,
                # synthesizerName[31], instrumentName[31], instrumentNumber, gmNumber)
                # Data starts at words[i+1]; ToneDescription begins after the
                # 4-byte NoteRequest "info" prefix fields.
                nr = b''.join(struct.pack('>I', w) for w in words[i + 1:i + ln - 1])
                gm = extract_gm_from_notereq(nr)
                if gm is not None:
                    note_requests[part] = gm
        i += ln
    return events, note_requests
 
 
def extract_gm_from_notereq(nr):
    """
    NoteRequest = { NoteRequestInfo info (8 bytes); ToneDescription tone }
    ToneDescription = { OSType synthesizerType(4); Str31 synthesizerName(32);
                        Str31 instrumentName(32); long instrumentNumber(4);
                        long gmNumber(4) }  == 76 bytes
    """
    if len(nr) < 8 + 76:
        return None
    tone = nr[8:8 + 76]
    gm = struct.unpack('>I', tone[72:76])[0]
    return gm if 0 <= gm <= 128 else None
 
 
# ---------------- MIDI writing ----------------
 
def vlq(n):
    if n == 0:
        return b'\x00'
    out = []
    while n:
        out.append(n & 0x7F)
        n >>= 7
    out.reverse()
    return bytes([b | 0x80 for b in out[:-1]] + [out[-1]])
 
 
def build_midi(events, note_requests, ticks_per_beat=480, tempo_us=500000):
    """
    Durations are in ms. With tempo 500000us/beat (120bpm) and 480 tpqn,
    1 beat = 500ms = 480 ticks, so ticks = ms * 480/500 = ms * 0.96.
    """
    ms_to_ticks = ticks_per_beat / (tempo_us / 1000.0)
 
    # Assign MIDI channels to parts. Part numbering in QTMA is 1-based in
    # practice; reserve channel 9 (drums) only if a part is explicitly GM drums.
    parts = sorted(set(
        [e[2] for e in events if e[1] in ('note', 'ctl')] + list(note_requests.keys())
    ))
    chan_of = {}
    next_chan = 0
    for p in parts:
        while next_chan == 9:      # skip drum channel for melodic parts
            next_chan += 1
        if next_chan > 15:
            next_chan = 15
        chan_of[p] = next_chan
        next_chan += 1
 
    abs_events = []  # (tick, order, bytes)
 
    # program changes
    for p, gm in sorted(note_requests.items()):
        ch = chan_of.get(p)
        if ch is None:
            continue
        prog = max(0, min(127, gm - 1 if gm >= 1 else 0))
        abs_events.append((0, 0, bytes([0xC0 | ch, prog])))
 
    for e in events:
        if e[1] == 'note':
            _, _, part, pitch, vol, dur = e
            ch = chan_of.get(part, 0)
            if not (0 <= pitch <= 127):
                continue
            v = max(1, min(127, vol))
            on_t = int(round(e[0] * ms_to_ticks))
            off_t = int(round((e[0] + max(dur, 1)) * ms_to_ticks))
            abs_events.append((on_t, 1, bytes([0x90 | ch, pitch, v])))
            abs_events.append((off_t, 0, bytes([0x80 | ch, pitch, 0])))
        elif e[1] == 'ctl':
            _, _, part, ctl, val = e
            ch = chan_of.get(part, 0)
            tick = int(round(e[0] * ms_to_ticks))
            # QTMA controller numbers are NOT MIDI CC numbers. Values are
            # 8.8 fixed point (signed 16-bit where applicable).
            sval = val - 0x10000 if val >= 0x8000 else val
            fixed = sval / 256.0
            msg = None
            if ctl == kControllerPitchBend or ctl == kControllerPartTranspose \
                    or ctl == kControllerTuneTranspose:
                # semitones w/ 8-bit fraction -> 14-bit bend, assume +-2 semitone range
                bend = int(round(8192 + (fixed / 2.0) * 8192))
                bend = max(0, min(16383, bend))
                msg = bytes([0xE0 | ch, bend & 0x7F, (bend >> 7) & 0x7F])
            elif ctl == kControllerAfterTouch:
                # channel pressure
                v = max(0, min(127, int(round(fixed))))
                msg = bytes([0xD0 | ch, v])
            elif ctl == kControllerPan:
                # 0 = "default"; 1..n = position in output 1..n (incl fractions)
                if val == 0:
                    v = 64
                else:
                    v = int(round((fixed - 1.0) * 127.0))
                    v = max(0, min(127, v))
                msg = bytes([0xB0 | ch, 10, v])
            elif ctl in (kControllerVolume, kControllerExpression,
                         kControllerModulationWheel, kControllerReverb,
                         kControllerTremolo, kControllerBreath, kControllerFoot):
                cc = ctl  # these QTMA numbers coincide with the MIDI CC numbers
                v = max(0, min(127, int(round(fixed))))
                msg = bytes([0xB0 | ch, cc, v])
            elif ctl in (kControllerSustain, kControllerPortamento,
                         kControllerSostenuto, kControllerSoftPedal):
                v = 127 if sval > 0 else 0
                msg = bytes([0xB0 | ch, ctl, v])
            # anything else (levers, part/tune volume, etc) is deliberately
            # dropped rather than emitted as a bogus MIDI CC.
            if msg:
                abs_events.append((tick, 0, msg))
 
    abs_events.sort(key=lambda x: (x[0], x[1]))
 
    track = bytearray()
    track += b'\x00\xFF\x51\x03' + tempo_us.to_bytes(3, 'big')
    last = 0
    for tick, _, data in abs_events:
        track += vlq(max(0, tick - last))
        track += data
        last = tick
    track += b'\x00\xFF\x2F\x00'
 
    hdr = b'MThd' + struct.pack('>IHHH', 6, 0, 1, ticks_per_beat)
    trk = b'MTrk' + struct.pack('>I', len(track)) + bytes(track)
    return hdr + trk, chan_of
 
 
def convert(musi_resource_bytes, out_path, label=''):
    d = musi_resource_bytes
    musi_len = struct.unpack('>I', d[0:4])[0]
    seq = d[musi_len:]
    if len(seq) % 4:
        seq = seq[:len(seq) - (len(seq) % 4)]
    words = list(struct.unpack('>%dI' % (len(seq) // 4), seq))
 
    # The tune header (inside the 'musi' atom) holds the NoteRequest general
    # events describing each part's instrument.
    hdr = d[8:musi_len]
    if len(hdr) % 4:
        hdr = hdr[:len(hdr) - (len(hdr) % 4)]
    hdr_words = list(struct.unpack('>%dI' % (len(hdr) // 4), hdr))
    _, note_requests = parse_tune(hdr_words)
 
    events, nr2 = parse_tune(words)
    note_requests.update(nr2)
 
    midi, chan_of = build_midi(events, note_requests)
    with open(out_path, 'wb') as f:
        f.write(midi)
 
    notes = [e for e in events if e[1] == 'note']
    pitches = [e[3] for e in notes]
    durs = [e[5] for e in notes]
    total_ms = max([e[0] for e in events], default=0)
    print(f"{label}: {len(notes)} notes, {len(events)} events, "
          f"{total_ms/1000.0:.1f}s, parts={sorted(chan_of.keys())}, "
          f"GM programs={ {p:g for p,g in sorted(note_requests.items())} }")
    if pitches:
        print(f"    pitch range {min(pitches)}-{max(pitches)}, "
              f"median dur {sorted(durs)[len(durs)//2]}ms")
    return len(notes)
 
 
if __name__ == '__main__':
    import struct as _s
    with open('/home/claude/data.bin', 'rb') as f:
        b = f.read()
 
    def u32(o): return _s.unpack('>I', b[o:o+4])[0]
    p = 0x0088
    master = []
    for i in range(256):
        master.append((u32(p), u32(p+4)))
        p += 8
    subOff, subLen = master[143]
    resids = []
    p = subOff
    for n in range(subLen // 8):
        roff, rlen = u32(p), u32(p+4)
        p += 8
        if roff:
            resids.append((n, roff, rlen))
 
    os.makedirs('/home/claude/midi_out', exist_ok=True)
    total = 0
    for n, roff, rlen in resids:
        data = b[roff:roff+rlen]
        resid = 0x9000 + n
        out = f'/home/claude/midi_out/cythera_0x{resid:04X}.mid'
        try:
            total += convert(data, out, label=f'0x{resid:04X}')
        except Exception as e:
            print(f'0x{resid:04X}: ERROR {e}')
    print('total notes:', total)