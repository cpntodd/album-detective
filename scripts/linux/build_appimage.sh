#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"

TOOLS_DIR="$ROOT_DIR/build/tools"
DIST_DIR="$ROOT_DIR/dist/linux"
VENV_DIR="${TMPDIR:-/tmp}/compare-packaging-venv"
TMP_BUILD_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/compare-appimage-build-XXXXXX")"
PYI_DIST_DIR="$TMP_BUILD_ROOT/pyinstaller-dist"
PYI_WORK_DIR="$TMP_BUILD_ROOT/pyinstaller-work"
APPDIR="$TMP_BUILD_ROOT/AppDir"
APP_NAME="compare"
DESKTOP_FILE="$APPDIR/${APP_NAME}.desktop"
ICON_FILE="$APPDIR/${APP_NAME}.png"
APPIMAGE_TOOL="$TOOLS_DIR/appimagetool.AppImage"
TMP_APPIMAGE="$TMP_BUILD_ROOT/Music-Compare-x86_64.AppImage"

cleanup() {
    rm -rf "$TMP_BUILD_ROOT"
}
trap cleanup EXIT

mkdir -p "$TOOLS_DIR" "$DIST_DIR"

python3 -m venv --copies "$VENV_DIR"
"$VENV_DIR/bin/python" -m pip install --upgrade pip
"$VENV_DIR/bin/python" -m pip install -r requirements.txt pyinstaller
"$VENV_DIR/bin/python" -m PyInstaller --noconfirm --clean --distpath "$PYI_DIST_DIR" --workpath "$PYI_WORK_DIR" build/compare.spec

mkdir -p "$APPDIR/usr/bin"
cp -r "$PYI_DIST_DIR/$APP_NAME" "$APPDIR/usr/bin/$APP_NAME"

cat > "$APPDIR/AppRun" << 'EOF'
#!/usr/bin/env bash
set -euo pipefail
HERE="$(dirname "$(readlink -f "$0")")"
exec "$HERE/usr/bin/compare/compare-bin" "$@"
EOF
chmod +x "$APPDIR/AppRun"

cat > "$DESKTOP_FILE" << EOF
[Desktop Entry]
Type=Application
Name=Music Compare
Exec=compare
Icon=compare
Categories=AudioVideo;Utility;
Terminal=false
EOF

# 1x1 transparent PNG placeholder icon in base64.
base64 -d > "$ICON_FILE" << 'EOF'
iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+iF9sAAAAASUVORK5CYII=
EOF

if [[ ! -x "$APPIMAGE_TOOL" ]]; then
    curl -L "https://github.com/AppImage/AppImageKit/releases/download/continuous/appimagetool-x86_64.AppImage" -o "$APPIMAGE_TOOL"
    chmod +x "$APPIMAGE_TOOL"
fi

ARCH=x86_64 "$APPIMAGE_TOOL" "$APPDIR" "$TMP_APPIMAGE"
cp "$TMP_APPIMAGE" "$DIST_DIR/Music-Compare-x86_64.AppImage"

echo "AppImage created at: $DIST_DIR/Music-Compare-x86_64.AppImage"
