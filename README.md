# Music Library vs Spotify (Python)

Local music scan and compare tool for music collectors.

This desktop application compares your local library against your online collections on platforms like Spotify to help you identify missing discography.

What it does:

- Scans a local music folder in read-only mode.
- Extracts `Track name`, `Artist`, and `Album` from metadata (or folder structure fallback).
- Cleans a Spotify library CSV to only those same fields.
- Compares local vs Spotify and exports albums/artists found online but not owned locally.
- Shows a UI with file explorer and Local vs Spotify tables.
- Includes a Preferences dialog with persistent configuration.

## Runtime folder structure

When the app starts, it creates and uses this structure in the current run directory:

- ROOT/Config
- ROOT/Logs
- ROOT/Output

Persistent config file:

- ROOT/Config/settings.json

Log files:

- ROOT/Logs/diagnostic.log
- ROOT/Logs/error.log

## Paths used by default

- Local folder (OS-aware):
  Linux: `/media/share/Media/Music`, then `~/Music`, then `~/music`
  Windows: `~/Music`, then `~/OneDrive/Music`
- Spotify CSV: `~/Downloads/My Spotify Library.csv`
- Output folder: `ROOT/Output` (fixed)

You can change all of these in the UI.

## Install

```bash
cd /media/share/Projects/compare
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Run

```bash
python main.py
```

## Packaging

### Build Linux AppImage (Debian)

```bash
cd /media/share/Projects/compare
./scripts/linux/build_appimage.sh
```

Artifacts:

- `dist/linux/Music-Compare-x86_64.AppImage`
- `dist/linux/compare/` (PyInstaller folder used for packaging)

### Build Windows EXE (Contributor workflow)

Run on Windows PowerShell:

```powershell
cd C:\path\to\compare
powershell -ExecutionPolicy Bypass -File .\scripts\windows\build_exe.ps1
```

Artifact:

- `dist/windows/compare/`

Note: Windows runtime testing is intended to be completed by a contributor on Windows.

## Output files

Generated in the selected output folder:

- `ROOT/Output/local_music_tracks.csv` with columns: `Track name`, `Artist`, `Album`
- `ROOT/Output/spotify_clean_tracks.csv` with columns: `Track name`, `Artist`, `Album`
- `ROOT/Output/spotify_not_owned_albums_artists.csv` with columns: `Artist`, `Album`

After export completes, the app asks:

- `Do you want to open file location?`

Select `Yes` to open the output folder in your system file explorer (`Windows` and `Linux` supported), or `No` to close the dialog.

## Notes

- Scanner reads files only; it does not modify local media.
- Supported audio extensions include `.mp3`, `.flac`, `.m4a`, `.aac`, `.ogg`, `.opus`, `.wav`, `.wma`, `.aiff`, `.ape`, `.alac`.
- Matching is case-insensitive and whitespace-normalized.
- Diagnostic and error events are logged to files under `ROOT/Logs`.
- AppImage runtime smoke test completed on Debian in this workspace: runtime metadata command and squashfs extraction succeeded, and direct launch stayed running until timeout (GUI expected).
