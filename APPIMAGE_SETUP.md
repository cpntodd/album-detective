# AppImage Launch Fix

## Problem
The AppImage fails to launch with error:
```
ModuleNotFoundError: No module named 'tkinter'
```

## Root Cause
**Tkinter is not installed on the build system.** Tkinter is a GUI framework included with Python but must be installed separately as a system package (`python3-tk`). When the AppImage is built without it, the bundled application cannot import tkinter and fails to start.

## Solution

### Step 1: Install tkinter on the build system
```bash
# For Debian/Ubuntu-based systems:
sudo apt-get update
sudo apt-get install -y python3-tk

# For Fedora/RHEL-based systems:
sudo dnf install -y python3-tkinter

# For Arch-based systems:
sudo pacman -S tk
```

### Step 2: Rebuild the AppImage
Once tkinter is installed, rebuild the AppImage:
```bash
cd /path/to/album-detective
bash scripts/linux/build_appimage.sh
```

The rebuilt AppImage will be at:
```
dist/linux/Music-Compare-x86_64.AppImage
```

### Step 3: Verify the AppImage launches
```bash
./dist/linux/Music-Compare-x86_64.AppImage
```

## Technical Details
- The build script now includes `--system-site-packages` flag when creating the venv, allowing PyInstaller to access system tkinter
- The PyInstaller spec file includes `tkinter` in the `hiddenimports` list
- Without tkinter installed on the build system, PyInstaller cannot bundle it into the binary

## Files Modified
- [scripts/linux/build_appimage.sh](scripts/linux/build_appimage.sh) - Added `--system-site-packages` flag
- [build/compare.spec](build/compare.spec) - Added tkinter and app.genre_verifier to hiddenimports
