# Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `running.lock` / "already running" | killed moodle-dl left lock | `pgrep -fl moodle-dl`; delete lock only if none running |
| `invalidlogin` on token.php | HKU CAS-only | use mobile launch flow (`references/moodle-login.md`) |
| `Operation not permitted` on Desktop | macOS privacy | Settings → Full Disk Access for terminal/python, reload launchd, run `doctor` |
| `UNMAPPED <folder>` | new course code | add row to `mappings` in `moodle-mirror.json`, rerun `sync` |
| `DUPLICATE <code>` skipped | two source folders, one code | keep one, move other out of source_root, rerun |
| `*.local-edit.bak` appears | mirror file hand-edited + remote changed | yours kept in `.bak`, mirror updated; merge by hand |
| withdrawn grows | teacher removed files | intended: local kept, index lists under Retained |
| links broken in Obsidian | `[]` in label | reconvert: labels strip brackets, targets encoded |
| token expired | password change / term rollover | repeat login flow, `save_token.py`, `doctor` |
| `run`: no downloader / pull failed | `downloader` empty or moodle-dl unconfigured | set `downloader` to `command -v moodle-dl`; run `moodle-dl --init` in `moodle-sync/`; or use `sync` |
| `destinations ... collide` | two codes → same folder | one folder per course in `mappings` |
| `must not overlap source_root` | mapping inside `moodle-sync/` | destinations must be vault folders outside the download dir |
| pptx md carries warning callout | intended (text-only extraction) | open original for layout/images |
