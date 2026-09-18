#!/usr/bin/env python3
"""Portable Moodle exact-mirror: snapshot -> <course>/99 Moodle Mirror/.

Slim port of moodle-local-sync/core.py + cli.py for the skill.
Generic course codes (e.g. PCLL8010, LAWS1234, COMP1111), relative paths only.
No LLM, no secrets in logs. Per-user config, chmod 600 recommended.
"""
from __future__ import annotations

import argparse
import fcntl
import filecmp
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

AUTO_START = "<!-- MOODLE-LOCAL-SYNC:AUTO:START -->"
AUTO_END = "<!-- MOODLE-LOCAL-SYNC:AUTO:END -->"
MANIFEST_VERSION = 1
CONTROL_FILES = {".DS_Store", "desktop.ini", "Thumbs.db"}
CODE_RE = re.compile(r"([A-Z]{2,10}\d{3,}[A-Z]?)")
CONFLICTS_DIRNAME = "conflicts"

# Pull-outcome signals, verified against moodle-dl 2.3.x default-verbosity output.
# - "is no longer available online": moodle_service.py WARNING (swallowed by -q)
# - "Error while trying to download files": console notify_about_failed_downloads
# - "The following error occurred during execution": notify_about_error
# - "Traceback ...": uncaught exception (usually also rc != 0)
PULL_FAILURE_SIGNALS = (
    "is no longer available online",
    "Error while trying to download files",
    "The following error occurred during execution",
    "Traceback (most recent call last)",
)
SUPPORTED_DL = (2, 3)  # (major, minor) whose output the signals above are pinned to
_DL_VERSION_RE = re.compile(r"moodle-dl\s+(\d+)\.(\d+)(?:\.(\d+))?")
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
_SECRET_QUERY = re.compile(r"(?i)((?:wstoken|token|privatetoken|password|cookie|autologinkey)=)[^&\s]+")
_SECRET_ASSIGN = re.compile(
    r"(?i)\b(wstoken|token|privatetoken|password|cookie|autologinkey)\b"
    r"(\s*[:=]\s*)(\"[^\"]*\"|'[^']*'|[^\s,;]+)"
)

class MirrorError(Exception):
    """Base for classified mirror failures (each branch gets its own next step)."""


class ConfigError(MirrorError, ValueError):
    """Bad config content: paths, mappings, mirror_folder. Fix the JSON."""


class MirrorStateError(MirrorError, RuntimeError):
    """State/integrity problems: corrupt manifest, bad last-run, broken markers."""


class MirrorEnvError(MirrorError, RuntimeError):
    """Environment problems: missing dirs, locks, permissions."""


class SyncBusyError(MirrorEnvError):
    """Another sync/download holds the lock."""

@dataclass(frozen=True)
class Config:
    source_root: Path
    vault_root: Path
    state_dir: Path
    changelog: Path
    mappings: dict
    ignored: tuple = ()
    mirror_folder: str = "99 Moodle Mirror"
    index_filename: str = "Moodle Mirror Index.md"
    downloader: Path | None = None
    pull_retries: int = 3
    pull_retry_seconds: int = 30


@dataclass
class SyncResult:
    started_at: str
    finished_at: str = ""
    added: int = 0
    updated: int = 0
    restored: int = 0
    withdrawn: int = 0
    conflicted: int = 0
    adopted: int = 0
    unchanged: int = 0
    scanned_courses: list = field(default_factory=list)
    unmapped_courses: list = field(default_factory=list)
    duplicate_courses: list = field(default_factory=list)
    missing_courses: list = field(default_factory=list)
    unrecognized_courses: list = field(default_factory=list)
    ignored_courses: list = field(default_factory=list)
    skipped_symlinks: int = 0
    recovered: bool = False
    incomplete: bool = False
    pull_verdict: str = "n/a"
    events: list = field(default_factory=list)

    def as_dict(self):
        d = asdict(self)
        if (self.incomplete or self.unmapped_courses or self.duplicate_courses
                or self.unrecognized_courses):
            d["status"] = "incomplete"
        elif self.recovered:
            d["status"] = "recovered"
        elif self.pull_verdict == "unverified":
            d["status"] = "unverified"
        else:
            d["status"] = "success"
        return d


def _now():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _rp(base: Path, v: str, f: str) -> Path:
    if not isinstance(v, str) or not v.strip():
        raise ConfigError(f"{f} must be non-empty")
    p = Path(v).expanduser()
    return p if p.is_absolute() else (base / p).resolve()

def _rel_name(value, field: str, *, single: bool = False) -> str:
    """Vault-relative name: no absolute, no '.'/'..' components."""
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{field} must be a non-empty relative path")
    path = Path(value.strip())
    if not path.parts:
        raise ConfigError(f"{field}: got {value!r} — name a real folder, not '.' or empty")
    if path.is_absolute() or any(p in (".", "..") for p in path.parts):
        raise ConfigError(f"{field} must stay inside the configured vault")
    if single and len(path.parts) != 1:
        raise ConfigError(f"{field} must be a single path component")
    return path.as_posix()

def _overlaps(a: Path, b: Path) -> bool:
    ar, br = a.resolve(), b.resolve()
    return ar == br or ar in br.parents or br in ar.parents

