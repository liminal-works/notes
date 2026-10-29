"""Plain-file storage. No database: each sheet is a folder.

data/
  sheets/S3F9A1C07/
    meta.json            {"id", "title", "folder", "created", "uploaded", "sides": {"A": {...}, "B": {...}}}
    A.jpg  A.thumb.jpg   cleaned page + thumbnail
    A.flat.jpg           straightened only (no cleanup), in case the cleanup ate light pencil
    originals/A-20261027-104500.jpg
  folders.json           [{"id": "f1a2b3c", "name": "Repair notes", "circle": 1, "created": ...}]
  circle_sheets.json     IDs of sheets printed with folder circles (older sheets have none)
  unmatched/             photos where no markers were found, kept for debugging

A sheet's "folder" is a folder id, or null for notes that aren't in a folder.
"""
import json
import os
import secrets
import shutil
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path

import img2pdf

from . import config
from .layout import CIRCLE_COUNT, SHEET_RE, SIDES
from .scan import DPI, ScanResult, encode_jpeg, thumbnail

_lock = threading.RLock()
FOLDER_NAME_MAX = 60


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _stamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def _write_atomic(path: Path, data: bytes):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
    with os.fdopen(fd, "wb") as f:
        f.write(data)
    os.replace(tmp, path)


# --- sheets -------------------------------------------------------------------

def sheets_dir() -> Path:
    d = config.DATA_DIR / "sheets"
    d.mkdir(parents=True, exist_ok=True)
    return d


def valid_id(sid: str) -> bool:
    return bool(SHEET_RE.fullmatch(sid or ""))


def norm_id(sid: str) -> str:
    """Sheet IDs are stored upper-case; accept any case in URLs."""
    if not valid_id(sid):
        raise ValueError("bad sheet id")
    return sid.upper()


def sheet_dir(sid: str) -> Path:
    return sheets_dir() / norm_id(sid)


def read_meta(sid: str) -> dict | None:
    p = sheet_dir(sid) / "meta.json"
    if not p.exists():
        return None
    meta = json.loads(p.read_text())
    meta.setdefault("folder", None)
    meta.setdefault("uploaded", meta.get("updated", meta.get("created", "")))
    return meta


def _write_meta(sid: str, meta: dict):
    _write_atomic(sheet_dir(sid) / "meta.json", json.dumps(meta, indent=2).encode())


def save_scan(sid: str, original: bytes, result: ScanResult, folder: str | None = None,
              circle_folder: str | None = None, circle: int | None = None) -> dict:
    sid = norm_id(sid)
    d = sheet_dir(sid)
    stamp = _stamp()
    with _lock:
        meta = read_meta(sid) or {"id": sid, "title": "", "folder": None, "created": _now(), "sides": {}}
        for side, page in result.pages.items():
            _write_atomic(d / f"{side}.jpg", encode_jpeg(page.clean))
            _write_atomic(d / f"{side}.flat.jpg", encode_jpeg(page.flat))
            _write_atomic(d / f"{side}.thumb.jpg", thumbnail(page.clean))
            prev = meta["sides"].get(side, {})
            meta["sides"][side] = {"updated": _now(), "scans": prev.get("scans", 0) + 1, "markers": page.markers}
        sides = "".join(sorted(result.pages))
        _write_atomic(d / "originals" / f"{sides}-{stamp}.jpg", original)
        # A filled-in circle on the paper wins; otherwise scanning from inside a
        # folder files an unfiled sheet there.
        if circle_folder and get_folder(circle_folder):
            meta["folder"] = circle_folder
        elif folder and not meta.get("folder") and get_folder(folder):
            meta["folder"] = folder
        if circle is not None:
            meta["circle"] = circle
        meta["uploaded"] = meta["updated"] = _now()
        _write_meta(sid, meta)
    return meta


def save_unmatched(original: bytes):
    _write_atomic(config.DATA_DIR / "unmatched" / f"{_stamp()}.jpg", original)


def list_sheets() -> list[dict]:
    """All sheets, most recently uploaded first."""
    out = []
    for d in sheets_dir().iterdir():
        if d.is_dir() and valid_id(d.name):
            m = read_meta(d.name)
            if m:
                out.append(m)
    out.sort(key=lambda m: m.get("uploaded", ""), reverse=True)
    return out


_UNSET = object()


def update_sheet(sid: str, title=_UNSET, folder=_UNSET) -> dict:
    with _lock:
        meta = read_meta(sid)
        if meta is None:
            raise KeyError(sid)
        if title is not _UNSET:
            meta["title"] = str(title or "").strip()[:200]
        if folder is not _UNSET:
            if folder and not get_folder(folder):
                raise LookupError("Folder not found.")
            meta["folder"] = folder or None
        _write_meta(sid, meta)
    return meta


