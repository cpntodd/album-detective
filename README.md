# Album Detective

![Banner](images/banner.png)

![Downloads](https://img.shields.io/github/downloads/cpntodd/album-detective/total)
![GitHub stars](https://img.shields.io/github/stars/cpntodd/album-detective?style=flat-square)
![GitHub watchers](https://img.shields.io/github/watchers/cpntodd/album-detective?style=flat-square)

I have been collecting CDs for at least 20 years now.

About 10 years ago, Apple removed purchased content from my account without warning or compensation. Since then, I have focused on preserving my offline CDs, DVDs, and Blu-rays, and I now host my own Jellyfin server to move away from modern streaming platforms.

I got tired of playing detective with spreadsheets and ten browser tabs just to answer one question:

"Which albums am I still missing?"

## Announcing Album Detective

Album Detective is the gap app between your cloud-based likes on Spotify and your offline or Jellyfin collection.

Short version: Album Detective is a desktop app for collectors who want to cross-reference local music against Spotify and Jellyfin data, then quickly review missing albums with artwork and export-ready results.

You export your Spotify liked list to .csv (or .ccv, depending on the tool), then scan your own media collection against that list.

Spotify API integration is in progress.

The CSV Viewer window shows you albums you do not have yet with clear images, because I am a visual kind of guy.

Then you can export that list and go hunting for those missing albums.

## Why this exists

- Collectors need workflow, not chaos.
- Album names are messy (Remastered, Deluxe, Special Edition, etc.), so matching has to be smarter than plain text compare.
- Missing-album review should be visual, quick, and filterable.
- Self-hosters need a bridge between streaming likes and offline ownership.

## What it does

- Read-only local scan with multi-threaded indexing.
- Incremental scan cache for faster repeat runs.
- Spotify CSV cleanup to app-compatible fields.
- Missing album detection using normalized artist and album keys.
- Compare source selection: Local or Jellyfin.
- Progress + cancel support for long operations.
- Persistent settings and theme selection.
- Genre verification module (MusicBrainz) to suggest consistent album genre tags for local libraries.

## Screenshots

### Main Menu

![Main Menu](images/main%20menu.png)

### Settings Menu

![Settings Menu](images/settings-menu.png)

### CSV Viewer Window

![CSV Viewer](images/csv-viewer.png)

## CSV Viewer (where the real work happens)

- Open from File -> View CSV in New Window.
- Sortable columns and live filtering.
- Open latest CSV quickly.
- Export visible rows to Excel.
- Row actions for opening album searches in Spotify and Jellyfin.
- Large 600x600 artwork preview panel on row selection for quick visual checks.
- Artwork caching progress bar with cached vs resolver counts.
- Thread selector to tune resolver throughput.
- Cache-first artwork loading from:
  - ROOT/cache/artwork
  - ~/cache/artwork

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

## Default paths

- Local folder (OS-aware):
  Linux: /media/share/Media/Music, then ~/Music, then ~/music
  Windows: ~/Music, then ~/OneDrive/Music
- Spotify CSV: ~/Downloads/My Spotify Library.csv
- Output folder: ROOT/Output (fixed)

You can change all of these in the UI.

## Quick start

```bash
cd /media/share/Projects/album\ detective
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Run

```bash
python main.py
```

## Compare flow

1. Choose compare source (Local or Jellyfin).
2. Run compare against Spotify data.
3. Review generated outputs in ROOT/Output.
4. Open CSV Viewer to inspect missing albums with artwork.

## Genre verification flow

Use Tools -> Verify Genres (MusicBrainz).

- Scans your local folder read-only and groups tracks by artist/album.
- Reads existing local genre tags (if present).
- Queries MusicBrainz release-group tags and picks a suggested canonical genre.
- Exports actionable suggestions to:
  - ROOT/Output/genre_tag_suggestions.csv

`Action` values in the export:

- add-genre: local metadata has no genre, suggestion found.
- update-genre: local genre differs and MusicBrainz match confidence is high.
- review: possible mismatch, manual review recommended.
- keep: local genre already consistent.
- no-match: no reliable MusicBrainz match found.

## Spotify API import

Use File -> Import -> From Spotify.

Before first import, open Settings -> Preferences and set:

- Spotify Client ID
- Spotify Client Secret
- Spotify Redirect URI (default: <http://127.0.0.1:8888/callback>)

Required Spotify app scopes used by this app:

- user-library-read
- user-follow-read

Import output is written to:

- ROOT/Output/spotify_clean_tracks.csv

The imported CSV uses the same format as the compare pipeline:

- Track name,Artist,Album

## Jellyfin and NAS import alternatives

Use menu: File -> Import

- From Jellyfin
  - Uses Jellyfin API key authentication.
  - Fetches all audio items recursively for selected user.
  - Normalizes to Track name,Artist,Album and writes to ROOT/Output/local_music_tracks.csv.
- From NAS (cached)
  - Traverses selected folder and computes a fast incremental fingerprint per file.
  - Uses local cache directory: ROOT/cache/.
  - Reuses cached metadata for unchanged files to speed up repeat imports.
  - Normalizes and writes to ROOT/Output/local_music_tracks.csv.

Both importers update the Local side in-app and keep comparison logic unchanged.

## Theme selector

Use Settings -> Preferences -> Theme to choose from 14 palettes.

Theme styling is applied across the app UI elements, including menu bars, buttons, labels, entry fields, comboboxes, tree views, tables, progress bars, and scrollbars.

## Packaging

### Build Linux AppImage (Debian)

**System Requirements:** `python3-tk` must be installed before building.

```bash
# Install tkinter (required for GUI bundling)
sudo apt-get update
sudo apt-get install -y python3-tk

# Build the AppImage
cd /media/share/Projects/album\ detective
./scripts/linux/build_appimage.sh
```

Artifacts:

- dist/linux/Music-Compare-x86_64.AppImage

**Troubleshooting:** If the AppImage fails with `ModuleNotFoundError: No module named 'tkinter'`, see [APPIMAGE_SETUP.md](APPIMAGE_SETUP.md) for detailed setup instructions.
- dist/linux/compare/ (PyInstaller folder used for packaging)

### Build Windows EXE (Contributor workflow)

Run on Windows PowerShell:

```powershell
cd C:\path\to\album-detective
powershell -ExecutionPolicy Bypass -File .\scripts\windows\build_exe.ps1
```

Artifact:

- dist/windows/compare/

Note: Windows runtime testing is intended to be completed by a contributor on Windows.

## Output files

Generated in the selected output folder:

- ROOT/Output/local_music_tracks.csv with columns: Track name, Artist, Album
- ROOT/Output/spotify_clean_tracks.csv with columns: Track name, Artist, Album
- ROOT/Output/spotify_not_owned_albums_artists.csv with columns: Artist, Album
- ROOT/Output/genre_tag_suggestions.csv with columns: Artist, Album, Local Genre, Suggested Genre, Match Score, Confidence, Action

## Notes

- Scanner reads files only; it does not modify local media.
- Supported audio extensions include .mp3, .flac, .m4a, .aac, .ogg, .opus, .wav, .wma, .aiff, .ape, .alac.
- Matching is case-insensitive, whitespace-normalized, and edition-aware for common suffixes.
- Diagnostic and error events are logged to files under ROOT/Logs.
