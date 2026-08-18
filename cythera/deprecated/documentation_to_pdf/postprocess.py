#!/usr/bin/env python3
"""
Post-processing passes ReportLab can't express directly.

1. patch_font_cmaps -- ReportLab writes TrueType subsets with /Flags 4
   (symbolic), no /Encoding, and a lone (1,0) Macintosh cmap subtable.  That
   combination is legal per PDF 32000-1 9.6.6.4 but Acrobat and Preview both
   prefer the (3,0) Microsoft/Symbol subtable for symbolic fonts and fall back
   to a substitute font when it is absent.  We add a (3,0) subtable mirroring
   the (1,0) one at 0xF000+code, which is what those viewers look for.

2. apply_links -- the document's pInf records carry live actions: action 1 is
   "go to chapter N" (the blue arrow buttons), action 3 is Print, action 4 is
   Quit.  Chapter jumps become real GoTo links; Print becomes a /Named /Print
   action.  Quit has no PDF equivalent and is left inert.
"""

import io
import os

import pymupdf
from fontTools.ttLib import TTFont
from fontTools.ttLib.tables._c_m_a_p import CmapSubtable


def patch_font_cmaps(doc):
    patched = []
    for xref in range(1, doc.xref_length()):
        if doc.xref_get_key(xref, "Type")[1] != "/FontDescriptor":
            continue
        kind, val = doc.xref_get_key(xref, "FontFile2")
        if kind == "null":
            continue
        ff = int(val.split()[0])
        try:
            data = doc.xref_stream(ff)
            tt = TTFont(io.BytesIO(data))
        except Exception:
            continue
        cm = tt["cmap"]
        if any(t.platformID == 3 and t.platEncID == 0 for t in cm.tables):
            continue
        base = {}
        for t in cm.tables:
            if t.platformID == 1 and t.platEncID == 0:
                base.update(t.cmap)
        if not base:
            continue
        st = CmapSubtable.newSubtable(4)
        st.platformID, st.platEncID, st.format, st.language = 3, 0, 4, 0
        st.cmap = dict((0xF000 + c, g) for c, g in base.items() if c < 256)
        cm.tables.append(st)

        buf = io.BytesIO()
        tt.save(buf)
        new = buf.getvalue()
        doc.update_stream(ff, new, compress=True)
        doc.xref_set_key(ff, "Length1", str(len(new)))
        name = doc.xref_get_key(xref, "FontName")[1].lstrip("/")
        patched.append(name)
    return patched


def apply_links(doc, links, chapter_page):
    """links: [{page, rect(top-left origin), action, arg}]
    chapter_page: {chapter_index_0based: page_index_0based}"""
    n_goto = n_print = n_skip = 0
    for lk in links:
        page = doc[lk["page"]]
        x0, y0, x1, y1 = lk["rect"]
        if lk["action"] == 1:
            tgt = chapter_page.get(lk["arg"] - 1)
            if tgt is None:
                n_skip += 1
                continue
            page.insert_link({
                "kind": pymupdf.LINK_GOTO,
                "from": pymupdf.Rect(x0, y0, x1, y1),
                "page": tgt,
                "to": pymupdf.Point(0, 0),
                "zoom": 0,
            })
            n_goto += 1
        elif lk["action"] == 3:
            h = page.rect.height
            annot = ("<</Type/Annot/Subtype/Link/Border[0 0 0]"
                     "/Rect[%g %g %g %g]/A<</S/Named/N/Print>>>>"
                     % (x0, h - y1, x1, h - y0))
            page._addAnnot_FromString((annot,))
            n_print += 1
        else:
            n_skip += 1                     # action 4 (Quit): no PDF analogue
    return n_goto, n_print, n_skip


def run(path, links, chapter_page):
    doc = pymupdf.open(path)
    fonts = patch_font_cmaps(doc)
    n_goto, n_print, n_skip = apply_links(doc, links, chapter_page)
    tmp = path + ".tmp"
    doc.save(tmp, garbage=3, deflate=True)
    doc.close()
    os.replace(tmp, path)
    return fonts, n_goto, n_print, n_skip
