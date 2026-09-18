"""P0-C tests: doctor separates 'sync ready' from 'run ready'.

rc reflects sync-readiness only; run-readiness is explicit lines.
doctor never touches network or the mirror.
"""
import json

from conftest import run_cli, write_config


def _dl_config(cache, **kw):
    p = cache / "config.json"
    data = {"moodle_domain": "moodle.example.test", "moodle_path": "/",
            "download_course_ids": ["111"], "token": "FAKETOKEN123"}
    data.update(kw)
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


def test_doctor_sync_only_labels_run_not_ready(mirror, workdir):
    cfg = write_config(workdir["vault"] / "moodle-mirror.json", downloader="")
    rc, out, err = run_cli(mirror, "--config", str(cfg), "doctor")
    assert rc == 0
    assert "sync" in out.lower() and "ready" in out.lower()
    assert "run" in out.lower() and ("not ready" in out.lower() or "NOT READY" in out)


def test_doctor_missing_binary(mirror, workdir, tmp_path):
    cfg = write_config(workdir["vault"] / "moodle-mirror.json",
                       downloader=str(tmp_path / "no-such-dl"))
    rc, out, err = run_cli(mirror, "--config", str(cfg), "doctor")
    assert "NOT READY" in out or "not ready" in out.lower()
    assert "downloader" in out.lower()


def test_doctor_missing_dl_config(mirror, workdir, tmp_path):
    import stat
    dl = tmp_path / "dl.sh"
    dl.write_text("#!/bin/sh\nexit 0\n")
    dl.chmod(dl.stat().st_mode | stat.S_IXUSR)
    cfg = write_config(workdir["vault"] / "moodle-mirror.json", downloader=str(dl))
    rc, out, err = run_cli(mirror, "--config", str(cfg), "doctor")
    assert "NOT READY" in out or "not ready" in out.lower()
    assert rc == 0  # sync itself is still fine


def test_doctor_corrupt_dl_config(mirror, workdir, tmp_path):
    import stat
    dl = tmp_path / "dl.sh"
    dl.write_text("#!/bin/sh\nexit 0\n")
    dl.chmod(dl.stat().st_mode | stat.S_IXUSR)
    (workdir["cache"] / "config.json").write_text("{broken", encoding="utf-8")
    cfg = write_config(workdir["vault"] / "moodle-mirror.json", downloader=str(dl))
    rc, out, err = run_cli(mirror, "--config", str(cfg), "doctor")
    assert "NOT READY" in out or "not ready" in out.lower()


def test_doctor_flags_missing_moodle_path(mirror, workdir, tmp_path):
    import stat
    dl = tmp_path / "dl.sh"
    dl.write_text("#!/bin/sh\nexit 0\n")
    dl.chmod(dl.stat().st_mode | stat.S_IXUSR)
    base = {"moodle_domain": "x", "download_course_ids": ["1"], "token": "T"}
    (workdir["cache"] / "config.json").write_text(json.dumps(base), encoding="utf-8")
    (workdir["cache"] / "config.json").chmod(0o600)
    from conftest import write_config
    cfg = write_config(workdir["vault"] / "moodle-mirror.json", downloader=str(dl))
    rc, out, err = run_cli(mirror, "--config", str(cfg), "doctor")
    assert "moodle_path" in out and ("NOT READY" in out)
    (workdir["cache"] / "config.json").write_text(
        json.dumps({**base, "moodle_path": "/"}), encoding="utf-8")
    (workdir["cache"] / "config.json").chmod(0o600)
    rc, out, err = run_cli(mirror, "--config", str(cfg), "doctor")
    assert "run READY" in out and "NOT READY" not in out


def test_doctor_complete_reports_run_ready(mirror, workdir, tmp_path):
    import stat
    dl = tmp_path / "dl.sh"
    dl.write_text("#!/bin/sh\nexit 0\n")
    dl.chmod(dl.stat().st_mode | stat.S_IXUSR)
    p = _dl_config(workdir["cache"])
    p.chmod(0o600)
    cfg = write_config(workdir["vault"] / "moodle-mirror.json", downloader=str(dl))
    rc, out, err = run_cli(mirror, "--config", str(cfg), "doctor")
    assert rc == 0
    assert "run" in out.lower() and "ready" in out.lower()
    assert "NOT READY" not in out
    assert "FAKETOKEN" not in out and "FAKETOKEN" not in err  # never echo credentials


def test_doctor_warns_loose_config_permissions(mirror, workdir, tmp_path):
    import stat
    dl = tmp_path / "dl.sh"
    dl.write_text("#!/bin/sh\nexit 0\n")
    dl.chmod(dl.stat().st_mode | stat.S_IXUSR)
    p = _dl_config(workdir["cache"])
    p.chmod(0o644)
    cfg = write_config(workdir["vault"] / "moodle-mirror.json", downloader=str(dl))
    rc, out, err = run_cli(mirror, "--config", str(cfg), "doctor")
    assert "600" in out or "chmod" in out.lower()
