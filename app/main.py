"""Web app: phone upload + browse/download from any browser.

Run:  uvicorn app.main:app --host 0.0.0.0 --port 8737
"""
import secrets
from pathlib import Path
from urllib.parse import urlencode

from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, RedirectResponse, Response
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from . import config, storage
from .layout import PAGE_RE, SHEET_RE, SIDES
from .scan import ScanError, scan
from .template import build_pdf as build_template, new_ids

STATIC = Path(__file__).parent / "static"
COOKIE = "notes_key"
KEY = config.upload_key()
TEN_YEARS = 10 * 365 * 24 * 3600


def _authorized(request: Request) -> bool:
    given = request.cookies.get(COOKIE) or request.headers.get("x-notes-key") or ""
    return secrets.compare_digest(given.encode(), KEY.encode())


def _set_key_cookie(resp: Response):
    resp.set_cookie(COOKIE, KEY, max_age=TEN_YEARS, httponly=True, samesite="lax")


def _err(msg: str, status: int = 400):
    return JSONResponse({"error": msg}, status_code=status)


def _need_key():
    return _err("Upload key required.", 401)


# --- pages --------------------------------------------------------------------

async def spa(request: Request):
    """Every page is the same HTML; the JS reads the path. `?key=` saves the key as a cookie."""
    key = request.query_params.get("key")
    if key is not None:
        params = {k: v for k, v in request.query_params.items() if k != "key"}
        url = request.url.path + (("?" + urlencode(params)) if params else "")
        resp = RedirectResponse(url, status_code=303)
        if secrets.compare_digest(key.encode(), KEY.encode()):
            _set_key_cookie(resp)
        return resp
    return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-cache"})


# --- api ----------------------------------------------------------------------

async def api_me(request: Request):
    return JSONResponse({
        "can_upload": _authorized(request),
        "base_url": config.BASE_URL,
    })


async def api_key(request: Request):
    body = await request.json()
    if not secrets.compare_digest(str(body.get("key", "")).strip().encode(), KEY.encode()):
        return _err("Invalid upload key.", 403)
    resp = JSONResponse({"ok": True})
    _set_key_cookie(resp)
    return resp


async def api_sheets(request: Request):
    return JSONResponse({"sheets": storage.list_sheets(), "folders": storage.list_folders()})


async def api_sheet(request: Request):
    sid = request.path_params["sid"]
    if not storage.valid_id(sid):
        return _err("Not a sheet ID.", 404)
    sid = sid.upper()
    if request.method == "GET":
        meta = storage.read_meta(sid)
        return JSONResponse({"sheet": meta}) if meta else JSONResponse({"sheet": None, "id": sid})
    if not _authorized(request):
        return _need_key()
    try:
        if request.method == "PATCH":
            body = await request.json()
            changes = {k: body[k] for k in ("title", "folder") if k in body}
            return JSONResponse({"sheet": storage.update_sheet(sid, **changes)})
        if request.method == "DELETE":
            side = request.query_params.get("side")
            if side is not None and side not in SIDES:
                return _err("Bad side.")
            return JSONResponse({"sheet": storage.delete_sheet(sid, side)})
    except KeyError:
        return _err("Sheet not found.", 404)
    except LookupError as e:
        return _err(str(e), 404)
    return _err("Method not allowed.", 405)


async def api_folders(request: Request):
    if request.method == "GET":
        return JSONResponse({"folders": storage.list_folders()})
    if not _authorized(request):
        return _need_key()
    body = await request.json()
    try:
        return JSONResponse({"folder": storage.create_folder(body.get("name", ""))})
    except ValueError as e:
        return _err(str(e))


async def api_folder(request: Request):
    fid = request.path_params["fid"]
    if not _authorized(request):
        return _need_key()
    try:
        if request.method == "PATCH":
            body = await request.json()
            return JSONResponse({"folder": storage.rename_folder(fid, body.get("name", ""))})
        if request.method == "DELETE":
            return JSONResponse({"moved": storage.delete_folder(fid)})
    except KeyError:
        return _err("Folder not found.", 404)
    except ValueError as e:
        return _err(str(e))
    return _err("Method not allowed.", 405)


