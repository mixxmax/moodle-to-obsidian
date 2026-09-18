"""P0: codeless course dirs must never silently succeed; mapping identity."""
import json

from conftest import run_cli, write_config


def _sync(mirror, cfg):
    rc, out, err = run_cli(mirror, "--config", str(cfg), "sync")
    assert rc == 0, err
    return out


def _codeless(workdir, name="Public Law Week 1"):
    d = workdir["cache"] / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "lecture.pdf").write_bytes(b"L")
    return d


def test_codeless_unmapped_is_incomplete_not_success(mirror, workdir):
    cfg = write_config(workdir["vault"] / "moodle-mirror.json",
                       mappings={"COMP1111": "C1"})
    _sync(mirror, cfg)  # clean baseline: stamp set
    before = json.loads((workdir["state"] / "manifest.json").read_text(encoding="utf-8"))
    assert "last_successful_sync" in before
    _codeless(workdir)  # moodle-dl style: fullname without code
    rc, out, err = run_cli(mirror, "--config", str(cfg), "sync")
    assert rc == 0
    assert "UNRECOGNIZED" in out and "Public Law Week 1" in out
    assert "不完整" in out
    status = json.loads((workdir["state"] / "last-run.json").read_text(encoding="utf-8"))
    assert status["status"] == "incomplete"
    after = json.loads((workdir["state"] / "manifest.json").read_text(encoding="utf-8"))
    assert after.get("last_successful_sync") == before["last_successful_sync"]
    log = (workdir["vault"] / "Log.md").read_text(encoding="utf-8")
    assert "UNRECOGNIZED" in log
    assert not (workdir["vault"] / "Public Law Week 1").exists()


def test_codeless_literal_mapping_mirrors(mirror, workdir):
    _codeless(workdir)
    cfg = write_config(workdir["vault"] / "moodle-mirror.json",
                       mappings={"COMP1111": "C1", "Public Law Week 1": "Pub Law"})
    out = _sync(mirror, cfg)
    assert "成功" in out
    assert (workdir["vault"] / "Pub Law" / "99 Moodle Mirror" / "lecture.pdf").exists()
    status = json.loads((workdir["state"] / "last-run.json").read_text(encoding="utf-8"))
    assert status["status"] == "success"


def test_codeless_null_mapping_ignored(mirror, workdir):
    _codeless(workdir)
    cfg = write_config(workdir["vault"] / "moodle-mirror.json",
                       mappings={"COMP1111": "C1", "Public Law Week 1": None})
    out = _sync(mirror, cfg)
    assert "IGNORED" in out
    status = json.loads((workdir["state"] / "last-run.json").read_text(encoding="utf-8"))
    assert status["status"] == "success"


def test_download_path_override_scanned(mirror, workdir):
    import json
    sub = workdir["cache"] / "downloads"
    (sub / "COMP1111 DL [2026]").mkdir(parents=True)
    (sub / "COMP1111 DL [2026]" / "d.pdf").write_bytes(b"D")
    (workdir["cache"] / "config.json").write_text(json.dumps(
        {"download_path": "downloads"}), encoding="utf-8")
    cfg = write_config(workdir["vault"] / "moodle-mirror.json",
                       mappings={"COMP1111": "C1"})
    out = _sync(mirror, cfg)
    assert "+1 新增" in out
    assert (workdir["vault"] / "C1" / "99 Moodle Mirror" / "d.pdf").exists()


def test_doctor_run_not_ready_hint(mirror, workdir):
    cfg = write_config(workdir["vault"] / "moodle-mirror.json", downloader="")
    rc, out, err = run_cli(mirror, "--config", str(cfg), "doctor")
    assert rc == 0
    assert "run NOT READY" in out
    assert "只能 sync" in out and "不要跑 run" in out


def test_code_unmapped_is_incomplete(mirror, workdir):
    cfg = write_config(workdir["vault"] / "moodle-mirror.json",
                       mappings={"COMP9999": "Elsewhere"})
    out = _sync(mirror, cfg)
    assert "UNMAPPED" in out
    status = json.loads((workdir["state"] / "last-run.json").read_text(encoding="utf-8"))
    assert status["status"] == "incomplete"
    assert "last_successful_sync" not in json.loads(
        (workdir["state"] / "manifest.json").read_text(encoding="utf-8"))


def test_code_null_mapping_ignored(mirror, workdir):
    cfg = write_config(workdir["vault"] / "moodle-mirror.json",
                       mappings={"COMP1111": None})
    out = _sync(mirror, cfg)
    assert "IGNORED" in out
    status = json.loads((workdir["state"] / "last-run.json").read_text(encoding="utf-8"))
    assert status["status"] == "success"


def test_duplicate_is_incomplete(mirror, workdir):
    (workdir["cache"] / "COMP1111 Dup").mkdir(parents=True, exist_ok=True)
    (workdir["cache"] / "COMP1111 Dup" / "x.pdf").write_bytes(b"X")
    cfg = write_config(workdir["vault"] / "moodle-mirror.json",
                       mappings={"COMP1111": "C1"})
    out = _sync(mirror, cfg)
    assert "DUPLICATE" in out
    status = json.loads((workdir["state"] / "last-run.json").read_text(encoding="utf-8"))
    assert status["status"] == "incomplete"
