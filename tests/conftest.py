"""Shared fixtures for offline mirror tests. No network, no real credentials."""
import importlib.util
import json
import os
import stat
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SCRIPTS = REPO / "scripts"


def load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod  # dataclasses needs the module namespace
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def mirror():
    return load("mirror")


@pytest.fixture()
def workdir(tmp_path):
    """Isolated vault + cache: <tmp>/vault, <tmp>/cache, <tmp>/state."""
    vault = tmp_path / "vault"
    cache = tmp_path / "cache"
    state = tmp_path / "state"
    vault.mkdir()
    cache.mkdir()
    (cache / "COMP1111 Week 1 [2026]").mkdir(parents=True)
    (cache / "COMP1111 Week 1 [2026]" / "a.pdf").write_bytes(b"AAA")
    return {"root": tmp_path, "vault": vault, "cache": cache, "state": state}


def write_config(path, *, downloader="", mappings=None, **kw):
    cfg = {
        "source_root": str(kw.get("source_root", "../cache")),
        "vault_root": ".",
        "state_dir": str(kw.get("state_dir", "../state")),
        "changelog": "./Log.md",
        "downloader": downloader,
        "mappings": mappings or {"COMP1111": "Course COMP1111"},
        "pull_retries": 1,
        "pull_retry_seconds": 0,
    }
    Path(path).write_text(json.dumps(cfg), encoding="utf-8")
    return Path(path)


def make_mock_dl(path, mode):
    """Executable fake downloader. mode: fail|partial|clean|no-version.

    Responds to --version like moodle-dl 2.3.13 unless no-version.
    partial prints real 2.3.x failure signals with rc 0.
    """
    script = f"""#!/bin/sh
if [ "$1" = "--version" ]; then
  {"echo 'moodle-dl 2.3.13'" if mode != "no-version" else "exit 0"}
  exit 0
fi
case "{mode}" in
  fail) echo "boom" >&2; exit 3;;
  partial)
    echo "2026-01-01  WARNING  {{moodle_service}}  The Moodle course with id 999 is no longer available online."
    echo "Error while trying to download files, look at the log for more details. List of failed downloads:"
    exit 0;;
  *) echo "No changes found."; exit 0;;
esac
"""
    p = Path(path)
    p.write_text(script, encoding="utf-8")
    p.chmod(p.stat().st_mode | stat.S_IXUSR)
    return str(p)


def write_dl_config(cache, **overrides):
    data = {"moodle_domain": "moodle.example.test", "moodle_path": "/",
            "download_course_ids": [111], "token": "FAKETOKEN123"}
    data.update(overrides)
    p = Path(cache) / "config.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    os.chmod(p, 0o600)
    return p


def run_cli(mirror, *argv):
    import io
    from contextlib import redirect_stderr, redirect_stdout
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        rc = mirror.main(list(argv))
    return rc, out.getvalue(), err.getvalue()