def load_config(path) -> Config:
    cp = Path(path).expanduser().resolve()
    try:
        raw = json.loads(cp.read_text(encoding="utf-8"))
    except FileNotFoundError as e:
        raise ConfigError(f"config not found: {cp}") from e
    except ValueError as e:
        raise ConfigError(f"config is not valid JSON: {cp} ({e})") from e
    if not isinstance(raw, dict):
        raise ConfigError(f"config root must be an object: {cp}")
    base = cp.parent
    src = _rp(base, raw.get("source_root", ""), "source_root")
    vault = _rp(base, raw.get("vault_root", ""), "vault_root")
    scan_root = _scan_root_for(src)
    state = _rp(base, raw.get("state_dir", str(src / ".moodle-local-sync")), "state_dir")
    log = _rp(base, raw.get("changelog", str(vault / "Moodle Sync Updates.md")), "changelog")
    mp = raw.get("mappings")
    if not isinstance(mp, dict) or not mp:
        raise ConfigError("mappings must be non-empty object")
    seen: dict[str, str] = {}
    clean_mp: dict[str, str] = {}
    ignored: list[str] = []
    for k, v in mp.items():
        if not isinstance(k, str) or not k.strip():
            raise ConfigError(f"bad mapping key: {k!r}")
        if v is None:
            ignored.append(str(k))  # explicitly ignored: skipped silently-ish
            continue
        if not isinstance(v, str) or not v.strip():
            raise ConfigError(f"bad destination for {k}: must be vault-relative or null")
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
        if _overlaps(dest_dir, src) or _overlaps(dest_dir, scan_root):
            raise ConfigError(f"destination for {k} must not overlap source_root")
        if not _within(vault, dest_dir):
            raise ConfigError(f"destination for {k} must stay inside vault_root")
        clean_mp[str(k)] = dest_rel
    if not clean_mp and not ignored:
        raise ConfigError("mappings must contain at least one destination or one null ignore")
    mirror_folder = _rel_name(raw.get("mirror_folder", "99 Moodle Mirror"), "mirror_folder")
    index_filename = _rel_name(
        raw.get("index_filename", "Moodle Mirror Index.md"), "index_filename", single=True
    )
    for code, dest_rel in clean_mp.items():
        mroot = (vault / dest_rel / mirror_folder).resolve()
        if not _within(vault / dest_rel, mroot):
            raise ConfigError(f"mirror_folder escapes course destination for {code}")
        if _overlaps(mroot, src) or _overlaps(mroot, scan_root):
            raise ConfigError(f"mirror root for {code} must not overlap source_root")
    try:
        retries = int(raw.get("pull_retries", 3))
        retry_secs = int(raw.get("pull_retry_seconds", 30))
    except (TypeError, ValueError) as e:
        raise ConfigError("pull_retries / pull_retry_seconds must be integers") from e
    if retries < 1 or retry_secs < 0:
        raise ConfigError("pull_retries must be >= 1 and pull_retry_seconds >= 0")
    dl = _rp(base, raw["downloader"], "downloader") if raw.get("downloader") else None
    return Config(src, vault, state, log, clean_mp, tuple(ignored), mirror_folder, index_filename,
                  dl, retries, retry_secs)
def _code(name: str):
    m = CODE_RE.search(name)
    return m.group(1) if m else None

def _default_text_mode():
    um = os.umask(0)
    os.umask(um)
    return 0o644 & ~um


def _atext(p: Path, t: str):
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tn = tempfile.mkstemp(prefix=f".{p.name}.tmp-", dir=str(p.parent))
    os.close(fd)
    tmp = Path(tn)
    try:
        with tmp.open("w", encoding="utf-8") as handle:
            handle.write(t)
            handle.flush()
            os.fsync(handle.fileno())
        # mkstemp yields 0600; text products (index, changelog, manifest)
        # follow the process umask like a normal editor save. _acopy keeps
        # source permissions untouched (deliberate, do not "fix" it here).
        os.chmod(tmp, _default_text_mode())
        os.replace(tmp, p)
    finally:
        tmp.unlink(missing_ok=True)

def _acopy(s: Path, d: Path):
    d.parent.mkdir(parents=True, exist_ok=True)
    fd, tn = tempfile.mkstemp(prefix=".mirror-", dir=str(d.parent))
    os.close(fd)
    tmp = Path(tn)
    try:
        shutil.copy2(s, tmp)
        os.replace(tmp, d)
    finally:
        tmp.unlink(missing_ok=True)

def _conflict_backup(state_dir: Path, code: str, rel: str, current_mirror: Path) -> str:
    """Shelve the locally-edited mirror copy under state_dir/conflicts/.

    Returns the state-relative backup path for the changelog. The mirror tree
    itself stays clean of *.bak files. Pre-existing legacy *.local-edit.bak
    files are left untouched."""
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = state_dir / CONFLICTS_DIRNAME / code / (rel + f".{stamp}.bak")
    if dest.exists():
        i = 1
        while True:
            cand = state_dir / CONFLICTS_DIRNAME / code / (rel + f".{stamp}.{i}.bak")
            if not cand.exists():
                dest = cand
                break
            i += 1
    _acopy(current_mirror, dest)
    return dest.relative_to(state_dir).as_posix()


def _within(parent: Path, child: Path) -> bool:
    pr, cr = parent.resolve(), child.resolve()
    return cr == pr or pr in cr.parents

def _same(a: Path, b: Path) -> bool:
    sa, sb = a.stat(), b.stat()
    if sa.st_size == sb.st_size and sa.st_mtime_ns == sb.st_mtime_ns:
        return True
    if sa.st_size != sb.st_size:
        return False
    return filecmp.cmp(a, b, shallow=False)

def _link(rel: str) -> str:
    label = rel.replace("[", "").replace("]", "")
    return f"[{label}]({quote(rel, safe='/-_.~')})"

def _index(code, src_name, when, files) -> str:
    cur = sorted(p for p, i in files.items() if i["status"] == "current")
    wd = sorted(p for p, i in files.items() if i["status"] == "withdrawn")
    L = [f"> Moodle source: **{src_name}** (`{code}`)", f"> Last sync: {when}", "",
         f"## Current materials ({len(cur)})"]
    # Group root-level files first under one heading, then per top folder.
    # (Ordered dict: each group title appears exactly once.)
    groups: dict[str, list[str]] = {}
    for r in cur:
        top = Path(r).parts[0] if "/" in r else "Course root"
        groups.setdefault(top, []).append(r)
    ordered = (["Course root"] if "Course root" in groups else []) + \
              sorted(g for g in groups if g != "Course root")
    for top in ordered:
        L += ["", f"### {top}"]
        L += [f"- {_link(r)}" for r in groups[top]]
    L += ["", f"## Retained after Moodle removal ({len(wd)})"]
    for r in wd:
        L.append(f"- {_link(r)} — gone from source since {files[r].get('withdrawn_at','?')}")
    return "\n".join(L)

def _write_index(p: Path, code, src, when, files) -> None:
    auto = _index(code, src, when, files)
    block = f"{AUTO_START}\n{auto}\n{AUTO_END}"
    if p.exists():
        existing = p.read_text(encoding="utf-8")
        starts = existing.count(AUTO_START)
        ends = existing.count(AUTO_END)
        if (starts, ends) != (1, 1):
            raise MirrorStateError(
                f"index markers broken in {p} (START x{starts}, END x{ends}, want 1 each): "
                "user text may contain a stray marker. Remove the extra AUTO block "
                "(keep handwritten notes), then re-run sync. Nothing was overwritten.")
        s, e = existing.find(AUTO_START), existing.find(AUTO_END)
        merged = existing[:s] + block + existing[e + len(AUTO_END):]
    else:
        merged = f"# Moodle Mirror Index\n\n{block}\n\n## My notes\n"
    _atext(p, merged.rstrip() + "\n")

