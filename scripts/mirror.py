#!/usr/bin/env python3
"""Portable Moodle exact-mirror: snapshot -> <course>/99 Moodle Mirror/.

Slim port of moodle-local-sync/core.py + cli.py for the skill.
Generic course codes (e.g. PCLL8010, LAWS1234, COMP1111), relative paths only.
No LLM, no secrets in logs. Per-user config, chmod 600 recommended.
"""
from __future__ import annotations
import argparse, filecmp, fcntl, json, os, re, shutil, subprocess, sys, tempfile, time
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

AUTO_START = "<!-- MOODLE-LOCAL-SYNC:AUTO:START -->"
AUTO_END = "<!-- MOODLE-LOCAL-SYNC:AUTO:END -->"
MANIFEST_VERSION = 1
CONTROL_FILES = {".DS_Store", "desktop.ini", "Thumbs.db"}
LOCAL_EDIT_SUFFIX = ".local-edit.bak"
CODE_RE = re.compile(r"([A-Z]{2,10}\d{3,}[A-Z]?)")

class ConfigError(ValueError): pass
class SyncBusyError(RuntimeError): pass

@dataclass(frozen=True)
class Config:
    source_root: Path; vault_root: Path; state_dir: Path; changelog: Path
    mappings: dict; mirror_folder: str = "99 Moodle Mirror"
    index_filename: str = "Moodle Mirror Index.md"
    downloader: Path | None = None; pull_retries: int = 3; pull_retry_seconds: int = 30

@dataclass
class SyncResult:
    started_at: str; finished_at: str = ""
    added: int = 0; updated: int = 0; restored: int = 0; withdrawn: int = 0
    conflicted: int = 0; adopted: int = 0; unchanged: int = 0
    scanned_courses: list = field(default_factory=list)
    unmapped_courses: list = field(default_factory=list)
    duplicate_courses: list = field(default_factory=list)
    missing_courses: list = field(default_factory=list)
    events: list = field(default_factory=list)
    def as_dict(self):
        d = asdict(self); d["status"] = "success"; return d

def _now(): return datetime.now().astimezone().isoformat(timespec="seconds")

def _rp(base: Path, v: str, f: str) -> Path:
    if not isinstance(v, str) or not v.strip(): raise ConfigError(f"{f} must be non-empty")
    p = Path(v).expanduser(); return p if p.is_absolute() else (base / p).resolve()

def _rel_name(value, field: str, *, single: bool = False) -> str:
    """Vault-relative name: no absolute, no '.'/'..' components."""
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{field} must be a non-empty relative path")
    path = Path(value.strip())
    if path.is_absolute() or not path.parts or any(p in (".", "..") for p in path.parts):
        raise ConfigError(f"{field} must stay inside the configured vault")
    if single and len(path.parts) != 1:
        raise ConfigError(f"{field} must be a single path component")
    return path.as_posix()

def _overlaps(a: Path, b: Path) -> bool:
    ar, br = a.resolve(), b.resolve()
    return ar == br or ar in br.parents or br in ar.parents

def load_config(path) -> Config:
    cp = Path(path).expanduser().resolve()
    try: raw = json.loads(cp.read_text(encoding="utf-8"))
    except FileNotFoundError as e: raise ConfigError(f"config not found: {cp}") from e
    base = cp.parent
    src = _rp(base, raw.get("source_root", ""), "source_root")
    vault = _rp(base, raw.get("vault_root", ""), "vault_root")
    state = _rp(base, raw.get("state_dir", str(src / ".moodle-local-sync")), "state_dir")
    log = _rp(base, raw.get("changelog", str(vault / "Moodle Sync Updates.md")), "changelog")
    mp = raw.get("mappings")
    if not isinstance(mp, dict) or not mp: raise ConfigError("mappings must be non-empty object")
    seen: dict[str, str] = {}
    clean_mp: dict[str, str] = {}
    for k, v in mp.items():
        if not isinstance(v, str) or not v.strip():
            raise ConfigError(f"bad destination for {k}: must be vault-relative")
        dest_rel = _rel_name(v, f"destination for {k}")
        dest_dir = (vault / dest_rel).resolve()
        # Resolved path so "./Example" and "Example" (and symlinks) collide
        key = dest_dir.as_posix().casefold()
        if key in seen:
            raise ConfigError(
                f"destinations of {k} and {seen[key]} collide: {dest_rel} "
                f"(two courses must not share one folder)"
            )
        seen[key] = str(k)
        if _overlaps(dest_dir, src):
            raise ConfigError(f"destination for {k} must not overlap source_root")
        if not _within(vault, dest_dir):
            raise ConfigError(f"destination for {k} must stay inside vault_root")
        clean_mp[str(k)] = dest_rel
    mirror_folder = _rel_name(raw.get("mirror_folder", "99 Moodle Mirror"), "mirror_folder")
    index_filename = _rel_name(
        raw.get("index_filename", "Moodle Mirror Index.md"), "index_filename", single=True
    )
    for code, dest_rel in clean_mp.items():
        mroot = (vault / dest_rel / mirror_folder).resolve()
        if not _within(vault / dest_rel, mroot):
            raise ConfigError(f"mirror_folder escapes course destination for {code}")
        if _overlaps(mroot, src):
            raise ConfigError(f"mirror root for {code} must not overlap source_root")
    dl = _rp(base, raw["downloader"], "downloader") if raw.get("downloader") else None
    return Config(src, vault, state, log, clean_mp, mirror_folder, index_filename,
                  dl, int(raw.get("pull_retries", 3)), int(raw.get("pull_retry_seconds", 30)))
