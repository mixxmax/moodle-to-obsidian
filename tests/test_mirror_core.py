"""Regression locks: behaviors that must survive the P0/P1 refactor."""

from conftest import run_cli, write_config


def _sync(mirror, cfg):
    rc, out, err = run_cli(mirror, "--config", str(cfg), "sync")
    assert rc == 0, err
    return out


def test_idempotent_second_run(mirror, workdir):
    cfg = write_config(workdir["vault"] / "moodle-mirror.json")
    _sync(mirror, cfg)
    out = _sync(mirror, cfg)
    assert "+0 新增" in out and "~0 更新" in out


def test_withdraw_keeps_local_file(mirror, workdir):
    cfg = write_config(workdir["vault"] / "moodle-mirror.json")
    _sync(mirror, cfg)
    (workdir["cache"] / "COMP1111 Week 1 [2026]" / "a.pdf").unlink()
    out = _sync(mirror, cfg)
    assert "1 撤回留底" in out
    kept = workdir["vault"] / "Course COMP1111" / "99 Moodle Mirror" / "a.pdf"
    assert kept.exists()


def test_local_edit_conflict_shelved_outside_mirror(mirror, workdir):
    cfg = write_config(workdir["vault"] / "moodle-mirror.json")
    _sync(mirror, cfg)
    mirrored = workdir["vault"] / "Course COMP1111" / "99 Moodle Mirror" / "a.pdf"
    mirrored.write_bytes(b"LOCAL")
    (workdir["cache"] / "COMP1111 Week 1 [2026]" / "a.pdf").write_bytes(b"REMOTE2")
    out = _sync(mirror, cfg)
    assert "1 冲突备份" in out
    mroot = workdir["vault"] / "Course COMP1111" / "99 Moodle Mirror"
    assert list(mroot.rglob("*.bak")) == []
    shelved = list((workdir["state"] / "conflicts").rglob("*.bak"))
    assert len(shelved) == 1 and shelved[0].read_bytes() == b"LOCAL"
    log = (workdir["vault"] / "Log.md").read_text(encoding="utf-8")
    assert "conflicts/" in log


def test_prune_negative_days_refused(mirror, workdir):
    cfg = write_config(workdir["vault"] / "moodle-mirror.json")
    bak = workdir["state"] / "conflicts" / "COMP1111" / "a.pdf.20990101-000000.bak"
    bak.parent.mkdir(parents=True, exist_ok=True)
    bak.write_bytes(b"x")
    rc, out, err = run_cli(mirror, "--config", str(cfg), "doctor", "--prune-conflicts", "-1")
    assert rc == 2
    assert bak.exists()
    assert "DAYS >= 1" in err


def test_prune_conflicts_by_age(mirror, workdir):
    import os
    import time
    cfg = write_config(workdir["vault"] / "moodle-mirror.json")
    old = workdir["state"] / "conflicts" / "COMP1111" / "a.pdf.20200101-000000.bak"
    new = workdir["state"] / "conflicts" / "COMP1111" / "b.pdf.20990101-000000.bak"
    old.parent.mkdir(parents=True, exist_ok=True)
    old.write_bytes(b"o")
    new.write_bytes(b"n")
    ancient = time.time() - 40 * 86400
    os.utime(old, (ancient, ancient))
    rc, out, err = run_cli(mirror, "--config", str(cfg), "doctor", "--prune-conflicts", "30")
    assert rc == 0
    assert not old.exists() and new.exists()
    assert "pruned 1" in out


def test_destination_collision_rejected(mirror, workdir):
    cfg = write_config(workdir["vault"] / "moodle-mirror.json",
                       mappings={"COMP1111": "Same", "COMP2222": "same"})
    rc, out, err = run_cli(mirror, "--config", str(cfg), "sync")
    assert rc == 2 and "collide" in err


def test_unmapped_course_reported(mirror, workdir):
    cfg = write_config(workdir["vault"] / "moodle-mirror.json",
                       mappings={"COMP9999": "Elsewhere"})
    out = _sync(mirror, cfg)
    assert "UNMAPPED" in out


def test_empty_section_dirs_mirrored(mirror, workdir):
    (workdir["cache"] / "COMP1111 Week 1 [2026]" / "Empty Section").mkdir(parents=True)
    cfg = write_config(workdir["vault"] / "moodle-mirror.json")
    _sync(mirror, cfg)
    assert (workdir["vault"] / "Course COMP1111" / "99 Moodle Mirror"
            / "Empty Section").is_dir()


def test_withdraw_then_restore(mirror, workdir):
    cfg = write_config(workdir["vault"] / "moodle-mirror.json")
    _sync(mirror, cfg)
    src = workdir["cache"] / "COMP1111 Week 1 [2026]" / "a.pdf"
    src.unlink()
    _sync(mirror, cfg)
    src.write_bytes(b"AAA")
    out = _sync(mirror, cfg)
    assert "1 恢复" in out


def test_bad_downloader_path_points_to_doctor(mirror, workdir):
    cfg = write_config(workdir["vault"] / "moodle-mirror.json",
                       downloader="/nonexistent/dl-xyz")
    rc, out, err = run_cli(mirror, "--config", str(cfg), "run")
    assert rc != 0
    assert "cannot execute downloader" in err
    assert "检查 moodle-mirror.json 中的 downloader 路径" in out
    assert "mappings" not in err  # must not misdirect to mappings


