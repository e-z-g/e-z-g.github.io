#!/usr/bin/env python3
"""
Render the DOCMaker document "Cythera Documentation" to PDF, reproducing what
DOCMaker's Print command would have produced.

Layout model (recovered from the resource fork):

  * Each of the 10 TEXT resources (128..137) is one DOCMaker "page" (chapter).
    Paragraphs are CR-separated and are word-wrapped to the column width.
  * The matching styl resource gives, per character range: font id, point size,
    face bits, colour, and -- critically -- the *line height* and *ascent* the
    original used.  We keep those verbatim so the authors' hand-tuned vertical
    spacing survives.
  * Every 0xCA byte in the text is a picture anchor.  The n-th anchor in a
    chapter binds to the n-th pInf record for that chapter, which names a PICT
    and an alignment (1=centre, 2=left, 3=right).  The picture is drawn with
    its *top* at the top of the line holding the anchor and overlaps whatever
    follows; the authors reserved the space by hand with blank lines (and, in
    the table of contents, with leading indents).  So we draw pictures without
    reserving anything -- the reservation is already in the text.

Page geometry is Letter with a 540pt column, which is what DOCMaker would have
reflowed the 620px document into when printing to US Letter.
"""

import argparse
import os
import struct
import sys

from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

import postprocess
from resource_fork_parser import res
from style_run_parser import TEXTS, parse_styl

# ---------------------------------------------------------------- geometry ---

# Measured off an actual DOCMaker print (the 2018 Macintosh Garden PDF, made
# with PSNormalizer from a real print job): 1in side margins giving a 468pt
# column, body from y=62 to y=725, footer baseline near y=738.  Pictures wider
# than the column are scaled down to fit it -- that is DOCMaker's own rule, and
# it is why the chapter 3 splash (541x406) clears its 349px reservation on
# paper but not on the 620px screen.
PAGE_W, PAGE_H = 612.0, 792.0           # US Letter
MARGIN_X       = 72.0                   # 1 inch
MARGIN_TOP     = 62.0
MARGIN_BOT     = 67.0
COL_W          = PAGE_W - 2 * MARGIN_X  # 468pt
BODY_BOT       = PAGE_H - MARGIN_BOT
FOOTER_Y       = 54.0                   # baseline, measured up from page bottom

TAB = 4.0        # sTwD[1]: tab stops every 4px, absolute from the left margin

FIRST_TEXT = 128
NCHAPTERS  = 10

# ------------------------------------------------------------------- fonts ---
# Classic Mac font ids -> PDF families.  rQDF 128 lists exactly the fonts this
# document uses: Charcoal, Geneva 9/10, Helvetica 9/12/18/24, Monaco 9,
# Times 12/14/18.  Geneva and Monaco are embedded from the system's real TTFs
# (their classic Mac originals have no bold/italic masters, so those two face
# bits are synthesized at draw time -- see draw_line).
# Built by prepare_fonts.py -- see that module for why the system originals
# cannot be embedded directly.  Using Apple's Times/Helvetica rather than the
# PDF base-14 Adobe faces matters: at 12pt they are visibly narrower, which is
# what makes the rebuilt page read like the Mac original.
_SYSTEM_FONTS = [
    "MacTimes", "MacTimes-Bold", "MacTimes-Italic", "MacTimes-BoldItalic",
    "MacHelvetica", "MacHelvetica-Bold", "MacHelvetica-Oblique",
    "MacHelvetica-BoldOblique", "Geneva", "Monaco",
]
HAVE_SYSTEM_FONT = {}
for _name in _SYSTEM_FONTS:
    try:
        pdfmetrics.registerFont(TTFont(_name, "build/fonts/%s.ttf" % _name))
        HAVE_SYSTEM_FONT[_name] = True
    except Exception:
        HAVE_SYSTEM_FONT[_name] = False

# Fallbacks to the base-14 faces if prepare_fonts.py hasn't been run.
_FALLBACK = {
    "MacTimes": "Times-Roman", "MacTimes-Bold": "Times-Bold",
    "MacTimes-Italic": "Times-Italic", "MacTimes-BoldItalic": "Times-BoldItalic",
    "MacHelvetica": "Helvetica", "MacHelvetica-Bold": "Helvetica-Bold",
    "MacHelvetica-Oblique": "Helvetica-Oblique",
    "MacHelvetica-BoldOblique": "Helvetica-BoldOblique",
    "Geneva": "Helvetica", "Monaco": "Courier",
}

