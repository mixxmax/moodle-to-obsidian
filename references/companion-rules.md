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
- Freshness is fingerprint-driven (`source_sha12`/`body_sha12` in frontmatter):
  source changed + md untouched → auto-update (`updated`); md user-edited →
  conflict, kept, `--force` rewrites with `.md.localbak`; same-name hand-written
  md (no fingerprint) is never touched (`--force` backs it to `.md.userbak`).
- Missing converter (no python-docx/pptx, no textutil) writes a link-only stub
  (`complete: false`); rerunning after install upgrades it in place.
- Flags: `--force`, `--dry-run`.
