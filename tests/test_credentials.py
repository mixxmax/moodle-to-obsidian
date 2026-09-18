"""P1-A: credential contract — token only, cleaned, preserved surroundings."""
import base64
import io
import json
import os
from contextlib import redirect_stdout
from pathlib import Path

from conftest import load, run_cli


def _b64(s):
    return base64.b64encode(s.encode()).decode()


def test_three_segment_keeps_privatetoken(tmp_path):
    st = load("save_token")
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"moodle_domain": "x", "privatetoken": "OLDPRIV999",
                               "token": "OLDTOKEN"}), encoding="utf-8")
    out = io.StringIO()
    with redirect_stdout(out):
        rc = st.main(["--config", str(cfg),
                      "--b64", _b64("zhang:::AB-CD_12efGH:::PRIVSECRET9999")])
    assert rc == 0
    data = json.loads(cfg.read_text(encoding="utf-8"))
    assert data["token"] == "ABCD12efGH"  # cleaned like upstream
    assert data["privatetoken"] == "OLDPRIV999"  # untouched
    assert data["moodle_domain"] == "x"
    assert "ABCD12efGH" not in out.getvalue() and "PRIVSECRET" not in out.getvalue()
    assert oct(os.stat(cfg).st_mode & 0o777) == "0o600"


def test_stdin_import_avoids_argv(tmp_path):
    import sys
    st = load("save_token")
    cfg = tmp_path / "c.json"
    old = sys.stdin
    try:
        sys.stdin = io.StringIO("moodledl://token=" + _b64("u:::TOKENABCDEF123:::P"))
        out = io.StringIO()
        with redirect_stdout(out):
            rc = st.main(["--config", str(cfg), "--b64-stdin"])
    finally:
        sys.stdin = old
    assert rc == 0
    assert json.loads(cfg.read_text(encoding="utf-8"))["token"] == "TOKENABCDEF123"


def test_cookie_switch_without_private_warns(mirror, workdir, tmp_path):
    import stat
    dl = tmp_path / "dl.sh"
    dl.write_text("#!/bin/sh\nexit 0\n")
    dl.chmod(dl.stat().st_mode | stat.S_IXUSR)
    (workdir["cache"] / "config.json").write_text(json.dumps(
        {"moodle_domain": "x", "download_course_ids": ["1"],
         "token": "T", "download_also_with_cookie": True}), encoding="utf-8")
    from conftest import write_config
    cfg = write_config(workdir["vault"] / "moodle-mirror.json", downloader=str(dl))
    rc, out, err = run_cli(mirror, "--config", str(cfg), "doctor")
    assert "privatetoken" in out and "--new-token --sso" in out
