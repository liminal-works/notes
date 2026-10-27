"""Turn a phone photo of a sheet into flat, cleaned-up page images.

1. Find the ArUco corner markers (they say which half, A or B, is in view).
2. For each half with at least 2 markers, compute a homography from the
   marker corners to their known printed positions and warp the half flat.
3. Clean up: divide out the background (shadows, paper tint, the faint mirrored
   print showing through from the back) and push near-white to pure white.
4. Read the QR code(s), if they decode, to learn the sheet ID.
"""
import io
from dataclasses import dataclass, field

import cv2
import numpy as np
from PIL import Image, ImageOps

from .layout import (
    ARUCO_DICT, MARKER_IDS, PAGE_RE, SIDES, crop_box, marker_corners, marker_rect, MARKER,
)

try:  # iPhone HEIC photos; Safari usually converts to JPEG on upload, this covers the rest.
    from pillow_heif import register_heif_opener
    register_heif_opener()
except ImportError:
    pass

DPI = 200
DETECT_MAX = 2600  # detection runs on a downscaled copy; warping uses full resolution

_aruco = cv2.aruco.ArucoDetector(
    cv2.aruco.getPredefinedDictionary(ARUCO_DICT),
    (lambda p: (setattr(p, "cornerRefinementMethod", cv2.aruco.CORNER_REFINE_SUBPIX), p)[1])(
        cv2.aruco.DetectorParameters()
    ),
)


class ScanError(Exception):
    pass


@dataclass
class Page:
    side: str
    clean: np.ndarray      # cleaned-up colour image (BGR)
    flat: np.ndarray       # straightened, but no cleanup
    markers: int           # how many of the 3 markers were found


@dataclass
class ScanResult:
    pages: dict = field(default_factory=dict)  # side -> Page
    qr_ids: dict = field(default_factory=dict)  # side -> "S0142"


def load_image(data: bytes) -> np.ndarray:
    try:
        im = Image.open(io.BytesIO(data))
        im = ImageOps.exif_transpose(im).convert("RGB")
    except Exception as e:
        raise ScanError(f"Image could not be read ({e.__class__.__name__}).")
    return cv2.cvtColor(np.asarray(im), cv2.COLOR_RGB2BGR)


def _detect_markers(gray: np.ndarray, scale: float):
    corners, ids, _ = _aruco.detectMarkers(gray)
    found = {}
    if ids is not None:
        for c, i in zip(corners, ids.flatten()):
            i = int(i)
            if i in MARKER_IDS and i not in found:
                found[i] = c.reshape(4, 2) / scale
    return found


def _detect_qr(gray: np.ndarray) -> dict:
    out = {}
    for det in (cv2.QRCodeDetectorAruco(), cv2.QRCodeDetector()):
        try:
            ok, texts, _, _ = det.detectAndDecodeMulti(gray)
        except cv2.error:
            continue
        if ok:
            for t in texts:
                m = PAGE_RE.search(t or "")
                if m:
                    out.setdefault(m.group(2).upper(), m.group(1).upper())
        if out:
            break
    return out


def _warp(img: np.ndarray, side: str, markers: dict) -> np.ndarray:
    cx, cy, cw, ch = crop_box(side)
    k = DPI / 72.0
    src, dst = [], []
    for mid, pts in markers.items():
        s, corner = MARKER_IDS[mid]
        if s != side:
            continue
        src.extend(pts)
        dst.extend(((x - cx) * k, (y - cy) * k) for x, y in marker_corners(side, corner))
    H, _ = cv2.findHomography(np.float32(src), np.float32(dst), cv2.RANSAC, 4.0)
    if H is None:
        raise ScanError("Corner markers could not be aligned.")
    size = (round(cw * k), round(ch * k))
    flat = cv2.warpPerspective(img, H, size, flags=cv2.INTER_CUBIC,
                               borderMode=cv2.BORDER_CONSTANT, borderValue=(255, 255, 255))
    return flat


def _hide_markers(img: np.ndarray, side: str) -> np.ndarray:
    """White out the corner markers; they're only there for alignment."""
    cx, cy, _, _ = crop_box(side)
    k = DPI / 72.0
    pad = 14
    for mid, (s, corner) in MARKER_IDS.items():
        if s == side:
            x, y = marker_rect(side, corner)
            x0, y0 = round((x - cx) * k) - pad, round((y - cy) * k) - pad
            x1, y1 = round((x + MARKER - cx) * k) + pad, round((y + MARKER - cy) * k) + pad
            img[max(0, y0):y1, max(0, x0):x1] = 255
    return img


def clean(flat: np.ndarray) -> np.ndarray:
    """Even out lighting and remove paper tint / show-through, keeping pen colour."""
    out = np.empty_like(flat)
    for c in range(3):
        ch = flat[:, :, c]
        bg = cv2.medianBlur(cv2.dilate(ch, np.ones((9, 9), np.uint8)), 41)
        out[:, :, c] = cv2.divide(ch, bg, scale=255)
    # levels: anything lighter than `hi` becomes white, darker than `lo` black
    lo, hi = 60.0, 205.0
    f = np.clip((out.astype(np.float32) - lo) / (hi - lo), 0, 1)
    f = f ** 1.4  # darken mid-tones so light pen strokes stay readable
    return (f * 255).astype(np.uint8)


def scan(data: bytes) -> ScanResult:
    img = load_image(data)
    h, w = img.shape[:2]
    scale = min(1.0, DETECT_MAX / max(h, w))
    small = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA) if scale < 1 else img
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)

    markers = _detect_markers(gray, scale)
    result = ScanResult(qr_ids=_detect_qr(gray))
    for side in SIDES:
        mine = {i: p for i, p in markers.items() if MARKER_IDS[i][0] == side}
        if len(mine) >= 2:
            flat = _warp(img, side, mine)
            result.pages[side] = Page(side, _hide_markers(clean(flat), side), flat, len(mine))
    if not result.pages:
        raise ScanError(
            "Corner markers not found. Retake the photo with the full page in view, "
            "flat and well lit."
        )
    return result


def encode_jpeg(img: np.ndarray, quality: int = 85) -> bytes:
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, quality, cv2.IMWRITE_JPEG_OPTIMIZE, 1])
    if not ok:
        raise ScanError("Image could not be encoded.")
    return buf.tobytes()


def thumbnail(img: np.ndarray, width: int = 360) -> bytes:
    h, w = img.shape[:2]
    t = cv2.resize(img, (width, round(h * width / w)), interpolation=cv2.INTER_AREA)
    return encode_jpeg(t, 75)
