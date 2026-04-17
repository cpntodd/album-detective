"""Album Detective version information.

Update VERSION for each release:
- Increment PATCH (0.0.X) for each major codebase update
"""

__version__ = "0.0.6"
__title__ = "Album Detective"
__description__ = "Desktop app for collectors to cross-reference local music against Spotify and Jellyfin data"
__author__ = "cpntodd"
__license__ = "MIT"

# Version history:
# 0.0.6 (April 17, 2026):
#   - About dialog avatar always shown in ellipse (Canvas)
#   - Avatar fetched from github.com/<username>.png, fallback to local icon
#   - UI polish: ellipse always shown, robust fallback, PIL ellipse masking
#
# 0.0.5 (April 17, 2026):
#   - Replaced static About popup with dynamic GitHub-backed About dialog
#   - Added clickable developer profile and repository links
#   - Added live avatar/profile/repo metadata with offline fallback
#
# 0.0.4 (April 17, 2026):
#   - Added StartupWMClass to Debian desktop entry for panel pinning compatibility
#   - Removed AppImage scripts/docs/workflow references
#   - Linux packaging is now Debian (.deb) only
#
# 0.0.3 (April 17, 2026):
#   - Tools panel UI updated to remove vertical tabs
#   - Tool buttons now shown in descending alphabetical order
#
# 0.0.2 (April 17, 2026):
#   - Persistent genre verification server with batching
#   - Three-level caching (memory, disk, report-level)
#   - Delta scanning with file change tracking
#   - Signature-based validation result caching
#   - Production-grade optimization patterns from HOI4StudioGUI
#
# 0.0.1 (Initial Release):
#   - Local music folder scanning
#   - Spotify CSV import and comparison
#   - Jellyfin integration
#   - Genre verification with MusicBrainz
#   - Desktop UI with theme support
