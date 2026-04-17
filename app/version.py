"""Album Detective version information.

Update VERSION for each release:
- Increment PATCH (0.0.X) for each major codebase update
"""

__version__ = "0.0.2"
__title__ = "Album Detective"
__description__ = "Desktop app for collectors to cross-reference local music against Spotify and Jellyfin data"
__author__ = "cpntodd"
__license__ = "MIT"

# Version history:
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
