# Companion Rules (md伴生)

One `.md` per source file, written alongside it. Original never modified.

- **docx must convert**: heading styles → `#/##/###`, tables → GFM tables, lists kept.
- **pdf must NOT convert**: Obsidian renders it natively; layout is the content.
- **pptx best-effort**: one `## Slide N — title` section each, keep speaker notes as
  `> [!note]`, add
  `> [!warning] Auto-extracted slide text — layout, images and animations may differ. Check the original.`
  at top.
- Frontmatter: `source_file`, `converted_from`; body header links back to original.
- **Link hygiene** (measured 2026-09-06): Obsidian ignores `\[` escapes and nested
  `[]` in link text → strip `[`/`]` from label; percent-encode target (`%5B/%5D` ok).
  Also encode stray `)` via `urllib.parse.quote(safe="/-_.~")`.
- Skip dirs: `98 Duplicates`, `00 Derived Materials`, `.moodle-local-sync`.
- Never overwrite an existing `.md` (reports `skipped`); delete it explicitly to reconvert.
