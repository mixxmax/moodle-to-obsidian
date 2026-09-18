# Moodle MCP, Read-Only Progress Layer (optional)

Upstream: https://github.com/loyaniu/moodle-mcp. Same user token from
`<SOURCE_ROOT>/config.json`, no second credential. Never daemonise; call on demand.

## Modes

- Dry-run (default): `python3 "<SKILL_DIR>/scripts/mcp_query.py" --config <SOURCE_ROOT>/config.json deadlines`
  verifies the token exists and prints the exact planned call. Nothing executes.
- Execute: add `--mcp-dir /path/to/moodle-mcp`. The shim sets `MOODLE_URL` /
  `MOODLE_TOKEN` from your config (redacted on screen), imports
  `moodle_mcp.server` from `<mcp-dir>/src`, calls the tool function, prints JSON.

## Tool names

`courses | assignments | deadlines | overdue | tasks | grades | progress |
health (--course-id required) | announcements | events | activity |
dashboard | briefing | review | load`

Course IDs are Moodle numeric IDs (from the course URL or `courses`).
Outputs are snapshots for the agent to summarise, not vault content.
