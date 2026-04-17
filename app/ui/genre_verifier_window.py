from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QObject, QRunnable, QThreadPool, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..genre_verifier import GenreSuggestion, GenreVerificationCancelled, verify_local_library_genres
from ..runtime import setup_logging


class GenreWorkerSignals(QObject):
    progress = Signal(int, int, str)
    diagnostic = Signal(str)
    completed = Signal(object)
    failed = Signal(str)
    cancelled = Signal()


class GenreWorker(QRunnable):
    def __init__(
        self,
        *,
        root_path: str,
        output_csv: Path,
        cache_file: Path,
        logger: logging.Logger,
        should_cancel: Callable[[], bool],
    ) -> None:
        super().__init__()
        self.root_path = root_path
        self.output_csv = output_csv
        self.cache_file = cache_file
        self.logger = logger
        self.should_cancel = should_cancel
        self.signals = GenreWorkerSignals()

    def run(self) -> None:
        try:
            suggestions = verify_local_library_genres(
                root_path=self.root_path,
                output_csv=self.output_csv,
                cache_file=self.cache_file,
                on_progress=lambda current, total, message: self.signals.progress.emit(current, total, message),
                should_cancel=self.should_cancel,
                on_diagnostic=lambda message: self.signals.diagnostic.emit(message),
                logger=self.logger,
            )
            self.signals.completed.emit(suggestions)
        except GenreVerificationCancelled:
            self.signals.cancelled.emit()
        except Exception as exc:
            self.signals.failed.emit(str(exc))