def _code(name: str):
    m = CODE_RE.search(name); return m.group(1) if m else None

def _atext(p: Path, t: str):
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tn = tempfile.mkstemp(prefix=f".{p.name}.tmp-", dir=str(p.parent)); os.close(fd)
    tmp = Path(tn)
    try:
        tmp.write_text(t, encoding="utf-8"); os.replace(tmp, p)
    finally: tmp.unlink(missing_ok=True)

def _acopy(s: Path, d: Path):
    d.parent.mkdir(parents=True, exist_ok=True)
    fd, tn = tempfile.mkstemp(prefix=".mirror-", dir=str(d.parent)); os.close(fd)
    tmp = Path(tn)
    try: shutil.copy2(s, tmp); os.replace(tmp, d)
    finally: tmp.unlink(missing_ok=True)

def _within(parent: Path, child: Path) -> bool:
    pr, cr = parent.resolve(), child.resolve()
    return cr == pr or pr in cr.parents

def _same(a: Path, b: Path) -> bool:
    sa, sb = a.stat(), b.stat()
    if sa.st_size == sb.st_size and sa.st_mtime_ns == sb.st_mtime_ns: return True
    if sa.st_size != sb.st_size: return False
    return filecmp.cmp(a, b, shallow=False)

def _link(rel: str) -> str:
    label = rel.replace("[", "").replace("]", "")
    return f"[{label}]({quote(rel, safe='/-_.~')})"

def _index(code, src_name, when, files) -> str:
    cur = sorted(p for p, i in files.items() if i["status"] == "current")
    wd = sorted(p for p, i in files.items() if i["status"] == "withdrawn")
    L = [f"> Moodle source: **{src_name}** (`{code}`)", f"> Last sync: {when}", "",
         f"## Current materials ({len(cur)})"]
    grp = None
    for r in cur:
        top = Path(r).parts[0] if "/" in r else "Course root"
        if top != grp: L += ["", f"### {top}"]; grp = top
        L.append(f"- {_link(r)}")
    L += ["", f"## Retained after Moodle removal ({len(wd)})"]
    for r in wd:
        L.append(f"- {_link(r)} — gone from source since {files[r].get('withdrawn_at','?')}")
    return "\n".join(L)

def _write_index(p: Path, code, src, when, files):
    auto = _index(code, src, when, files); block = f"{AUTO_START}\n{auto}\n{AUTO_END}"
    if p.exists():
        ex = p.read_text(encoding="utf-8"); s, e = ex.find(AUTO_START), ex.find(AUTO_END)
        merged = ex[:s] + block + ex[e+len(AUTO_END):] if s != -1 and e > s else block + "\n\n" + ex
    else: merged = f"# Moodle Mirror Index\n\n{block}\n\n## My notes\n"
    _atext(p, merged.rstrip() + "\n")