def delete_sheet(sid: str, side: str | None = None):
    d = sheet_dir(sid)
    with _lock:
        meta = read_meta(sid)
        if meta is None:
            raise KeyError(sid)
        if side is None or set(meta["sides"]) <= {side}:
            shutil.rmtree(d)
            return None
        for suffix in ("jpg", "flat.jpg", "thumb.jpg"):
            (d / f"{side}.{suffix}").unlink(missing_ok=True)
        meta["sides"].pop(side, None)
        meta["updated"] = _now()
        _write_meta(sid, meta)
        return meta


def page_path(sid: str, side: str, kind: str = "jpg") -> Path:
    if side not in SIDES or kind not in ("jpg", "flat.jpg", "thumb.jpg"):
        raise ValueError("bad page")
    return sheet_dir(sid) / f"{side}.{kind}"


def build_pdf(sids: list[str]) -> bytes:
    pages = []
    for sid in sids:
        for side in SIDES:
            p = page_path(sid, side)
            if p.exists():
                pages.append(p.read_bytes())
    if not pages:
        raise KeyError("no pages")
    layout = img2pdf.get_fixed_dpi_layout_fun((DPI, DPI))
    return img2pdf.convert(pages, layout_fun=layout)


def existing_ids() -> set[str]:
    return {d.name for d in sheets_dir().iterdir() if valid_id(d.name)}


# --- folders ------------------------------------------------------------------

def _folders_path() -> Path:
    return config.DATA_DIR / "folders.json"


def list_folders() -> list[dict]:
    p = _folders_path()
    folders = json.loads(p.read_text()) if p.exists() else []
    return sorted(folders, key=lambda f: f["name"].lower())


def _save_folders(folders: list[dict]):
    _write_atomic(_folders_path(), json.dumps(folders, indent=2).encode())


def get_folder(fid: str) -> dict | None:
    return next((f for f in list_folders() if f["id"] == fid), None)


def _clean_name(name: str, folders: list[dict], skip: str | None = None) -> str:
    name = " ".join(str(name or "").split())[:FOLDER_NAME_MAX]
    if not name:
        raise ValueError("Folder name is required.")
    if any(f["name"].lower() == name.lower() and f["id"] != skip for f in folders):
        raise ValueError(f"A folder named “{name}” already exists.")
    return name


def create_folder(name: str) -> dict:
    with _lock:
        folders = list_folders()
        folder = {"id": "f" + secrets.token_hex(3), "name": _clean_name(name, folders), "created": _now()}
        _save_folders(folders + [folder])
    return folder


def update_folder(fid: str, name=_UNSET, circle=_UNSET) -> dict:
    """Rename a folder and/or link it to a circle number (1-5, or None to unlink)."""
    with _lock:
        folders = list_folders()
        folder = next((f for f in folders if f["id"] == fid), None)
        if folder is None:
            raise KeyError(fid)
        if name is not _UNSET:
            folder["name"] = _clean_name(name, folders, skip=fid)
        if circle is not _UNSET:
            if circle is not None:
                try:
                    circle = int(circle)
                except (TypeError, ValueError):
                    raise ValueError("Circle must be a number from 1 to 5.")
                if not 1 <= circle <= CIRCLE_COUNT:
                    raise ValueError("Circle must be a number from 1 to 5.")
                for f in folders:  # a circle belongs to one folder at a time
                    if f.get("circle") == circle:
                        f["circle"] = None
            folder["circle"] = circle
        _save_folders(folders)
    return folder


def folder_for_circle(n: int) -> dict | None:
    return next((f for f in list_folders() if f.get("circle") == n), None)


# --- which sheets have folder circles -----------------------------------------

def _circle_sheets_path() -> Path:
    return config.DATA_DIR / "circle_sheets.json"


def record_circle_sheets(ids: list[str]):
    """Remember sheet IDs printed with folder circles, so older sheets are never read for them."""
    with _lock:
        p = _circle_sheets_path()
        known = set(json.loads(p.read_text())) if p.exists() else set()
        known.update(i.upper() for i in ids)
        _write_atomic(p, json.dumps(sorted(known)).encode())


def has_circles(sid: str) -> bool:
    p = _circle_sheets_path()
    return p.exists() and sid.upper() in set(json.loads(p.read_text()))


def delete_folder(fid: str) -> int:
    """Remove a folder. Its notes are kept and become unfiled. Returns how many moved."""
    with _lock:
        folders = list_folders()
        if not any(f["id"] == fid for f in folders):
            raise KeyError(fid)
        moved = 0
        for meta in list_sheets():
            if meta.get("folder") == fid:
                meta["folder"] = None
                _write_meta(meta["id"], meta)
                moved += 1
        _save_folders([f for f in folders if f["id"] != fid])
    return moved