async def api_upload(request: Request):
    if not _authorized(request):
        return _need_key()
    limit = config.MAX_UPLOAD_MB * 1024 * 1024
    if int(request.headers.get("content-length") or 0) > limit + 64 * 1024:
        return _err(f"Photo exceeds the {config.MAX_UPLOAD_MB} MB limit.", 413)
    form = await request.form(max_files=1, max_fields=6)
    up = form.get("photo")
    if up is None or not hasattr(up, "read"):
        return _err("No photo in the upload.")
    data = await up.read()
    await form.close()
    if len(data) > limit:
        return _err(f"Photo exceeds the {config.MAX_UPLOAD_MB} MB limit.", 413)

    hint = str(form.get("sheet") or "")
    m = PAGE_RE.fullmatch(hint)
    hint_id = m.group(1).upper() if m else (hint.upper() if SHEET_RE.fullmatch(hint) else None)
    folder = str(form.get("folder") or "") or None

    try:
        result = await run_in_threadpool(scan, data)
    except ScanError as e:
        await run_in_threadpool(storage.save_unmatched, data)
        return _err(str(e), 422)

    warnings = []
    qr = set(result.qr_ids.values())
    if len(qr) > 1:
        return _err("This photo contains two different sheets. Photograph one sheet at a time.", 422)
    sid = next(iter(qr), None) or hint_id
    if sid is None:
        await run_in_threadpool(storage.save_unmatched, data)
        return _err("QR code could not be read. Scan the sheet's QR code with the camera and upload from that page.", 422)
    if hint_id and sid != hint_id:
        warnings.append(f"QR code reads {sid}, not {hint_id}. Saved as {sid}.")
    for side, page in result.pages.items():
        if page.markers < 3:
            warnings.append(f"Side {side}: {page.markers} of 3 corner markers found. The page may be slightly skewed.")

    meta = await run_in_threadpool(storage.save_scan, sid, data, result, folder)
    return JSONResponse({"sheet": meta, "saved_sides": sorted(result.pages), "warnings": warnings})


# --- files --------------------------------------------------------------------

async def page_image(request: Request):
    sid = request.path_params["sid"]
    side, _, kind = request.path_params["name"].partition(".")
    try:
        p = storage.page_path(sid, side, kind)
    except ValueError:
        return _err("Not found.", 404)
    if not p.exists():
        return _err("Not found.", 404)
    return FileResponse(p, headers={"Cache-Control": "no-cache"})


async def sheet_pdf(request: Request):
    if "sid" in request.path_params:
        sids = [request.path_params["sid"]]
    else:
        sids = [s for s in request.query_params.get("ids", "").split(",") if s]
    if not sids or not all(storage.valid_id(s) for s in sids):
        return _err("Bad sheet list.", 400)
    sids = [s.upper() for s in sids]
    try:
        pdf = await run_in_threadpool(storage.build_pdf, sids)
    except KeyError:
        return _err("No scanned pages for the selected sheets.", 404)
    name = sids[0] if len(sids) == 1 else f"notes-{len(sids)}-sheets"
    disp = "attachment" if request.query_params.get("download") else "inline"
    return Response(pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'{disp}; filename="{name}.pdf"'})


async def template_pdf(request: Request):
    try:
        count = int(request.query_params.get("count") or 50)
    except ValueError:
        return _err("count must be a number.")
    if not 1 <= count <= 500:
        return _err("count must be 1-500.")
    ids = new_ids(count, storage.existing_ids())
    pdf = await run_in_threadpool(build_template, ids)
    name = f"notes-sheets-{count}.pdf"
    return Response(pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="{name}"'})


routes = [
    Route("/", spa),
    Route("/s/{page}", spa),
    Route("/print", spa),
    Route("/f/{fid}", spa),
    Route("/api/me", api_me),
    Route("/api/key", api_key, methods=["POST"]),
    Route("/api/sheets", api_sheets),
    Route("/api/sheets/{sid}", api_sheet, methods=["GET", "PATCH", "DELETE"]),
    Route("/api/folders", api_folders, methods=["GET", "POST"]),
    Route("/api/folders/{fid}", api_folder, methods=["PATCH", "DELETE"]),
    Route("/api/upload", api_upload, methods=["POST"]),
    Route("/img/{sid}/{name}", page_image),
    Route("/pdf/{sid}.pdf", sheet_pdf),
    Route("/pdf", sheet_pdf),
    Route("/template.pdf", template_pdf),
    Mount("/static", StaticFiles(directory=STATIC), name="static"),
]

app = Starlette(routes=routes)
print(f"[notes] upload key: {KEY}   (open {config.BASE_URL}/?key={KEY} once on each device)", flush=True)