@contextmanager
def _lock(state: Path):
    state.mkdir(parents=True, exist_ok=True); h = (state / "sync.lock").open("a+")
    try:
        try: fcntl.flock(h.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as e: raise SyncBusyError("another sync is running") from e
        yield
    finally:
        try: fcntl.flock(h.fileno(), fcntl.LOCK_UN)
        finally: h.close()

def _manifest(p: Path):
    if not p.exists(): return {"version": MANIFEST_VERSION, "courses": {}}
    m = json.loads(p.read_text(encoding="utf-8"))
    if m.get("version") != MANIFEST_VERSION: raise RuntimeError("unsupported manifest")
    return m

def synchronize(cfg: Config) -> SyncResult:
    if not cfg.source_root.is_dir(): raise RuntimeError(f"source_root missing: {cfg.source_root}")
    if not cfg.vault_root.is_dir(): raise RuntimeError(f"vault_root missing: {cfg.vault_root}")
    if (cfg.source_root / "running.lock").exists():
        raise SyncBusyError("download still running; mirror not started")
    with _lock(cfg.state_dir):
        mp = _manifest(cfg.state_dir / "manifest.json"); courses = mp["courses"]
        res = SyncResult(started_at=_now())
        by_code: dict[str, list[Path]] = {}
        for it in sorted(cfg.source_root.iterdir(), key=lambda x: x.name.casefold()):
            if it.is_dir():
                c = _code(it.name)
                if c: by_code.setdefault(c, []).append(it)
        for code in sorted(by_code):
            if len(by_code[code]) > 1:
                res.duplicate_courses.append(code); continue
            src_course = by_code[code][0]; dest_name = cfg.mappings.get(code)
            if dest_name is None:
                res.unmapped_courses.append(src_course.name); continue
            res.scanned_courses.append(code)
            course_root = (cfg.vault_root / dest_name).resolve()
            if not _within(cfg.vault_root, course_root):
                raise RuntimeError(f"course destination escapes vault: {dest_name}")
            if _overlaps(course_root, cfg.source_root):
                raise RuntimeError(f"course destination overlaps source_root: {dest_name}")
            course_root.mkdir(parents=True, exist_ok=True)
            mroot = (course_root / cfg.mirror_folder).resolve()
            if not _within(course_root, mroot):
                raise RuntimeError("mirror folder escapes course destination")
            if _overlaps(mroot, cfg.source_root):
                raise RuntimeError("mirror root must not overlap source_root")
            if mroot.exists() and mroot.is_symlink():
                raise RuntimeError("mirror folder must not be a symbolic link")
            mroot.mkdir(parents=True, exist_ok=True)
            prev = courses.get(code, {}).get("files", {}); nxt: dict = {}
            srcs = sorted((x for x in src_course.rglob("*") if x.is_file() and not x.is_symlink()
                           and x.name not in CONTROL_FILES),
                          key=lambda x: x.relative_to(src_course).as_posix().casefold())
            for s in srcs:
                rel = s.relative_to(src_course).as_posix()
                if Path(rel).is_absolute() or ".." in Path(rel).parts: continue
                d = mroot / rel
                if not _within(mroot, d.parent): continue
                old = prev.get(rel); ev = None; st = s.stat()
                if not d.exists():
                    _acopy(s, d); ev = "restored" if old and old.get("status") == "withdrawn" else ("updated" if old else "added")
                elif not _same(s, d):
                    edited = old and old.get("mtime_ns") is not None and d.stat().st_mtime_ns != old["mtime_ns"]
                    if edited or old is None:
                        bak = d.with_name(d.name + LOCAL_EDIT_SUFFIX); i = 1
                        while bak.exists(): bak = d.with_name(f"{d.name}{LOCAL_EDIT_SUFFIX}.{i}"); i += 1
                        _acopy(d, bak); _acopy(s, d); ev = "conflicted"
                    else:
                        _acopy(s, d); ev = "restored" if old.get("status") == "withdrawn" else "updated"
                elif old is None: res.adopted += 1
                elif old.get("status") == "withdrawn": ev = "restored"
                else: res.unchanged += 1
                nxt[rel] = {"status": "current", "size": st.st_size, "mtime_ns": st.st_mtime_ns,
                            "first_seen": old.get("first_seen") if old else res.started_at, "last_seen": res.started_at}
                if ev: setattr(res, ev, getattr(res, ev) + 1); res.events.append({"type": ev, "course": code, "path": rel})
            for rel, old in prev.items():
                if rel in nxt: continue
                r = dict(old)
                if old.get("status") != "withdrawn":
                    r["withdrawn_at"] = res.started_at; res.withdrawn += 1
                    res.events.append({"type": "withdrawn", "course": code, "path": rel})
                r["status"] = "withdrawn"; nxt[rel] = r
            courses[code] = {"source_name": src_course.name, "destination": dest_name,
                             "last_scanned": res.started_at, "files": nxt}
            _write_index(mroot / cfg.index_filename, code, src_course.name, res.started_at, nxt)
        for code in sorted(courses):
            if code not in by_code: res.missing_courses.append(code)
        res.finished_at = _now(); mp["last_successful_sync"] = res.finished_at
        lines = [f"\n## Sync {res.finished_at}",
                 f"- Added {res.added} · Updated {res.updated} · Restored {res.restored} · Withdrawn {res.withdrawn} · Conflicted {res.conflicted} · Adopted {res.adopted} · Unchanged {res.unchanged}"]
        for e in res.events: lines.append(f"- {e['type']} `{e['course']}` {e['path']}")
        for u in res.unmapped_courses: lines.append(f"- UNMAPPED {u}")
        for d_ in res.duplicate_courses: lines.append(f"- DUPLICATE {d_} (skipped)")
        _atext(cfg.state_dir / "manifest.json", json.dumps(mp, ensure_ascii=False, indent=2) + "\n")
        _atext(cfg.state_dir / "last-run.json", json.dumps(res.as_dict(), ensure_ascii=False, indent=2) + "\n")
        old_log = cfg.changelog.read_text(encoding="utf-8") if cfg.changelog.exists() else "# Moodle Sync Updates\n"
        _atext(cfg.changelog, old_log.rstrip() + "\n" + "\n".join(lines) + "\n")
        return res

def _next_hint(cfg: Config, result: dict | None = None, *, failed: str | None = None) -> str:
    """One actionable next step for humans / agents."""
    if failed == "pull":
        return "先修好 moodle-dl（token / download_course_ids / 网络），再跑 run；或改用 sync 只映射已有缓存"
    if failed == "no_downloader":
        return "要拉取：在 moodle-mirror.json 填 downloader，并完成 moodle-sync/config.json；只要映射：改跑 sync"
    if failed == "config":
        return "按上方报错改 moodle-mirror.json（路径 / mappings / mirror_folder），再 doctor"
    if failed == "busy":
        return "等待当前下载结束；确认无 moodle-dl 进程后再删 running.lock"
    if result:
        if result.get("unmapped_courses"):
            return "把 UNMAPPED 课号写进 mappings，再跑 sync（只需②映射）"
        if result.get("duplicate_courses"):
            return "下载树里同课号多文件夹，先理清 moodle-sync 后再 sync"
        if result.get("conflicted", 0):
            return "打开对应 *.local-edit.bak 对比本地修改；确认后可继续用 Obsidian 看 99 Moodle Mirror"
        if result.get("added", 0) or result.get("updated", 0) or result.get("restored", 0):
            return "在 Obsidian 打开各课「99 Moodle Mirror」；若要全文搜 Word/PPT，再说「生成伴生 md」"
        return "本轮无文件变化。有新课件时再 run；只要重映缓存则 sync"
    if not cfg.downloader:
        return "配置齐全后可 sync（只映射）；若要联网拉取，先填 downloader 再 run"
    return "可执行 run（①拉取+②映射）或 sync（只②）"

def _print_guide(cfg: Config, *, mode: str, result: dict | None = None, failed: str | None = None) -> None:
    """Human-facing where/what-next block (same shape for CLI and agents)."""
    if mode == "run":
        stage = "①拉取 + ②映射" if not failed else "①拉取（失败，镜像未改）"
    elif mode == "sync":
        stage = "②映射"
    elif mode == "doctor":
        stage = "自检 doctor"
    else:
        stage = mode
    status = "失败" if failed else "成功"
    print("")
    print(f"{'❌' if failed else '✅'} 本轮：{stage} — {status}")
    print(f"📁 缓存（①）：{cfg.source_root}")
    print(f"📁 笔记库根：{cfg.vault_root}")
    print(f"📝 更新记录：{cfg.changelog}")
    if result and result.get("scanned_courses"):
        print("📁 已进库镜像（②）：")
        for code in result["scanned_courses"]:
            dest = cfg.mappings.get(code)
            if not dest:
                continue
            mroot = cfg.vault_root / dest / cfg.mirror_folder
            print(f"   - {code} → {mroot}")
    if result:
        print(
            f"📊 计数：+{result.get('added', 0)} 新增 · ~{result.get('updated', 0)} 更新 · "
            f"{result.get('restored', 0)} 恢复 · {result.get('withdrawn', 0)} 撤回留底 · "
            f"{result.get('conflicted', 0)} 冲突备份"
        )
        for u in result.get("unmapped_courses") or []:
            print(f"   · UNMAPPED {u}")
        for d in result.get("duplicate_courses") or []:
            print(f"   · DUPLICATE {d}")
    print(f"👉 下一步：{_next_hint(cfg, result, failed=failed)}")

def _doctor(cfg: Config) -> int:
    ok = True
    for good, msg in [(cfg.source_root.is_dir(), f"source_root: {cfg.source_root}"),
                      (cfg.vault_root.is_dir(), f"vault_root: {cfg.vault_root}"),
                      (bool(cfg.mappings), f"mappings: {len(cfg.mappings)}")]:
        print(f"{'OK' if good else 'ISSUE'}  {msg}"); ok &= good
    if cfg.downloader:
        exe = cfg.downloader.is_file() and os.access(cfg.downloader, os.X_OK)
        print(f"{'OK' if exe else 'ISSUE'}  downloader: {cfg.downloader}"); ok &= exe
    else: print("OK  downloader: not configured (sync-only mode)")
    busy = (cfg.source_root / "running.lock").exists()
    print(f"{'BUSY' if busy else 'OK'}  download lock")
    if busy:
        ok = False
        _print_guide(cfg, mode="doctor", failed="busy")
    elif not ok:
        _print_guide(cfg, mode="doctor", failed="config")
    else:
        _print_guide(cfg, mode="doctor")
    return 0 if ok else 2

def _pull(cfg: Config) -> int:
    if cfg.downloader is None:
        print("mirror.py: no downloader configured (sync-only mode).", file=sys.stderr)
        print("To enable 'run': set 'downloader' to your moodle-dl binary AND configure", file=sys.stderr)
        print("moodle-dl itself (moodle-sync/config.json via 'moodle-dl --init': moodle_domain,", file=sys.stderr)
        print("download_course_ids, token). Or use 'sync' to mirror an existing snapshot.", file=sys.stderr)
        return 2
    for a in range(1, cfg.pull_retries + 1):
        c = subprocess.run([str(cfg.downloader), "-q"], cwd=cfg.source_root,
                           capture_output=True, text=True)
        out = re.sub(r"(?i)((?:token|password|cookie)=)[^&\s]+", r"\1[REDACTED]", (c.stdout or "") + (c.stderr or ""))
        if out: sys.stderr.write(out)
        if c.returncode == 0: return 0
        if a < cfg.pull_retries: time.sleep(cfg.pull_retry_seconds)
    return c.returncode or 1

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="mirror.py"); ap.add_argument("--config", required=True, type=Path)
    sp = ap.add_subparsers(dest="cmd", required=True)
    sp.add_parser("doctor"); s = sp.add_parser("status"); s.add_argument("--json", action="store_true")
    sp.add_parser("sync"); sp.add_parser("run")
    a = ap.parse_args(argv)
    cfg = None
    try:
        cfg = load_config(a.config)
        if a.cmd == "doctor": return _doctor(cfg)
        if a.cmd == "status":
            p = cfg.state_dir / "last-run.json"
            if not p.exists():
                print("no completed sync yet")
                print(f"📁 缓存（①）：{cfg.source_root}")
                print(f"📁 笔记库根：{cfg.vault_root}")
                print(f"👉 下一步：先 run 或 sync 完成首轮同步")
                return 1
            d = json.loads(p.read_text(encoding="utf-8"))
            print(json.dumps(d, ensure_ascii=False, indent=2) if a.json else
                  f"+{d['added']} added ~{d['updated']} updated, {d['restored']} restored, "
                  f"{d['withdrawn']} withdrawn, {d.get('conflicted',0)} conflicted, "
                  f"{d.get('adopted',0)} adopted, {d['unchanged']} unchanged @ {d['finished_at']}")
            if not a.json:
                _print_guide(cfg, mode="sync", result=d)
            return 0
        mode = "run" if a.cmd == "run" else "sync"
        if a.cmd == "run":
            rc = _pull(cfg)
            if rc != 0:
                print("pull failed; mirror unchanged", file=sys.stderr)
                fail = "no_downloader" if cfg.downloader is None else "pull"
                _print_guide(cfg, mode="run", failed=fail)
                return rc
        r = synchronize(cfg).as_dict()
        print(f"mirror done: +{r['added']} added ~{r['updated']} updated, {r['restored']} restored, "
              f"{r['withdrawn']} withdrawn, {r['conflicted']} conflicted, "
              f"{r['adopted']} adopted, {r['unchanged']} unchanged")
        _print_guide(cfg, mode=mode, result=r)
        return 0
    except (ConfigError, RuntimeError, OSError) as e:
        print(f"mirror.py: {e}", file=sys.stderr)
        if cfg is not None:
            fail = "busy" if isinstance(e, SyncBusyError) else "config"
            _print_guide(cfg, mode=getattr(a, "cmd", "sync"), failed=fail)
        else:
            print("👉 下一步：检查 --config 路径与 moodle-mirror.json 是否可读")
        return 3 if isinstance(e, SyncBusyError) else 2

if __name__ == "__main__":
    raise SystemExit(main())
