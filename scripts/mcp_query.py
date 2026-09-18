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
import argparse
import inspect
import json
import os
import re
import sys
from pathlib import Path

TOOLS_NOARG = {"deadlines": "get_upcoming_deadlines", "overdue": "get_overdue_assignments",
               "tasks": "get_actionable_tasks", "dashboard": "semester_dashboard",
               "briefing": "daily_briefing", "review": "weekly_review",
               "courses": "get_my_courses", "events": "get_upcoming_events",
               "load": "get_study_load", "activity": "get_recent_activity"}
TOOLS_COURSE = {"assignments": "get_assignments", "grades": "get_grades",
                "progress": "get_course_progress", "health": "get_course_health",
                "announcements": "get_course_announcements"}

ALL_TOOLS = set(TOOLS_NOARG) | set(TOOLS_COURSE)
# Verified against the pinned vendor checkout (api.py signatures): only health
# has a required courseid; the rest default to all-courses scope.
COURSE_ID_REQUIRED = {"health"}


def _call_with_course_id(fn, course_id):
    """Bind --course-id using the INSTALLED function signature, not guesses."""
    try:
        params = list(inspect.signature(fn).parameters.values())
    except (TypeError, ValueError):
        params = []
    positional = [p for p in params
                  if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)]
    if not positional:
        if course_id:
            raise TypeError(f"{getattr(fn, '__name__', fn)} takes no course id")
        return fn()
    first = positional[0]
    if not course_id:
        if first.default is first.empty:
            raise TypeError(f"{first.name} is required (pass --course-id)")
        return fn()
    name = (first.name or "").lower()
    if "courseids" in name and name != "courseid":
        return fn([int(course_id)])
    if first.annotation is int or "courseid" in name:
        return fn(int(course_id))
    return fn(course_id)

def _dl_config(path: Path) -> dict:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as e:
        print(f"mcp_query: unreadable config ({type(e).__name__}): {path} — "
              "fix the JSON or re-run 'moodle-dl --init'", file=sys.stderr)
        raise SystemExit(2) from e
    if not isinstance(raw, dict):
        print(f"mcp_query: config root must be an object: {path}", file=sys.stderr)
        raise SystemExit(2)
    return raw

def _env(cfg: dict) -> tuple[str, str]:
    domain = str(cfg.get("moodle_domain", "moodle.hku.hk")).strip().rstrip("/")
    path = str(cfg.get("moodle_path", "/"))
    if not path.startswith("/"):
        path = "/" + path
    if not path.endswith("/"):
        path += "/"
    return f"https://{domain}{path}webservice/rest/server.php", str(cfg.get("token", ""))

def _redact_text(s: str, token: str) -> str:
    out = s
    if token and len(token) >= 8:
        out = out.replace(token, "[REDACTED]")
    # common key=value leaks
    out = re.sub(r"(?i)((?:token|wstoken|password|cookie|privatetoken)[=:]\s*)([^\s,&\"']+)",
                 r"\1[REDACTED]", out)
    return out

_SECRET_KEYS = {"token", "wstoken", "password", "cookie", "privatetoken", "moodle_token"}


def _redact_obj(obj, token: str):
    if isinstance(obj, dict):
        return {
            k: ("[REDACTED]" if str(k).lower() in _SECRET_KEYS
                else _redact_obj(v, token))
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [_redact_obj(x, token) for x in obj]
    if isinstance(obj, str):
        return _redact_text(obj, token)
    return obj

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
        print("no token in config; run save_token.py first", file=sys.stderr)
        return 2
    if a.tool not in ALL_TOOLS:
        print(f"unknown tool: {a.tool} (valid: {', '.join(sorted(ALL_TOOLS))})",
              file=sys.stderr)
        return 2

    if not a.mcp_dir:
        print("DRY-RUN (no --mcp-dir given: local args validated only, no Moodle call)")
        if a.tool in COURSE_ID_REQUIRED and not a.course_id:
            print(f"{a.tool} needs --course-id", file=sys.stderr)
            return 2
        print(f"MOODLE_URL={url}")
        print("MOODLE_TOKEN=[REDACTED present]")
        fn = TOOLS_NOARG.get(a.tool, TOOLS_COURSE.get(a.tool))
        scope = f"courseid={a.course_id}" if a.course_id else (
            "all-courses scope" if a.tool in TOOLS_COURSE else "")
        print(f"planned call: moodle_mcp.server.{fn}({scope})")
        print("Execute via: python3 mcp_query.py ... --mcp-dir /path/to/moodle-mcp")
        return 0

    src = Path(a.mcp_dir).expanduser() / "src"
    if not (src / "moodle_mcp" / "server.py").exists():
        print(f"mcp checkout not found at {src}/moodle_mcp/server.py", file=sys.stderr)
        return 2
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
            print(f"cannot import moodle_mcp from {src}: {e}", file=sys.stderr)
            return 2
    fn_name = TOOLS_NOARG.get(a.tool, TOOLS_COURSE.get(a.tool))
    if fn_name is None or not hasattr(S, fn_name):
        print(f"unknown tool: {a.tool}", file=sys.stderr)
        return 2
    fn = getattr(S, fn_name)
    try:
        res = _call_with_course_id(fn, a.course_id)
    except TypeError as e:
        print(f"argument mismatch calling {fn_name}: {e} "
              "(check --course-id against the installed moodle-mcp signature)",
              file=sys.stderr)
        return 2
    except Exception as e:
        msg = _redact_text(f"{type(e).__name__}: {str(e)[:200]}", token)
        print(f"moodle API call failed: {msg}", file=sys.stderr)
        return 1
    safe = _redact_obj(res, token)
    print(json.dumps(safe, ensure_ascii=False, indent=2, default=str))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
