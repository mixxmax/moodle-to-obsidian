"""P0-B: every doc command runs verbatim from a third directory.

Covers SKILL.md Steps 1-3 + status with <SKILL_DIR>/<VAULT> only.
"""
import json
import os
from pathlib import Path

from conftest import REPO, run_cli

SKILL = os.fspath(REPO)


def _sh(mirror, va, *args):
    return run_cli(mirror, *[a.replace("<SKILL_DIR>", SKILL).replace("<VAULT>", va)
                             for a in args])


def test_doc_walkthrough_from_third_dir(mirror, tmp_path, monkeypatch):
    va = os.fspath(tmp_path / "vault")
    (tmp_path / "vault" / "moodle-sync" / "COMP1111 Intro [2026]").mkdir(parents=True)
    (tmp_path / "vault" / "moodle-sync" / "COMP1111 Intro [2026]" / "f.pdf").write_bytes(b"D")
    (tmp_path / "third").mkdir()
    monkeypatch.chdir(tmp_path / "third")

    import shutil
    shutil.copy(Path(SKILL) / "config.template.json", tmp_path / "vault" / "moodle-mirror.json")
    cfg = tmp_path / "vault" / "moodle-mirror.json"
    c = json.loads(cfg.read_text(encoding="utf-8"))
    c["mappings"] = {"COMP1111": "Course COMP1111"}
    c["downloader"] = ""
    cfg.write_text(json.dumps(c), encoding="utf-8")

    rc, out, _ = _sh(mirror, va, "--config", "<VAULT>/moodle-mirror.json", "doctor")
    assert rc == 0 and "sync ready" in out and "NOT READY" in out
    rc, out, _ = _sh(mirror, va, "--config", "<VAULT>/moodle-mirror.json", "sync")
    assert rc == 0 and "+1 新增" in out
    rc, out, _ = _sh(mirror, va, "--config", "<VAULT>/moodle-mirror.json", "status")
    assert rc == 0
    assert (tmp_path / "vault" / "Course COMP1111" / "99 Moodle Mirror" / "f.pdf").exists()
