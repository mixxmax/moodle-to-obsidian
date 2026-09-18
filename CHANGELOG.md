# Changelog

## v1.0.0 (2026-09-19)

First distributable release. Tested: 69 pytest green, ruff clean,
compileall clean on 3.9/3.11. Requires moodle-dl 2.3.x (signal patterns
pinned to it; other versions run as explicitly-marked unverified).

### Pull that cannot lie (P0)

- `run` classifies pull outcome as ok / failed / unverified (dropped `-q`;
  failure signals matched against moodle-dl 2.3.x output). Failed pulls
  never touch mirror, manifest, changelog or success stamp.
- `run` enforces the download-config gate before pulling; `doctor` reports
  `sync ready` separately from `run READY / NOT READY`.
- Honest status model: `success / recovered / incomplete / unverified` in
  `last-run.json`; `last_successful_sync` advances only on fully verified runs.

### Course identity (P0)

- Mapping keys accept course codes (`LAWS1234`) or literal source folder
  names (`Public Law Week 1`); value `null` = explicitly ignored.
- Unmapped / duplicated / unrecognized / vanished courses mark the run
  `incomplete` (no stamp) instead of false success; vanished courses are
  retained, never auto-withdrawn.
- Internal dirs (`state_dir`, `misc_files_path` override) are excluded from
  the course scan, so the default layout stays green.

### Data integrity (P1)

- Corrupt manifest is renamed aside and rebuilt visibly (adopted counts in
  terminal + changelog); schema violations (incl. per-file records) raise
  actionable errors without tracebacks; `status` validates its schema.
- Conflict backups moved out of the mirror tree into
  `state_dir/conflicts/` (`doctor --prune-conflicts N` to clean).
- `save_token.py` keeps its token-only contract (cleansed, mode 600,
  preserves `privatetoken`), gains `--b64-stdin` and `--verify` against the
  installed moodle-dl parser; native `--init --sso` documented as primary.
- Effective `download_path` / `misc_files_path` overrides honored for scan
  root, lock file and overlap guards.

### Companions (P1)

- Fingerprint-driven freshness (`source_sha12` / `body_sha12` /
  `file_sha12`): source changes auto-update, user edits conflict safely,
  hand-written same-name files untouched, `--force` / `--dry-run` /
  `--adopt-legacy` (timestamped backups), missing-converter stubs that
  upgrade after install.

### Quality (M3)

- 69 tests, ruff (E,F,I,UP,B,SIM) clean, CI matrix 3.9/3.11/13,
  `requirements.txt` pins, classified exceptions with per-branch next steps,
  `--log-file` / `--verbose` diagnostics, `status --json --events N`.
