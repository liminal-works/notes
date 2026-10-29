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

# Ruled lines (college-ruled spacing). Page A: top half only, bottom half blank. Page B: full page.
RULE_SPACING = 9 / 32 * INCH
RULE_TOP = MARGIN + QR + 0.30 * INCH   # first line sits below the QR code and its label
RULE_BOTTOM = PAGE_H / 2               # page A: last line at the middle of the page
# Page B is ruled all the way down, stopping just above the bottom corner markers
# (a line touching a marker could stop it from being detected).
RULE_BOTTOM_FULL = PAGE_H - MARGIN - MARKER - 0.15 * INCH

# Title line: between the top-left marker and the QR code, level with the marker's bottom edge.
TITLE_GAP = 0.22 * INCH

# Faint dot grid filling page A's blank bottom half.
DOT_STEP = 0.25 * INCH

# Folder circles 01-05 along the bottom of page A, between the bottom corner markers.
# Filling one in files the scan into the folder linked to that number.
CIRCLE_COUNT = 5
CIRCLE_R = 0.07 * INCH
CIRCLE_SIDE = "A"
STRIP_GAP = 0.28 * INCH  # clearance between the strip and the markers

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


def rule_lines(side: str):
    """Ruled lines for a half as (x0, x1, y) tuples, in sheet coordinates."""
    x0 = half_left(side) + MARGIN
    x1 = half_left(side) + HALF_W - MARGIN
    bottom = RULE_BOTTOM if side == "A" else RULE_BOTTOM_FULL
    n = int((bottom - RULE_TOP) // RULE_SPACING) + 1
    return [(x0, x1, RULE_TOP + k * RULE_SPACING) for k in range(n)]


def title_line(side: str):
    """(x0, x1, y) of the title line."""
    x0 = half_left(side) + MARGIN + MARKER + TITLE_GAP
    x1 = qr_rect(side)[0] - TITLE_GAP
    return x0, x1, MARGIN + MARKER


def dot_grid(side: str):
    """Dot centres for page A's bottom half (empty list for page B)."""
    if side != "A":
        return []
    left, right = half_left(side) + MARGIN, half_left(side) + HALF_W - MARGIN
    bottom = PAGE_H - MARGIN - MARKER - 0.25 * INCH
    dots, y = [], RULE_BOTTOM + DOT_STEP
    while y <= bottom + 0.01:
        x = left
        while x <= right + 0.01:
            dots.append((x, y))
            x += DOT_STEP
        y += DOT_STEP
    return dots


def circle_centres(side: str = CIRCLE_SIDE):
    """Centres of the folder circles 1..5, in sheet coordinates (empty for the other page)."""
    if side != CIRCLE_SIDE:
        return []
    x0 = half_left(side)
    left = x0 + MARGIN + MARKER + STRIP_GAP
    right = x0 + HALF_W - MARGIN - MARKER - STRIP_GAP
    y = PAGE_H - MARGIN - MARKER / 2
    slot = (right - left) / CIRCLE_COUNT
    return [(left + slot * (i + 0.5), y) for i in range(CIRCLE_COUNT)]