FAMILY = {
    20: "MacTimes",       # Times
    21: "MacHelvetica",   # Helvetica
    1:  "Geneva",         # application font
    3:  "Geneva",
    4:  "Monaco",
}


def psfont(fid, face):
    """Return (fontname, synth_bold, synth_italic).  synth_* are True when
    the chosen font has no real bold/italic master and the style must be
    faked at draw time."""
    fam = FAMILY.get(fid, "MacTimes")
    bold = bool(face & 1)
    ital = bool(face & 2)

    # Geneva and Monaco ship regular-weight only, so their bold/italic must be
    # synthesized.  In this document that is 1 italic run and 7 bold runs.
    if fam in ("Geneva", "Monaco"):
        if HAVE_SYSTEM_FONT.get(fam):
            return fam, bold, ital
        return _FALLBACK[fam], bold, ital

    slant = "-Italic" if fam == "MacTimes" else "-Oblique"
    if bold and ital:
        name = fam + ("-BoldItalic" if fam == "MacTimes" else "-BoldOblique")
    elif bold:
        name = fam + "-Bold"
    elif ital:
        name = fam + slant
    else:
        name = fam
    if not HAVE_SYSTEM_FONT.get(name):
        return _FALLBACK[name], False, False
    return name, False, False


# --------------------------------------------------------------- resources ---

PICTS = dict((r[0], r[2]) for r in res["PICT"])


def pict_size(pid):
    t, l, b, r = struct.unpack(">hhhh", PICTS[pid][2:10])
    return r - l, b - t


def chapter_titles():
    out = {}
    for rid, name, p in res["STR "]:
        if 2001 <= rid <= 2010:
            out[rid - 2001] = p[1:1 + p[0]].decode("mac-roman")
    return out


