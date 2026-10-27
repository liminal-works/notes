# Project notes for Claude

Self-hosted scrap-paper notes scanner. Read README.md for the full picture.

## Production

- Runs on the user's VPS at `http://67.217.63.103:8737` (same VPS as glub.chat; no domain, plain HTTP).
- Code: `/opt/notes` (a clone of this public repo). Data: `/var/lib/notes`. Upload key: `/var/lib/notes/upload_key.txt`.
- systemd service `notes`, running as a DynamicUser (it can't read `/root`, which is why the code is in `/opt`).
- Python 3.10 on Ubuntu; the venv is `/opt/notes/.venv`.
- **After pushing changes, tell the user to deploy with:**
  `cd /opt/notes && git pull && systemctl restart notes`
  (plus `.venv/bin/pip install -r requirements.txt` if dependencies changed, or copying the unit
  file and `systemctl daemon-reload` if `deploy/notes.service` changed).
- You can't reach the VPS from a Claude session; the user runs commands there and pastes output.

## Things that must keep working

- Printed sheets are permanent. QR codes encode `http://67.217.63.103:8737/s/<ID>-<A|B>`; don't change
  that URL shape.
- Sheet IDs are `S` + 4–8 hex digits. New sheets get 8 random hex digits. The first printed batch is
  S0001–S0050 (decimal digits are valid hex) and must stay valid.
- Existing `meta.json` files in `/var/lib/notes/sheets/` must load without migration.
- Phone uploads are shrunk client-side (1600 px, JPEG 0.8) because the user's signal at work is weak.

## Style

- UI text: neutral and professional, not written as personal notes to the user.
