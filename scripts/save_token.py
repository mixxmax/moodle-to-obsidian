#!/usr/bin/env python3
"""Save per-user Moodle token into moodle-dl's config (moodle-sync/config.json).
That file belongs to moodle-dl (keys: moodle_domain, moodle_path,
download_course_ids, token); this script only sets 'token' and preserves
everything else. Never prints the token.

Setup order: run 'moodle-dl --init' inside moodle-sync/ first (creates the
file with domain + course IDs), then save the token here.

Usage:
  python3 save_token.py --config moodle-sync/config.json --url 'moodledl://token=<base64>'
  python3 save_token.py --config moodle-sync/config.json --b64 '<base64>'
The base64 decodes to '<id>:::<token>[:::<privatetoken>]'. Only the token part
is stored. File is chmod 600 after write.
"""
import argparse, base64, json, os
from pathlib import Path

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--url", default="")
    ap.add_argument("--b64", default="")
    a = ap.parse_args()
    b64 = a.b64 or (a.url.split("token=", 1)[1].strip() if "token=" in a.url else "")
    if not b64:
        print("need --url 'moodledl://token=...' or --b64 ...", flush=True); return 2
    try:
        raw = base64.b64decode(b64.strip()).decode("utf-8", "replace")
    except Exception:
        print("bad base64", flush=True); return 2
    parts = raw.split(":::")
    token = parts[1] if len(parts) >= 2 else parts[0]
    if len(token) < 8:
        print("decoded token looks invalid", flush=True); return 2
    cp = Path(a.config).expanduser()
    cfg = json.loads(cp.read_text(encoding="utf-8")) if cp.exists() else {}
    cfg["token"] = token
    cp.parent.mkdir(parents=True, exist_ok=True)
    cp.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    try: os.chmod(cp, 0o600)
    except OSError: pass
    print(f"saved to {cp} (chmod 600). Token NOT printed.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
