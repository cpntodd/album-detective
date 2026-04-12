from __future__ import annotations

import csv
import logging
import sys
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote_plus

from PySide6.QtCore import QObject, QRunnable, QSize, Qt, QThreadPool, Signal
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..runtime import setup_logging
from ..utils.artwork_resolver import ArtworkResolver


ARTWORK_COLUMN = 0
MIN_ROW_HEIGHT = 86
DEFAULT_ARTWORK_THREADS = 4
MIN_ARTWORK_THREADS = 1
MAX_ARTWORK_THREADS = 16
THUMBNAIL_SIZE = 72
PREVIEW_SIZE = 600


@dataclass(frozen=True)
class CSVRow:
    values: dict[str, str]

    @property
    def artist(self) -> str:
        return self.values.get("Artist", "").strip()

    @property
    def album(self) -> str:
        return self.values.get("Album", "").strip()


class ArtworkWorkerSignals(QObject):
    resolved = Signal(str, str, str)


class ArtworkWorker(QRunnable):
    def __init__(self, artist: str, album: str, resolver: ArtworkResolver) -> None:
        super().__init__()
        self.artist = artist
        self.album = album
        self.resolver = resolver
        self.signals = ArtworkWorkerSignals()

    def run(self) -> None:
        resolution = self.resolver.resolve(self.artist, self.album)
        if resolution is None:
            self.signals.resolved.emit(self.artist, self.album, "")
            return
        self.signals.resolved.emit(self.artist, self.album, str(resolution.image_path))


