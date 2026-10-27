"""Settings, read from environment variables (see README)."""
import os
import secrets
from pathlib import Path

# Public address printed into every QR code. Changing it later does not break
# already-uploaded notes (they are stored by sheet ID), but printed sheets keep
# whatever address they were printed with.
BASE_URL = os.environ.get("NOTES_BASE_URL", "http://67.217.63.103:8737").rstrip("/")

HOST = os.environ.get("NOTES_HOST", "0.0.0.0")
PORT = int(os.environ.get("NOTES_PORT", "8737"))

DATA_DIR = Path(os.environ.get("NOTES_DATA_DIR", Path(__file__).resolve().parent.parent / "data"))

MAX_UPLOAD_MB = int(os.environ.get("NOTES_MAX_UPLOAD_MB", "25"))


def upload_key() -> str:
    """The key that protects uploads and edits.

    Uses NOTES_UPLOAD_KEY if set; otherwise generates one on first run and keeps
    it in data/upload_key.txt.
    """
    env = os.environ.get("NOTES_UPLOAD_KEY")
    if env:
        return env.strip()
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    path = DATA_DIR / "upload_key.txt"
    if not path.exists():
        path.write_text(secrets.token_urlsafe(18) + "\n")
        path.chmod(0o600)
    return path.read_text().strip()
