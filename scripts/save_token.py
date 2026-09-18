#!/usr/bin/env python3
"""Save per-user Moodle token into moodle-dl's config (moodle-sync/config.json).
That file belongs to moodle-dl (keys: moodle_domain, moodle_path,
download_course_ids, token, privatetoken); this script only sets 'token' and
preserves everything else (including an existing privatetoken). Never prints
the token.

Contract (deliberate): the third segment (privatetoken, needed for
cookie-based downloads) is NOT written by this script. Get the complete
credential via the native flow instead:

    cd <vault>/moodle-sync && moodle-dl --init --sso
    # or, to rotate only the token:
    moodle-dl --new-token --sso

Setup order: run 'moodle-dl --init' inside moodle-sync/ first (creates the
file with domain + course IDs), then save the token here.

Usage:
  python3 save_token.py --config moodle-sync/config.json --url 'moodledl://token=<base64>'
  python3 save_token.py --config moodle-sync/config.json --b64 '<base64>'
  echo '<base64>' | python3 save_token.py --config moodle-sync/config.json --b64-stdin
The base64 decodes to '<id>:::<token>[:::<privatetoken>]'. Only the token part
is stored (cleaned to [A-Za-z0-9] like upstream). File is chmod 600 after write.
"""
import argparse, base64, json, os, re, sys
from pathlib import Path

_TOKEN_CLEAN = re.compile(r"[^A-Za-z0-9]+")


def _clean(token: str) -> str:
    return _TOKEN_CLEAN.sub("", token)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--url", default="")
    ap.add_argument("--b64", default="")
    ap.add_argument("--b64-stdin", action="store_true",
                    help="read the base64 (or full moodledl:// URL) from stdin; "
                         "keeps secrets out of shell history and -b64")
    a = ap.parse_args(argv)
    if a.b64_stdin:
        b64 = sys.stdin.read().strip()
        if "token=" in b64:
            b64 = b64.split("token=", 1)[1].strip()
    else:
        b64 = a.b64 or (a.url.split("token=", 1)[1].strip() if "token=" in a.url else "")
    if not b64:
        print("need --url 'moodledl://token=...' or --b64 ... or --b64-stdin", flush=True)
        return 2
    try:
        raw = base64.b64decode(b64.strip()).decode("utf-8", "replace")
    except Exception:
        print("bad base64", flush=True); return 2
    parts = raw.split(":::")
    if len(parts) < 2:
        print("decoded payload unexpected (want '<id>:::<token>[:::<privatetoken>]')",
              flush=True)
        return 2
    token = _clean(parts[1])
    if len(token) < 8:
        print("decoded token looks invalid", flush=True); return 2
    if len(parts) > 2:
        print("note: payload carries a privatetoken segment; this script stores only "
              "the ws token. For cookie-based downloads run 'moodle-dl --new-token --sso'.",
              flush=True)
    cp = Path(a.config).expanduser()
    try:
        cfg = json.loads(cp.read_text(encoding="utf-8")) if cp.exists() else {}
    except ValueError:
        print(f"existing config is not valid JSON, left untouched: {cp}", flush=True)
        return 2
    if not isinstance(cfg, dict):
        print(f"existing config root must be an object, left untouched: {cp}", flush=True)
        return 2
    cfg["token"] = token  # everything else (incl. privatetoken) preserved
    cp.parent.mkdir(parents=True, exist_ok=True)
    cp.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    try: os.chmod(cp, 0o600)
    except OSError: pass
    print(f"saved to {cp} (chmod 600). Token NOT printed.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
