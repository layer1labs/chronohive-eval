#!/usr/bin/env python3
# © 2026 Layer1Labs Silicon Inc. All rights reserved.
# CONFIDENTIAL — ChronoHive Evaluation Package. Licensed solely for
# evaluation under the ChronoHive Terms of Confidentiality (TOC.md) and
# the ChronoHive Evaluation License (LICENSE). Do not distribute.
"""Generate styled customer-facing PDFs from the Markdown docs (fpdf2).

Usage: python3 scripts/make_pdfs.py
Writes pdf/*.pdf next to the docs. Regenerate after editing any source doc.
"""
from __future__ import annotations

import os
import re
import sys
from datetime import datetime, timezone

from fpdf import FPDF

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTDIR = os.path.join(REPO, "pdf")

# (markdown path, pdf name, cover subtitle)
DOCS = [
    ("README.md", "ChronoHive-Eval-Quickstart.pdf", "Evaluation quickstart"),
    ("docs/ARCHITECTURE.md", "ChronoHive-How-It-Works.pdf",
     "System architecture and evaluation guide"),
    ("docs/API.md", "ChronoHive-Eval-API-Reference.pdf", "API reference"),
    ("docs/LF_TOOLCHAIN.md", "ChronoHive-LF-Toolchain.pdf",
     "LF toolchain and compile pipeline"),
    ("TOC.md", "ChronoHive-TOC.pdf", "Terms of Confidentiality"),
]

TEAL = (15, 118, 110)
TEAL_DK = (17, 94, 89)
INK = (30, 41, 59)
MUTED = (100, 116, 139)
CODE_BG = (248, 250, 252)
RULE = (226, 232, 240)
TABLE_HEAD_BG = (15, 118, 110)
TABLE_ALT_BG = (240, 253, 250)
FOOTER_TEXT = "\u00a9 2026 Layer1Labs Silicon Inc. \u2014 CONFIDENTIAL \u2014 PROPRIETARY"


class DocPDF(FPDF):
    def __init__(self, subtitle: str):
        super().__init__(format="Letter")
        self.subtitle = subtitle
        self.set_auto_page_break(True, margin=28)
        self.set_margins(25, 22, 25)
        # Vendored fonts keep PDF output byte-deterministic across machines
        # (no dependency on whatever the host's fonts-dejavu-core ships).
        fd = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts")
        if not os.path.exists(os.path.join(fd, "DejaVuSans.ttf")):
            fd = "/usr/share/fonts/truetype/dejavu"
        self.add_font("DVS", "", f"{fd}/DejaVuSans.ttf")
        self.add_font("DVS", "B", f"{fd}/DejaVuSans-Bold.ttf")
        # No Sans oblique shipped on this box; fall back to upright faces.
        self.add_font("DVS", "I", f"{fd}/DejaVuSans.ttf")
        self.add_font("DVS", "BI", f"{fd}/DejaVuSans-Bold.ttf")
        self.add_font("DVM", "", f"{fd}/DejaVuSansMono.ttf")
        self.add_font("DVM", "B", f"{fd}/DejaVuSansMono-Bold.ttf")

    def header(self):
        if self.page_no() == 1:
            return
        self.set_font("DVS", "I", 8)
        self.set_text_color(*MUTED)
        self.cell(0, 6, self.subtitle, align="R")
        self.ln(5)
        self.set_draw_color(*RULE)
        self.line(self.l_margin, self.get_y(), self.w - self.r_margin,
                  self.get_y())
        self.ln(7)

    def footer(self):
        self.set_y(-20)
        self.set_draw_color(*RULE)
        self.line(self.l_margin, self.get_y(), self.w - self.r_margin,
                  self.get_y())
        self.ln(3)
        self.set_font("DVS", "", 7.5)
        self.set_text_color(*MUTED)
        self.cell(0, 5, FOOTER_TEXT, align="C")
        self.ln(4)
        self.cell(0, 5, f"Page {self.page_no()}", align="C")


# ---------------------------------------------------------------- inline
INLINE_RE = re.compile(
    r"(\*\*.+?\*\*|\*[^*]+?\*|`[^`]+?`|\[[^\]]+?\]\([^)]+?\))")


def _inline_parts(pdf: DocPDF, text: str, base_size: int):
    """Yield (font_style, text) segments; handles **bold**, *ital*, `code`,
    [label](url)."""
    pos = 0
    for m in INLINE_RE.finditer(text):
        if m.start() > pos:
            yield ("", text[pos:m.start()])
        tok = m.group(0)
        if tok.startswith("**"):
            yield ("B", tok[2:-2])
        elif tok.startswith("`"):
            yield ("CODE", tok[1:-1])
        elif tok.startswith("["):
            label = tok[1:tok.index("]")]
            yield ("", label)
        else:
            yield ("I", tok[1:-1])
        pos = m.end()
    if pos < len(text):
        yield ("", text[pos:])


