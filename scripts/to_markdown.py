#!/usr/bin/env python3
"""Convert Office files under a course folder to Markdown companions.

One .md per source file, written alongside it, so everything is readable
inside Obsidian without leaving the app. Structure is preserved where the
source carries it: docx heading styles become headings, docx tables become
Markdown tables, pptx slides become sections (text-only, flagged as degraded).

The original file is never modified. Each .md links back to its source.
If python-docx/python-pptx is missing, a link-only stub is written instead
of crashing, so the file stays discoverable.
"""
import os
import re
import subprocess
import sys
from urllib.parse import quote

try:
    import docx
    from docx.table import Table
    from docx.text.paragraph import Paragraph
    HAS_DOCX = True
except ImportError:
    HAS_DOCX = False

try:
    from pptx import Presentation
    HAS_PPTX = True
except ImportError:
    HAS_PPTX = False

SKIP_DIRS = {"98 Duplicates", "00 Derived Materials", ".moodle-local-sync"}
DEFAULT_ROOT = sys.argv[1] if len(sys.argv) > 1 else "."
ROOT = os.path.abspath(DEFAULT_ROOT)
EXTS = {".docx", ".pptx", ".doc", ".rtf", ".ppt"}


def enc(path_frag):
    return quote(path_frag)


def clean(text):
    text = text.replace("\u00a0", " ").replace("\x0b", " ")
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


def esc_cell(text):
    return clean(text).replace("|", "\\|").replace("\n", " ")


def iter_block_items(parent):
    """Yield paragraphs and tables in document order."""
    body = parent.element.body
    for child in body.iterchildren():
        if child.tag.endswith("}p"):
            yield Paragraph(child, parent)
        elif child.tag.endswith("}tbl"):
            yield Table(child, parent)


def table_to_md(tbl):
    rows = []
    for row in tbl.rows:
        rows.append([esc_cell(c.text) for c in row.cells])
    if not rows:
        return []
    width = max(len(r) for r in rows)
    rows = [r + [""] * (width - len(r)) for r in rows]
    # drop fully empty rows
    rows = [r for r in rows if any(c for c in r)]
    if not rows:
        return []
    out = ["| " + " | ".join(rows[0]) + " |",
           "|" + "|".join([" --- "] * width) + "|"]
    for r in rows[1:]:
        out.append("| " + " | ".join(r) + " |")
    out.append("")
    return out


def style_prefix(p):
    name = (p.style.name or "").lower()
    if name.startswith("heading"):
        m = re.search(r"(\d)", name)
        lvl = int(m.group(1)) if m else 2
        return "#" * min(lvl + 1, 6) + " "
    if name.startswith("title"):
        return "## "
    if "list" in name or p.style.name in ("List Paragraph",):
        return "- "
    return ""


def convert_docx(path):
    d = docx.Document(path)
    lines = []
    for block in iter_block_items(d):
        if isinstance(block, Table):
            lines.extend(table_to_md(block))
            continue
        txt = clean(block.text)
        if not txt:
            continue
        pre = style_prefix(block)
        if pre.startswith("#"):
            lines.append("")
            lines.append(pre + txt)
            lines.append("")
        else:
            lines.append(pre + txt if pre else txt)
            lines.append("")
    return lines


def convert_pptx(path):
    prs = Presentation(path)
    lines = []
    for i, slide in enumerate(prs.slides, 1):
        title = ""
        try:
            if slide.shapes.title is not None:
                title = clean(slide.shapes.title.text)
        except Exception:
            pass
        lines.append("")
        lines.append(f"## Slide {i}" + (f" — {title}" if title else ""))
        lines.append("")
        for shape in slide.shapes:
            if shape == getattr(slide.shapes, "title", None):
                continue
            if shape.has_table:
                lines.extend(pptx_table_to_md(shape.table))
                continue
            if not shape.has_text_frame:
                continue
            for para in shape.text_frame.paragraphs:
                txt = clean("".join(r.text for r in para.runs))
                if not txt or txt == title:
                    continue
                indent = "  " * max(0, para.level)
                lines.append(f"{indent}- {txt}")
        if slide.has_notes_slide:
            note = clean(slide.notes_slide.notes_text_frame.text)
            if note:
                lines.append("")
                lines.append("> [!note] Speaker notes")
                for ln in note.splitlines():
                    if clean(ln):
                        lines.append("> " + clean(ln))
        lines.append("")
    return lines