class CSVViewerWindow(QMainWindow):
    def __init__(
        self,
        csv_path: Path,
        *,
        output_dir: Path,
        cache_dir: Path,
        jellyfin_base_url: str,
        logger: logging.Logger,
    ) -> None:
        super().__init__()
        self.logger = logger.getChild("csv_viewer")
        self.output_dir = output_dir
        self.cache_dir = cache_dir
        self.jellyfin_base_url = jellyfin_base_url.rstrip("/")
        self.csv_path = csv_path
        self.rows: list[CSVRow] = []
        self.columns: list[str] = []
        self._artwork_total = 0
        self._artwork_completed = 0
        self._artwork_with_image = 0
        self._artwork_cached_hits = 0
        self._resolver_keys: set[tuple[str, str]] = set()
        self._artwork_scheduled_keys: set[tuple[str, str]] = set()
        self._artwork_completed_keys: set[tuple[str, str]] = set()
        self._artwork_paths: dict[tuple[str, str], str] = {}
        self.thread_pool = QThreadPool.globalInstance()
        self.artwork_resolver = ArtworkResolver(cache_root=self.cache_dir, use_cache=True, logger=self.logger)
        self._set_artwork_threads(DEFAULT_ARTWORK_THREADS)

        self.setWindowTitle("CSV Viewer")
        self.resize(1180, 760)

        central = QWidget(self)
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        toolbar = QHBoxLayout()
        layout.addLayout(toolbar)

        toolbar.addWidget(QLabel("Search"))

        self.search_input = QLineEdit(self)
        self.search_input.setPlaceholderText("Filter rows live...")
        self.search_input.textChanged.connect(self._apply_filter)
        toolbar.addWidget(self.search_input, stretch=1)

        open_last_button = QPushButton("Open Last CSV", self)
        open_last_button.clicked.connect(self._open_last_generated_csv)
        toolbar.addWidget(open_last_button)

        export_button = QPushButton("Export to Excel", self)
        export_button.clicked.connect(self._export_to_excel)
        toolbar.addWidget(export_button)

        toolbar.addWidget(QLabel("Threads"))
        self.thread_selector = QSpinBox(self)
        self.thread_selector.setRange(MIN_ARTWORK_THREADS, MAX_ARTWORK_THREADS)
        self.thread_selector.setValue(DEFAULT_ARTWORK_THREADS)
        self.thread_selector.setSingleStep(1)
        self.thread_selector.setToolTip("Adjust concurrent artwork lookups")
        self.thread_selector.valueChanged.connect(self._on_threads_changed)
        toolbar.addWidget(self.thread_selector)

        self.table = QTableWidget(self)
        self.table.setSortingEnabled(True)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setIconSize(QSize(THUMBNAIL_SIZE, THUMBNAIL_SIZE))
        self.table.verticalHeader().setDefaultSectionSize(MIN_ROW_HEIGHT)
        self.table.horizontalHeader().setSectionsClickable(True)
        self.table.horizontalHeader().setStretchLastSection(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.table.cellClicked.connect(self._on_table_cell_clicked)
        self.table.cellDoubleClicked.connect(self._open_row_targets)
        self.table.verticalScrollBar().valueChanged.connect(self._on_table_scrolled)

        content_row = QHBoxLayout()
        content_row.addWidget(self.table, stretch=1)

        preview_panel = QFrame(self)
        preview_panel.setFrameShape(QFrame.StyledPanel)
        preview_layout = QVBoxLayout(preview_panel)
        preview_layout.setContentsMargins(10, 10, 10, 10)
        preview_layout.setSpacing(8)

        preview_layout.addWidget(QLabel("Artwork Preview", self))
        self.preview_image = QLabel(self)
        self.preview_image.setAlignment(Qt.AlignCenter)
        self.preview_image.setMinimumSize(PREVIEW_SIZE, PREVIEW_SIZE)
        self.preview_image.setMaximumSize(PREVIEW_SIZE, PREVIEW_SIZE)
        self.preview_image.setStyleSheet("border: 1px solid #4a4a4a; background: #1f2430;")
        self.preview_image.setText("Select an album to preview artwork")
        preview_layout.addWidget(self.preview_image, alignment=Qt.AlignTop)

        self.preview_meta = QLabel(self)
        self.preview_meta.setWordWrap(True)
        self.preview_meta.setText("No album selected")
        preview_layout.addWidget(self.preview_meta)
        preview_layout.addStretch(1)

        content_row.addWidget(preview_panel, stretch=0)
        layout.addLayout(content_row, stretch=1)

        self.artwork_progress = QProgressBar(self)
        self.artwork_progress.setTextVisible(True)
        layout.addWidget(self.artwork_progress)

        self.status_label = QLabel(self)
        layout.addWidget(self.status_label)

        self._load_csv(self.csv_path)

    def _load_csv(self, csv_path: Path) -> None:
        if not csv_path.exists():
            QMessageBox.warning(self, "CSV Viewer", f"CSV not found:\n{csv_path}")
            return

        try:
            with csv_path.open("r", newline="", encoding="utf-8-sig") as handle:
                reader = csv.DictReader(handle)
                if not reader.fieldnames:
                    raise ValueError("CSV has no header row.")

                self.columns = [str(column).strip() for column in reader.fieldnames if str(column).strip()]
                self.rows = [
                    CSVRow(values={column: str((row.get(column) or "")).strip() for column in self.columns})
                    for row in reader
                ]
        except Exception as exc:
            self.logger.exception("Failed to read CSV: %s", csv_path)
            QMessageBox.critical(self, "CSV Viewer", str(exc))
            return

        self.csv_path = csv_path
        self.setWindowTitle(f"CSV Viewer - {self.csv_path.name}")
        self._populate_table()
        self.status_label.setText(f"Loaded {len(self.rows)} rows from {self.csv_path}")

    def _populate_table(self) -> None:
        self.table.setSortingEnabled(False)
        self.table.clear()
        self.table.setRowCount(len(self.rows))
        self.table.setColumnCount(len(self.columns) + 1)
        self.table.setHorizontalHeaderLabels(["Artwork", *self.columns])
        self._artwork_total = 0
        self._artwork_completed = 0
        self._artwork_with_image = 0
        self._artwork_cached_hits = 0
        self._resolver_keys.clear()
        self._artwork_scheduled_keys.clear()
        self._artwork_completed_keys.clear()
        self._artwork_paths.clear()
        self._clear_preview()

        key_to_display: dict[tuple[str, str], tuple[str, str]] = {}
        for row in self.rows:
            if not row.artist or not row.album:
                continue
            key = (row.artist.casefold(), row.album.casefold())
            key_to_display.setdefault(key, (row.artist, row.album))

        for row_index, row in enumerate(self.rows):
            artwork_item = QTableWidgetItem("")
            artwork_item.setFlags(artwork_item.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(row_index, ARTWORK_COLUMN, artwork_item)

            for offset, column in enumerate(self.columns, start=1):
                cell_item = QTableWidgetItem(row.values.get(column, ""))
                cell_item.setFlags(cell_item.flags() & ~Qt.ItemIsEditable)
                self.table.setItem(row_index, offset, cell_item)

        # Preload every cached artwork first, independent of scroll position.
        for key, (artist, album) in key_to_display.items():
            cached_only = self.artwork_resolver.resolve_cached_only(artist, album)
            if cached_only is None:
                self._resolver_keys.add(key)
                continue
            path_str = str(cached_only.image_path)
            self._artwork_paths[key] = path_str
            self._artwork_with_image += 1
            self._artwork_cached_hits += 1
            self._apply_artwork_icon(artist, album, path_str)

        self._artwork_total = len(self._resolver_keys)
        self._update_artwork_progress()

        self.table.setColumnWidth(ARTWORK_COLUMN, THUMBNAIL_SIZE + 18)
        for index in range(1, self.table.columnCount()):
            self.table.horizontalHeader().setSectionResizeMode(index, QHeaderView.ResizeToContents)

        self.table.setSortingEnabled(True)
        self._apply_filter(self.search_input.text())
        self._queue_initial_artwork()

    def _queue_initial_artwork(self) -> None:
        # Prioritize what the user can see first, then a small warm-up window.
        self._queue_visible_artwork(buffer_rows=4)
        if self.table.rowCount() > 0:
            self._queue_row_window(0, min(self.table.rowCount() - 1, 80))

    def _on_table_scrolled(self, _value: int) -> None:
        self._queue_visible_artwork(buffer_rows=6)

    def _queue_visible_artwork(self, *, buffer_rows: int = 4) -> None:
        if self.table.rowCount() <= 0:
            return

        first_visible = self.table.rowAt(0)
        if first_visible < 0:
            first_visible = 0

        last_visible = self.table.rowAt(self.table.viewport().height() - 1)
        if last_visible < 0:
            last_visible = min(self.table.rowCount() - 1, first_visible + 20)

        start = max(0, first_visible - buffer_rows)
        end = min(self.table.rowCount() - 1, last_visible + buffer_rows)
        self._queue_row_window(start, end)

    def _queue_row_window(self, start_row: int, end_row: int) -> None:
        for row_index in range(start_row, end_row + 1):
            artist = self._cell_text(row_index, "Artist")
            album = self._cell_text(row_index, "Album")
            if not artist or not album:
                continue
            self._queue_artwork(artist, album)

    def _queue_artwork(self, artist: str, album: str) -> None:
        if not artist or not album:
            return

        key = (artist.casefold(), album.casefold())
        if key not in self._resolver_keys:
            return
        if key in self._artwork_scheduled_keys:
            return
        self._artwork_scheduled_keys.add(key)

        worker = ArtworkWorker(artist=artist, album=album, resolver=self.artwork_resolver)
        worker.signals.resolved.connect(self._on_artwork_lookup_finished)
        self.thread_pool.start(worker)

    def _mark_artwork_completed(self, key: tuple[str, str]) -> None:
        if key in self._artwork_completed_keys:
            return
        self._artwork_completed_keys.add(key)
        self._artwork_completed = min(len(self._artwork_completed_keys), self._artwork_total)
        self._update_artwork_progress()

    def _on_threads_changed(self, value: int) -> None:
        self._set_artwork_threads(value)

    def _set_artwork_threads(self, threads: int) -> None:
        bounded_threads = max(MIN_ARTWORK_THREADS, min(MAX_ARTWORK_THREADS, int(threads)))
        self.thread_pool.setMaxThreadCount(bounded_threads)
        # Higher thread count lowers pacing delay to increase throughput.
        self.artwork_resolver.min_request_interval = max(0.04, 0.32 / bounded_threads)
        self.logger.info(
            "Artwork threads set to %s (request interval %.3fs)",
            bounded_threads,
            self.artwork_resolver.min_request_interval,
        )

    def _on_artwork_lookup_finished(self, artist: str, album: str, image_path: str) -> None:
        key = (artist.casefold(), album.casefold())
        if image_path:
            self._artwork_paths[key] = image_path
            self._artwork_with_image += 1
            self._apply_artwork_icon(artist, album, image_path)

            selected_row = self.table.currentRow()
            if selected_row >= 0:
                selected_artist = self._cell_text(selected_row, "Artist")
                selected_album = self._cell_text(selected_row, "Album")
                if selected_artist.casefold() == artist.casefold() and selected_album.casefold() == album.casefold():
                    self._update_preview(selected_artist, selected_album)

        self._mark_artwork_completed(key)

    def _update_artwork_progress(self) -> None:
        if self._artwork_total <= 0:
            self.artwork_progress.setRange(0, 1)
            self.artwork_progress.setValue(1)
            self.artwork_progress.setFormat(
                f"Artwork resolver: 0 remaining (all cached: {self._artwork_cached_hits}, found: {self._artwork_with_image})"
            )
            return

        remaining = max(self._artwork_total - self._artwork_completed, 0)
        self.artwork_progress.setRange(0, self._artwork_total)
        self.artwork_progress.setValue(self._artwork_completed)
        self.artwork_progress.setFormat(
            "Artwork resolver: "
            f"{remaining} left ({self._artwork_completed}/{self._artwork_total}, "
            f"cached: {self._artwork_cached_hits}, found: {self._artwork_with_image})"
        )

    def _apply_artwork_icon(self, artist: str, album: str, image_path: str) -> None:
        artist_column = self._column_index("Artist")
        album_column = self._column_index("Album")
        if artist_column is None or album_column is None:
            return

        for row_index in range(self.table.rowCount()):
            artist_item = self.table.item(row_index, artist_column)
            album_item = self.table.item(row_index, album_column)
            if artist_item is None or album_item is None:
                continue
            if artist_item.text().strip() != artist or album_item.text().strip() != album:
                continue
            artwork_item = self.table.item(row_index, ARTWORK_COLUMN)
            if artwork_item is not None:
                artwork_item.setIcon(QIcon(image_path))

    def _on_table_cell_clicked(self, row_index: int, _column_index: int) -> None:
        artist = self._cell_text(row_index, "Artist")
        album = self._cell_text(row_index, "Album")
        self._update_preview(artist, album)

    def _clear_preview(self) -> None:
        self.preview_image.setPixmap(QPixmap())
        self.preview_image.setText("Select an album to preview artwork")
        self.preview_meta.setText("No album selected")

    def _update_preview(self, artist: str, album: str) -> None:
        clean_artist = artist.strip()
        clean_album = album.strip()
        if not clean_artist and not clean_album:
            self._clear_preview()
            return

        self.preview_meta.setText(f"Artist: {clean_artist or 'Unknown'}\nAlbum: {clean_album or 'Unknown'}")
        image_path = self._artwork_paths.get((clean_artist.casefold(), clean_album.casefold()))
        if not image_path:
            self.preview_image.setPixmap(QPixmap())
            self.preview_image.setText("Artwork not loaded yet")
            return

        pixmap = QPixmap(image_path)
        if pixmap.isNull():
            self.preview_image.setPixmap(QPixmap())
            self.preview_image.setText("Artwork unavailable")
            return

        scaled = pixmap.scaled(PREVIEW_SIZE, PREVIEW_SIZE, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
        self.preview_image.setText("")
        self.preview_image.setPixmap(scaled)

    def _apply_filter(self, text: str) -> None:
        needle = text.strip().casefold()
        visible_count = 0
        for row_index in range(self.table.rowCount()):
            haystack = self._row_text(row_index)
            matches = needle in haystack if needle else True
            self.table.setRowHidden(row_index, not matches)
            if matches:
                visible_count += 1
        self.status_label.setText(f"Showing {visible_count} of {len(self.rows)} rows from {self.csv_path}")

    def _export_to_excel(self) -> None:
        try:
            import pandas as pd
        except ImportError:
            QMessageBox.information(
                self,
                "Export to Excel",
                "pandas is not installed, so Excel export is unavailable in this build.",
            )
            return

        target_path, _ = QFileDialog.getSaveFileName(
            self,
            "Export to Excel",
            str(self.csv_path.with_suffix(".xlsx")),
            "Excel Files (*.xlsx)",
        )
        if not target_path:
            return

        visible_rows = [
            row.values
            for row_index, row in enumerate(self.rows)
            if not self.table.isRowHidden(row_index)
        ]

        try:
            frame = pd.DataFrame(visible_rows, columns=self.columns)
            frame.to_excel(target_path, index=False)
        except Exception as exc:
            self.logger.exception("Excel export failed")
            QMessageBox.critical(self, "Export to Excel", str(exc))
            return

        QMessageBox.information(self, "Export to Excel", f"Excel export written to:\n{target_path}")

    def _open_last_generated_csv(self) -> None:
        csv_files = sorted(self.output_dir.glob("*.csv"), key=lambda path: path.stat().st_mtime, reverse=True)
        if not csv_files:
            QMessageBox.information(self, "Open Last CSV", f"No CSV files found in:\n{self.output_dir}")
            return
        self._load_csv(csv_files[0])

    def _open_row_targets(self, row_index: int, _column_index: int) -> None:
        if row_index < 0 or row_index >= self.table.rowCount():
            return

        artist = self._cell_text(row_index, "Artist")
        album = self._cell_text(row_index, "Album")
        if not artist and not album:
            return

        query = quote_plus(f"{artist} {album}".strip())
        spotify_url = f"https://open.spotify.com/search/{query}"
        jellyfin_url = self._build_jellyfin_url(query)

        menu = QMenu(self)
        spotify_action = menu.addAction("Open in Spotify")
        jellyfin_action = menu.addAction("Open in Jellyfin")
        jellyfin_action.setEnabled(bool(jellyfin_url))

        selected_action = menu.exec(self.cursor().pos())
        if selected_action == spotify_action:
            webbrowser.open(spotify_url)
        elif selected_action == jellyfin_action and jellyfin_url:
            webbrowser.open(jellyfin_url)

    def _build_jellyfin_url(self, query: str) -> str:
        if not self.jellyfin_base_url:
            return ""
        return f"{self.jellyfin_base_url}/web/index.html#!/search?term={query}"

    def _column_index(self, column_name: str) -> int | None:
        try:
            return self.columns.index(column_name) + 1
        except ValueError:
            return None

    def _cell_text(self, row_index: int, column_name: str) -> str:
        column_index = self._column_index(column_name)
        if column_index is None:
            return ""
        item = self.table.item(row_index, column_index)
        return item.text().strip() if item is not None else ""

    def _row_text(self, row_index: int) -> str:
        values: list[str] = []
        for column_name in self.columns:
            values.append(self._cell_text(row_index, column_name))
        return " ".join(values).casefold()


def run_csv_viewer(
    csv_path: Path,
    *,
    output_dir: Path,
    cache_dir: Path,
    jellyfin_base_url: str,
) -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    logger = setup_logging((cache_dir.parent / "Logs") if cache_dir.name == "cache" else (output_dir.parent / "Logs"))
    window = CSVViewerWindow(
        csv_path=csv_path,
        output_dir=output_dir,
        cache_dir=cache_dir,
        jellyfin_base_url=jellyfin_base_url,
        logger=logger,
    )
    window.show()
    return app.exec()