def pinf_for(ci):
    """pInf records for chapter ci, in document order."""
    recs = []
    for rid, name, p in res["pInf"]:
        if rid // 100 - 2 == ci:
            v = struct.unpack(">%dh" % (len(p) // 2), p)
            recs.append((rid, v))
    recs.sort()
    return [dict(pict=v[0], align=v[1], action=v[3],
                 arg=(v[4] if len(v) > 4 else 0)) for rid, v in recs]


def char_styles(tid):
    """Per-character style dicts for a TEXT resource."""
    runs = parse_styl(tid)
    n = len(TEXTS[tid])
    out = [runs[0]] * n
    for i, r in enumerate(runs):
        end = runs[i + 1]["start"] if i + 1 < len(runs) else n
        for j in range(max(0, r["start"]), min(end, n)):
            out[j] = r
    return out


# ------------------------------------------------------------------ layout ---

def advance(ch, st, x):
    """Width of one character laid out at pen position x."""
    if ch == "\t":
        return (int(x // TAB) + 1) * TAB - x
    fn = psfont(st["font"], st["face"])[0]
    if ch == "\xa0":                      # picture anchor: renders as a space
        return stringWidth(" ", fn, st["size"])
    return stringWidth(ch, fn, st["size"])


def wrap(chars, colw):
    """Greedy word wrap.  chars is [(ch, style)]; returns a list of lines,
    each a list of (ch, style, x, w)."""
    n = len(chars)
    if n == 0:
        return [[]]
    out = []
    i = 0
    while i < n:
        x = 0.0
        j = i
        items = []
        lastsp = -1                       # index in `items` of last space
        while j < n:
            ch, st = chars[j]
            w = advance(ch, st, x)
            if x + w > colw and items:
                break
            items.append((ch, st, x, w))
            x += w
            if ch == " ":
                lastsp = len(items) - 1
            j += 1
        if j >= n:
            out.append(items)
            return out
        if lastsp >= 0:
            out.append(items[:lastsp])    # drop the break space
            i += lastsp + 1
        else:
            out.append(items)             # unbreakable run: hard split
            i = j
    return out


def layout_chapter(ci):
    """Return a flat list of line dicts for one chapter."""
    tid = FIRST_TEXT + ci
    text = TEXTS[tid]
    styles = char_styles(tid)
    pics = pinf_for(ci)
    pic_i = 0

    lines = []
    pos = 0
    for para in text.split(b"\r"):
        pstyle = styles[min(pos, len(styles) - 1)] if styles else None
        chars = [(bytes([b]).decode("mac-roman"), styles[pos + k])
                 for k, b in enumerate(para)]
        for items in wrap(chars, COL_W):
            if items:
                h = max(st["height"] for _, st, _, _ in items)
                a = max(st["ascent"] for _, st, _, _ in items)
            else:
                h = pstyle["height"] if pstyle else 12
                a = pstyle["ascent"] if pstyle else 9
            line = dict(h=h, a=a, items=items, pics=[])
            for ch, st, x, w in items:
                if ch == "\xa0":
                    if pic_i < len(pics):
                        line["pics"].append(pics[pic_i])
                        pic_i += 1
            lines.append(line)
        pos += len(para) + 1

    if pic_i != len(pics):
        print("  ! chapter %d: bound %d/%d pictures" % (ci + 1, pic_i, len(pics)),
              file=sys.stderr)

    # Every chapter ends with a few blank lines of padding after the
    # Print/Quit button row.  On paper that padding does nothing but push the
    # buttons onto an otherwise empty page, so drop it.
    while lines and is_blank(lines[-1]):
        lines.pop()
    return resolve_overlaps(lines)


def is_blank(line):
    return not line["pics"] and all(ch in " \t\xa0" for ch, _, _, _ in line["items"])


def pic_rect(p):
    """(x0, x1, height) of a picture within the column."""
    pw, ph = pict_size(p["pict"])
    scale = min(1.0, COL_W / pw)
    w, h = pw * scale, ph * scale
    if p["align"] == 2:
        x = 0.0
    elif p["align"] == 3:
        x = COL_W - w
    else:
        x = (COL_W - w) / 2.0
    return x, x + w, h


def resolve_overlaps(lines):
    """Treat pictures as floats.

    A picture is drawn from the top of its anchor line downwards and normally
    just overlaps the blank lines the authors left for it.  Where they left
    room *beside* a picture instead -- the table of contents indents its
    entries clear of the blue "Go To" arrows -- the overlap is intentional and
    must be preserved.  But one picture (the chapter 3 splash, PICT 2011) is
    406px tall in a 349px reservation and would print straight through the
    "Welcome" heading.  So: push a line down only when it would actually
    collide, i.e. when its glyphs overlap a live picture horizontally too.
    """
    active = []                      # (x0, x1, y_bottom)
    y = 0.0
    for line in lines:
        xs = [(x, x + w) for ch, _, x, w in line["items"] if ch not in " \t\xa0"]
        pad = 0.0
        if xs:
            tx0 = min(a for a, _ in xs)
            tx1 = max(b for _, b in xs)
            for px0, px1, pybot in active:
                if pybot > y + pad and tx0 < px1 and tx1 > px0:
                    pad = max(pad, pybot - y)
        line["pad"] = pad
        y += pad
        for p in line["pics"]:        # registered after, so it never pushes its own line
            px0, px1, ph = pic_rect(p)
            active.append((px0, px1, y + ph))
        y += line["h"]
        active = [a for a in active if a[2] > y]
    return lines


def paginate(lines, imgdir):
    """Split lines into pages.  A line carrying a picture is only placed if the
    picture fits on the remaining page, so no image straddles a break."""
    pages = []
    cur = []
    y = MARGIN_TOP
    for line in lines:
        picneed = 0.0
        for p in line["pics"]:
            picneed = max(picneed, pic_rect(p)[2])
        need = max(line["h"], picneed)
        pad = line.get("pad", 0.0)
        if cur and y + pad + need > BODY_BOT:
            pages.append(cur)
            cur = []
            y = MARGIN_TOP
        if not cur:
            if is_blank(line):
                continue                   # swallow blank lines at page top
            pad = 0.0                      # and drop float padding at page top
        y += pad
        cur.append((y, line))
        y += line["h"]
    if cur:
        pages.append(cur)
    return pages


# ------------------------------------------------------------------ render ---

def draw_line(c, ytop, line, imgdir, imgcache, links=None, page_index=0):
    # pictures first, so text drawn on the same line stays on top
    for p in line["pics"]:
        pid = p["pict"]
        path = os.path.join(imgdir, "%d.png" % pid)
        if not os.path.exists(path):
            continue
        pw, ph = pict_size(pid)
        scale = min(1.0, COL_W / pw)
        w, h = pw * scale, ph * scale
        align = p["align"]
        if align == 2:
            x = 0.0
        elif align == 3:
            x = COL_W - w
        else:
            x = (COL_W - w) / 2.0
        if path not in imgcache:
            imgcache[path] = ImageReader(path)
        c.drawImage(imgcache[path], MARGIN_X + x, PAGE_H - (ytop + h),
                    width=w, height=h, mask=None)
        # pInf action 1 = go to chapter, 3 = Print, 4 = Quit.  Record the
        # live ones; postprocess.py turns them into PDF annotations.
        if links is not None and p["action"] in (1, 3, 4):
            links.append(dict(page=page_index,
                              rect=(MARGIN_X + x, ytop, MARGIN_X + x + w, ytop + h),
                              action=p["action"], arg=p.get("arg", 0)))

    baseline = PAGE_H - (ytop + line["a"])
    # group runs of identical style into single show-text ops
    run = []
    run_st = None
    run_x = 0.0

    def flush():
        if not run:
            return
        st = run_st
        fn, sbold, sital = psfont(st["font"], st["face"])
        size = st["size"]
        r, g, b = st["color"]
        color = (r / 255.0, g / 255.0, b / 255.0)
        s = "".join(run)
        x0 = MARGIN_X + run_x

        # Geneva/Monaco have no real bold/italic masters, so fake them here:
        # italic as a horizontal shear, bold as a stroked-and-filled fill.
        c.saveState()
        c.translate(x0, baseline)
        if sital:
            c.transform(1, 0, 0.20, 1, 0, 0)
        if sbold:
            c.setLineWidth(size * 0.045)    # stroke width is graphics-state, not text-object
            tx = c.beginText(0, 0)
            tx.setFont(fn, size)
            tx.setFillColorRGB(*color)
            tx.setStrokeColorRGB(*color)
            tx.setTextRenderMode(2)         # fill then stroke
            tx.textOut(s)
            c.drawText(tx)
        else:
            c.setFont(fn, size)
            c.setFillColorRGB(*color)
            c.drawString(0, 0, s)
        c.restoreState()

        if st["face"] & 4:                 # underline
            w = stringWidth(s, fn, size)
            c.setStrokeColorRGB(*color)
            c.setLineWidth(max(0.5, size / 14.0))
            uy = baseline - size * 0.13
            c.line(x0, uy, x0 + w, uy)

    for ch, st, x, w in line["items"]:
        if ch in "\t\xa0":
            flush()
            run = []
            run_st = None
            continue
        key = (st["font"], st["size"], st["face"], st["color"])
        if run_st is None or key != (run_st["font"], run_st["size"],
                                     run_st["face"], run_st["color"]):
            flush()
            run = []
            run_st = st
            run_x = x
        run.append(ch)
    flush()


def footer(c, title, pageno):
    c.setFont("MacHelvetica" if HAVE_SYSTEM_FONT.get("MacHelvetica")
              else "Helvetica", 8)
    c.setFillColorRGB(0.35, 0.35, 0.35)
    c.drawString(MARGIN_X, FOOTER_Y, title)
    c.drawRightString(PAGE_W - MARGIN_X, FOOTER_Y, "Page %d" % pageno)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-o", "--out", default="Cythera Documentation.pdf")
    ap.add_argument("--imgdir", default="build/img")
    ap.add_argument("--no-footer", action="store_true")
    args = ap.parse_args()

    titles = chapter_titles()
    c = canvas.Canvas(args.out, pagesize=(PAGE_W, PAGE_H))
    c.setTitle("Cythera Documentation")
    c.setAuthor("David Dunham and Glenn Andreas")
    c.setSubject("Ambrosia Software - Cythera")
    c.setCreator("DOCMaker document rebuilt from resource fork")

    imgcache = {}
    links = []
    chapter_page = {}
    pageno = 0
    for ci in range(NCHAPTERS):
        lines = layout_chapter(ci)
        pages = paginate(lines, args.imgdir)
        title = titles.get(ci, "Chapter %d" % (ci + 1))
        print("  ch%2d  %-38s %3d lines -> %2d pages"
              % (ci + 1, title, len(lines), len(pages)))
        for pi, page in enumerate(pages):
            pageno += 1
            for ytop, line in page:
                draw_line(c, ytop, line, args.imgdir, imgcache,
                          links, pageno - 1)
            if not args.no_footer:
                footer(c, title, pageno)
            if pi == 0:
                chapter_page[ci] = pageno - 1
                key = "ch%d" % ci
                c.bookmarkPage(key)
                c.addOutlineEntry(title, key, level=0)
            c.showPage()
    c.showOutline()
    c.save()

    fonts, n_goto, n_print, n_skip = postprocess.run(args.out, links, chapter_page)
    print("  fonts given a (3,0) cmap: %s" % (", ".join(fonts) or "none"))
    print("  links: %d chapter jumps, %d Print buttons, %d inert (Quit)"
          % (n_goto, n_print, n_skip))
    print("wrote %s (%d pages)" % (args.out, pageno))


if __name__ == "__main__":
    main()