def pptx_table_to_md(tbl):
    rows = [[esc_cell(c.text) for c in row.cells] for row in tbl.rows]
    rows = [r for r in rows if any(c for c in r)]
    if not rows:
        return []
    width = max(len(r) for r in rows)
    rows = [r + [""] * (width - len(r)) for r in rows]
    out = ["", "| " + " | ".join(rows[0]) + " |",
           "|" + "|".join([" --- "] * width) + "|"]
    for r in rows[1:]:
        out.append("| " + " | ".join(r) + " |")
    out.append("")
    return out


def convert_legacy(path):
    """.doc / .rtf / .ppt via textutil."""
    try:
        txt = subprocess.run(["textutil", "-convert", "txt", "-stdout", path],
                             capture_output=True, text=True, timeout=120).stdout
    except Exception:
        return []
    lines = []
    for ln in txt.splitlines():
        c = clean(ln)
        if c:
            lines.append(c)
            lines.append("")
    return lines


def main():
    converted, failed, skipped = 0, [], 0
    for dp, dn, fn in os.walk(ROOT):
        dn[:] = [d for d in dn if d not in SKIP_DIRS]
        if any(s in dp for s in SKIP_DIRS):
            continue
        for f in sorted(fn):
            stem, ext = os.path.splitext(f)
            if ext.lower() not in EXTS or f.startswith("~$"):
                continue
            src = os.path.join(dp, f)
            out = os.path.join(dp, stem + ".md")
            if os.path.exists(out):
                skipped += 1
                continue
            degraded = False
            try:
                if ext.lower() == ".docx":
                    if not HAS_DOCX:
                        raise RuntimeError("python-docx not installed (pip install python-docx)")
                    body = convert_docx(src)
                elif ext.lower() == ".pptx":
                    if not HAS_PPTX:
                        raise RuntimeError("python-pptx not installed (pip install python-pptx)")
                    body = convert_pptx(src)
                else:
                    body = convert_legacy(src)
            except RuntimeError as e:
                body = [f"> [!warning] Converter unavailable: {e}. Open the original file.", ""]
                degraded = True
            except Exception as e:
                failed.append((os.path.relpath(src, ROOT), str(e)[:80]))
                continue
            if not body:
                failed.append((os.path.relpath(src, ROOT), "empty output"))
                continue

            # Obsidian does NOT recognize escaped brackets (\\[ \\]) in link
            # TEXT — strip them from the display name instead; the URL keeps
            # percent-encoded %5B %5D (verified working by user test 2026-09-06)
            safe = f.replace("[", "").replace("]", "")
            head = [
                "---",
                f'source_file: "{f}"',
                f"converted_from: {ext.lower().lstrip('.')}",
                "---",
                "",
                f"# {stem}",
                "",
            ]
            if ext.lower() in (".pptx", ".ppt"):
                head += ["> [!warning] Auto-extracted slide text — layout, images and animations may differ. Check the original.", ""]
            if degraded:
                pass  # body already carries the converter-unavailable warning
            head += [
                f"> 由 `{f}` 自动转换为 Markdown，便于在 Obsidian 内阅读与全文检索。"
                f" 原件格式（排版、图片、缩进）以原文为准：[{safe}]({enc(f)})",
                "",
                "---",
                "",
            ]
            # collapse runs of blank lines
            text = "\n".join(head + body)
            text = re.sub(r"\n{3,}", "\n\n", text).rstrip() + "\n"
            with open(out, "w", encoding="utf-8") as fh:
                fh.write(text)
            converted += 1

    print("converted:", converted)
    print("skipped (md already there):", skipped)
    print("failed:", len(failed))
    for p, e in failed:
        print("   !", p, "|", e)


if __name__ == "__main__":
    main()