def test_corrupt_mirror_config_clean_error(mirror, tmp_path):
    (tmp_path / "bad.json").write_text("{oops", encoding="utf-8")
    rc, out, err = run_cli(mirror, "--config", str(tmp_path / "bad.json"), "sync")
    assert rc == 2
    assert "Traceback" not in err and "valid JSON" in err


def test_noninteger_retries_clean_error(mirror, tmp_path):
    import json
    (tmp_path / "v").mkdir()
    (tmp_path / "c").mkdir()
    (tmp_path / "v" / "m.json").write_text(json.dumps(
        {"source_root": "../c", "vault_root": ".", "state_dir": "../s",
         "mappings": {"X": "Y"}, "pull_retries": "three"}), encoding="utf-8")
    rc, out, err = run_cli(mirror, "--config", str(tmp_path / "v" / "m.json"), "sync")
    assert rc == 2
    assert "Traceback" not in err and "integers" in err


def test_dot_destination_names_folder(mirror, workdir):
    cfg = write_config(workdir["vault"] / "moodle-mirror.json",
                       mappings={"COMP1111": "."})
    rc, out, err = run_cli(mirror, "--config", str(cfg), "sync")
    assert rc == 2
    assert "name a real folder" in err


def test_status_json_truncates_events(mirror, workdir):
    import json
    (workdir["cache"] / "COMP1111 Week 1 [2026]" / "b.pdf").write_bytes(b"B")
    cfg = write_config(workdir["vault"] / "moodle-mirror.json")
    _sync(mirror, cfg)
    rc, out, err = run_cli(mirror, "--config", str(cfg), "status", "--json",
                           "--events", "1")
    assert rc == 0
    d = json.loads(out)
    assert len(d["events"]) == 1 and "events_truncated" in d
    rc, out, err = run_cli(mirror, "--config", str(cfg), "status", "--json",
                           "--events", "0")
    assert rc == 0 and "events_truncated" not in json.loads(out)


def test_missing_course_marks_incomplete(mirror, workdir):
    import json
    import shutil
    (workdir["cache"] / "COMP2222 Second [2026]").mkdir(parents=True)
    (workdir["cache"] / "COMP2222 Second [2026]" / "b.pdf").write_bytes(b"B")
    cfg = write_config(workdir["vault"] / "moodle-mirror.json",
                       mappings={"COMP1111": "C1", "COMP2222": "C2"})
    _sync(mirror, cfg)
    before = json.loads((workdir["state"] / "manifest.json").read_text(encoding="utf-8"))
    assert "last_successful_sync" in before
    shutil.rmtree(workdir["cache"] / "COMP2222 Second [2026]")
    rc, out, err = run_cli(mirror, "--config", str(cfg), "sync")
    assert rc == 0
    assert "MISSING-COURSE" in out and "COMP2222" in out
    assert "不完整" in out  # no green-only success
    log = (workdir["vault"] / "Log.md").read_text(encoding="utf-8")
    assert "MISSING-COURSE" in log and "COMP2222" in log
    after = json.loads((workdir["state"] / "manifest.json").read_text(encoding="utf-8"))
    assert after.get("last_successful_sync") == before["last_successful_sync"]
    assert "COMP2222" in after["courses"]  # history kept, not withdrawn
    assert (workdir["vault"] / "C2" / "99 Moodle Mirror" / "b.pdf").exists()
    status = json.loads((workdir["state"] / "last-run.json").read_text(encoding="utf-8"))
    assert status["status"] == "incomplete"


def test_broken_index_blocks_before_copy(mirror, workdir):
    cfg = write_config(workdir["vault"] / "moodle-mirror.json")
    _sync(mirror, cfg)
    idx = (workdir["vault"] / "Course COMP1111" / "99 Moodle Mirror"
           / "Moodle Mirror Index.md")
    idx.write_text("<!-- MOODLE-LOCAL-SYNC:AUTO:END -->\norphan\n" + idx.read_text(encoding="utf-8"),
                   encoding="utf-8")
    (workdir["cache"] / "COMP1111 Week 1 [2026]" / "new.pdf").write_bytes(b"NEW")
    manifest_before = (workdir["state"] / "manifest.json").read_bytes()
    log_before = (workdir["vault"] / "Log.md").read_bytes()
    rc, out, err = run_cli(mirror, "--config", str(cfg), "sync")
    assert rc == 2
    assert "Traceback" not in err
    assert not (workdir["vault"] / "Course COMP1111" / "99 Moodle Mirror" / "new.pdf").exists()
    assert (workdir["state"] / "manifest.json").read_bytes() == manifest_before
    assert (workdir["vault"] / "Log.md").read_bytes() == log_before


def test_handwritten_index_section_survives(mirror, workdir):
    cfg = write_config(workdir["vault"] / "moodle-mirror.json")
    _sync(mirror, cfg)
    idx = workdir["vault"] / "Course COMP1111" / "99 Moodle Mirror" / "Moodle Mirror Index.md"
    idx.write_text(idx.read_text(encoding="utf-8") + "\n- my hand note\n", encoding="utf-8")
    _sync(mirror, cfg)
    assert idx.read_text(encoding="utf-8").count("my hand note") == 1
