"""Geometry of the printed bi-fold sheet, shared by the template and the scanner.

All values are in PDF points (1/72 inch) with the origin at the TOP-LEFT of the
landscape letter sheet and y growing downward (image convention). The sheet is
folded along the vertical centre line into two portrait halves, A (left) and
B (right).
"""
import re
import secrets

import cv2

INCH = 72.0
PAGE_W = 11 * INCH          # letter, landscape
PAGE_H = 8.5 * INCH
HALF_W = PAGE_W / 2         # each half is 5.5" x 8.5" portrait
FOLD_X = HALF_W

MARGIN = 0.35 * INCH        # inset of markers/QR from every edge of a half (printers can't print the outer ~0.25")
MARKER = 0.45 * INCH        # ArUco marker size
QR = 0.80 * INCH            # QR size (~2 cm)
CROP_INSET = 0.12 * INCH    # trim when cropping, so printer offset never shows the table under the paper

ARUCO_DICT = cv2.aruco.DICT_4X4_50

# Each half has its QR in the top-right corner and ArUco markers in the other three.
# marker id -> (side, corner)
MARKER_IDS = {
    0: ("A", "tl"), 1: ("A", "bl"), 2: ("A", "br"),
    3: ("B", "tl"), 4: ("B", "bl"), 5: ("B", "br"),
}
SIDES = ("A", "B")

# Sheet IDs are "S" + 4-8 hex digits. New sheets get 8 random hex digits
# (about 4 billion possibilities). The first printed batch used S0001-S0050:
# decimal digits are valid hex, so those IDs still match and keep working.
SHEET_RE = re.compile(r"S[0-9A-F]{4,8}", re.I)
PAGE_RE = re.compile(r"\b(S[0-9A-F]{4,8})-([AB])\b", re.I)


def new_sheet_id() -> str:
    return "S" + secrets.token_hex(4).upper()


def half_left(side: str) -> float:
    return 0.0 if side == "A" else HALF_W


def marker_rect(side: str, corner: str):
    """Top-left (x, y) of a marker, in sheet coordinates."""
    x0 = half_left(side)
    x = x0 + MARGIN if corner in ("tl", "bl") else x0 + HALF_W - MARGIN - MARKER
    y = MARGIN if corner == "tl" else PAGE_H - MARGIN - MARKER
    return x, y


def marker_corners(side: str, corner: str):
    """The marker's 4 corners in the order OpenCV reports them: TL, TR, BR, BL."""
    x, y = marker_rect(side, corner)
    return [(x, y), (x + MARKER, y), (x + MARKER, y + MARKER), (x, y + MARKER)]


def qr_rect(side: str):
    x0 = half_left(side)
    return x0 + HALF_W - MARGIN - QR, MARGIN


def crop_box(side: str):
    """Region of the sheet kept for a half: (x, y, w, h)."""
    x0 = half_left(side)
    return x0 + CROP_INSET, CROP_INSET, HALF_W - 2 * CROP_INSET, PAGE_H - 2 * CROP_INSET


def page_url(base_url: str, sid: str, side: str) -> str:
    return f"{base_url}/s/{sid}-{side}"
