#!/usr/bin/env python3
"""
Normalise the system Geneva/Monaco TrueType fonts for PDF embedding.

macOS ships these two as Apple-flavoured sfnt files: they carry bitmap strikes
(bdat/bloc), Apple layout tables (morx, Zapf, feat, just, prop, bsln), and a
glyf table whose entries fontTools flags as "too much glyph data: 4 excess
bytes".  ReportLab's subsetter copies glyph data verbatim by byte range, so the
malformation is carried into the embedded font program, and strict rasterisers
(Acrobat, Preview/CoreGraphics) reject it and silently substitute a system
font.  MuPDF is lenient, which is why it looked fine in the proofs.

Running the fonts through fontTools recompiles glyf/loca from parsed outlines,
drops the Apple-only tables, and lets us guarantee a (3,1) Microsoft Unicode
cmap -- the subtable ReportLab and every viewer look for first.
"""

import os
import sys

from fontTools import subset
from fontTools.ttLib import TTFont
from fontTools.ttLib.tables._c_m_a_p import CmapSubtable

OUT_DIR = "build/fonts"

_T = "/System/Library/Fonts/Times.ttc"
_H = "/System/Library/Fonts/Helvetica.ttc"

# (registered name, source file, face index within the collection).
# Apple's own Times and Helvetica, not the PDF base-14 Adobe faces: at 12pt
# QuickDraw renders Apple Times noticeably narrower and more angular than
# Adobe Times-Roman, and that difference is what makes a rebuilt page fail to
# look like the original on screen.
SOURCES = [
    ("MacTimes",                _T, 0),
    ("MacTimes-Bold",           _T, 1),
    ("MacTimes-Italic",         _T, 2),
    ("MacTimes-BoldItalic",     _T, 3),
    ("MacHelvetica",            _H, 0),
    ("MacHelvetica-Bold",       _H, 1),
    ("MacHelvetica-Oblique",    _H, 2),
    ("MacHelvetica-BoldOblique", _H, 3),
    ("Geneva",                  "/System/Library/Fonts/Geneva.ttf", 0),
    ("Monaco",                  "/System/Library/Fonts/Monaco.ttf", 0),
]

# Everything the document can ask of these two faces: printable ASCII plus the
# handful of Mac Roman specials that survive the mac-roman -> Unicode mapping.
CHARS = set(chr(c) for c in range(0x20, 0x7F)) | set(" ©•–—“”‘’…")

DROP = ["bdat", "bloc", "EBDT", "EBLC", "EBSC", "Zapf", "morx", "mort",
        "feat", "just", "prop", "bsln", "fdsc", "fond", "meta", "hdmx",
        "kerx", "lcar", "opbd", "trak", "avar", "gvar", "cvar"]


def build(name, src, out, face=0):
    tt = TTFont(src, fontNumber=face, recalcBBoxes=True, recalcTimestamp=False)

    opts = subset.Options()
    opts.drop_tables += DROP
    opts.layout_features = []
    opts.name_IDs = [1, 2, 3, 4, 6]
    opts.notdef_outline = True
    opts.recalc_bounds = True
    opts.glyph_names = False
    opts.legacy_cmap = True
    opts.symbol_cmap = False
    opts.passthrough_tables = False

    s = subset.Subsetter(options=opts)
    s.populate(text="".join(sorted(CHARS)))
    s.subset(tt)

    # These Apple fonts carry their names only in Mac-platform records, which
    # the subsetter drops.  Without a Windows (3,1,0x409) family/full/
    # PostScript name, ReportLab 5.0 takes a code path that references a
    # non-existent rl_config attribute and refuses to load the font at all.
    nm = tt["name"]
    for nid, val in ((1, name), (2, "Regular"), (3, "%s;rebuilt" % name),
                     (4, name), (6, name)):
        nm.setName(val, nid, 3, 1, 0x409)     # Windows / Unicode BMP / en-US
        nm.setName(val, nid, 1, 0, 0)         # Macintosh / Roman / English

    # Guarantee a (3,1) Microsoft/Unicode-BMP subtable.  Geneva ships only a
    # (0,3) subtable, which some consumers skip over.
    cm = tt["cmap"]
    uni = {}
    for st in cm.tables:
        if st.isUnicode():
            uni.update(st.cmap)
    if not any(st.platformID == 3 and st.platEncID == 1 for st in cm.tables):
        st = CmapSubtable.newSubtable(4)
        st.platformID, st.platEncID, st.format, st.language = 3, 1, 4, 0
        st.cmap = dict(uni)
        cm.tables.append(st)

    os.makedirs(os.path.dirname(out), exist_ok=True)
    tt.save(out)
    return uni


def main():
    for name, src, face in SOURCES:
        if not os.path.exists(src):
            print("  ! missing %s" % src, file=sys.stderr)
            continue
        out = os.path.join(OUT_DIR, name + ".ttf")
        build(name, src, out, face)
        chk = TTFont(out)
        subs = ["(%d,%d)" % (t.platformID, t.platEncID)
                for t in chk["cmap"].tables]
        print("  %-26s %5d glyphs %6d bytes  cmap %s"
              % (name, chk["maxp"].numGlyphs, os.path.getsize(out),
                 ",".join(subs)))


if __name__ == "__main__":
    main()