@contextmanager
def _lock(state: Path):
    state.mkdir(parents=True, exist_ok=True)
    h = (state / "sync.lock").open("a+")
    try:
        try:
            fcntl.flock(h.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as e:
            raise SyncBusyError("another sync is running") from e
        yield
    finally:
        try:
            fcntl.flock(h.fileno(), fcntl.LOCK_UN)
        finally:
            h.close()

def _manifest(p: Path):
    """Load manifest. Returns (manifest, reset_note).

    A corrupt file is NEVER parsed in place: it is renamed to
    manifest.json.corrupt-<ts> and sync restarts from empty (everything
    already mirrored is then counted as adopted, visibly)."""
    if not p.exists():
        return {"version": MANIFEST_VERSION, "courses": {}}, None
    try:
        m = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        bak = p.with_name(f"{p.name}.corrupt-{stamp}")
        try:
            p.rename(bak)
        except OSError as ee:
            raise MirrorStateError(f"manifest unreadable and cannot back it up: {ee}") from ee
        note = (f"manifest was corrupt ({type(e).__name__}), preserved as "
                f"{bak.name}; restarting history — mirrored files count as adopted")
        return {"version": MANIFEST_VERSION, "courses": {}}, note
    if m.get("version") != MANIFEST_VERSION or not isinstance(m.get("courses"), dict):
        raise MirrorStateError(
            f"unsupported manifest in {p} (version {m.get('version')!r}). "
            "Recovery: inspect it, then either restore from backup or move it aside "
            f"(e.g. mv {p.name} {p.name}.bak) and re-run sync; mirrored files will "
            "be adopted, never deleted.")
    return m, None

def _resolve_identity(cfg: Config, code: str | None, dirname: str):
    """Map a source folder to (identity, destination, ignored).

    identity is the course code, or 'name:<dirname>' when moodle-dl named the
    folder from course.fullname without a code. mappings accepts both keys;
    a null value means explicitly ignored."""
    ident = code if code else f"name:{dirname}"
    if (code and code in cfg.ignored) or dirname in cfg.ignored:
        return ident, None, True
    dest = (cfg.mappings.get(code) if code else None) or cfg.mappings.get(dirname)
    return ident, dest, False


def _read_dl_raw(cfg: Config) -> dict:
    """moodle-dl's own config, best-effort (missing/corrupt -> {})."""
    try:
        raw = json.loads((cfg.source_root / "config.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return raw if isinstance(raw, dict) else {}


def _resolve_under(base: Path, value) -> Path | None:
    if not value or not isinstance(value, str) or not value.strip():
        return None
    p = Path(value.strip())
    return p if p.is_absolute() else (base / p)


def _scan_root_for(source_root: Path) -> Path:
    """Effective download dir: dl config download_path or source_root itself.

    Mirrors upstream (cwd-relative since we invoke the downloader with
    cwd=source_root and no --path flag)."""
    try:
        raw = json.loads((source_root / "config.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return source_root
    if not isinstance(raw, dict):
        return source_root
    dp = raw.get("download_path")
    if not dp or not isinstance(dp, str) or not dp.strip():
        return source_root
    p = Path(dp.strip())
    return (p if p.is_absolute() else (source_root / p)).resolve()


def _effective_dl_dirs(cfg: Config):
    """(scan_root, lock_file, notes) honoring dl config overrides.

    Upstream resolves download_path/misc_files_path against its cwd, which is
    source_root in our `_pull` invocation — so relative values resolve the
    same way here. If you override download_path, keep it inside source_root
    or point source_root at it; the manifest is relative to the scan root."""
    raw = _read_dl_raw(cfg)
    scan = _scan_root_for(cfg.source_root)
    notes = []
    if scan != cfg.source_root.resolve():
        notes.append(f"scanning {scan} (dl config download_path override)")
    misc = _resolve_under(cfg.source_root, raw.get("misc_files_path"))
    lock_base = misc if misc is not None else cfg.source_root
    if misc is not None:
        notes.append(f"lock dir {lock_base} (dl config misc_files_path override)")
    return scan.resolve(), (lock_base.resolve() / "running.lock"), notes


def _internal_dirs(cfg: Config, scan_root: Path) -> list[Path]:
    """Dirs inside the scan root that are ours, never courses.

    Default template keeps state_dir inside source_root; a misc_files_path
    override may add another. Without this, the state dir itself would be
    reported UNRECOGNIZED and poison every default-layout run."""
    out = []
    cand = cfg.state_dir.resolve()
    try:
        cand.relative_to(scan_root)
        out.append(cand)
    except ValueError:
        pass
    raw = _read_dl_raw(cfg)
    misc = _resolve_under(cfg.source_root, raw.get("misc_files_path"))
    if misc is not None:
        misc = misc.resolve()
        if misc != scan_root:
            try:
                misc.relative_to(scan_root)
                out.append(misc)
            except ValueError:
                pass
    return out


def _is_internal(path: Path, internal: list[Path]) -> bool:
    rp = path.resolve()
    return any(rp == ex or ex in rp.parents for ex in internal)


def _check_indexes(cfg: Config, planned: dict) -> None:
    """Pre-flight: validate AUTO markers of every index about to be rewritten.

    Runs BEFORE any file is copied so a broken index aborts the run with
    mirror, manifest and changelog all untouched."""
    for dest in planned.values():
        idx = cfg.vault_root / dest / cfg.mirror_folder / cfg.index_filename
        if not idx.exists():
            continue
        try:
            txt = idx.read_text(encoding="utf-8")
        except OSError as e:
            raise MirrorStateError(f"cannot read index {idx}: {e}") from e
        starts, ends = txt.count(AUTO_START), txt.count(AUTO_END)
        if (starts, ends) != (1, 1):
            raise MirrorStateError(
                f"index markers broken in {idx} (START x{starts}, END x{ends}, "
                "want 1 each). Nothing in this run was changed: no mirror files "
                "copied, manifest and changelog untouched. Remove the extra AUTO "
                "block (keep handwritten notes), then re-run sync.")


def synchronize(cfg: Config, pull_verdict: str = "n/a") -> SyncResult:
    if not cfg.source_root.is_dir():
        raise MirrorEnvError(f"source_root missing: {cfg.source_root}")
    if not cfg.vault_root.is_dir():
        raise MirrorEnvError(f"vault_root missing: {cfg.vault_root}")
    scan_root, lock_file, dl_notes = _effective_dl_dirs(cfg)
    if not scan_root.is_dir():
        raise MirrorEnvError(f"effective scan dir missing: {scan_root}")
    if lock_file.exists():
        raise SyncBusyError("download still running; mirror not started")
    with _lock(cfg.state_dir):
        for n in dl_notes:
            print(f"note: {n}")
        mp, reset_note = _manifest(cfg.state_dir / "manifest.json")
        courses = mp["courses"]
        res = SyncResult(started_at=_now(), pull_verdict=pull_verdict)
        if reset_note:
            res.recovered = True
            print(f"⚠️ {reset_note}", file=sys.stderr)
        by_code: dict[str, list[Path]] = {}
        dirnames: dict[str, str] = {}
        internal = _internal_dirs(cfg, scan_root)
        for it in sorted(scan_root.iterdir(), key=lambda x: x.name.casefold()):
            if not it.is_dir() or _is_internal(it, internal):
                continue
            c = _code(it.name)
            ident = c if c else f"name:{it.name}"
            by_code.setdefault(ident, []).append(it)
            dirnames[ident] = it.name
        planned: dict[str, str] = {}
        for ident, paths in by_code.items():
            if len(paths) != 1:
                continue
            name = dirnames[ident]
            code = None if ident.startswith("name:") else ident
            _, dest, ignored_flag = _resolve_identity(cfg, code, name)
            if dest is not None and not ignored_flag:
                planned[ident] = dest
        _check_indexes(cfg, planned)
        for code in sorted(by_code):
            if len(by_code[code]) > 1:
                res.duplicate_courses.append(dirnames[code])
                continue
            src_course = by_code[code][0]
            name = dirnames[code]
            ident, dest_name, ignored_flag = _resolve_identity(
                cfg, None if code.startswith("name:") else code, name)
            if ignored_flag:
                res.ignored_courses.append(name)
                continue
            if dest_name is None:
                if code.startswith("name:"):
                    res.unrecognized_courses.append(name)
                else:
                    res.unmapped_courses.append(name)
                continue
            label = code if not code.startswith("name:") else name
            res.scanned_courses.append(label)
            course_root = (cfg.vault_root / dest_name).resolve()
            if not _within(cfg.vault_root, course_root):
                raise ConfigError(f"course destination escapes vault: {dest_name}")
            if _overlaps(course_root, cfg.source_root):
                raise ConfigError(f"course destination overlaps source_root: {dest_name}")
            course_root.mkdir(parents=True, exist_ok=True)
            mroot = (course_root / cfg.mirror_folder).resolve()
            if not _within(course_root, mroot):
                raise ConfigError("mirror folder escapes course destination")
            if _overlaps(mroot, cfg.source_root):
                raise ConfigError("mirror root must not overlap source_root")
            if mroot.exists() and mroot.is_symlink():
                raise MirrorEnvError("mirror folder must not be a symbolic link")
            mroot.mkdir(parents=True, exist_ok=True)
            prev = courses.get(code, {}).get("files", {})
            nxt: dict = {}
            for link in sorted(src_course.rglob("*")):
                if link.is_symlink():
                    rel = link.relative_to(src_course).as_posix()
                    res.skipped_symlinks += 1
                    res.events.append({
                        "type": "skipped-symlink", "course": label, "path": rel,
                    })
            srcs = sorted((x for x in src_course.rglob("*") if x.is_file() and not x.is_symlink()
                           and x.name not in CONTROL_FILES),
                          key=lambda x: x.relative_to(src_course).as_posix().casefold())
            # Empty section folders carry no files but are part of the native
            # tree: recreate them so the mirror is structurally complete.
            # (A folder holding only control files/symlinks counts as empty:
            # neither is ever mirrored as content.)
            for d_empty in sorted(src_course.rglob("*")):
                if not (d_empty.is_dir() and not d_empty.is_symlink()):
                    continue
                try:
                    children = list(d_empty.iterdir())
                except OSError:
                    continue
                if not any(p.name not in CONTROL_FILES and not p.is_symlink()
                           for p in children):
                    (mroot / d_empty.relative_to(src_course)).mkdir(
                        parents=True, exist_ok=True)
            for s in srcs:
                rel = s.relative_to(src_course).as_posix()
                if Path(rel).is_absolute() or ".." in Path(rel).parts:
                    continue
                d = mroot / rel
                if not _within(mroot, d.parent):
                    continue
                old = prev.get(rel)
                ev = None
                st = s.stat()
                backup_rel = None
                if not d.exists():
                    _acopy(s, d)
                    if old and old.get("status") == "withdrawn":
                        ev = "restored"
                    elif old:
                        ev = "updated"
                    else:
                        ev = "added"
                elif not _same(s, d):
                    edited = old and old.get("mtime_ns") is not None and d.stat().st_mtime_ns != old["mtime_ns"]
                    if edited or old is None:
                        backup_rel = _conflict_backup(cfg.state_dir, label, rel, d)
                        _acopy(s, d)
                        ev = "conflicted"
                    else:
                        _acopy(s, d)
                        ev = ("restored"
                              if old.get("status") == "withdrawn"
                              else "updated")
                elif old is None:
                    res.adopted += 1
                    res.events.append({"type": "adopted", "course": label, "path": rel})
                elif old.get("status") == "withdrawn":
                    ev = "restored"
                else:
                    res.unchanged += 1
                nxt[rel] = {"status": "current", "size": st.st_size, "mtime_ns": st.st_mtime_ns,
                            "first_seen": old.get("first_seen") if old else res.started_at, "last_seen": res.started_at}
                if ev:
                    setattr(res, ev, getattr(res, ev) + 1)
                    evt = {"type": ev, "course": label, "path": rel}
                    if backup_rel:
                        evt["backup"] = backup_rel
                    res.events.append(evt)
            for rel, old in prev.items():
                if rel in nxt:
                    continue
                r = dict(old)
                if old.get("status") != "withdrawn":
                    r["withdrawn_at"] = res.started_at
                    res.withdrawn += 1
                    res.events.append({"type": "withdrawn", "course": label, "path": rel})
                r["status"] = "withdrawn"
                nxt[rel] = r
            courses[code] = {"source_name": src_course.name, "destination": dest_name,
                             "last_scanned": res.started_at, "files": nxt}
            _write_index(mroot / cfg.index_filename, label, src_course.name, res.started_at, nxt)
        for code in sorted(courses):
            if code not in by_code:
                res.missing_courses.append(code)
                res.incomplete = True
        res.finished_at = _now()
        if res.unmapped_courses or res.duplicate_courses or res.unrecognized_courses:
            res.incomplete = True
        summary = res.as_dict()
        # last_successful_sync means "last fully-verified incremental sync".
        # Incomplete / recovered / unverified runs write manifest + last-run
        # (with their honest status) but must NOT advance the stamp.
        if summary["status"] == "success":
            mp["last_successful_sync"] = res.finished_at
        if reset_note:
            res.events.append({"type": "note", "course": "-", "path": reset_note})
        lines = [f"\n## Sync {res.finished_at}",
                 f"- Added {res.added} · Updated {res.updated} · Restored {res.restored} · "
                 f"Withdrawn {res.withdrawn} · Conflicted {res.conflicted} · "
                 f"Adopted {res.adopted} · Unchanged {res.unchanged}"]
        if res.skipped_symlinks:
            lines.append(f"- Skipped {res.skipped_symlinks} symlink(s) "
                         "(not followed, listed as skipped-symlink events)")
        for e in res.events:
            if e["type"] == "note":
                lines.append(f"- ⚠️ {e['path']}")
            elif e["type"] == "conflicted" and e.get("backup"):
                lines.append(f"- conflicted `{e['course']}` {e['path']} "
                             f"(local copy kept at state:{e['backup']})")
            else:
                lines.append(f"- {e['type']} `{e['course']}` {e['path']}")
        for u in res.unmapped_courses:
            lines.append(f"- UNMAPPED {u}")
        for d_ in res.duplicate_courses:
            lines.append(f"- DUPLICATE {d_} (skipped)")
        for g in res.unrecognized_courses:
            lines.append(f"- UNRECOGNIZED {g} (no course code in folder name and no "
                         "literal mapping; map the folder name or set it to null to ignore)")
        for g in res.ignored_courses:
            lines.append(f"- IGNORED {g}")
        for m in res.missing_courses:
            lines.append(f"- MISSING-COURSE `{m}` (source folder vanished; "
                         "local mirror retained, NOT withdrawn)")
        if summary["status"] != "success":
            lines.append(f"- run status: {summary['status']} (not a verified incremental "
                         "sync; last_successful_sync untouched)")
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
    if failed == "run_not_ready":
        return ("按上方 NOT READY 原因修好 moodle-dl 配置（--init / token / course_ids / "
                "downloader 路径），当前只能 sync；不要跑 run")
    if failed == "downloader_not_found":
        return "检查 moodle-mirror.json 中的 downloader 路径是否存在可执行，然后重新运行 doctor"
    if failed == "config":
        return "按上方报错改 moodle-mirror.json（路径 / mappings / mirror_folder），再 doctor"
    if failed == "state":
        return "状态文件异常：按上方指引检查 state_dir（损坏文件已自动留底），恢复后重跑 sync"
    if failed == "env":
        return "运行环境问题（目录 / 锁 / 权限）：按上方报错处理后重试"
    if failed == "busy":
        return "等待当前下载结束；确认无 moodle-dl 进程后再删 running.lock"
    if result:
        if result.get("unrecognized_courses"):
            return ("有课程目录无法识别（无课程代码）：把字面目录名写入 mappings "
                    "（或置 null 忽略），再跑 sync")
        if result.get("unmapped_courses") or result.get("duplicate_courses"):
            return ("有未映射/重复课程：写入 mappings（字面目录名亦可）或置 null 忽略，"
                    "再跑 sync；此前轮次不计成功")
        if result.get("missing_courses"):
            return ("源课程目录消失（下载不完整或已撤课）：先检查 moodle-sync 下该课文件夹，"
                    "确认后重跑 run 补拉；本地镜像已保留，未标撤回")
        if result.get("conflicted", 0):
            return ("打开更新记录找 state:conflicts/ 下的对应备份，对比本地修改；"
                    "确认后可继续用 Obsidian 看 99 Moodle Mirror")
        if result.get("added", 0) or result.get("updated", 0) or result.get("restored", 0):
            return "在 Obsidian 打开各课「99 Moodle Mirror」；若要全文搜 Word/PPT，再说「生成伴生 md」"
        return "本轮无文件变化。有新课件时再 run；只要重映缓存则 sync"
    if not cfg.downloader:
        return "配置齐全后可 sync（只映射）；若要联网拉取，先填 downloader 再 run"
    return "可执行 run（①拉取+②映射）或 sync（只②）"

def _print_guide(cfg: Config, *, mode: str, result: dict | None = None, failed: str | None = None,
                 pull_note: str | None = None) -> None:
    """Human-facing where/what-next block (same shape for CLI and agents)."""
    run_state = (result or {}).get("status", "success")
    if failed == "run_not_ready":
        print("")
        print("⚠️ 本轮：自检 doctor — sync 就绪，run 未就绪")
        stage = "自检 doctor"
    elif mode == "run":
        if failed:
            stage = "①拉取（失败，镜像未改）"
        elif pull_note or run_state == "unverified":
            stage = "①拉取（完整性未验证）+ ②映射"
        elif run_state == "incomplete":
            stage = "①拉取 + ②映射（部分课程缺失）"
        elif run_state == "recovered":
            stage = "①拉取 + ②映射（历史重建）"
        else:
            stage = "①拉取 + ②映射"
    elif mode == "sync":
        if run_state == "incomplete":
            stage = "②映射（部分课程缺失）"
        elif run_state == "recovered":
            stage = "②映射（历史重建）"
        else:
            stage = "②映射"
    elif mode == "doctor":
        stage = "自检 doctor"
    else:
        stage = mode
    if failed == "run_not_ready":
        status, icon = "sync 就绪 / run 未就绪", "⚠️"
    elif failed:
        status, icon = "失败", "❌"
    elif pull_note or run_state == "unverified":
        status, icon = "映射成功（拉取未验证）", "⚠️"
    elif run_state == "incomplete":
        status, icon = "映射不完整", "⚠️"
    elif run_state == "recovered":
        status, icon = "映射成功（历史为新基线）", "⚠️"
    else:
        status, icon = "成功", "✅"
    print("")
    print(f"{icon} 本轮：{stage} — {status}")
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
            f"{result.get('conflicted', 0)} 冲突备份 · {result.get('adopted', 0)} 已有认领"
        )
        if result.get("adopted", 0):
            print("   · adopted = 未做增量比对直接认领的既有文件（首次运行或 manifest 重建时正常）")
        for u in result.get("unmapped_courses") or []:
            print(f"   · UNMAPPED {u}")
        for d in result.get("duplicate_courses") or []:
            print(f"   · DUPLICATE {d}")
        for g in result.get("unrecognized_courses") or []:
            print(f"   · UNRECOGNIZED {g} (map the folder name or set it to null)")
        for g in result.get("ignored_courses") or []:
            print(f"   · IGNORED {g}")
        if result.get("skipped_symlinks", 0):
            print(f"   · SKIPPED-SYMLINK x{result['skipped_symlinks']} "
                  "(symlink 未跟随，详情见更新记录)")
        for m in result.get("missing_courses") or []:
            print(f"   · MISSING-COURSE {m} "
                  "(源课程消失；本地镜像保留，未标撤回)")
    print(f"👉 下一步：{_next_hint(cfg, result, failed=failed)}")

def _redact(text: str) -> str:
    text = _SECRET_QUERY.sub(r"\1[REDACTED]", text)
    return _SECRET_ASSIGN.sub(r"\1\2[REDACTED]", text)


def _dl_version(downloader: Path):
    """Probe `downloader --version` -> (major, minor, patch...) or None if unparseable."""
    try:
        c = subprocess.run([str(downloader), "--version"], capture_output=True,
                           text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    m = _DL_VERSION_RE.search((c.stdout or "") + "\n" + (c.stderr or ""))
    if not m:
        return None
    return tuple(int(g) for g in m.groups() if g is not None)


def _dl_config_status(cfg: Config) -> tuple[bool, list[str]]:
    """Check moodle-dl's own config (<source_root>/config.json) without echoing values.

    Returns (ready, reasons). A loose file mode is a warning reason only when
    it is the sole problem it still blocks run-readiness: credentials must not
    sit world-readable."""
    p = cfg.source_root / "config.json"
    if not p.is_file():
        return False, [f"missing {p} (run 'moodle-dl --init' inside {cfg.source_root})"]
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False, [f"unreadable JSON: {p} (fix or re-run 'moodle-dl --init'"]
    if not isinstance(raw, dict):
        return False, [f"config root must be an object: {p}"]
    reasons = []
    if not raw.get("moodle_domain"):
        reasons.append(f"empty moodle_domain in {p}")
    if not raw.get("moodle_path"):
        reasons.append(f"empty moodle_path in {p} (upstream get_moodle_path() requires it)")
    if not raw.get("token"):
        reasons.append(f"empty token in {p} (run save_token.py or 'moodle-dl --new-token --sso')")
    # Upstream compares course_id ints; empty whitelist = download ALL, so an
    # empty whitelist is only sane together with a blacklist.
    wl = raw.get("download_course_ids", [])
    bl = raw.get("dont_download_course_ids", [])
    for key, ids in (("download_course_ids", wl), ("dont_download_course_ids", bl)):
        if ids and (not isinstance(ids, list)
                     or any(not isinstance(i, int) or isinstance(i, bool) for i in ids)):
            reasons.append(f"{key} must be an int list in {p} "
                           "(upstream compares ints; strings silently match nothing)")
    if not wl and not bl:
        reasons.append(f"download_course_ids empty and no dont_download_course_ids in {p} "
                       "(upstream then downloads ALL courses; fill one list)")
    if raw.get("download_also_with_cookie") and not raw.get("privatetoken"):
        reasons.append(f"download_also_with_cookie is on but privatetoken missing in {p} "
                       "(cookie downloads will silently fail; run 'moodle-dl --new-token --sso')")
    try:
        if stat.S_IMODE(p.stat().st_mode) != 0o600:
            reasons.append(f"{p} is not mode 600 (run: chmod 600 {p})")
    except OSError:
        reasons.append(f"cannot stat {p}")
    return (not reasons), reasons


def _prune_conflicts(state_dir: Path, days: int) -> tuple[int, int]:
    """Delete conflict backups older than DAYS. Returns (removed, kept)."""
    if days < 1:
        raise ConfigError("--prune-conflicts needs DAYS >= 1 "
                          f"(got {days}; refusing to wipe recent backups)")
    root = state_dir / CONFLICTS_DIRNAME
    if not root.is_dir():
        return 0, 0
    cutoff = time.time() - days * 86400
    removed, kept = 0, 0
    for p in sorted(root.rglob("*")):
        if not p.is_file() or p.is_symlink():
            continue
        if p.stat().st_mtime < cutoff:
            p.unlink()
            removed += 1
        else:
            kept += 1
    return removed, kept


def _doctor(cfg: Config, prune_days: int | None = None) -> int:
    if prune_days is not None:
        removed, kept = _prune_conflicts(cfg.state_dir, prune_days)
        print(f"pruned {removed} conflict backup(s) older than {prune_days}d, kept {kept}")
    ok = True
    scan_root = _scan_root_for(cfg.source_root)
    for good, msg in [(cfg.source_root.is_dir(), f"source_root: {cfg.source_root}"),
                      (scan_root.is_dir(), f"scan root: {scan_root}"),
                      (cfg.vault_root.is_dir(), f"vault_root: {cfg.vault_root}"),
                      (bool(cfg.mappings or cfg.ignored),
                       f"mappings: {len(cfg.mappings)} destinations, {len(cfg.ignored)} ignored")]:
        print(f"{'OK' if good else 'ISSUE'}  {msg}")
        ok &= good
    scan_root, lock_file, dl_notes = _effective_dl_dirs(cfg)
    for n in dl_notes:
        print(f"note: {n}")
    busy = lock_file.exists()
    print(f"{'BUSY' if busy else 'OK'}  download lock ({lock_file.parent})")
    if busy:
        ok = False
    print(f"{'OK' if ok else 'ISSUE'}  sync ready" if ok else "ISSUE  sync NOT ready")
    # --- run readiness (informational; never affects the sync verdict) ---
    run_ready, run_reasons = True, []
    if cfg.downloader is None:
        run_ready = False
        run_reasons = ["sync-only mode: downloader not configured"]
    elif not (cfg.downloader.is_file() and os.access(cfg.downloader, os.X_OK)):
        run_ready = False
        run_reasons = [f"downloader not found/executable: {cfg.downloader}"]
    else:
        print(f"OK  downloader: {cfg.downloader}")
        dl_ok, dl_reasons = _dl_config_status(cfg)
        if not dl_ok:
            run_ready = False
            run_reasons = dl_reasons
    print(f"{'OK  run READY' if run_ready else 'ISSUE  run NOT READY'}")
    for r in run_reasons:
        print(f"   · {r}")
    # --- dependency pins (informational; sync itself needs none) ---
    req = Path(__file__).resolve().parent.parent / "requirements.txt"
    if not req.is_file():
        print("ISSUE  requirements.txt missing next to scripts/ (dependency pins unknown)")
    else:
        for lib, label in (("docx", "python-docx"), ("pptx", "python-pptx")):
            try:
                __import__(lib)
                print(f"OK  {label}: importable (companions render full content)")
            except ImportError:
                print(f"ISSUE  {label}: not importable "
                      "(companions degrade to link-only stubs; pip install -r requirements.txt)")
    # --- credential hygiene: warn, never write ---
    if (cfg.vault_root / ".git").exists() and _within(cfg.vault_root, cfg.source_root):
        print("ISSUE  vault is a git repo and the download cache (with credentials) "
              "lives inside it")
        print(f"   · keep secrets out of git: printf '*\\n' > {cfg.source_root / '.gitignore'}")
        print("   · or point source_root outside the vault (recommended) and re-run doctor")
    if _within(cfg.vault_root, cfg.source_root):
        print("HINT  download cache lives inside the vault: Obsidian will index it "
              "twice (cache + mirror). Settings → Files & Links → Excluded files → "
              f"add {cfg.source_root.relative_to(cfg.vault_root).as_posix()}/")
    if busy:
        _print_guide(cfg, mode="doctor", failed="busy")
    elif not ok:
        _print_guide(cfg, mode="doctor", failed="config")
    elif not run_ready:
        _print_guide(cfg, mode="doctor", failed="run_not_ready")
    else:
        _print_guide(cfg, mode="doctor")
    return 0 if ok else 2

def _pull(cfg: Config) -> tuple[int, str, str]:
    """Run the downloader. Returns (exit_code, verdict, note).

    verdict is one of:
      ok         rc 0, no failure signals, downloader version pinned (2.3.x)
      failed     rc != 0, or rc 0 with failure signals -> caller must NOT mirror
      unverified rc 0 and clean, but downloader version unknown -> mirror may
                 proceed only with an explicit completeness caveat
    Runs WITHOUT -q: moodle-dl 2.3.x demotes course-gone/download-failure
    signals to WARNING/INFO, which -q would swallow while rc stays 0.
    """
    if cfg.downloader is None:
        print("mirror.py: no downloader configured (sync-only mode).", file=sys.stderr)
        print("To enable 'run': set 'downloader' to your moodle-dl binary AND configure", file=sys.stderr)
        print("moodle-dl itself (moodle-sync/config.json via 'moodle-dl --init': moodle_domain,", file=sys.stderr)
        print("download_course_ids, token). Or use 'sync' to mirror an existing snapshot.", file=sys.stderr)
        return 2, "failed", "no_downloader"
    ver = _dl_version(cfg.downloader)
    trusted = ver is not None and tuple(ver[:2]) == SUPPORTED_DL
    ver_note = (f"downloader version {'.'.join(str(v) for v in ver)}" if ver is not None
                else "downloader version unknown (expected moodle-dl 2.3.x)")
    rc, output = 1, ""
    for a in range(1, cfg.pull_retries + 1):
        try:
            c = subprocess.run([str(cfg.downloader)], cwd=cfg.source_root,
                               capture_output=True, text=True, timeout=600)
        except (OSError, subprocess.SubprocessError) as e:
            print(f"mirror.py: cannot execute downloader: {e}", file=sys.stderr)
            return 3, "failed", "downloader_not_found"
        output = _ANSI_RE.sub("", (c.stdout or "") + (c.stderr or ""))
        output = _redact(output)
        if output.strip():
            sys.stderr.write(output if output.endswith("\n") else output + "\n")
        rc = c.returncode or 0
        if rc == 0:
            break
        if "already running" in (c.stderr or "").lower():
            print("Another moodle-dl instance is already running.", file=sys.stderr)
            return 3, "failed", "downloader busy"
        if a < cfg.pull_retries:
            print(f"Pull attempt {a} failed; retrying…", file=sys.stderr)
            time.sleep(cfg.pull_retry_seconds)
    if rc != 0:
        return rc, "failed", f"downloader exit {rc}"
    hits = [s for s in PULL_FAILURE_SIGNALS if s in output]
    if hits:
        print(f"mirror.py: pull reported failures ({'; '.join(hits)}); mirror unchanged.",
              file=sys.stderr)
        return 1, "failed", f"failure signals: {'; '.join(hits)}"
    if not trusted:
        return 0, "unverified", ver_note + "; signal patterns pinned to moodle-dl 2.3.x"
    return 0, "ok", ver_note

def _validated_status(p: Path) -> dict:
    """Load last-run.json or raise a user-actionable error (never a traceback)."""
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise MirrorStateError(
            f"last-run.json unreadable ({type(e).__name__}); state may be corrupt. "
            f"Inspect {p}, restore from backup, or re-run sync "
            "(mirrored files are adopted, never deleted).") from e
    if not isinstance(d, dict):
        raise MirrorStateError(f"last-run.json root must be an object: {p}")
    missing = [k for k in ("added", "updated", "restored", "withdrawn",
                           "conflicted", "adopted", "unchanged",
                           "finished_at") if k not in d]
    if missing:
        raise MirrorStateError(
            f"last-run.json missing keys {missing}; state may be from an older "
            "version. Re-run sync to rewrite it.")
    return d


def _status_body(cfg: Config, a) -> int:
    p = cfg.state_dir / "last-run.json"
    if not p.exists():
        print("no completed sync yet")
        print(f"📁 缓存（①）：{cfg.source_root}")
        print(f"📁 笔记库根：{cfg.vault_root}")
        print("👉 下一步：先 run 或 sync 完成首轮同步")
        return 1
    try:
        d = _validated_status(p)
    except MirrorStateError as e:
        print(f"mirror.py: {e}", file=sys.stderr)
        return 2
    if a.json:
        out_d = dict(d)
        evs = out_d.get("events", [])
        if a.events and len(evs) > a.events:
            out_d["events"] = evs[:a.events]
            out_d["events_truncated"] = f"showing {a.events} of {len(evs)} (use --events 0 for all)"
        print(json.dumps(out_d, ensure_ascii=False, indent=2))
    else:
        print(f"+{d['added']} added ~{d['updated']} updated, {d['restored']} restored, "
              f"{d['withdrawn']} withdrawn, {d.get('conflicted', 0)} conflicted, "
              f"{d.get('adopted', 0)} adopted, {d['unchanged']} unchanged @ {d['finished_at']}")
        _print_guide(cfg, mode="sync", result=d)
    return 0


def _setup_logging(verbose: bool = False, log_file: str | None = None):
    """Diagnostics channel. Human summary stays on stdout prints; this is the
    second observability leg (pull verdicts, state resets). Never silences."""
    import logging
    handlers = [logging.StreamHandler(sys.stderr)]
    if log_file:
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))
    logging.basicConfig(level=logging.DEBUG if verbose else logging.INFO,
                        handlers=handlers,
                        format="%(asctime)s %(levelname)s %(message)s", force=True)
    return logging.getLogger("moodle-mirror")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="mirror.py")
    ap.add_argument("--config", required=True, type=Path)
    ap.add_argument("--log-file", default=None, help="also write diagnostics here")
    ap.add_argument("--verbose", action="store_true", help="debug-level diagnostics")
    sp = ap.add_subparsers(dest="cmd", required=True)
    sp.add_parser("doctor").add_argument(
        "--prune-conflicts", type=int, metavar="DAYS", default=None,
        help="delete conflict backups older than DAYS, then run checks")
    s = sp.add_parser("status")
    s.add_argument("--json", action="store_true")
    s.add_argument("--events", type=int, default=50, metavar="N",
        help="max events in --json output (0 = all); terminal always shows counts")
    sp.add_parser("sync")
    sp.add_parser("run")
    a = ap.parse_args(argv)
    log = _setup_logging(verbose=a.verbose, log_file=a.log_file)
    cfg = None
    try:
        cfg = load_config(a.config)
        log.info("config loaded: %s (vault %s)", a.config, cfg.vault_root)
        if a.cmd == "doctor":
            return _doctor(cfg, prune_days=a.prune_conflicts)
        if a.cmd == "status":
            return _status_body(cfg, a)
        mode = "run" if a.cmd == "run" else "sync"
        pull_note = None
        verdict = "n/a"
        if a.cmd == "run":
            dl_ok, dl_reasons = _dl_config_status(cfg)
            if not dl_ok:
                for r_ in dl_reasons:
                    print(f"   · {r_}", file=sys.stderr)
                print("dl config not ready; mirror unchanged", file=sys.stderr)
                _print_guide(cfg, mode="run", failed="run_not_ready")
                return 2
            rc, verdict, note = _pull(cfg)
            log.info("pull verdict=%s note=%s", verdict, note)
            if verdict == "failed":
                print("pull failed; mirror unchanged", file=sys.stderr)
                if cfg.downloader is None or note == "no_downloader":
                    fail = "no_downloader"
                elif "busy" in note:
                    fail = "busy"
                elif "downloader_not_found" in note:
                    fail = "downloader_not_found"
                else:
                    fail = "pull"
                _print_guide(cfg, mode="run", failed=fail)
                return rc or 1
            if verdict == "unverified":
                pull_note = note
                print(f"⚠️ pull ran but completeness UNVERIFIED: {note}; "
                      "mirror proceeds, verify new files on Moodle manually.", file=sys.stderr)
        r = synchronize(cfg, pull_verdict=verdict).as_dict()
        log.info("sync done: added=%s updated=%s restored=%s withdrawn=%s conflicted=%s "
                 "adopted=%s unchanged=%s skipped_symlinks=%s",
                 r["added"], r["updated"], r["restored"], r["withdrawn"],
                 r["conflicted"], r["adopted"], r["unchanged"],
                 r.get("skipped_symlinks", 0))
        print(f"mirror done: +{r['added']} added ~{r['updated']} updated, {r['restored']} restored, "
              f"{r['withdrawn']} withdrawn, {r['conflicted']} conflicted, "
              f"{r['adopted']} adopted, {r['unchanged']} unchanged")
        if pull_note:
            clog = cfg.changelog.read_text(encoding="utf-8")
            _atext(cfg.changelog, clog.rstrip() + f"\n- ⚠️ pull completeness UNVERIFIED: {pull_note}\n")
        _print_guide(cfg, mode=mode, result=r, pull_note=pull_note)
        return 0
    except SyncBusyError as e:
        print(f"mirror.py: {e}", file=sys.stderr)
        if cfg is not None:
            _print_guide(cfg, mode=getattr(a, "cmd", "sync"), failed="busy")
        return 3
    except ConfigError as e:
        print(f"mirror.py: {e}", file=sys.stderr)
        if cfg is not None:
            _print_guide(cfg, mode=getattr(a, "cmd", "sync"), failed="config")
        else:
            print("👉 下一步：检查 --config 路径与 moodle-mirror.json 是否可读")
        return 2
    except MirrorStateError as e:
        print(f"mirror.py: {e}", file=sys.stderr)
        if cfg is not None:
            _print_guide(cfg, mode=getattr(a, "cmd", "sync"), failed="state")
        return 2
    except (MirrorEnvError, OSError) as e:
        print(f"mirror.py: {e}", file=sys.stderr)
        if cfg is not None:
            _print_guide(cfg, mode=getattr(a, "cmd", "sync"), failed="env")
        return 2

if __name__ == "__main__":
    raise SystemExit(main())
