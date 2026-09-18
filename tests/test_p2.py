"""S2-5/S2-6: symlink visibility, MCP arg validation (offline-testable parts)."""
import json

from conftest import load, run_cli, write_config


def _sync(mirror, cfg):
    rc, out, err = run_cli(mirror, "--config", str(cfg), "sync")
    assert rc == 0, err
    return out


def test_symlink_reported_not_silent(mirror, workdir):
    cfg = write_config(workdir["vault"] / "moodle-mirror.json")
    outside = workdir["root"] / "outside"
    outside.mkdir()
    (outside / "x.pdf").write_bytes(b"X")
    (workdir["cache"] / "COMP1111 Week 1 [2026]" / "Linked").symlink_to(outside, target_is_directory=True)
    out = _sync(mirror, cfg)
    assert "skipped-symlink" in out.lower()
    assert "outside" not in (workdir["vault"] / "Course COMP1111" / "99 Moodle Mirror" / "Linked").as_posix() \
        or not (workdir["vault"] / "Course COMP1111" / "99 Moodle Mirror" / "Linked").exists()
    log = (workdir["vault"] / "Log.md").read_text(encoding="utf-8")
    assert "skipped-symlink" in log
    assert "Linked" in log


def test_index_single_course_root_heading(mirror, workdir):
    (workdir["cache"] / "COMP1111 Week 1 [2026]" / "mmm.pdf").write_bytes(b"M")
    (workdir["cache"] / "COMP1111 Week 1 [2026]" / "mid").mkdir(exist_ok=True)
    (workdir["cache"] / "COMP1111 Week 1 [2026]" / "mid" / "i.pdf").write_bytes(b"I")
    cfg = write_config(workdir["vault"] / "moodle-mirror.json")
    _sync(mirror, cfg)
    idx = (workdir["vault"] / "Course COMP1111" / "99 Moodle Mirror"
           / "Moodle Mirror Index.md").read_text(encoding="utf-8")
    assert idx.count("### Course root") == 1


def test_broken_auto_markers_error_loudly(mirror, workdir):
    cfg = write_config(workdir["vault"] / "moodle-mirror.json")
    _sync(mirror, cfg)
    idx = (workdir["vault"] / "Course COMP1111" / "99 Moodle Mirror"
           / "Moodle Mirror Index.md")
    idx.write_text("<!-- MOODLE-LOCAL-SYNC:AUTO:END -->\norphan\n" + idx.read_text(encoding="utf-8"),
                   encoding="utf-8")
    rc, out, err = run_cli(mirror, "--config", str(cfg), "sync")
    assert rc == 2
    assert "Traceback" not in err and "marker" in err.lower()


def test_text_files_0644(mirror, workdir):
    import os
    cfg = write_config(workdir["vault"] / "moodle-mirror.json")
    _sync(mirror, cfg)
    for p in [(workdir["vault"] / "Course COMP1111" / "99 Moodle Mirror" / "Moodle Mirror Index.md"),
              (workdir["vault"] / "Log.md")]:
        assert oct(os.stat(p).st_mode & 0o777) == "0o644"


def test_mcp_unknown_tool_rejected_in_dryrun(tmp_path):
    mq = load("mcp_query")
    (tmp_path / "c.json").write_text(json.dumps({"token": "T"}), encoding="utf-8")
    import io
    from contextlib import redirect_stderr, redirect_stdout
    out, err = io.StringIO(), io.StringIO()
    import sys
    old = sys.argv
    sys.argv = ["mcp_query.py", "--config", str(tmp_path / "c.json"), "drop_tables"]
    try:
        with redirect_stdout(out), redirect_stderr(err):
            rc = mq.main()
    finally:
        sys.argv = old
    assert rc == 2
    assert "unknown tool" in err.getvalue()


def test_mcp_health_requires_course_id(tmp_path):
    mq = load("mcp_query")
    (tmp_path / "c.json").write_text(json.dumps({"token": "T"}), encoding="utf-8")
    import io
    import sys
    from contextlib import redirect_stderr, redirect_stdout
    for args, want_rc, want in ((["--config", str(tmp_path / "c.json"), "health"], 2, "course-id"),
                               (["--config", str(tmp_path / "c.json"), "grades"], 0, "all-courses")):
        out, err = io.StringIO(), io.StringIO()
        old = sys.argv
        sys.argv = ["mcp_query.py", *args]
        try:
            with redirect_stdout(out), redirect_stderr(err):
                rc = mq.main()
        finally:
            sys.argv = old
        assert rc == want_rc, (args, out.getvalue(), err.getvalue())
        assert want in (out.getvalue() + err.getvalue())
