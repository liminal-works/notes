# notes

A personal, self-hosted Rocketbook for scrap paper.

Print a template onto the blank back of scrap printer paper, fold it in half, write
on it, then scan the QR code with your phone. The app straightens and cleans the
photo and keeps each sheet as images plus a PDF you can open or download from any
browser.

## How it works

**The sheet.** Letter, landscape, folded on the dotted line into two halves, **A**
(left) and **B** (right). Each half has:

- a QR code (top-right) holding a link like `http://67.217.63.103:8737/s/S0142-A`
- three small square markers (ArUco) in the other corners, used to straighten the photo
- a small grey label `S0142-A` so you can read the sheet number

Every printed sheet has its own number, so a rescan replaces that page instead of
creating a duplicate.

**Scanning.** Point the iPhone camera at a half's QR code. It opens that sheet's page;
tap **Scan side A**, take the photo, done. You can photograph one half or the whole
unfolded sheet; the markers tell the server which halves are in the photo, and the
QR (if readable) confirms which sheet it is.

**Processing** (`app/scan.py`): find markers → warp each half flat at 200 DPI →
divide out lighting and paper tint (this also removes the faint mirrored print showing
through from the back) → whiten the background → hide the corner markers.

**Storage** is plain files, no database:

```
data/
  sheets/S0142/
    meta.json        title, dates, which sides exist
    A.jpg            cleaned page (what you see and what goes in the PDF)
    A.flat.jpg       straightened only, no cleanup ("unfiltered" link), useful for light pencil
    A.thumb.jpg
    originals/       every photo you uploaded
  unmatched/         photos where no markers were found
  state.json         highest sheet number printed so far
  upload_key.txt     generated upload key (if NOTES_UPLOAD_KEY isn't set)
```

Back up the `data/` folder and you've backed up everything.

## Pages

| URL | What |
|---|---|
| `/` | All notes, newest first. Search, select several, download as one PDF. |
| `/s/S0142-A` | One sheet (what the QR opens). Scan, rename, open/download PDF, delete. |
| `/print` | Make a template PDF. Suggests the next unused sheet number. |
| `/pdf/S0142.pdf` | PDF of one sheet (side A then B). Add `?download=1` to download. |
| `/pdf?ids=S0142,S0143` | Several sheets in one PDF. |
| `/template.pdf?start=1&count=50` | Template sheets. |

Viewing and downloading are open. **Uploading, renaming and deleting need the upload
key.** Open `http://67.217.63.103:8737/?key=YOUR_KEY` once on each device (phone, work
PC); it's saved as a cookie. Or just tap Scan and type it when asked.

## Deploy on the VPS

```bash
sudo apt install -y python3-venv git
sudo git clone https://github.com/liminal-works/notes /opt/notes
cd /opt/notes
sudo python3 -m venv .venv
sudo .venv/bin/pip install -r requirements.txt

sudo cp deploy/notes.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now notes

sudo ufw allow 8737/tcp            # if you use ufw; open the port in your VPS firewall too
sudo cat /var/lib/notes/upload_key.txt   # your upload key
```

Then visit `http://67.217.63.103:8737/?key=<that key>` on your phone and on your work PC.

It runs on port **8737** so it doesn't clash with anything already on 80/443 (glub.chat).

Update later with:

```bash
cd /opt/notes && sudo git pull && sudo .venv/bin/pip install -r requirements.txt && sudo systemctl restart notes
```

Logs: `journalctl -u notes -f`

### Settings (environment variables)

| Variable | Default |
|---|---|
| `NOTES_BASE_URL` | `http://67.217.63.103:8737`. Printed into the QR codes. |
| `NOTES_UPLOAD_KEY` | generated, stored in `data/upload_key.txt` |
| `NOTES_DATA_DIR` | `./data` (the systemd unit uses `/var/lib/notes`) |
| `NOTES_MAX_UPLOAD_MB` | `25` |

If the server's IP ever changes, update `NOTES_BASE_URL` and print new sheets. Notes
already uploaded are unaffected; old printed sheets just won't open the right page
from the phone camera anymore (you can still upload them with **Scan a sheet** on the
home page, which reads the sheet number from the photo's QR).

## Run locally

```bash
pip install -r requirements.txt
uvicorn app.main:app --port 8737
python -m app.template --start 1 --count 5 -o sheets.pdf   # template without the server
```

## Printing tips

- Print at **Actual size / 100%**, landscape. Scaling still works (the markers define
  the geometry) but actual size is best.
- Run one test page to find which way the scrap paper goes in the tray.
- Pen works best. Very light pencil may get washed out by the cleanup; the
  "unfiltered" link on each page shows the straightened photo without cleanup.
