"""Regression locks: behaviors that must survive the P0/P1 refactor."""
import json
from pathlib import Path

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


def test_local_edit_conflict_backs_up(mirror, workdir):
    cfg = write_config(workdir["vault"] / "moodle-mirror.json")
    _sync(mirror, cfg)
    mirrored = workdir["vault"] / "Course COMP1111" / "99 Moodle Mirror" / "a.pdf"
    mirrored.write_bytes(b"LOCAL")
    (workdir["cache"] / "COMP1111 Week 1 [2026]" / "a.pdf").write_bytes(b"REMOTE2")
    out = _sync(mirror, cfg)
    assert "1 冲突备份" in out
    assert mirrored.with_name(mirrored.name + ".local-edit.bak").exists()


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


def test_handwritten_index_section_survives(mirror, workdir):
    cfg = write_config(workdir["vault"] / "moodle-mirror.json")
    _sync(mirror, cfg)
    idx = workdir["vault"] / "Course COMP1111" / "99 Moodle Mirror" / "Moodle Mirror Index.md"
    idx.write_text(idx.read_text(encoding="utf-8") + "\n- my hand note\n", encoding="utf-8")
    _sync(mirror, cfg)
    assert idx.read_text(encoding="utf-8").count("my hand note") == 1