def write_para(pdf: DocPDF, text: str, size: int = 10, style: str = "",
               color=INK, space_after: float = 4, align: str = "L"):
    x0 = pdf.get_x()
    pdf.set_text_color(*color)
    for fstyle, seg in _inline_parts(pdf, text, size):
        if fstyle == "CODE":
            pdf.set_font("DVM", "", size - 0.5)
            pdf.set_text_color(*TEAL_DK)
        else:
            pdf.set_font("DVS", style + fstyle, size)
            pdf.set_text_color(*color)
        pdf.write(5.2, seg)
    pdf.ln(space_after + 2.2)
    pdf.set_x(x0)


def write_heading(pdf: DocPDF, level: int, text: str):
    sizes = {1: 17, 2: 13.5, 3: 11.5}
    size = sizes.get(level, 11)
    pdf.ln(4 if level > 1 else 2)
    if pdf.get_y() > 235:
        pdf.add_page()
    pdf.set_font("DVS", "B", size)
    pdf.set_text_color(*TEAL_DK if level > 1 else TEAL)
    # strip inline markers for width calc simplicity; write plain
    clean = re.sub(r"\*\*|\*|`", "", text)
    pdf.multi_cell(0, size * 0.55, clean)
    if level <= 2:
        pdf.set_draw_color(*RULE)
        y = pdf.get_y() + 1
        pdf.line(pdf.l_margin, y, pdf.l_margin + (60 if level == 2 else 90), y)
        pdf.ln(4)
    else:
        pdf.ln(2)


def write_code(pdf: DocPDF, lines: list[str]):
    if pdf.get_y() > 225:
        pdf.add_page()
    pdf.set_fill_color(*CODE_BG)
    pdf.set_draw_color(*RULE)
    pdf.set_font("DVM", "", 8.2)
    x = pdf.get_x()
    w = pdf.w - pdf.l_margin - pdf.r_margin
    for line in lines:
        if pdf.get_y() > 255:
            pdf.add_page()
        y = pdf.get_y()
        pdf.set_x(x)
        pdf.cell(w, 5.4, "  " + line.replace("\t", "    ")[:110], fill=True)
        pdf.ln(5.4)
        # subtle left accent on first line
        if line is lines[0]:
            pdf.set_draw_color(*TEAL)
            pdf.line(x, y, x, y + 5.4 * len(lines))
            pdf.set_draw_color(*RULE)
    pdf.ln(4)


def write_bullets(pdf: DocPDF, items: list[tuple[int, str]], ordered=False):
    for idx, (depth, text) in enumerate(items):
        if pdf.get_y() > 250:
            pdf.add_page()
        x = pdf.l_margin + depth * 8
        pdf.set_x(x)
        bullet = f"{idx + 1}." if ordered else "\u2022"
        pdf.set_font("DVS", "B", 10)
        pdf.set_text_color(*TEAL)
        bw = pdf.get_string_width(bullet + " ") + 2
        pdf.cell(bw, 5.2, bullet + " ")
        pdf.set_text_color(*INK)
        x0 = pdf.get_x()
        for fstyle, seg in _inline_parts(pdf, text, 10):
            if fstyle == "CODE":
                pdf.set_font("DVM", "", 9)
                pdf.set_text_color(*TEAL_DK)
            else:
                pdf.set_font("DVS", fstyle, 10)
                pdf.set_text_color(*INK)
            pdf.write(5.2, seg)
        pdf.ln(7.2)
    pdf.ln(2)


def write_quote(pdf: DocPDF, lines: list[str]):
    pdf.set_text_color(*MUTED)
    pdf.set_font("DVS", "I", 9.5)
    x = pdf.l_margin
    for line in lines:
        if not line.strip():
            continue
        pdf.set_x(x + 4)
        pdf.multi_cell(pdf.w - pdf.l_margin - pdf.r_margin - 4, 5.2, line)
    # left bar
    pdf.ln(3)


