---
name: moodle-to-obsidian
description: "把 Moodle 课件按原生目录结构同步进 Obsidian（拉取+映射、自持登录、docx 伴生）。在用户说 Moodle同步到Obsidian、moodle mirror、课件落库、伴生md 时使用。"
---

# Moodle to Obsidian Skill

Lightweight pipeline: exact mirror, no LLM in the pipe, condense afterwards.

**Product promise:** 课程自动落地，结构不乱，更新不漏。系统只组织、不解读。

## Step 1: Detect environment and auth state

Run detection first, then follow the decision tree:

```
!`command -v moodle-dl && echo MOODLEDL_OK || echo MOODLEDL_MISSING`
!`python3 -c "import docx; print('DOCX_OK')" 2>/dev/null || echo DOCX_MISSING`
!`ls moodle-mirror.json 2>/dev/null || echo NO_MIRROR_CONFIG`
!`ls moodle-sync/config.json 2>/dev/null || echo NO_DL_CONFIG`
!`ls moodle-sync/running.lock 2>/dev/null && echo LOCKED || echo UNLOCKED`
```

| Observation | Path |
|---|---|
| `NO_MIRROR_CONFIG` or `NO_DL_CONFIG` | Go Step 2 (login + config setup) |
| `MOODLEDL_MISSING` | `pip install moodle-dl` / `uv tool install moodle-dl`, then Step 2. Without it only `sync` works, `run` is unavailable |
| `DOCX_MISSING` | `pip install python-docx python-pptx`; without them companions degrade to link-only stubs (file stays discoverable, content not extracted) |
| `LOCKED` | Stop: `pgrep -fl moodle-dl`, delete `running.lock` only if no process |

Two config files, two owners (do not merge):

| File | Owner | Keys |
|---|---|---|
| `moodle-mirror.json` (vault root, copy from `config.template.json`) | mirror (`scripts/mirror.py`) | `source_root`, `vault_root`, `mappings`, `downloader` |
| `moodle-sync/config.json` (`chmod 600`) | moodle-dl downloader | `moodle_domain`, `moodle_path`, `download_course_ids`, `token` |

Defaults: `vault_root` = current Obsidian vault; `source_root` = `<vault>/moodle-sync`; `mirror_folder` = `99 Moodle Mirror`; `state_dir` = `<source>/.moodle-local-sync`.

## Step 2: Set up per-user login (user-owned credential)

Never use anyone else's token. Each user owns `moodle-sync/config.json` (`chmod 600`).

1. Mirror config: copy `config.template.json` → `<vault>/moodle-mirror.json`, fill `mappings` (course code → vault folder; replace the example entries). Set `downloader` to your moodle-dl path (or empty for sync-only mode).
2. Download config: `mkdir -p moodle-sync && cd moodle-sync && moodle-dl --init` (creates the dir if missing; sets `moodle_domain`, `download_course_ids`). Course IDs come from the Moodle course page URL or `mcp_query.py courses`.
3. Get token via controlled browser (HKU is CAS-only, password API fails):
   login Moodle → visit `https://<domain>/admin/tool/mobile/launch.php?service=moodle_mobile_app&passport=12345&urlscheme=moodledl` → browser shows `ERR_ABORTED` = success → read `moodledl://token=<base64>` from Network → run:
   `python3 scripts/save_token.py --config moodle-sync/config.json --url 'moodledl://token=...'`
   (writes only `token`, preserves the rest; never prints it).
   Detail: `references/moodle-login.md`.
4. `python3 scripts/mirror.py --config moodle-mirror.json doctor`

Gate: `doctor` must print OK before any sync. `run` additionally needs `downloader` set + moodle-dl configured; otherwise use `sync`.

## Step 3: Mirror exactly (no restructuring)

```bash
python3 scripts/mirror.py --config moodle-mirror.json run    # pull (needs downloader) + mirror
python3 scripts/mirror.py --config moodle-mirror.json sync   # mirror existing snapshot only
python3 scripts/mirror.py --config moodle-mirror.json status
```

Rules: native tree kept, add/update in place, withdrawn kept and marked, local edits backed up to `*.local-edit.bak`, every run appends changelog. Never let LLM rename or reorganise this layer.

## Step 4: Generate md companions (docx must, pdf must-not)

```bash
python3 scripts/to_markdown.py "<vault>/<Course Folder>"
```

Rules: one `.md` per source alongside it, frontmatter records source, top links back; docx headings/tables preserved (link-only stub if python-docx missing); pptx per-slide sections always carry a downgrade warning; PDF untouched (Obsidian renders it); link hygiene: label strips `[]`, target percent-encoded. Detail: `references/companion-rules.md`.

## Step 5: Optional progress layer via moodle-mcp (read-only)

Shares the same user token from `moodle-sync/config.json`, never stores a second copy:

```
!`python3 scripts/mcp_query.py --config moodle-sync/config.json deadlines 2>/dev/null || echo MCP_FAILED`
```

Without `--mcp-dir` the shim is a dry-run planner (verifies token, prints the exact call). With `--mcp-dir /path/to/moodle-mcp` it executes and prints JSON:

```bash
python3 scripts/mcp_query.py --config moodle-sync/config.json briefing --mcp-dir /path/to/moodle-mcp
```

Tools: `assignments/deadlines/grades/progress/health/dashboard/briefing/courses/...`. Only on demand, never daemonised. Detail: `references/moodle-mcp.md`.

## Step 6 (optional): Advanced note structuring — only if user asks

**Not part of the default sync pipeline.** Skip unless the user explicitly wants
condensation / five-principles / structured topic cards.

If asked: after mirror + companions exist, read `references/five-principles.md`
(universal labels; rename per subject). Other frameworks are fine too — this is
one optional method, not required.

Gate: propose patch → user confirms → write; never invent sources from general knowledge.

## Step 7: Respond with structured output

1. Synced courses + Added/Updated/Withdrawn/Conflicted counts
2. Companion md converted/skipped/failed counts
3. (If asked) MCP summary: overdue, due this week, grades changed
4. Links to per-course `Moodle Mirror Index.md` and changelog
5. Next action (e.g. fix unmapped course; only mention condensation if user asked)

## Reference Files

- `references/moodle-login.md` — per-user token capture, storage, expiry
- `references/companion-rules.md` — conversion fidelity + link hygiene
- `references/five-principles.md` — optional note-structuring method (skip unless asked)
- `references/moodle-mcp.md` — read-only progress queries
- `references/troubleshooting.md` — lock/permission/duplicate/missing
- `config.template.json` — mappings + paths, no secrets
