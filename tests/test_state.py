"""P1-B: corrupt state is preserved + rebuilt visibly; status never tracebacks."""
import json

from conftest import run_cli, write_config


def _sync(mirror, cfg):
    rc, out, err = run_cli(mirror, "--config", str(cfg), "sync")
    assert rc == 0, err
    return out


def test_corrupt_manifest_backed_up_and_adopted_visible(mirror, workdir):
    cfg = write_config(workdir["vault"] / "moodle-mirror.json")
    _sync(mirror, cfg)
    (workdir["state"] / "manifest.json").write_text("{bad", encoding="utf-8")
    rc, out, err = run_cli(mirror, "--config", str(cfg), "sync")
    assert rc == 0, err
    assert "Traceback" not in out and "Traceback" not in err
    backups = list(workdir["state"].glob("manifest.json.corrupt-*"))
    assert len(backups) == 1
    assert "adopted" in (workdir["vault"] / "Log.md").read_text(encoding="utf-8")
    assert "已有认领" in out


def test_corrupt_manifest_recovered_no_stamp(mirror, workdir):
    import json
    cfg = write_config(workdir["vault"] / "moodle-mirror.json")
    _sync(mirror, cfg)
    (workdir["state"] / "manifest.json").write_text("{bad", encoding="utf-8")
    rc, out, err = run_cli(mirror, "--config", str(cfg), "sync")
    assert rc == 0, err
    mp = json.loads((workdir["state"] / "manifest.json").read_text(encoding="utf-8"))
    assert "last_successful_sync" not in mp
    status = json.loads((workdir["state"] / "last-run.json").read_text(encoding="utf-8"))
    assert status["status"] == "recovered"
    assert "历史" in out or "recovered" in out.lower() or "⚠️" in out


def test_unknown_manifest_version_errors_loudly_keeps_file(mirror, workdir):
    cfg = write_config(workdir["vault"] / "moodle-mirror.json")
    _sync(mirror, cfg)
    mp = workdir["state"] / "manifest.json"
    mp.write_text(json.dumps({"version": 999, "courses": {}}), encoding="utf-8")
    rc, out, err = run_cli(mirror, "--config", str(cfg), "sync")
    assert rc == 2
    assert "Traceback" not in err
    assert "Recovery" in err or "恢复" in err or "move it aside" in err
    assert mp.exists()  # never silently replaced


def test_status_corrupt_last_run_clean_error(mirror, workdir):
    cfg = write_config(workdir["vault"] / "moodle-mirror.json")
    _sync(mirror, cfg)
    (workdir["state"] / "last-run.json").write_text("{", encoding="utf-8")
    rc, out, err = run_cli(mirror, "--config", str(cfg), "status")
    assert rc == 2
    assert "Traceback" not in err


def test_status_missing_keys_clean_error(mirror, workdir):
    cfg = write_config(workdir["vault"] / "moodle-mirror.json")
    _sync(mirror, cfg)
    (workdir["state"] / "last-run.json").write_text(
        json.dumps({"started_at": "x", "finished_at": "y"}), encoding="utf-8")
    rc, out, err = run_cli(mirror, "--config", str(cfg), "status")
    assert rc == 2
    assert "Traceback" not in err and "KeyError" not in err
