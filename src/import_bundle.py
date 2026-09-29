"""A whole 5.x install in one zip (v6 Phase 6, onboarding): its data folder —
worktimer.db, notes/ with their pasted images, and .pat_key for the tracker
tokens — optionally beside its config folder, with the settings Settings wrote.
Settings → Import takes it as one file.

Nothing is extracted as it stands: members are read by name, and only what
WorkTimer knows is kept — the database, the key, notes (*.md,
notes_meta.json, images in a note's _assets folder) and the user's settings
files (ConfigLoader.USER_FILES). Unsafe paths are skipped; the member count
and the unpacked size are capped before anything is read.
"""

import shutil
import tempfile
import zipfile
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from . import clock
from .config import ConfigLoader
from .user_paths import NOTE_IMAGE_SUFFIXES

MAX_MEMBERS = 20_000
MAX_UNPACKED_BYTES = 300 * 1024 * 1024


@dataclass
class Bundle:
    db_path: Path
    pat_key_path: Path | None
    notes: dict = field(default_factory=dict)     # path under notes/ -> bytes
    settings: dict = field(default_factory=dict)  # settings file name -> bytes


def is_bundle(path) -> bool:
    return zipfile.is_zipfile(path)


def _member_path(name: str) -> PurePosixPath | None:
    """A member's path, or None when it is unsafe or not a file of the install
    (absolute, a drive, '..', macOS metadata)."""
    path = PurePosixPath(name.replace("\\", "/"))
    if (not path.parts or path.is_absolute() or ".." in path.parts
            or ":" in path.parts[0] or path.parts[0] == "__MACOSX"):
        return None
    return path


def _note_path(rel: PurePosixPath) -> bool:
    """What a notes folder holds: notes, their metadata, a note's images."""
    if len(rel.parts) == 1:
        return rel.suffix.lower() == ".md" or rel.name == "notes_meta.json"
    return (len(rel.parts) == 2 and rel.parts[0].endswith("_assets")
            and rel.suffix.lower() in NOTE_IMAGE_SUFFIXES)


@contextmanager
def opened(path):
    """The bundle's database and key in a temp folder (removed afterwards);
    its notes and settings in memory. ValueError when it isn't one."""
    with zipfile.ZipFile(path) as zf:
        infos = [i for i in zf.infolist() if not i.is_dir()]
        if len(infos) > MAX_MEMBERS:
            raise ValueError(f"The zip holds more than {MAX_MEMBERS:,} files")
        if sum(i.file_size for i in infos) > MAX_UNPACKED_BYTES:
            raise ValueError("The zip unpacks to more than 300 MB — zip only WorkTimer's "
                             "data and config folders")
        members = {p: i for i in infos if (p := _member_path(i.filename)) is not None}
        dbs = sorted((p for p in members if p.name == "worktimer.db"), key=lambda p: len(p.parts))
        if not dbs:
            raise ValueError("The zip has no worktimer.db — zip WorkTimer's data folder")
        base = dbs[0].parent
        notes_root = base / "notes"
        config_roots = {base.parent / "config", base / "config"}

        bundle_notes, bundle_settings = {}, {}
        for p, info in members.items():
            if p.is_relative_to(notes_root) and _note_path(p.relative_to(notes_root)):
                bundle_notes[p.relative_to(notes_root).as_posix()] = zf.read(info)
            elif p.parent in config_roots and p.name in ConfigLoader.USER_FILES:
                bundle_settings[p.name] = zf.read(info)

        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "worktimer.db"
            db_path.write_bytes(zf.read(members[dbs[0]]))
            key_info = members.get(base / ".pat_key")
            key_path = None
            if key_info is not None:
                key_path = Path(tmp) / ".pat_key"
                key_path.write_bytes(zf.read(key_info))
            yield Bundle(db_path, key_path, bundle_notes, bundle_settings)


def _stamp() -> str:
    return clock.now_local().strftime("%Y%m%d-%H%M%S")


def place_notes(files: dict, notes_dir: Path) -> Path | None:
    """Write the bundle's notes into `notes_dir`. Notes already there are
    moved aside first — never overwritten; returns where to, if anywhere."""
    notes_dir = Path(notes_dir)
    moved = None
    if notes_dir.exists() and any(notes_dir.iterdir()):
        moved = notes_dir.with_name(f"{notes_dir.name}.before-import-{_stamp()}")
        shutil.move(str(notes_dir), str(moved))
    for rel, content in files.items():
        target = notes_dir / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    notes_dir.mkdir(parents=True, exist_ok=True)
    return moved


def place_settings(files: dict, settings_dir: Path) -> list[str]:
    """Write the bundle's settings files into the user's `settings_dir`; a
    file already there is kept in before-import-<stamp>/. Returns the names."""
    settings_dir = Path(settings_dir)
    keep = settings_dir / f"before-import-{_stamp()}"
    for name, content in files.items():
        if name not in ConfigLoader.USER_FILES:
            continue
        target = settings_dir / name
        if target.exists():
            keep.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, keep / name)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    return sorted(n for n in files if n in ConfigLoader.USER_FILES)
