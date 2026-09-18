---
name: moodle-to-obsidian
description: "从 Moodle 拉取/下载课件并按课程文件夹整理，也可单独映射进 Obsidian；拉取与映射是两段可分开的功能（可只拉、只映射，或一起跑）。自持登录。用户说 Moodle同步、课件拉取、映射进Obsidian、伴生md 时使用。"
---

# Moodle to Obsidian Skill

Lightweight pipeline: exact mirror, no LLM in the pipe, condense afterwards.

**Product promise:** 课程自动落地，结构不乱；拉取完整性按判据如实报告（ok / 失败阻断 / 未验证），不谎报更新不漏。系统只组织、不解读。

## Path convention (read this first)

- `<SKILL_DIR>` = the directory that contains this SKILL.md (scripts + template live here).
- `<VAULT>` = the absolute path of the user's Obsidian vault.
- `<SOURCE_ROOT>` = the downloader cache dir (moodle-dl's cwd; its `config.json`
  and `running.lock` live here). Default: `<SOURCE_ROOT>` = `<VAULT>/moodle-sync`;
  it may point outside the vault (recommended for git/cloud-synced vaults).
- Every command below is copy-paste runnable from **any** working directory:
  script paths always start with `<SKILL_DIR>/scripts/`, configs always use
  `<VAULT>/...` absolute paths. Never rely on "currently cd'ed where".

## Step 1: Detect environment and auth state

Run detection first, then follow the decision tree:

```
!`command -v moodle-dl && echo MOODLEDL_OK || echo MOODLEDL_MISSING`
!`python3 -c "import docx; print('DOCX_OK')" 2>/dev/null || echo DOCX_MISSING`
!`ls <VAULT>/moodle-mirror.json 2>/dev/null || echo NO_MIRROR_CONFIG`
!`ls <SOURCE_ROOT>/config.json 2>/dev/null || echo NO_DL_CONFIG`
!`ls <SOURCE_ROOT>/running.lock 2>/dev/null && echo LOCKED || echo UNLOCKED`
```

| Observation | Path |
|---|---|
| `NO_MIRROR_CONFIG` or `NO_DL_CONFIG` | Go Step 2 (login + config setup) |
| `MOODLEDL_MISSING` | `pip install moodle-dl` / `uv tool install moodle-dl`, then Step 2. Without it only `sync` works, `run` is unavailable |
| `DOCX_MISSING` | `pip install -r "<SKILL_DIR>/requirements.txt"` (pins); without them companions degrade to link-only stubs (file stays discoverable, content not extracted) |
| `LOCKED` | Stop: `pgrep -fl moodle-dl`, delete `running.lock` only if no process |

Two config files, two owners (do not merge):

| File | Owner | Keys |
|---|---|---|
| `moodle-mirror.json` (vault root, copy from `config.template.json`) | mirror (`scripts/mirror.py`) | `source_root`, `vault_root`, `mappings`, `downloader` |
| `<SOURCE_ROOT>/config.json` (`chmod 600`) | moodle-dl downloader | `moodle_domain`, `moodle_path`, `download_course_ids`, `token` |

Defaults: `vault_root` = current Obsidian vault; `source_root` = `<SOURCE_ROOT>` (default `<vault>/moodle-sync`); `mirror_folder` = `99 Moodle Mirror`; `state_dir` = `<source>/.moodle-local-sync`.

## Step 2: Set up per-user login (user-owned credential)

Never use anyone else's token. Each user owns `<SOURCE_ROOT>/config.json` (`chmod 600`).

1. Mirror config: copy `<SKILL_DIR>/config.template.json` → `<VAULT>/moodle-mirror.json`, fill `mappings` (course code → vault folder; replace the example entries). Set `downloader` to your moodle-dl path (or empty for sync-only mode).
2. Download config: `mkdir -p <SOURCE_ROOT> && cd <SOURCE_ROOT> && moodle-dl --init` (sets `moodle_domain`, `download_course_ids`). Course IDs come from the Moodle course page URL or `mcp_query.py courses`.
3. Get token via controlled browser (HKU is CAS-only, password API fails):
   login Moodle → visit `https://<domain>/admin/tool/mobile/launch.php?service=moodle_mobile_app&passport=12345&urlscheme=moodledl` → browser shows `ERR_ABORTED` = success → read `moodledl://token=<base64>` from Network → run:
   `python3 "<SKILL_DIR>/scripts/save_token.py" --config <SOURCE_ROOT>/config.json --url 'moodledl://token=...'`
   (writes only `token`, preserves the rest; never prints it).
   Detail: `references/moodle-login.md`.
4. `python3 "<SKILL_DIR>/scripts/mirror.py" --config <VAULT>/moodle-mirror.json doctor`

Gate: `doctor` must report sync ready before any sync. It separately reports
`run READY` / `run NOT READY` (downloader + dl-config preconditions); a NOT READY
run means use `sync` until fixed.

## Step 3: Mirror exactly (no restructuring)

