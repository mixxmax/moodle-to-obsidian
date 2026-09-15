#!/usr/bin/env python3
"""Read-only moodle-mcp query shim. Reuses the user's own download token.

Token source: moodle-sync/config.json (moodle-dl's file: moodle_domain,
moodle_path, token). Never stores a second copy, never prints it.

Two modes:
  --mcp-dir <checkout>  import loyaniu/moodle-mcp from <checkout>/src and
                        EXECUTE the tool, print JSON. Env vars are set before
                        import (moodle.py reads them at import time).
  (no --mcp-dir)        DRY-RUN: verify token present, print the exact
                        invocation the user's MCP host should run. Exit 0.

Usage:
  python3 mcp_query.py --config moodle-sync/config.json deadlines
  python3 mcp_query.py --config moodle-sync/config.json grades --course-id 12345
  python3 mcp_query.py --config moodle-sync/config.json briefing --mcp-dir /path/to/moodle-mcp
"""
import argparse, json, os, sys
from pathlib import Path

TOOLS_NOARG = {"deadlines": "get_upcoming_deadlines", "overdue": "get_overdue_assignments",
               "tasks": "get_actionable_tasks", "dashboard": "semester_dashboard",
               "briefing": "daily_briefing", "review": "weekly_review",
               "courses": "get_my_courses", "events": "get_upcoming_events",
               "load": "get_study_load", "activity": "get_recent_activity"}
TOOLS_COURSE = {"assignments": "get_assignments", "grades": "get_grades",
                "progress": "get_course_progress", "health": "get_course_health",
                "announcements": "get_course_announcements"}

def _dl_config(path: Path) -> dict:
    try: return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError: return {}

def _env(cfg: dict) -> tuple[str, str]:
    domain = str(cfg.get("moodle_domain", "moodle.hku.hk")).strip().rstrip("/")
    path = str(cfg.get("moodle_path", "/"))
    if not path.startswith("/"): path = "/" + path
    if not path.endswith("/"): path += "/"
    return f"https://{domain}{path}webservice/rest/server.php", str(cfg.get("token", ""))

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True, help="moodle-dl config (moodle-sync/config.json)")
    ap.add_argument("tool", help="|".join(sorted(set(TOOLS_NOARG) | set(TOOLS_COURSE))))
    ap.add_argument("--course-id", default="")
    ap.add_argument("--mcp-dir", default="")
    a = ap.parse_args()

    cfg = _dl_config(Path(a.config).expanduser())
    url, token = _env(cfg)
    if not token:
        print("no token in config; run save_token.py first", file=sys.stderr); return 2

    if a.tool in TOOLS_COURSE and not a.course_id and a.tool in ("health",):
        print("health needs --course-id", file=sys.stderr); return 2

    if not a.mcp_dir:
        print("DRY-RUN (no --mcp-dir given; nothing executed)")
        print(f"MOODLE_URL={url}")
        print("MOODLE_TOKEN=[REDACTED present]")
        fn = TOOLS_NOARG.get(a.tool, TOOLS_COURSE.get(a.tool, a.tool))
        print(f"planned call: moodle_mcp.server.{fn}({('courseid=' + a.course_id) if a.course_id else ''})")
        print("Execute via: python3 mcp_query.py ... --mcp-dir /path/to/moodle-mcp")
        return 0

    src = Path(a.mcp_dir).expanduser() / "src"
    if not (src / "moodle_mcp" / "server.py").exists():
        print(f"mcp checkout not found at {src}/moodle_mcp/server.py", file=sys.stderr); return 2
    os.environ["MOODLE_URL"] = url
    os.environ["MOODLE_TOKEN"] = token
    sys.path.insert(0, str(src))
    try:
        from moodle_mcp import server as S
    except ImportError:
        # server.py needs the MCP SDK (FastMCP); api.py is the same tool
        # functions without that dependency.
        try:
            from moodle_mcp import api as S
        except ImportError as e:
            print(f"cannot import moodle_mcp from {src}: {e}", file=sys.stderr); return 2
    fn_name = TOOLS_NOARG.get(a.tool, TOOLS_COURSE.get(a.tool))
    if fn_name is None or not hasattr(S, fn_name):
        print(f"unknown tool: {a.tool}", file=sys.stderr); return 2
    fn = getattr(S, fn_name)
    try:
        if a.tool in TOOLS_COURSE:
            res = fn(int(a.course_id)) if a.course_id else (fn() if a.tool != "assignments" else fn(None))
        else:
            res = fn()
    except Exception as e:
        print(f"moodle API call failed: {type(e).__name__}: {str(e)[:200]}", file=sys.stderr); return 1
    print(json.dumps(res, ensure_ascii=False, indent=2, default=str))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