class GenreVerifierWindow(QMainWindow):
    def __init__(
        self,
        *,
        local_music_folder: str,
        output_dir: Path,
        cache_dir: Path,
        logger: logging.Logger,
    ) -> None:
        super().__init__()
        self.logger = logger.getChild("genre_tool")
        self.output_dir = output_dir
        self.cache_dir = cache_dir
        self._cancel_requested = False
        self._results: list[GenreSuggestion] = []
        self._diag_network_backoff_count = 0
        self.thread_pool = QThreadPool.globalInstance()

        self.setWindowTitle("Genre Verifier")
        self.resize(1180, 760)

        central = QWidget(self)
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        path_row = QHBoxLayout()
        path_row.addWidget(QLabel("Local Music Folder"))
        self.local_path_input = QLineEdit(self)
        self.local_path_input.setText(local_music_folder)
        path_row.addWidget(self.local_path_input, stretch=1)
        browse_btn = QPushButton("Browse", self)
        browse_btn.clicked.connect(self._browse_local_folder)
        path_row.addWidget(browse_btn)
        layout.addLayout(path_row)

        output_row = QHBoxLayout()
        output_row.addWidget(QLabel("Output CSV"))
        self.output_csv_input = QLineEdit(self)
        self.output_csv_input.setText(str(self.output_dir / "genre_tag_suggestions.csv"))
        output_row.addWidget(self.output_csv_input, stretch=1)
        output_btn = QPushButton("Select", self)
        output_btn.clicked.connect(self._browse_output_csv)
        output_row.addWidget(output_btn)
        layout.addLayout(output_row)

        action_row = QHBoxLayout()
        self.run_btn = QPushButton("Run Verification", self)
        self.run_btn.clicked.connect(self._run_verification)
        action_row.addWidget(self.run_btn)

        self.cancel_btn = QPushButton("Cancel", self)
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self._cancel_verification)
        action_row.addWidget(self.cancel_btn)

        self.open_output_btn = QPushButton("Open Output CSV", self)
        self.open_output_btn.clicked.connect(self._open_output_csv)
        action_row.addWidget(self.open_output_btn)
        action_row.addStretch(1)
        layout.addLayout(action_row)

        self.progress = QProgressBar(self)
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        layout.addWidget(self.progress)

        self.status_label = QLabel("Ready", self)
        layout.addWidget(self.status_label)

        self.table = QTableWidget(self)
        self.table.setColumnCount(8)
        self.table.setHorizontalHeaderLabels(
            [
                "Artist",
                "Album",
                "Local Genre",
                "Suggested Genre",
                "MusicBrainz Tags",
                "Match Score",
                "Confidence",
                "Action",
            ]
        )
        self.table.setSortingEnabled(True)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.table, stretch=1)

    def _browse_local_folder(self) -> None:
        selected = QFileDialog.getExistingDirectory(self, "Select Local Music Folder", self.local_path_input.text() or "/")
        if selected:
            self.local_path_input.setText(selected)

    def _browse_output_csv(self) -> None:
        selected, _ = QFileDialog.getSaveFileName(
            self,
            "Select Output CSV",
            self.output_csv_input.text() or str(self.output_dir / "genre_tag_suggestions.csv"),
            "CSV Files (*.csv)",
        )
        if selected:
            self.output_csv_input.setText(selected)

    def _run_verification(self) -> None:
        local_path = self.local_path_input.text().strip()
        if not local_path:
            QMessageBox.warning(self, "Genre Verifier", "Local music folder is required.")
            return
        if not Path(local_path).exists():
            QMessageBox.warning(self, "Genre Verifier", f"Folder not found:\n{local_path}")
            return

        output_csv = Path(self.output_csv_input.text().strip() or (self.output_dir / "genre_tag_suggestions.csv"))
        output_csv.parent.mkdir(parents=True, exist_ok=True)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        self._cancel_requested = False
        self._diag_network_backoff_count = 0
        self._set_running(True)
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.status_label.setText("Preparing genre verification...")

        worker = GenreWorker(
            root_path=local_path,
            output_csv=output_csv,
            cache_file=self.cache_dir / "musicbrainz_genre_cache.json",
            logger=self.logger,
            should_cancel=lambda: self._cancel_requested,
        )
        worker.signals.progress.connect(self._on_progress)
        worker.signals.diagnostic.connect(self._on_diagnostic)
        worker.signals.completed.connect(self._on_completed)
        worker.signals.failed.connect(self._on_failed)
        worker.signals.cancelled.connect(self._on_cancelled)
        self.thread_pool.start(worker)

    def _cancel_verification(self) -> None:
        self._cancel_requested = True
        self.status_label.setText("Cancelling genre verification...")

    def _set_running(self, running: bool) -> None:
        self.run_btn.setEnabled(not running)
        self.cancel_btn.setEnabled(running)
        self.local_path_input.setEnabled(not running)
        self.output_csv_input.setEnabled(not running)

    def _on_progress(self, current: int, total: int, message: str) -> None:
        total_safe = max(total, 1)
        pct = int((current / total_safe) * 100)
        self.progress.setRange(0, 100)
        self.progress.setValue(pct)
        self.status_label.setText(self._with_diagnostics(f"{message} ({current}/{total})"))

    def _on_diagnostic(self, message: str) -> None:
        if "network-backoff" not in message:
            return
        self._diag_network_backoff_count += 1
        self.status_label.setText(self._with_diagnostics(self.status_label.text().split(" | diag", 1)[0]))

    def _with_diagnostics(self, value: str) -> str:
        if self._diag_network_backoff_count <= 0:
            return value
        return f"{value} | diag backoff:{self._diag_network_backoff_count}"

    def _on_completed(self, suggestions: object) -> None:
        self._set_running(False)
        self.progress.setValue(100)
        self._results = list(suggestions) if isinstance(suggestions, list) else []
        self._populate_results_table(self._results)

        add_count = sum(1 for item in self._results if item.action == "add-genre")
        update_count = sum(1 for item in self._results if item.action == "update-genre")
        review_count = sum(1 for item in self._results if item.action == "review")

        self.status_label.setText(
            self._with_diagnostics(
                "Genre verification complete. "
                f"Albums: {len(self._results)} | Add: {add_count} | Update: {update_count} | Review: {review_count}"
            )
        )

        QMessageBox.information(
            self,
            "Genre Verifier",
            "Genre verification complete.\n\n"
            f"Albums: {len(self._results)}\n"
            f"Add genre: {add_count}\n"
            f"Update genre: {update_count}\n"
            f"Manual review: {review_count}",
        )

    def _on_failed(self, error_message: str) -> None:
        self._set_running(False)
        self.status_label.setText(self._with_diagnostics("Genre verification failed"))
        QMessageBox.critical(self, "Genre Verifier", error_message)

    def _on_cancelled(self) -> None:
        self._set_running(False)
        self.progress.setValue(0)
        self.status_label.setText(self._with_diagnostics("Genre verification cancelled"))

    def _populate_results_table(self, suggestions: list[GenreSuggestion]) -> None:
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(suggestions))

        for row_index, row in enumerate(suggestions):
            self.table.setItem(row_index, 0, QTableWidgetItem(row.artist))
            self.table.setItem(row_index, 1, QTableWidgetItem(row.album))
            self.table.setItem(row_index, 2, QTableWidgetItem(row.local_genre))
            self.table.setItem(row_index, 3, QTableWidgetItem(row.suggested_genre))
            self.table.setItem(row_index, 4, QTableWidgetItem(row.musicbrainz_tags))
            self.table.setItem(row_index, 5, QTableWidgetItem(str(row.match_score)))
            self.table.setItem(row_index, 6, QTableWidgetItem(row.confidence))
            self.table.setItem(row_index, 7, QTableWidgetItem(row.action))

        self.table.resizeColumnsToContents()
        self.table.setSortingEnabled(True)

    def _open_output_csv(self) -> None:
        output_csv = Path(self.output_csv_input.text().strip() or "")
        if not output_csv.exists():
            QMessageBox.information(self, "Genre Verifier", "Output CSV does not exist yet.")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(output_csv.resolve())))


def run_genre_verifier_tool(
    *,
    local_music_folder: str,
    output_dir: Path,
    cache_dir: Path,
) -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    logger = setup_logging((cache_dir.parent / "Logs") if cache_dir.name == "cache" else (output_dir.parent / "Logs"))
    window = GenreVerifierWindow(
        local_music_folder=local_music_folder,
        output_dir=output_dir,
        cache_dir=cache_dir,
        logger=logger,
    )
    window.show()
    return app.exec()