```bash
python3 "<SKILL_DIR>/scripts/mirror.py" --config <VAULT>/moodle-mirror.json run    # pull (needs downloader) + mirror
python3 "<SKILL_DIR>/scripts/mirror.py" --config <VAULT>/moodle-mirror.json sync   # mirror existing snapshot only
python3 "<SKILL_DIR>/scripts/mirror.py" --config <VAULT>/moodle-mirror.json status
```

Pull verdicts (printed, never silent): `ok` → mirror proceeds; `failed`
(rc != 0 or failure signals in pull output) → mirror blocked, nothing stamped;
`unverified` (downloader version outside pinned moodle-dl 2.3.x) → mirror
proceeds with an explicit completeness caveat in terminal + changelog.

Rules: native tree kept, add/update in place, withdrawn kept and marked, local edits shelved to `state_dir/conflicts/` (mirror stays `.bak`-free), every run appends changelog. Never let LLM rename or reorganise this layer.

## Step 4: Generate md companions (docx must, pdf must-not)

```bash
python3 "<SKILL_DIR>/scripts/to_markdown.py" "<VAULT>/<Course Folder>"
```

Rules: one `.md` per source alongside it, frontmatter records source, top links back; docx headings/tables preserved (link-only stub if python-docx missing); pptx per-slide sections always carry a downgrade warning; PDF untouched (Obsidian renders it); link hygiene: label strips `[]`, target percent-encoded. Freshness is fingerprint-driven: source changed → auto-update; user-edited → conflict kept (`--force` overwrites with backup); `--dry-run` previews. Detail: `references/companion-rules.md`.

## Step 5: Optional progress layer via moodle-mcp (read-only)

Shares the same user token from `<SOURCE_ROOT>/config.json`, never stores a second copy:

```
!`python3 "<SKILL_DIR>/scripts/mcp_query.py" --config <SOURCE_ROOT>/config.json deadlines 2>/dev/null || echo MCP_FAILED`
```

Without `--mcp-dir` the shim is a dry-run planner (verifies token, prints the exact call). With `--mcp-dir /path/to/moodle-mcp` it executes and prints JSON:

```bash
python3 "<SKILL_DIR>/scripts/mcp_query.py" --config <SOURCE_ROOT>/config.json briefing --mcp-dir /path/to/moodle-mcp
```

Tools: `assignments/deadlines/grades/progress/health/dashboard/briefing/courses/...`. Only on demand, never daemonised. Detail: `references/moodle-mcp.md`.

## Step 6 (optional): Advanced note structuring — only if user asks

**Not part of the default sync pipeline.** Skip unless the user explicitly wants
condensation / five-principles / structured topic cards.

If asked: after mirror + companions exist, read `references/five-principles.md`
(universal labels; rename per subject). Other frameworks are fine too — this is
one optional method, not required.

Gate: propose patch → user confirms → write; never invent sources from general knowledge.

## Step 7: Respond with structured output (user guidance — required)

After every `doctor` / `run` / `sync` / companion step, reply in this shape
(mirror.py already prints a similar block — paraphrase it for the user, do not omit paths):

```text
✅/❌/⚠️ 本轮：①拉取 / ②映射 / ①+② / 伴生md / 自检 — 成功、失败或映射成功（拉取未验证）
📁 缓存（①）：<absolute or vault-relative moodle-sync/>
📁 笔记库根：<vault_root>
📁 已进库镜像（②）：各课 <Course>/99 Moodle Mirror/ （列出本轮扫到的课）
📝 更新记录：Moodle Sync Updates.md
📊 计数：+added · ~updated · restored · withdrawn · conflicted · adopted（已有认领）[· SKIPPED-SYMLINK xN]
👉 下一步：<一条可执行建议>
```

Next-step picker (use the first that matches):

| 情况 | 👉 下一步 |
|---|---|
| pull 失败 / 无 downloader | 修好 token 与 course_ids 再 `run`；或改用 `sync` 只映射 |
| UNMAPPED 课号 | 写入 `mappings` 后再 `sync` |
| conflicted > 0 | 在更新记录里找 `state:conflicts/` 对应备份，对比本地修改 |
| 本轮有新增/更新 | 在 Obsidian 打开 `99 Moodle Mirror`；需要可搜再说「生成伴生 md」 |
| 本轮无变化 | 有新课件再 `run`；只重映缓存则 `sync` |
| doctor：sync ready + run READY | 可 `run`（①+②）或 `sync`（只②） |
| doctor：sync ready，但 run NOT READY | 先按 NOT READY 原因修 run 前提；当前只能 `sync` |
| doctor 失败 | 按 ISSUE 改配置后再 doctor |

Also include when relevant: companion md counts; (only if asked) MCP summary.  
Do **not** push five-principles / condensation unless the user asked.

## Reference Files

- `references/moodle-login.md` — per-user token capture, storage, expiry
- `references/companion-rules.md` — conversion fidelity + link hygiene
- `references/five-principles.md` — optional note-structuring method (skip unless asked)
- `references/moodle-mcp.md` — read-only progress queries
- `references/troubleshooting.md` — lock/permission/duplicate/missing
- `config.template.json` — mappings + paths, no secrets
