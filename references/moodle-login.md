# Per-User Moodle Login (HKU)

HKU Moodle is CAS-only: posting your portal password to `/login/token.php`
returns `invalidlogin`. Use the mobile-app launch flow instead. Each user keeps
their own token in their own `moodle-sync/config.json` (`chmod 600`).

Two files — do not merge them:

| File | Owner | Purpose |
|---|---|---|
| `<vault>/moodle-mirror.json` | mirror (`scripts/mirror.py`) | paths + `mappings` + `downloader` (copy from `config.template.json`) |
| `moodle-sync/config.json` | moodle-dl | `moodle_domain`, `moodle_path`, `download_course_ids`, `token` |

## Recommended full-credential flow (native, preferred)

For the complete credential (ws token + `privatetoken` for cookie-based
downloads), use moodle-dl itself — this is the only path that stores both:

```bash
cd <VAULT>/moodle-sync && moodle-dl --init --sso
# rotate later: moodle-dl --new-token --sso
```

`scripts/save_token.py` below is a fallback that stores **only** the ws token
(it preserves an existing `privatetoken` but never writes one). If your
dl config has `download_also_with_cookie=true` without `privatetoken`,
`doctor` warns and cookie downloads will silently fail — re-run `--new-token --sso`.

## Where to keep the cache (informed choice)

Default layout keeps `moodle-sync/` (cache + credentials) inside the vault for
one-folder portability. If your vault is a git repo or cloud-synced, prefer
pointing `source_root` outside the vault (e.g. `~/moodle-cache`) and only the
`99 Moodle Mirror/` results live in the vault: `doctor` flags a git-tracked
vault with an inside cache and tells you the exact `.gitignore` line.

## Fallback: token-only capture (HKU)

1. `pip install moodle-dl` (or `uv tool install moodle-dl`). Find it: `command -v moodle-dl`.
2. Mirror config: copy `config.template.json` → `<vault>/moodle-mirror.json`,
   fill `mappings`, set `downloader` (or empty for sync-only).
3. Download config: `mkdir -p moodle-sync && cd moodle-sync && moodle-dl --init`
   — creates the dir if missing; sets domain and `download_course_ids`
   (IDs from the Moodle course URL or `mcp_query.py courses`).
4. Log in to `https://moodle.hku.hk` in a controlled Chrome you own.
5. Visit:
   `https://moodle.hku.hk/admin/tool/mobile/launch.php?service=moodle_mobile_app&passport=12345&urlscheme=moodledl`
6. Chrome reports `ERR_ABORTED` — this IS the success signal (custom scheme).
7. Open DevTools → Network, find the `moodledl://token=<base64>` request.
8. Run (from any directory; `<SKILL_DIR>` = skill repo dir, `<VAULT>` = vault root):
   `python3 "<SKILL_DIR>/scripts/save_token.py" --config <VAULT>/moodle-sync/config.json --url 'moodledl://token=<base64>'`
   Prefer stdin (`--b64-stdin`) so the secret never lands in shell history.
9. `python3 "<SKILL_DIR>/scripts/mirror.py" --config <VAULT>/moodle-mirror.json doctor`

## Rules

- Never paste anyone else's token; never commit either config.
- Token expiry / password change → repeat steps 4–8.
- The skill never uploads the token anywhere; MCP reuses the same file.
