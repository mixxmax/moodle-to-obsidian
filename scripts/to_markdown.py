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
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
from datetime import datetime
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
EXTS = {".docx", ".pptx", ".doc", ".rtf", ".ppt"}
LEGACY_EXTS = {".doc", ".rtf", ".ppt"}

FRONT_RE = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)

# Ownership evidence for pre-fingerprint companions: our generator always
# emits this boilerplate line. A same-name md WITHOUT it is a user file.
GENERATOR_MARKER = "自动转换为 Markdown"
ORIGINAL_MARKER = "原件格式"


def enc(path_frag):
    return quote(path_frag)


def sha12_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()[:12]


def sha12_text(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def parse_frontmatter(text):
    """Our own frontmatter -> dict, or None if absent/unparseable."""
    m = FRONT_RE.match(text)
    if not m:
        return None
    out = {}
    for line in m.group(1).splitlines():
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        out[k.strip()] = v.strip()
    return out


def body_of(text):
    m = FRONT_RE.match(text)
    return text[m.end():] if m else text


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
    """.doc / .rtf / .ppt via textutil (macOS). Raises RuntimeError when the
    converter itself is unavailable so the caller writes a stub instead."""
    if shutil.which("textutil") is None:
        raise RuntimeError("textutil not found (macOS only for .doc/.rtf/.ppt)")
    try:
        txt = subprocess.run(["textutil", "-convert", "txt", "-stdout", path],
                             capture_output=True, text=True, timeout=120).stdout
    except Exception as e:
        raise RuntimeError(f"textutil failed: {e}") from e
    lines = []
    for ln in txt.splitlines():
        c = clean(ln)
        if c:
            lines.append(c)
            lines.append("")
    return lines


def build_text(f, ext, body, source_sha, complete):
    safe = f.replace("[", "").replace("]", "")
    head = [
        "---",
        f"source_file: {json.dumps(f, ensure_ascii=False)}",
        f"converted_from: {ext.lower().lstrip('.')}",
        f"source_sha12: {source_sha}",
        f"complete: {'true' if complete else 'false'}",
        "BODY-SHA12-PLACEHOLDER",
        "FILE-SHA12-PLACEHOLDER",
        "---",
        "",
        f"# {os.path.splitext(f)[0]}",
        "",
    ]
    if ext.lower() in (".pptx", ".ppt"):
        head += ["> [!warning] Auto-extracted slide text — layout, images and "
                 "animations may differ. Check the original.", ""]
    head += [
        f"> 由 `{f}` 自动转换为 Markdown，便于在 Obsidian 内阅读与全文检索。"
        f" 原件格式（排版、图片、缩进）以原文为准：[{safe}]({enc(f)})",
        "",
        "---",
        "",
    ]
    text = "\n".join(head + body)
    text = re.sub(r"\n{3,}", "\n\n", text).rstrip() + "\n"
    body_sha = sha12_text(body_of(text))
    text = text.replace("BODY-SHA12-PLACEHOLDER", f"body_sha12: {body_sha}", 1)
    file_sha = sha12_text("".join(
        ln for ln in text.splitlines(keepends=True)
        if not ln.startswith("file_sha12:") and "FILE-SHA12-PLACEHOLDER" not in ln))
    text = text.replace("FILE-SHA12-PLACEHOLDER", f"file_sha12: {file_sha}", 1)
    return text


def _unique_backup(path, suffix):
    """Timestamped backup path; never reuses an existing backup."""
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    cand = f"{path}.{suffix}.{stamp}"
    if not os.path.exists(cand):
        return cand
    i = 1
    while True:
        cand2 = f"{cand}.{i}"
        if not os.path.exists(cand2):
            return cand2
        i += 1


def _fm_source_file(fm):
    """Decode our source_file frontmatter value; None if absent/unparseable."""
    raw = (fm or {}).get("source_file", "").strip()
    if not raw:
        return None
    try:
        return json.loads(raw)
    except ValueError:
        return raw.strip('"')


def _is_legacy_ours(existing, f):
    """Pre-fingerprint md that carries our boilerplate for THIS source file."""
    return (GENERATOR_MARKER in existing and ORIGINAL_MARKER in existing
            and _fm_source_file(parse_frontmatter(existing)) == f)


def _file_sha_ok(existing, fm):
    """True when the file is byte-identical to what we last generated."""
    if not fm:
        return False
    if fm.get("file_sha12"):
        canon = "".join(ln for ln in existing.splitlines(keepends=True)
                         if not ln.startswith("file_sha12:"))
        return sha12_text(canon) == fm["file_sha12"]
    if fm.get("body_sha12"):
        return sha12_text(body_of(existing)) == fm["body_sha12"]
    return False


def convert_source(src, ext):
    """Returns (body_lines, complete_bool). Raises RuntimeError for stub cases."""
    if ext == ".docx":
        if not HAS_DOCX:
            raise RuntimeError("python-docx not installed (pip install python-docx)")
        return convert_docx(src), True
    if ext == ".pptx":
        if not HAS_PPTX:
            raise RuntimeError("python-pptx not installed (pip install python-pptx)")
        return convert_pptx(src), True
    return convert_legacy(src), True


def stub_body(reason):
    return [f"> [!warning] Converter unavailable: {reason}. Open the original file.", ""]


def main(argv=None):
    ap = argparse.ArgumentParser(prog="to_markdown.py",
        description="Generate .md companions next to Office files.")
    ap.add_argument("root", nargs="?", default=".")
    ap.add_argument("--force", action="store_true",
        help="regenerate even user-edited companions (timestamped backup first)")
    ap.add_argument("--adopt-legacy", action="store_true",
        help="one-shot migration: regenerate pre-fingerprint companions that carry "
             "our boilerplate (timestamped .legacybak backup first)")
    ap.add_argument("--dry-run", action="store_true",
        help="report what would change without writing")
    a = ap.parse_args(argv)
    root = os.path.abspath(a.root)
    converted, updated, skipped = 0, 0, 0
    conflicts, failed = [], []
    user_files, legacy_files = [], []
    for dp, dn, fn in os.walk(root):
        dn[:] = [d for d in dn if d not in SKIP_DIRS]
        if any(s in dp for s in SKIP_DIRS):
            continue
        for f in sorted(fn):
            stem, ext = os.path.splitext(f)
            if ext.lower() not in EXTS or f.startswith("~$"):
                continue
            src = os.path.join(dp, f)
            out = os.path.join(dp, stem + ".md")
            source_sha = sha12_file(src)
            if os.path.exists(out):
                with open(out, encoding="utf-8") as fh:
                    existing = fh.read()
                fm = parse_frontmatter(existing)
                if fm and "source_sha12" in fm:
                    if not _file_sha_ok(existing, fm):
                        conflicts.append(os.path.relpath(out, root))
                        if a.force and not a.dry_run:
                            shutil.copy2(out, _unique_backup(out, "localbak"))
                        else:
                            continue
                    elif (fm.get("source_sha12") == source_sha
                            and fm.get("complete", "true") == "true"):
                        skipped += 1
                        continue
                    # else: source changed or stub upgrade -> regenerate
                elif _is_legacy_ours(existing, f):
                    legacy_files.append(os.path.relpath(out, root))
                    if (a.adopt_legacy or a.force) and not a.dry_run:
                        shutil.copy2(out, _unique_backup(out, "legacybak"))
                    else:
                        continue
                else:
                    user_files.append(os.path.relpath(out, root))
                    if a.force and not a.dry_run:
                        shutil.copy2(out, _unique_backup(out, "userbak"))
                    else:
                        skipped += 1
                        continue
                action = "updated"
            else:
                action = "converted"
            try:
                body, complete = convert_source(src, ext.lower())
            except RuntimeError as e:
                body, complete = stub_body(str(e)), False
            except Exception as e:
                failed.append((os.path.relpath(src, root), str(e)[:80]))
                continue
            if not body:
                failed.append((os.path.relpath(src, root), "empty output"))
                continue
            text = build_text(f, ext, body, source_sha, complete)
            if not a.dry_run:
                with open(out, "w", encoding="utf-8") as fh:
                    fh.write(text)
            if action == "updated":
                updated += 1
            else:
                converted += 1

    print("converted:", converted)
    print("updated:", updated)
    print("skipped (up to date):", skipped)
    print("conflicts (user-edited, kept; --force with timestamped backup to overwrite):",
          len(conflicts))
    for p in conflicts:
        print("   =", p)
    if legacy_files:
        print("legacy companions (pre-fingerprint, kept; --adopt-legacy migrates "
              "with timestamped backup):", len(legacy_files))
        for p in legacy_files:
            print("   =", p)
    if user_files:
        print("user-owned .md (not ours, kept; --force with .userbak to overwrite):",
              len(user_files))
        for p in user_files:
            print("   =", p)
    print("failed:", len(failed))
    for p, e in failed:
        print("   !", p, "|", e)


if __name__ == "__main__":
    main()
