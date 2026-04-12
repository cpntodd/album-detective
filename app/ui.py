from __future__ import annotations

import logging
import threading
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .compare import spotify_not_owned, unique_album_artist
from .config_store import AppConfig, ConfigStore
from .csv_io import read_spotify_csv, write_album_artist_csv, write_track_csv
from .models import AlbumArtistRecord
from .platform_support import open_in_file_explorer
from .runtime import RuntimePaths
from .scanner import scan_music_folder


class SettingsDialog(tk.Toplevel):
    def __init__(self, parent: tk.Tk, current_config: AppConfig, on_save: callable) -> None:
        super().__init__(parent)
        self.title("Preferences")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()
        self.on_save = on_save

        self.local_var = tk.StringVar(value=current_config.local_music_folder)
        self.spotify_var = tk.StringVar(value=current_config.spotify_csv_path)

        frame = ttk.Frame(self, padding=12)
        frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(frame, text="Local Music Folder:").grid(row=0, column=0, sticky="w")
        ttk.Entry(frame, textvariable=self.local_var, width=60).grid(row=0, column=1, padx=6)
        ttk.Button(frame, text="Browse", command=self._browse_local).grid(row=0, column=2)

        ttk.Label(frame, text="Spotify CSV:").grid(row=1, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(frame, textvariable=self.spotify_var, width=60).grid(row=1, column=1, padx=6, pady=(8, 0))
        ttk.Button(frame, text="Browse", command=self._browse_spotify).grid(row=1, column=2, pady=(8, 0))

        buttons = ttk.Frame(frame)
        buttons.grid(row=2, column=0, columnspan=3, sticky="e", pady=(14, 0))
        ttk.Button(buttons, text="Save", command=self._save).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(buttons, text="Cancel", command=self.destroy).pack(side=tk.LEFT)

        self.protocol("WM_DELETE_WINDOW", self.destroy)

    def _browse_local(self) -> None:
        selected = filedialog.askdirectory(initialdir=self.local_var.get() or "/", parent=self)
        if selected:
            self.local_var.set(selected)

    def _browse_spotify(self) -> None:
        selected = filedialog.askopenfilename(
            initialdir=str(Path(self.spotify_var.get()).parent),
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
            parent=self,
        )
        if selected:
            self.spotify_var.set(selected)

    def _save(self) -> None:
        cfg = AppConfig(
            local_music_folder=self.local_var.get().strip(),
            spotify_csv_path=self.spotify_var.get().strip(),
        )
        self.on_save(cfg)
        self.destroy()


class MusicCompareApp(tk.Tk):
    def __init__(self, paths: RuntimePaths, config_store: ConfigStore, logger: logging.Logger) -> None:
        super().__init__()
        self.paths = paths
        self.config_store = config_store
        self.logger = logger.getChild("ui")

        self.title("Music Library vs Spotify")
        self.geometry("1300x760")
        self.minsize(1000, 600)

        config = self.config_store.load()

        self.local_tracks = []
        self.spotify_tracks = []
        self.local_pairs: list[AlbumArtistRecord] = []
        self.spotify_pairs: list[AlbumArtistRecord] = []
        self.missing_pairs: list[AlbumArtistRecord] = []

        self.local_path_var = tk.StringVar(value=config.local_music_folder)
        self.spotify_csv_var = tk.StringVar(value=config.spotify_csv_path)
        self.output_dir_var = tk.StringVar(value=str(self.paths.output_dir))
        self.status_var = tk.StringVar(value="Ready")

        self._build_menu()
        self._build_layout()
        self.logger.info("UI initialized")

    def _build_menu(self) -> None:
        menu_bar = tk.Menu(self)

        file_menu = tk.Menu(menu_bar, tearoff=0)
        file_menu.add_command(label="Run Compare", command=self.run_compare)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.destroy)

        edit_menu = tk.Menu(menu_bar, tearoff=0)
        edit_menu.add_command(label="Clear Tables", command=self.clear_tables)

        settings_menu = tk.Menu(menu_bar, tearoff=0)
        settings_menu.add_command(label="Preferences", command=self.open_settings)
        settings_menu.add_separator()
        settings_menu.add_command(label="Select Local Folder", command=self.browse_local)
        settings_menu.add_command(label="Select Spotify CSV", command=self.browse_spotify)

        about_menu = tk.Menu(menu_bar, tearoff=0)
        about_menu.add_command(label="About", command=self.show_about)

        menu_bar.add_cascade(label="File", menu=file_menu)
        menu_bar.add_cascade(label="Edit", menu=edit_menu)
        menu_bar.add_cascade(label="Settings", menu=settings_menu)
        menu_bar.add_cascade(label="About", menu=about_menu)

        self.config(menu=menu_bar)

    def _build_layout(self) -> None:
        root_frame = ttk.Frame(self, padding=8)
        root_frame.pack(fill=tk.BOTH, expand=True)

        controls = ttk.Frame(root_frame)
        controls.pack(fill=tk.X, pady=(0, 8))

        ttk.Label(controls, text="Local Music Folder:").grid(row=0, column=0, sticky="w")
        ttk.Entry(controls, textvariable=self.local_path_var).grid(row=0, column=1, sticky="ew", padx=4)
        ttk.Button(controls, text="Browse", command=self.browse_local).grid(row=0, column=2)

        ttk.Label(controls, text="Spotify CSV:").grid(row=1, column=0, sticky="w")
        ttk.Entry(controls, textvariable=self.spotify_csv_var).grid(row=1, column=1, sticky="ew", padx=4)
        ttk.Button(controls, text="Browse", command=self.browse_spotify).grid(row=1, column=2)

        ttk.Label(controls, text="Output Folder:").grid(row=2, column=0, sticky="w")
        ttk.Entry(controls, textvariable=self.output_dir_var, state="readonly").grid(row=2, column=1, sticky="ew", padx=4)
        ttk.Label(controls, text="Fixed: ROOT/Output").grid(row=2, column=2, sticky="w")

        ttk.Button(controls, text="Scan + Compare", command=self.run_compare).grid(row=3, column=1, sticky="e", pady=(6, 0))
        controls.columnconfigure(1, weight=1)

        content = ttk.Panedwindow(root_frame, orient=tk.HORIZONTAL)
        content.pack(fill=tk.BOTH, expand=True)

        left_panel = ttk.Labelframe(content, text="File Explorer", padding=6)
        right_panel = ttk.Frame(content)

        content.add(left_panel, weight=2)
        content.add(right_panel, weight=3)

        self.file_tree = ttk.Treeview(left_panel, columns=("type",), show="tree")
        self.file_tree.pack(fill=tk.BOTH, expand=True)

        top_headers = ttk.Frame(right_panel)
        top_headers.pack(fill=tk.X)
        ttk.Label(top_headers, text="Local", anchor="center", font=("TkDefaultFont", 12, "bold")).pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Label(top_headers, text="Spotify", anchor="center", font=("TkDefaultFont", 12, "bold")).pack(side=tk.LEFT, fill=tk.X, expand=True)

        tables_frame = ttk.Panedwindow(right_panel, orient=tk.HORIZONTAL)
        tables_frame.pack(fill=tk.BOTH, expand=True)

        local_frame = ttk.Frame(tables_frame)
        spotify_frame = ttk.Frame(tables_frame)
        tables_frame.add(local_frame, weight=1)
        tables_frame.add(spotify_frame, weight=1)

        self.local_table = self._build_album_artist_table(local_frame)
        self.spotify_table = self._build_album_artist_table(spotify_frame)

        status = ttk.Label(root_frame, textvariable=self.status_var, anchor="w")
        status.pack(fill=tk.X, pady=(6, 0))

    def _build_album_artist_table(self, parent: ttk.Frame) -> ttk.Treeview:
        columns = ("artist", "album")
        table = ttk.Treeview(parent, columns=columns, show="headings", height=24)
        table.heading("artist", text="Artist")
        table.heading("album", text="Album")
        table.column("artist", width=260, anchor="w")
        table.column("album", width=280, anchor="w")

        yscroll = ttk.Scrollbar(parent, orient=tk.VERTICAL, command=table.yview)
        table.configure(yscrollcommand=yscroll.set)

        table.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        yscroll.pack(side=tk.RIGHT, fill=tk.Y)
        return table

    def _set_status(self, value: str) -> None:
        self.status_var.set(value)
        self.update_idletasks()

    def browse_local(self) -> None:
        selected = filedialog.askdirectory(initialdir=self.local_path_var.get() or "/")
        if selected:
            self.local_path_var.set(selected)

    def browse_spotify(self) -> None:
        selected = filedialog.askopenfilename(
            initialdir=str(Path(self.spotify_csv_var.get()).parent),
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
        )
        if selected:
            self.spotify_csv_var.set(selected)

    def open_settings(self) -> None:
        current = AppConfig(
            local_music_folder=self.local_path_var.get().strip(),
            spotify_csv_path=self.spotify_csv_var.get().strip(),
        )

        def _save_from_dialog(new_config: AppConfig) -> None:
            self.local_path_var.set(new_config.local_music_folder)
            self.spotify_csv_var.set(new_config.spotify_csv_path)
            self._persist_current_inputs()
            self.logger.info("Preferences updated")

        SettingsDialog(self, current, _save_from_dialog)

    def _persist_current_inputs(self) -> None:
        cfg = AppConfig(
            local_music_folder=self.local_path_var.get().strip(),
            spotify_csv_path=self.spotify_csv_var.get().strip(),
        )
        self.config_store.save(cfg)

    def clear_tables(self) -> None:
        for table in (self.local_table, self.spotify_table):
            for item in table.get_children():
                table.delete(item)

    def show_about(self) -> None:
        messagebox.showinfo(
            "About",
            "Music Library vs Spotify\n\n"
            "Scans your local library read-only, cleans Spotify CSV, and exports albums/artists listened to on Spotify but not found locally.",
        )

    def run_compare(self) -> None:
        self._persist_current_inputs()
        worker = threading.Thread(target=self._run_compare_worker, daemon=True)
        worker.start()

    def _run_compare_worker(self) -> None:
        try:
            self._set_status("Scanning local files (read-only)...")
            local_path = self.local_path_var.get().strip()
            spotify_csv = self.spotify_csv_var.get().strip()
            output_dir = self.paths.output_dir

            if not local_path:
                raise ValueError("Local music folder is required.")
            if not spotify_csv:
                raise ValueError("Spotify CSV path is required.")

            self.logger.info("Compare run started")
            self.logger.info("Local folder: %s", local_path)
            self.logger.info("Spotify CSV: %s", spotify_csv)
            self.logger.info("Output folder: %s", output_dir)

            self.local_tracks = scan_music_folder(local_path, on_progress=self._set_status)
            self.local_pairs = unique_album_artist(self.local_tracks)

            self._set_status("Reading Spotify CSV...")
            self.spotify_tracks = read_spotify_csv(spotify_csv)
            self.spotify_pairs = unique_album_artist(self.spotify_tracks)

            self._set_status("Comparing local library vs Spotify...")
            self.missing_pairs = spotify_not_owned(self.local_tracks, self.spotify_tracks)

            output_dir.mkdir(parents=True, exist_ok=True)
            local_csv = output_dir / "local_music_tracks.csv"
            spotify_clean_csv = output_dir / "spotify_clean_tracks.csv"
            missing_csv = output_dir / "spotify_not_owned_albums_artists.csv"

            write_track_csv(local_csv, self.local_tracks)
            write_track_csv(spotify_clean_csv, self.spotify_tracks)
            write_album_artist_csv(missing_csv, self.missing_pairs)
            self.logger.info("Wrote local CSV: %s", local_csv)
            self.logger.info("Wrote spotify-clean CSV: %s", spotify_clean_csv)
            self.logger.info("Wrote missing album/artist CSV: %s", missing_csv)

            self._refresh_file_tree(Path(local_path))
            self._refresh_tables()

            self._set_status(
                f"Done. Local tracks: {len(self.local_tracks)} | Spotify tracks: {len(self.spotify_tracks)} | Missing albums/artists: {len(self.missing_pairs)}"
            )
            self.logger.info(
                "Compare run completed: local=%s spotify=%s missing=%s",
                len(self.local_tracks),
                len(self.spotify_tracks),
                len(self.missing_pairs),
            )

            messagebox.showinfo(
                "Completed",
                "Export complete.\n\n"
                f"- {local_csv}\n"
                f"- {spotify_clean_csv}\n"
                f"- {missing_csv}",
            )

            should_open = messagebox.askyesno(
                "Open File Location",
                "Do you want to open file location?",
            )
            if should_open:
                try:
                    open_in_file_explorer(output_dir)
                    self.logger.info("Opened output folder in file explorer")
                except Exception as open_exc:
                    self.logger.exception("Failed to open output folder")
                    messagebox.showerror("Error", f"Could not open file location: {open_exc}")
        except Exception as exc:
            self._set_status("Failed")
            self.logger.exception("Compare run failed")
            messagebox.showerror("Error", str(exc))

    def _refresh_file_tree(self, root_path: Path) -> None:
        for item in self.file_tree.get_children():
            self.file_tree.delete(item)

        root_id = self.file_tree.insert("", "end", text=str(root_path), open=True)

        try:
            self._populate_tree(root_id, root_path, depth=0, max_depth=3)
        except Exception:
            pass

    def _populate_tree(self, parent_id: str, path: Path, depth: int, max_depth: int) -> None:
        if depth >= max_depth:
            return

        children = sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name.casefold()))
        for child in children[:300]:
            node = self.file_tree.insert(parent_id, "end", text=child.name, open=False)
            if child.is_dir():
                self._populate_tree(node, child, depth + 1, max_depth)

    def _refresh_tables(self) -> None:
        self.clear_tables()

        for rec in self.local_pairs:
            self.local_table.insert("", "end", values=(rec.artist, rec.album))

        for rec in self.missing_pairs:
            self.spotify_table.insert("", "end", values=(rec.artist, rec.album))


def run_app(paths: RuntimePaths, config_store: ConfigStore, logger: logging.Logger) -> None:
    app = MusicCompareApp(paths=paths, config_store=config_store, logger=logger)
    app.mainloop()
