"""Plain-file storage. No database: each sheet is a folder.

data/
  sheets/S0142/
    meta.json            {"id", "title", "created", "updated", "sides": {"A": {...}, "B": {...}}}
    A.jpg  A.thumb.jpg   cleaned page + thumbnail
    A.flat.jpg           straightened only (no cleanup), in case the cleanup ate light pencil
    originals/A-20261027-104500.jpg
  unmatched/             photos where no markers were found, kept for debugging
  state.json             {"last_template_sheet": 50}
"""
import json
import os
import shutil
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path

import img2pdf

from . import config
from .layout import SHEET_RE, SIDES
from .scan import DPI, ScanResult, encode_jpeg, thumbnail

_lock = threading.Lock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _stamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def sheets_dir() -> Path:
    d = config.DATA_DIR / "sheets"
    d.mkdir(parents=True, exist_ok=True)
    return d


def valid_id(sid: str) -> bool:
    return bool(SHEET_RE.fullmatch(sid or ""))


def sheet_dir(sid: str) -> Path:
    if not valid_id(sid):
        raise ValueError("bad sheet id")
    return sheets_dir() / sid


def _write_atomic(path: Path, data: bytes):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
    with os.fdopen(fd, "wb") as f:
        f.write(data)
    os.replace(tmp, path)


def read_meta(sid: str) -> dict | None:
    p = sheet_dir(sid) / "meta.json"
    if not p.exists():
        return None
    return json.loads(p.read_text())


def _write_meta(sid: str, meta: dict):
    _write_atomic(sheet_dir(sid) / "meta.json", json.dumps(meta, indent=2).encode())


def save_scan(sid: str, original: bytes, result: ScanResult) -> dict:
    d = sheet_dir(sid)
    stamp = _stamp()
    with _lock:
        meta = read_meta(sid) or {"id": sid, "title": "", "created": _now(), "sides": {}}
        for side, page in result.pages.items():
            _write_atomic(d / f"{side}.jpg", encode_jpeg(page.clean))
            _write_atomic(d / f"{side}.flat.jpg", encode_jpeg(page.flat))
            _write_atomic(d / f"{side}.thumb.jpg", thumbnail(page.clean))
            prev = meta["sides"].get(side, {})
            meta["sides"][side] = {"updated": _now(), "scans": prev.get("scans", 0) + 1, "markers": page.markers}
        sides = "".join(sorted(result.pages))
        _write_atomic(d / "originals" / f"{sides}-{stamp}.jpg", original)
        meta["updated"] = _now()
        _write_meta(sid, meta)
    return meta


def save_unmatched(original: bytes):
    _write_atomic(config.DATA_DIR / "unmatched" / f"{_stamp()}.jpg", original)


def list_sheets() -> list[dict]:
    out = []
    for d in sheets_dir().iterdir():
        if d.is_dir() and valid_id(d.name):
            m = read_meta(d.name)
            if m:
                out.append(m)
    out.sort(key=lambda m: m.get("updated", ""), reverse=True)
    return out


def set_title(sid: str, title: str) -> dict:
    with _lock:
        meta = read_meta(sid)
        if meta is None:
            raise KeyError(sid)
        meta["title"] = title.strip()[:200]
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


# --- template numbering -----------------------------------------------------

def _state() -> dict:
    p = config.DATA_DIR / "state.json"
    return json.loads(p.read_text()) if p.exists() else {}


def next_template_start() -> int:
    highest = _state().get("last_template_sheet", 0)
    for d in sheets_dir().iterdir():
        m = SHEET_RE.fullmatch(d.name)
        if m:
            highest = max(highest, int(m.group(1)))
    return highest + 1


def note_template_printed(start: int, count: int):
    with _lock:
        st = _state()
        st["last_template_sheet"] = max(st.get("last_template_sheet", 0), start + count - 1)
        _write_atomic(config.DATA_DIR / "state.json", json.dumps(st).encode())
