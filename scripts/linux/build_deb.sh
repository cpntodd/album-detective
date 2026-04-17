#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"

VERSION="${1:-0.0.1}"
ARCH="amd64"
PKG_NAME="album-detective"
APP_NAME="compare"
APP_BIN="compare-bin"
DIST_DIR="$ROOT_DIR/dist/linux"
TOOLS_TMP="$(mktemp -d "${TMPDIR:-/tmp}/compare-deb-build-XXXXXX")"
VENV_DIR="${TMPDIR:-/tmp}/compare-packaging-venv"
PYI_DIST_DIR="$TOOLS_TMP/pyinstaller-dist"
PYI_WORK_DIR="$TOOLS_TMP/pyinstaller-work"
PKG_ROOT="$TOOLS_TMP/${PKG_NAME}_${VERSION}_${ARCH}"

cleanup() {
    rm -rf "$TOOLS_TMP"
}
trap cleanup EXIT

mkdir -p "$DIST_DIR"

python3 -m venv --copies "$VENV_DIR"
"$VENV_DIR/bin/python" -m pip install --upgrade pip
"$VENV_DIR/bin/python" -m pip install -r requirements.txt pyinstaller
"$VENV_DIR/bin/python" -m PyInstaller --noconfirm --clean --distpath "$PYI_DIST_DIR" --workpath "$PYI_WORK_DIR" build/compare.spec

mkdir -p "$PKG_ROOT/DEBIAN"
mkdir -p "$PKG_ROOT/opt/$PKG_NAME"
mkdir -p "$PKG_ROOT/usr/bin"
mkdir -p "$PKG_ROOT/usr/share/applications"
mkdir -p "$PKG_ROOT/usr/share/icons/hicolor/512x512/apps"

cp -r "$PYI_DIST_DIR/$APP_NAME" "$PKG_ROOT/opt/$PKG_NAME/$APP_NAME"
cp "$ROOT_DIR/images/icon.png" "$PKG_ROOT/usr/share/icons/hicolor/512x512/apps/$PKG_NAME.png"

cat > "$PKG_ROOT/usr/bin/$PKG_NAME" << 'EOF'
#!/usr/bin/env bash
set -euo pipefail
exec /opt/album-detective/compare/compare-bin "$@"
EOF
chmod +x "$PKG_ROOT/usr/bin/$PKG_NAME"

cat > "$PKG_ROOT/usr/share/applications/$PKG_NAME.desktop" << EOF
[Desktop Entry]
Type=Application
Name=Album Detective
Exec=$PKG_NAME
Icon=$PKG_NAME
Categories=AudioVideo;Utility;
Terminal=false
EOF

INSTALLED_SIZE_KB="$(du -sk "$PKG_ROOT" | awk '{print $1}')"

cat > "$PKG_ROOT/DEBIAN/control" << EOF
Package: $PKG_NAME
Version: $VERSION
Section: utils
Priority: optional
Architecture: $ARCH
Maintainer: cpntodd
Depends: libglib2.0-0, libx11-6, libxext6, libxrender1, libxi6, libxkbcommon0, libfontconfig1, libdbus-1-3
Installed-Size: $INSTALLED_SIZE_KB
Description: Album Detective desktop app
 Cross-reference local music collections against Spotify/Jellyfin and review missing albums.
EOF

DEB_PATH="$DIST_DIR/${PKG_NAME}_${VERSION}_${ARCH}.deb"
dpkg-deb --root-owner-group --build "$PKG_ROOT" "$DEB_PATH"

echo ".deb created at: $DEB_PATH"
