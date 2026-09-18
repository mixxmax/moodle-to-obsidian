"""P0-A red tests: pull outcome must gate the mirror step.

Contract: rc!=0 OR failure signals in output -> no synchronize(),
no manifest/last-run success stamp, no green success banner.
rc==0 clean -> mirror proceeds. Unknown downloader version -> mirror
proceeds but pull is explicitly marked unverified.
"""
import json
from pathlib import Path

from conftest import make_mock_dl, run_cli, write_config


def _mirror_files(root):
    return list((root / "vault").rglob("99 Moodle Mirror"))


def test_pull_rc_nonzero_blocks_mirror(mirror, workdir, tmp_path):
    dl = make_mock_dl(tmp_path / "dl-fail.sh", "fail")
    cfg = write_config(workdir["vault"] / "moodle-mirror.json", downloader=dl)
    rc, out, err = run_cli(mirror, "--config", str(cfg), "run")
    assert rc != 0
    assert _mirror_files(workdir["root"]) == []
    assert not (workdir["state"] / "last-run.json").exists()
    assert "成功" not in out or "失败" in out  # no green-only success
    assert "失败" in out


def test_pull_partial_signals_block_mirror(mirror, workdir, tmp_path):
    dl = make_mock_dl(tmp_path / "dl-partial.sh", "partial")
    cfg = write_config(workdir["vault"] / "moodle-mirror.json", downloader=dl)
    rc, out, err = run_cli(mirror, "--config", str(cfg), "run")
    assert rc != 0
    assert _mirror_files(workdir["root"]) == []
    assert not (workdir["state"] / "last-run.json").exists()
    assert "失败" in out or "不完整" in out


def test_pull_clean_mirrors(mirror, workdir, tmp_path):
    dl = make_mock_dl(tmp_path / "dl-clean.sh", "clean")
    cfg = write_config(workdir["vault"] / "moodle-mirror.json", downloader=dl)
    rc, out, err = run_cli(mirror, "--config", str(cfg), "run")
    assert rc == 0
    assert _mirror_files(workdir["root"]) != []
    assert "成功" in out


def test_pull_unknown_version_marks_unverified(mirror, workdir, tmp_path):
    dl = make_mock_dl(tmp_path / "dl-noversion.sh", "no-version")
    cfg = write_config(workdir["vault"] / "moodle-mirror.json", downloader=dl)
    rc, out, err = run_cli(mirror, "--config", str(cfg), "run")
    assert rc == 0  # mirror still proceeds...
    assert _mirror_files(workdir["root"]) != []
    assert "未验证" in out  # ...but pull is not claimed successful
