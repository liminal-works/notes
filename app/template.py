"""Printable bi-fold template: one landscape letter page per sheet.

Run directly to write a PDF:  python -m app.template --count 50 -o sheets.pdf

Every sheet gets a fresh random ID, so there's no numbering to keep track of.
"""
import argparse
import io

import cv2
from reportlab.graphics import renderPDF
from reportlab.graphics.barcode.qr import QrCodeWidget
from reportlab.graphics.shapes import Drawing
from reportlab.lib.colors import Color, black
from reportlab.pdfgen import canvas

from . import config
from .layout import (
    ARUCO_DICT, FOLD_X, MARKER, MARKER_IDS, PAGE_H, PAGE_W, QR, marker_rect, new_sheet_id, page_url, qr_rect,
)

_DICT = cv2.aruco.getPredefinedDictionary(ARUCO_DICT)
GREY = Color(0.6, 0.6, 0.6)


def _rl_y(y: float, h: float) -> float:
    """Convert a top-left-origin y to reportlab's bottom-left origin."""
    return PAGE_H - y - h


def _draw_marker(c: canvas.Canvas, marker_id: int, x: float, y: float):
    # 4x4 data bits + 1-cell black border = 6x6 cells; drawn as vector squares so it prints crisp.
    bits = cv2.aruco.generateImageMarker(_DICT, marker_id, 6)
    cell = MARKER / 6
    c.setFillColor(black)
    for r in range(6):
        for col in range(6):
            if bits[r, col] < 128:
                c.rect(x + col * cell, _rl_y(y + r * cell, cell), cell, cell, stroke=0, fill=1)


def _draw_qr(c: canvas.Canvas, data: str, x: float, y: float):
    w = QrCodeWidget(data, barLevel="M", barBorder=0)
    x0, y0, x1, y1 = w.getBounds()
    s = QR / (x1 - x0)
    d = Drawing(QR, QR, transform=[s, 0, 0, s, -x0 * s, -y0 * s])
    d.add(w)
    renderPDF.draw(d, c, x, _rl_y(y, QR))


def draw_sheet(c: canvas.Canvas, sid: str, base_url: str):
    # fold line
    c.setStrokeColor(GREY)
    c.setLineWidth(0.6)
    c.setDash(1, 4)
    c.line(FOLD_X, 0.3 * 72, FOLD_X, PAGE_H - 0.3 * 72)
    c.setDash()
    for mid, (side, corner) in MARKER_IDS.items():
        _draw_marker(c, mid, *marker_rect(side, corner))
    for side in ("A", "B"):
        qx, qy = qr_rect(side)
        _draw_qr(c, page_url(base_url, sid, side), qx, qy)
        c.setFillColor(GREY)
        c.setFont("Helvetica", 7)
        c.drawRightString(qx + QR, _rl_y(qy + QR + 9, 0), f"{sid}-{side}")


def new_ids(count: int, taken=frozenset()) -> list[str]:
    """`count` random sheet IDs, unique within the batch and not in `taken`."""
    ids: list[str] = []
    while len(ids) < count:
        sid = new_sheet_id()
        if sid not in taken and sid not in ids:
            ids.append(sid)
    return ids


def build_pdf(ids: list[str], base_url: str | None = None) -> bytes:
    base_url = base_url or config.BASE_URL
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(PAGE_W, PAGE_H))
    c.setTitle(f"Notes sheets ({len(ids)})")
    for sid in ids:
        draw_sheet(c, sid, base_url)
        c.showPage()
    c.save()
    return buf.getvalue()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=50)
    ap.add_argument("-o", "--out", default="sheets.pdf")
    a = ap.parse_args()
    with open(a.out, "wb") as f:
        f.write(build_pdf(new_ids(a.count)))
    print(f"wrote {a.out}")