def split_row(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def _cell_runs(cell: str):
    """Return (base_style, clean_text) for a table cell.

    A cell fully wrapped in **...** renders bold; other inline markers are
    stripped (tables stay clean and legible).
    """
    cell = cell.strip()
    if cell.startswith("**") and cell.endswith("**") and len(cell) > 4:
        return "B", cell[2:-2].replace("`", "")
    return "", cell.replace("**", "").replace("*", "").replace("`", "")


def _wrap_lines(pdf: DocPDF, text: str, cw: float) -> list[str]:
    words = text.split(" ")
    lines: list[str] = []
    cur = ""
    for wd in words:
        t = (cur + " " + wd).strip()
        if not cur or pdf.get_string_width(t) <= cw - 6:
            cur = t
        else:
            lines.append(cur)
            cur = wd
    if cur:
        lines.append(cur)
    return lines or [""]


def write_table(pdf: DocPDF, rows: list[list[str]]):
    if not rows:
        return
    ncols = max(len(r) for r in rows)
    rows = [r + [""] * (ncols - len(r)) for r in rows]
    w = pdf.w - pdf.l_margin - pdf.r_margin
    pdf.set_font("DVS", "", 8.5)
    widths = []
    for c in range(ncols):
        mx = max(pdf.get_string_width(_cell_runs(r[c])[1]) for r in rows) + 10
        widths.append(min(mx, w * 0.55))
    total = sum(widths)
    widths = [x / total * w for x in widths]
    header, body = rows[0], rows[1:]
    # skip the markdown separator row if present
    if body and all(set(c) <= set("-: ") for c in body[0]):
        body = body[1:]

    LINE = 5.6
    PAD = 3

    def row(cells, is_header, fill):
        # measure
        wrapped = []
        for i, c in enumerate(cells):
            style, clean = _cell_runs(c)
            pdf.set_font("DVS", ("B" if is_header else "") + style, 8.5)
            wrapped.append((style, _wrap_lines(pdf, clean, widths[i])))
        nlines = max(len(x[1]) for x in wrapped)
        rh = nlines * LINE + PAD * 2
        if pdf.get_y() + rh > 258:
            pdf.add_page()
        y0 = pdf.get_y()
        x = pdf.l_margin
        for i, (style, lines) in enumerate(wrapped):
            pdf.set_fill_color(*fill)
            pdf.rect(x, y0, widths[i], rh, style="F")
            pdf.set_font("DVS", ("B" if is_header else "") + style, 8.5)
            pdf.set_text_color(*((255, 255, 255) if is_header else INK))
            ty = y0 + PAD + LINE * 0.75
            for ln in lines:
                pdf.text(x + 3, ty, ln)
                ty += LINE
            x += widths[i]
        pdf.set_y(y0 + rh)
        pdf.set_x(pdf.l_margin)

    row(header, True, TABLE_HEAD_BG)
    for i, r in enumerate(body):
        row(r, False, TABLE_ALT_BG if i % 2 == 0 else (255, 255, 255))
    pdf.ln(5)


# ---------------------------------------------------------------- blocks
def parse_blocks(src: str, base: str):
    """Split markdown into typed blocks."""
    lines = src.split("\n")
    i, n = 0, len(lines)
    while i < n:
        line = lines[i]
        s = line.strip()
        if not s:
            i += 1
            continue
        if s.startswith("```"):
            buf = []
            i += 1
            while i < n and not lines[i].strip().startswith("```"):
                buf.append(lines[i].rstrip("\n"))
                i += 1
            i += 1
            yield ("code", buf)
            continue
        if s.startswith("#"):
            level = len(s) - len(s.lstrip("#"))
            yield ("h", (level, s[level:].strip()))
            i += 1
            continue
        if re.match(r"^!\[.*?\]\(.*?\)$", s):
            m = re.match(r"^!\[(.*?)\]\((.*?)\)$", s)
            yield ("img", (m.group(1), os.path.join(base, m.group(2))))
            i += 1
            continue
        if s.startswith(">"):
            buf = []
            while i < n and lines[i].strip().startswith(">"):
                buf.append(lines[i].strip()[1:].strip())
                i += 1
            yield ("quote", buf)
            continue
        if s.startswith("|"):
            buf = []
            while i < n and lines[i].strip().startswith("|"):
                buf.append(split_row(lines[i]))
                i += 1
            yield ("table", buf)
            continue
        if re.match(r"^(\*|-|\d+\.)\s", s):
            buf = []
            ordered = bool(re.match(r"^\d+\.\s", s))
            while i < n and re.match(r"^(\s*(\*|-|\d+\.)\s)", lines[i]):
                m2 = re.match(r"^(\s*)(?:\*|-|\d+\.)\s(.*)$", lines[i])
                depth = len(m2.group(1)) // 2
                text = m2.group(2)
                i += 1
                # wrapped continuation lines: indented, not a new block
                while (i < n and lines[i].strip()
                       and lines[i].startswith((" ", "\t"))
                       and not re.match(r"^\s*(\*|-|\d+\.)\s", lines[i])
                       and not re.match(r"^(```|>|#{1,6}\s|\||---+\s*$)", lines[i].strip())):
                    text += " " + lines[i].strip()
                    i += 1
                buf.append((depth, text))
            yield ("list", (ordered, buf))
            continue
        if re.match(r"^---+$", s):
            yield ("hr", None)
            i += 1
            continue
        # paragraph: gather until blank or block start
        buf = [s]
        i += 1
        while i < n:
            t = lines[i].strip()
            if (not t or t.startswith("#") or t.startswith("```")
                    or t.startswith(">") or t.startswith("|")
                    or re.match(r"^(\*|-|\d+\.)\s", t)
                    or re.match(r"^!\[", t) or re.match(r"^---+$", t)):
                break
            buf.append(t)
            i += 1
        yield ("para", " ".join(buf))


def cover(pdf: DocPDF, title: str, subtitle: str):
    pdf.add_page()
    pdf.ln(38)
    pdf.set_draw_color(*TEAL)
    pdf.set_line_width(1.2)
    pdf.line(25, pdf.get_y(), 60, pdf.get_y())
    pdf.ln(8)
    pdf.set_font("DVS", "B", 26)
    pdf.set_text_color(*TEAL_DK)
    pdf.multi_cell(0, 12, title, align="L")
    pdf.ln(4)
    pdf.set_font("DVS", "", 13)
    pdf.set_text_color(*MUTED)
    pdf.multi_cell(0, 7, subtitle)
    pdf.ln(10)
    pdf.set_draw_color(*TEAL)
    pdf.set_line_width(0.6)
    # confidential banner box
    pdf.set_fill_color(*TABLE_ALT_BG)
    pdf.set_font("DVS", "B", 9)
    pdf.set_text_color(*TEAL_DK)
    x = pdf.get_x()
    pdf.multi_cell(pdf.w - pdf.l_margin - pdf.r_margin, 6,
                   "CONFIDENTIAL \u2014 PROPRIETARY\n"
                   "Licensed solely for evaluation under the ChronoHive Terms\n"
                   "of Confidentiality and the ChronoHive Evaluation License.\n"
                   "Do not distribute, copy, or publicly host.",
                   fill=True, align="C")
    pdf.ln(14)
    pdf.set_font("DVS", "", 9)
    pdf.set_text_color(*MUTED)
    pdf.cell(0, 6, "\u00a9 2026 Layer1Labs Silicon Inc. All rights reserved.",
             align="C")


def build(md_path: str, pdf_name: str, subtitle: str):
    src = open(md_path, encoding="utf-8").read()
    base = os.path.dirname(md_path)
    # doc title = first H1
    m = re.search(r"^#\s+(.+)$", src, re.M)
    title = m.group(1).strip() if m else pdf_name
    pdf = DocPDF(subtitle)
    # Reproducible builds: fixed document date so regeneration is
    # byte-identical (CI freshness check depends on this).
    pdf.set_creation_date(datetime(2026, 9, 29, 0, 0, 0, tzinfo=timezone.utc))
    cover(pdf, title, subtitle)
    pdf.add_page()
    skip_first_h1 = True
    for kind, payload in parse_blocks(src, base):
        if kind == "h":
            level, text = payload
            if level == 1 and skip_first_h1:
                skip_first_h1 = False
                continue
            write_heading(pdf, level, text)
        elif kind == "para":
            # skip the confidential banner quote (it's on the cover already)
            if "CONFIDENTIAL" in payload and "Do not distribute" in payload:
                continue
            write_para(pdf, payload)
        elif kind == "code":
            write_code(pdf, payload)
        elif kind == "list":
            ordered, items = payload
            write_bullets(pdf, items, ordered)
        elif kind == "quote":
            if any("CONFIDENTIAL" in l for l in payload):
                continue
            write_quote(pdf, payload)
        elif kind == "table":
            write_table(pdf, payload)
        elif kind == "img":
            alt, path = payload
            if os.path.exists(path):
                if pdf.get_y() > 190:
                    pdf.add_page()
                w = pdf.w - pdf.l_margin - pdf.r_margin
                pdf.image(path, x=pdf.l_margin, w=w)
                pdf.ln(3)
                pdf.set_font("DVS", "I", 8.5)
                pdf.set_text_color(*MUTED)
                pdf.multi_cell(0, 5, alt, align="C")
                pdf.ln(4)
        elif kind == "hr":
            pdf.ln(2)
            pdf.set_draw_color(*RULE)
            y = pdf.get_y()
            pdf.line(pdf.l_margin, y, pdf.w - pdf.r_margin, y)
            pdf.ln(6)
    out = os.path.join(OUTDIR, pdf_name)
    pdf.output(out)
    print("wrote", out, f"({os.path.getsize(out)//1024} KB)")


def main():
    os.makedirs(OUTDIR, exist_ok=True)
    for md_rel, pdf_name, subtitle in DOCS:
        build(os.path.join(REPO, md_rel), pdf_name, subtitle)


if __name__ == "__main__":
    sys.exit(main())
