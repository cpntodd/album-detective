from __future__ import annotations

import csv
import logging
import sys
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote_plus

from PySide6.QtCore import QObject, QRunnable, QSize, Qt, QThreadPool, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..runtime import setup_logging
from ..utils.artwork_resolver import ArtworkResolver


ARTWORK_COLUMN = 0
MIN_ROW_HEIGHT = 58


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
        self.thread_pool = QThreadPool.globalInstance()
        self.artwork_resolver = ArtworkResolver(cache_root=self.cache_dir, use_cache=True, logger=self.logger)

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

        self.table = QTableWidget(self)
        self.table.setSortingEnabled(True)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setIconSize(QSize(48, 48))
        self.table.verticalHeader().setDefaultSectionSize(MIN_ROW_HEIGHT)
        self.table.horizontalHeader().setSectionsClickable(True)
        self.table.horizontalHeader().setStretchLastSection(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.table.cellDoubleClicked.connect(self._open_row_targets)
        layout.addWidget(self.table, stretch=1)

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

        for row_index, row in enumerate(self.rows):
            artwork_item = QTableWidgetItem("")
            artwork_item.setFlags(artwork_item.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(row_index, ARTWORK_COLUMN, artwork_item)

            for offset, column in enumerate(self.columns, start=1):
                cell_item = QTableWidgetItem(row.values.get(column, ""))
                cell_item.setFlags(cell_item.flags() & ~Qt.ItemIsEditable)
                self.table.setItem(row_index, offset, cell_item)

            self._queue_artwork(row)

        self.table.setColumnWidth(ARTWORK_COLUMN, 68)
        for index in range(1, self.table.columnCount()):
            self.table.horizontalHeader().setSectionResizeMode(index, QHeaderView.ResizeToContents)

        self.table.setSortingEnabled(True)
        self._apply_filter(self.search_input.text())

    def _queue_artwork(self, row: CSVRow) -> None:
        if not row.artist or not row.album:
            return

        worker = ArtworkWorker(artist=row.artist, album=row.album, resolver=self.artwork_resolver)
        worker.signals.resolved.connect(self._apply_artwork_icon)
        self.thread_pool.start(worker)

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
