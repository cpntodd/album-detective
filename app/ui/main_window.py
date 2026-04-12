from __future__ import annotations

import logging
import os
import subprocess
import sys
import threading
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from ..compare import spotify_not_owned, unique_album_artist
from ..config_store import AppConfig, ConfigStore
from ..csv_io import read_spotify_csv, write_album_artist_csv, write_track_csv
from ..models import AlbumArtistRecord, TrackRecord
from ..nas_scanner import scan_nas_cached
from ..platform_support import open_in_file_explorer
from ..runtime import RuntimePaths
from ..scanner import ScanCancelled, load_cached_records_for_root, scan_music_folder
from ..jellyfin_client import JellyfinClient
from ..spotify_client import SpotifyClient
from ..theme_manager import apply_theme, key_to_label, label_to_key, theme_labels


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
        self.force_reindex_var = tk.BooleanVar(value=current_config.force_reindex)
        self.scan_profile_var = tk.StringVar(value=current_config.scan_profile)
        self.max_workers_var = tk.StringVar(value=str(current_config.max_scan_workers))
        self.spotify_client_id_var = tk.StringVar(value=current_config.spotify_client_id)
        self.spotify_client_secret_var = tk.StringVar(value=current_config.spotify_client_secret)
        self.spotify_redirect_uri_var = tk.StringVar(value=current_config.spotify_redirect_uri)
        self.jellyfin_server_url_var = tk.StringVar(value=current_config.jellyfin_server_url)
        self.jellyfin_api_key_var = tk.StringVar(value=current_config.jellyfin_api_key)
        self.jellyfin_user_id_var = tk.StringVar(value=current_config.jellyfin_user_id)
        self.theme_var = tk.StringVar(value=key_to_label(current_config.theme_name))

        frame = ttk.Frame(self, padding=12)
        frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(frame, text="Local Music Folder:").grid(row=0, column=0, sticky="w")
        ttk.Entry(frame, textvariable=self.local_var, width=60).grid(row=0, column=1, padx=6)
        ttk.Button(frame, text="Browse", command=self._browse_local).grid(row=0, column=2)

        ttk.Label(frame, text="Spotify CSV:").grid(row=1, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(frame, textvariable=self.spotify_var, width=60).grid(row=1, column=1, padx=6, pady=(8, 0))
        ttk.Button(frame, text="Browse", command=self._browse_spotify).grid(row=1, column=2, pady=(8, 0))

        ttk.Checkbutton(
            frame,
            text="Force full re-index (ignore local cache)",
            variable=self.force_reindex_var,
        ).grid(row=2, column=0, columnspan=3, sticky="w", pady=(10, 0))

        ttk.Label(frame, text="Scan Profile:").grid(row=3, column=0, sticky="w", pady=(8, 0))
        profile_combo = ttk.Combobox(
            frame,
            textvariable=self.scan_profile_var,
            values=("auto", "local", "network"),
            state="readonly",
            width=12,
        )
        profile_combo.grid(row=3, column=1, sticky="w", padx=6, pady=(8, 0))

        ttk.Label(frame, text="Max Worker Threads (0 = auto):").grid(row=4, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(frame, textvariable=self.max_workers_var, width=8).grid(row=4, column=1, sticky="w", padx=6, pady=(8, 0))

        ttk.Label(frame, text="Spotify Client ID:").grid(row=5, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(frame, textvariable=self.spotify_client_id_var, width=60).grid(row=5, column=1, padx=6, pady=(8, 0))

        ttk.Label(frame, text="Spotify Client Secret:").grid(row=6, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(frame, textvariable=self.spotify_client_secret_var, width=60, show="*").grid(row=6, column=1, padx=6, pady=(8, 0))

        ttk.Label(frame, text="Spotify Redirect URI:").grid(row=7, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(frame, textvariable=self.spotify_redirect_uri_var, width=60).grid(row=7, column=1, padx=6, pady=(8, 0))

        ttk.Label(frame, text="Jellyfin Server URL:").grid(row=8, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(frame, textvariable=self.jellyfin_server_url_var, width=60).grid(row=8, column=1, padx=6, pady=(8, 0))

        ttk.Label(frame, text="Jellyfin API Key:").grid(row=9, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(frame, textvariable=self.jellyfin_api_key_var, width=60, show="*").grid(row=9, column=1, padx=6, pady=(8, 0))

        ttk.Label(frame, text="Jellyfin User ID (optional):").grid(row=10, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(frame, textvariable=self.jellyfin_user_id_var, width=60).grid(row=10, column=1, padx=6, pady=(8, 0))

        ttk.Label(frame, text="Theme:").grid(row=11, column=0, sticky="w", pady=(8, 0))
        ttk.Combobox(
            frame,
            textvariable=self.theme_var,
            values=theme_labels(),
            state="readonly",
            width=56,
        ).grid(row=11, column=1, padx=6, pady=(8, 0), sticky="w")

        buttons = ttk.Frame(frame)
        buttons.grid(row=12, column=0, columnspan=3, sticky="e", pady=(14, 0))
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
        try:
            max_workers = max(0, int(self.max_workers_var.get().strip() or "0"))
        except ValueError:
            messagebox.showerror("Invalid value", "Max Worker Threads must be a whole number.", parent=self)
            return

        cfg = AppConfig(
            local_music_folder=self.local_var.get().strip(),
            spotify_csv_path=self.spotify_var.get().strip(),
            force_reindex=self.force_reindex_var.get(),
            scan_profile=self.scan_profile_var.get().strip().lower() or "auto",
            max_scan_workers=max_workers,
            spotify_client_id=self.spotify_client_id_var.get().strip(),
            spotify_client_secret=self.spotify_client_secret_var.get().strip(),
            spotify_redirect_uri=self.spotify_redirect_uri_var.get().strip() or "http://127.0.0.1:8888/callback",
            jellyfin_server_url=self.jellyfin_server_url_var.get().strip(),
            jellyfin_api_key=self.jellyfin_api_key_var.get().strip(),
            jellyfin_user_id=self.jellyfin_user_id_var.get().strip(),
            theme_name=label_to_key(self.theme_var.get().strip()),
        )
        self.on_save(cfg)
        self.destroy()


class JellyfinImportDialog(tk.Toplevel):
    def __init__(
        self,
        parent: tk.Tk,
        server_url: str,
        api_key: str,
        user_id: str,
        on_fetch_users: callable,
        on_submit: callable,
    ) -> None:
        super().__init__(parent)
        self.title("Import From Jellyfin")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        self.on_fetch_users = on_fetch_users
        self.on_submit = on_submit

        self.server_var = tk.StringVar(value=server_url)
        self.api_key_var = tk.StringVar(value=api_key)
        self.user_var = tk.StringVar(value=user_id)

        frame = ttk.Frame(self, padding=12)
        frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(frame, text="Server URL:").grid(row=0, column=0, sticky="w")
        ttk.Entry(frame, textvariable=self.server_var, width=58).grid(row=0, column=1, padx=6)

        ttk.Label(frame, text="API Key:").grid(row=1, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(frame, textvariable=self.api_key_var, width=58, show="*").grid(row=1, column=1, padx=6, pady=(8, 0))

        ttk.Label(frame, text="User:").grid(row=2, column=0, sticky="w", pady=(8, 0))
        self.user_combo = ttk.Combobox(frame, textvariable=self.user_var, values=(), width=56)
        self.user_combo.grid(row=2, column=1, padx=6, pady=(8, 0), sticky="w")

        btn_row = ttk.Frame(frame)
        btn_row.grid(row=3, column=0, columnspan=2, sticky="e", pady=(12, 0))
        ttk.Button(btn_row, text="Fetch Users", command=self._fetch_users).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(btn_row, text="Import", command=self._submit).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(btn_row, text="Cancel", command=self.destroy).pack(side=tk.LEFT)

    def _fetch_users(self) -> None:
        try:
            users = self.on_fetch_users(self.server_var.get().strip(), self.api_key_var.get().strip())
        except Exception as exc:
            messagebox.showerror("Jellyfin", str(exc), parent=self)
            return

        labels = [f"{u.get('Name', '')} ({u.get('Id', '')})" for u in users if u.get("Id")]
        self.user_combo.configure(values=labels)

        if labels and not self.user_var.get().strip():
            self.user_var.set(labels[0])

    def _submit(self) -> None:
        server = self.server_var.get().strip()
        key = self.api_key_var.get().strip()
        raw_user = self.user_var.get().strip()

        if not server or not key:
            messagebox.showerror("Jellyfin", "Server URL and API key are required.", parent=self)
            return

        # Accept either plain user ID or combo label "Name (id)".
        user_id = raw_user
        if raw_user.endswith(")") and "(" in raw_user:
            user_id = raw_user.rsplit("(", 1)[1].rstrip(")").strip()

        self.on_submit(server, key, user_id)
        self.destroy()


class CompareSourceDialog(tk.Toplevel):
    def __init__(self, parent: tk.Tk, on_submit: callable) -> None:
        super().__init__(parent)
        self.title("Compare Source")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()
        self.on_submit = on_submit

        self.source_var = tk.StringVar(value="")

        frame = ttk.Frame(self, padding=12)
        frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(frame, text="Which source to compare from?").grid(row=0, column=0, sticky="w")

        self.source_combo = ttk.Combobox(
            frame,
            textvariable=self.source_var,
            values=("Local", "Jellyfin"),
            state="readonly",
            width=24,
        )
        self.source_combo.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        self.source_combo.bind("<<ComboboxSelected>>", self._on_selected)

        button_row = ttk.Frame(frame)
        button_row.grid(row=2, column=0, sticky="e", pady=(14, 0))
        self.compare_btn = ttk.Button(button_row, text="Compare", command=self._submit, state=tk.DISABLED)
        self.compare_btn.pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(button_row, text="Cancel", command=self.destroy).pack(side=tk.LEFT)

    def _on_selected(self, _event: tk.Event) -> None:
        enabled = tk.NORMAL if self.source_var.get().strip() else tk.DISABLED
        self.compare_btn.configure(state=enabled)

    def _submit(self) -> None:
        source = self.source_var.get().strip()
        if not source:
            return
        self.on_submit(source)
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
        self.force_reindex_var = tk.BooleanVar(value=config.force_reindex)
        self.scan_profile_var = tk.StringVar(value=config.scan_profile)
        self.max_scan_workers_var = tk.StringVar(value=str(config.max_scan_workers))
        self.spotify_client_id_var = tk.StringVar(value=config.spotify_client_id)
        self.spotify_client_secret_var = tk.StringVar(value=config.spotify_client_secret)
        self.spotify_redirect_uri_var = tk.StringVar(value=config.spotify_redirect_uri)
        self.jellyfin_server_url_var = tk.StringVar(value=config.jellyfin_server_url)
        self.jellyfin_api_key_var = tk.StringVar(value=config.jellyfin_api_key)
        self.jellyfin_user_id_var = tk.StringVar(value=config.jellyfin_user_id)
        self.theme_name_var = tk.StringVar(value=config.theme_name)
        self.output_dir_var = tk.StringVar(value=str(self.paths.output_dir))
        self.status_var = tk.StringVar(value="Ready")
        self.progress_var = tk.DoubleVar(value=0.0)
        self._cancel_event = threading.Event()
        self._worker_thread: threading.Thread | None = None
        self._tree_node_paths: dict[str, Path] = {}
        self._menus: list[tk.Menu] = []
        self._style = ttk.Style(self)

        self._build_menu()
        self._build_layout()
        self._apply_selected_theme()
        self.logger.info("UI initialized")

    def _build_menu(self) -> None:
        menu_bar = tk.Menu(self)

        file_menu = tk.Menu(menu_bar, tearoff=0)
        file_menu.add_command(label="Run Compare", command=self.run_compare)
        file_menu.add_command(label="View CSV in New Window", command=self.open_csv_viewer)
        import_menu = tk.Menu(file_menu, tearoff=0)
        import_menu.add_command(label="From Spotify", command=self.import_from_spotify)
        import_menu.add_command(label="From Jellyfin", command=self.import_from_jellyfin)
        import_menu.add_command(label="From NAS (cached)", command=self.import_from_nas_cached)
        file_menu.add_cascade(label="Import", menu=import_menu)
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
        self._menus = [menu_bar, file_menu, import_menu, edit_menu, settings_menu, about_menu]

    def _apply_selected_theme(self) -> None:
        applied_key = apply_theme(
            root=self,
            style=self._style,
            theme_key=self.theme_name_var.get().strip(),
            menus=self._menus,
        )
        self.theme_name_var.set(applied_key)

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

        button_row = ttk.Frame(controls)
        button_row.grid(row=3, column=1, sticky="e", pady=(6, 0))

        self.scan_btn = ttk.Button(button_row, text="Scan + Compare", command=self.run_compare)
        self.scan_btn.pack(side=tk.LEFT)

        self.cancel_btn = ttk.Button(button_row, text="Cancel Job", command=self.cancel_compare, state=tk.DISABLED)
        self.cancel_btn.pack(side=tk.LEFT, padx=(8, 0))

        controls.columnconfigure(1, weight=1)

        content = ttk.Panedwindow(root_frame, orient=tk.HORIZONTAL)
        content.pack(fill=tk.BOTH, expand=True)

        left_panel = ttk.Labelframe(content, text="File Explorer", padding=6)
        right_panel = ttk.Frame(content)

        content.add(left_panel, weight=2)
        content.add(right_panel, weight=3)

        self.file_tree = ttk.Treeview(left_panel, show="tree")
        tree_scroll = ttk.Scrollbar(left_panel, orient=tk.VERTICAL, command=self.file_tree.yview)
        self.file_tree.configure(yscrollcommand=tree_scroll.set)
        self.file_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        tree_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self._init_file_tree()

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

        self.progress_bar = ttk.Progressbar(root_frame, variable=self.progress_var, mode="determinate", maximum=100)
        self.progress_bar.pack(fill=tk.X, pady=(6, 0))

        status = ttk.Label(root_frame, textvariable=self.status_var, anchor="w")
        status.pack(fill=tk.X, pady=(4, 0))

    def _filesystem_roots(self) -> list[Path]:
        if os.name == "nt":
            roots: list[Path] = []
            for code in range(ord("A"), ord("Z") + 1):
                drive = f"{chr(code)}:\\"
                drive_path = Path(drive)
                if drive_path.exists():
                    roots.append(drive_path)
            return roots

        roots = [Path("/"), Path.home(), Path("/media"), Path("/mnt")]
        unique: list[Path] = []
        seen: set[str] = set()
        for root in roots:
            key = str(root)
            if key in seen:
                continue
            seen.add(key)
            if root.exists():
                unique.append(root)
        return unique

    def _dir_has_subdirs(self, path: Path) -> bool:
        try:
            with os.scandir(path) as entries:
                for entry in entries:
                    if entry.is_dir(follow_symlinks=False):
                        return True
        except OSError:
            return False
        return False

    def _insert_dir_node(self, parent_id: str, path: Path, display_name: str | None = None) -> str:
        text = display_name if display_name is not None else (path.name or str(path))
        node_id = self.file_tree.insert(parent_id, "end", text=text, open=False)
        self._tree_node_paths[node_id] = path
        if self._dir_has_subdirs(path):
            self.file_tree.insert(node_id, "end", text="...")
        return node_id

    def _populate_node_children(self, node_id: str) -> None:
        path = self._tree_node_paths.get(node_id)
        if path is None:
            return

        children = self.file_tree.get_children(node_id)
        if children and children[0] in self._tree_node_paths:
            return

        for child in children:
            self.file_tree.delete(child)

        try:
            dirs = [
                Path(entry.path)
                for entry in os.scandir(path)
                if entry.is_dir(follow_symlinks=False)
            ]
        except OSError:
            return

        dirs.sort(key=lambda p: p.name.casefold())
        for child_dir in dirs:
            self._insert_dir_node(node_id, child_dir)

    def _on_tree_open(self, _event: tk.Event) -> None:
        node_id = self.file_tree.focus()
        if node_id:
            self._populate_node_children(node_id)

    def _on_tree_double_click(self, event: tk.Event) -> None:
        node_id = self.file_tree.identify_row(event.y)
        if not node_id:
            selected = self.file_tree.selection()
            if not selected:
                return
            node_id = selected[0]

        self.file_tree.selection_set(node_id)
        self.file_tree.focus(node_id)

        path = self._tree_node_paths.get(node_id)
        if path and path.is_dir():
            self.local_path_var.set(str(path))
            self._set_status(f"Selected local folder: {path}")
            self._load_preview_from_cache(path)

    def _load_preview_from_cache(self, selected_path: Path) -> None:
        if self._worker_thread and self._worker_thread.is_alive():
            return

        cache_file = self.paths.config_dir / "local_index_cache.json"
        cached_tracks = load_cached_records_for_root(str(selected_path), cache_file)
        if not cached_tracks:
            return

        self.local_tracks = cached_tracks
        self.local_pairs = unique_album_artist(self.local_tracks)

        spotify_path = Path(self.spotify_csv_var.get().strip())
        if spotify_path.exists():
            self.spotify_tracks = read_spotify_csv(spotify_path)
            self.spotify_pairs = unique_album_artist(self.spotify_tracks)
            self.missing_pairs = spotify_not_owned(self.local_tracks, self.spotify_tracks)
        else:
            self.spotify_tracks = []
            self.spotify_pairs = []
            self.missing_pairs = []

        self._refresh_tables()
        self._set_status(
            f"Cached preview loaded. Local albums/artists: {len(self.local_pairs)} | Missing on local: {len(self.missing_pairs)}"
        )
        self.logger.info("Loaded cached preview for selected folder: %s", selected_path)

    def _init_file_tree(self) -> None:
        for item in self.file_tree.get_children():
            self.file_tree.delete(item)
        self._tree_node_paths.clear()

        for root in self._filesystem_roots():
            display_name = str(root) if os.name == "nt" else (root.name or str(root))
            self._insert_dir_node("", root, display_name=display_name)

        self.file_tree.bind("<<TreeviewOpen>>", self._on_tree_open)
        self.file_tree.bind("<Double-1>", self._on_tree_double_click)

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

    def open_csv_viewer(self) -> None:
        default_csv = self._default_csv_for_viewer()
        selected = filedialog.askopenfilename(
            title="View CSV in New Window",
            initialdir=str(default_csv.parent),
            initialfile=default_csv.name,
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
            parent=self,
        )
        if not selected:
            return

        try:
            command = self._csv_viewer_command(Path(selected))
            subprocess.Popen(command)
            self.logger.info("Opened CSV viewer for %s", selected)
        except Exception as exc:
            self.logger.exception("Failed to open CSV viewer")
            messagebox.showerror("CSV Viewer", f"Could not open CSV viewer: {exc}", parent=self)

    def _default_csv_for_viewer(self) -> Path:
        preferred_files = [
            self.paths.output_dir / "spotify_not_owned_albums_artists.csv",
            self.paths.output_dir / "spotify_clean_tracks.csv",
            Path(self.spotify_csv_var.get().strip() or self.paths.output_dir / "spotify_clean_tracks.csv"),
        ]

        for candidate in preferred_files:
            if candidate.exists():
                return candidate

        return self.paths.output_dir / "spotify_not_owned_albums_artists.csv"

    def _csv_viewer_command(self, csv_path: Path) -> list[str]:
        cache_dir = self.paths.root_dir / "cache"
        cache_dir.mkdir(parents=True, exist_ok=True)

        args = [
            "--view-csv",
            str(csv_path),
            "--output-dir",
            str(self.paths.output_dir),
            "--cache-dir",
            str(cache_dir),
            "--jellyfin-base-url",
            self.jellyfin_server_url_var.get().strip(),
        ]

        if getattr(sys, "frozen", False):
            return [sys.executable, *args]

        project_root = Path(__file__).resolve().parents[2]
        return [sys.executable, str(project_root / "main.py"), *args]

    def open_settings(self) -> None:
        current = AppConfig(
            local_music_folder=self.local_path_var.get().strip(),
            spotify_csv_path=self.spotify_csv_var.get().strip(),
            force_reindex=self.force_reindex_var.get(),
            scan_profile=self.scan_profile_var.get().strip().lower() or "auto",
            max_scan_workers=max(0, int(self.max_scan_workers_var.get().strip() or "0")),
            spotify_client_id=self.spotify_client_id_var.get().strip(),
            spotify_client_secret=self.spotify_client_secret_var.get().strip(),
            spotify_redirect_uri=self.spotify_redirect_uri_var.get().strip() or "http://127.0.0.1:8888/callback",
            jellyfin_server_url=self.jellyfin_server_url_var.get().strip(),
            jellyfin_api_key=self.jellyfin_api_key_var.get().strip(),
            jellyfin_user_id=self.jellyfin_user_id_var.get().strip(),
            theme_name=self.theme_name_var.get().strip() or "palette_1",
        )

        def _save_from_dialog(new_config: AppConfig) -> None:
            self.local_path_var.set(new_config.local_music_folder)
            self.spotify_csv_var.set(new_config.spotify_csv_path)
            self.force_reindex_var.set(new_config.force_reindex)
            self.scan_profile_var.set(new_config.scan_profile)
            self.max_scan_workers_var.set(str(new_config.max_scan_workers))
            self.spotify_client_id_var.set(new_config.spotify_client_id)
            self.spotify_client_secret_var.set(new_config.spotify_client_secret)
            self.spotify_redirect_uri_var.set(new_config.spotify_redirect_uri)
            self.jellyfin_server_url_var.set(new_config.jellyfin_server_url)
            self.jellyfin_api_key_var.set(new_config.jellyfin_api_key)
            self.jellyfin_user_id_var.set(new_config.jellyfin_user_id)
            self.theme_name_var.set(new_config.theme_name)
            self._persist_current_inputs()
            self._apply_selected_theme()
            self.logger.info("Preferences updated")

        SettingsDialog(self, current, _save_from_dialog)

    def _persist_current_inputs(self) -> None:
        cfg = AppConfig(
            local_music_folder=self.local_path_var.get().strip(),
            spotify_csv_path=self.spotify_csv_var.get().strip(),
            force_reindex=self.force_reindex_var.get(),
            scan_profile=self.scan_profile_var.get().strip().lower() or "auto",
            max_scan_workers=max(0, int(self.max_scan_workers_var.get().strip() or "0")),
            spotify_client_id=self.spotify_client_id_var.get().strip(),
            spotify_client_secret=self.spotify_client_secret_var.get().strip(),
            spotify_redirect_uri=self.spotify_redirect_uri_var.get().strip() or "http://127.0.0.1:8888/callback",
            jellyfin_server_url=self.jellyfin_server_url_var.get().strip(),
            jellyfin_api_key=self.jellyfin_api_key_var.get().strip(),
            jellyfin_user_id=self.jellyfin_user_id_var.get().strip(),
            theme_name=self.theme_name_var.get().strip() or "palette_1",
        )
        self.config_store.save(cfg)

    def import_from_spotify(self) -> None:
        if self._worker_thread and self._worker_thread.is_alive():
            messagebox.showinfo("Busy", "Another job is already running.")
            return

        if not self.spotify_client_id_var.get().strip() or not self.spotify_client_secret_var.get().strip():
            messagebox.showerror(
                "Spotify Credentials Required",
                "Open Settings > Preferences and set Spotify Client ID and Spotify Client Secret.",
            )
            return

        self._persist_current_inputs()
        self._set_running_state(True)
        self.progress_bar.configure(mode="indeterminate")
        self.progress_bar.start(12)
        self._set_status("Connecting to Spotify...")

        self._worker_thread = threading.Thread(target=self._import_spotify_worker, daemon=True)
        self._worker_thread.start()

    def _import_spotify_worker(self) -> None:
        try:
            token_cache = self.paths.config_dir / "spotify_token_cache"
            client = SpotifyClient(
                client_id=self.spotify_client_id_var.get().strip(),
                client_secret=self.spotify_client_secret_var.get().strip(),
                redirect_uri=self.spotify_redirect_uri_var.get().strip() or "http://127.0.0.1:8888/callback",
                token_cache_path=token_cache,
            )

            def _progress(msg: str) -> None:
                self.after(0, self._set_status, msg)

            tracks = client.get_normalized_library(on_progress=_progress)

            output_csv = self.paths.output_dir / "spotify_clean_tracks.csv"
            write_track_csv(output_csv, tracks)

            self.spotify_csv_var.set(str(output_csv))
            self._persist_current_inputs()

            selected_local = Path(self.local_path_var.get().strip())
            if selected_local.exists() and selected_local.is_dir():
                self._load_preview_from_cache(selected_local)

            self.after(0, self._set_status, f"Spotify import complete. Rows exported: {len(tracks)}")
            messagebox.showinfo("Spotify Import", f"Imported and exported to:\n{output_csv}")
        except Exception as exc:
            self.logger.exception("Spotify import failed")
            messagebox.showerror("Spotify Import Failed", str(exc))
        finally:
            self.after(0, self.progress_bar.stop)
            self.after(0, lambda: self.progress_bar.configure(mode="determinate"))
            self.after(0, self._set_running_state, False)

    def _rows_to_track_records(self, rows: list[dict]) -> list[TrackRecord]:
        records: list[TrackRecord] = []
        for row in rows:
            records.append(
                TrackRecord(
                    track_name=str(row.get("Track name") or "").strip(),
                    artist=str(row.get("Artist") or "").strip(),
                    album=str(row.get("Album") or "").strip(),
                )
            )
        return records

    def import_from_jellyfin(self) -> None:
        if self._worker_thread and self._worker_thread.is_alive():
            messagebox.showinfo("Busy", "Another job is already running.")
            return

        def _fetch_users(server_url: str, api_key: str) -> list[dict]:
            client = JellyfinClient(server_url=server_url, api_key=api_key)
            return client.get_users()

        def _submit(server_url: str, api_key: str, user_id: str) -> None:
            self.jellyfin_server_url_var.set(server_url)
            self.jellyfin_api_key_var.set(api_key)
            self.jellyfin_user_id_var.set(user_id)
            self._persist_current_inputs()

            self._set_running_state(True)
            self.progress_bar.configure(mode="indeterminate")
            self.progress_bar.start(12)
            self._set_status("Importing from Jellyfin...")

            self._worker_thread = threading.Thread(
                target=self._import_jellyfin_worker,
                args=(server_url, api_key, user_id),
                daemon=True,
            )
            self._worker_thread.start()

        JellyfinImportDialog(
            parent=self,
            server_url=self.jellyfin_server_url_var.get().strip(),
            api_key=self.jellyfin_api_key_var.get().strip(),
            user_id=self.jellyfin_user_id_var.get().strip(),
            on_fetch_users=_fetch_users,
            on_submit=_submit,
        )

    def _import_jellyfin_worker(self, server_url: str, api_key: str, user_id: str) -> None:
        try:
            client = JellyfinClient(server_url=server_url, api_key=api_key)

            if not user_id:
                users = client.get_users()
                if not users:
                    raise RuntimeError("No Jellyfin users found.")
                user_id = str(users[0].get("Id") or "").strip()
                self.jellyfin_user_id_var.set(user_id)

            def _progress(msg: str) -> None:
                self.after(0, self._set_status, msg)

            rows = client.get_audio_items(user_id=user_id, on_progress=_progress)
            records = self._rows_to_track_records(rows)

            self.local_tracks = records
            self.local_pairs = unique_album_artist(records)

            spotify_path = Path(self.spotify_csv_var.get().strip())
            if spotify_path.exists():
                self.spotify_tracks = read_spotify_csv(spotify_path)
                self.spotify_pairs = unique_album_artist(self.spotify_tracks)
                self.missing_pairs = spotify_not_owned(self.local_tracks, self.spotify_tracks)
            else:
                self.spotify_tracks = []
                self.spotify_pairs = []
                self.missing_pairs = []

            output_csv = self.paths.output_dir / "local_music_tracks.csv"
            write_track_csv(output_csv, records)

            self.after(0, self._refresh_tables)
            self.after(0, self._set_status, f"Jellyfin import complete. Tracks: {len(records)}")
        except Exception as exc:
            self.logger.exception("Jellyfin import failed")
            messagebox.showerror("Jellyfin Import Failed", str(exc))
        finally:
            self.after(0, self.progress_bar.stop)
            self.after(0, lambda: self.progress_bar.configure(mode="determinate"))
            self.after(0, self._set_running_state, False)

    def import_from_nas_cached(self) -> None:
        if self._worker_thread and self._worker_thread.is_alive():
            messagebox.showinfo("Busy", "Another job is already running.")
            return

        selected = filedialog.askdirectory(initialdir=self.local_path_var.get() or "/")
        if not selected:
            return

        self.local_path_var.set(selected)
        self._persist_current_inputs()
        self._cancel_event.clear()
        self._set_running_state(True)
        self._update_progress(0.0, "Starting NAS cached import...")

        self._worker_thread = threading.Thread(
            target=self._import_nas_cached_worker,
            args=(selected,),
            daemon=True,
        )
        self._worker_thread.start()

    def _import_nas_cached_worker(self, root_path: str) -> None:
        try:
            cache_dir = self.paths.root_dir / "cache"

            def _progress(cur: int, total: int, msg: str) -> None:
                total_safe = max(total, 1)
                pct = (cur / total_safe) * 95.0
                self.after(0, self._update_progress, pct, f"{msg} ({cur}/{total})")

            rows = scan_nas_cached(
                root_path=root_path,
                cache_dir=cache_dir,
                on_progress=_progress,
                should_cancel=self._cancel_event.is_set,
            )

            records = self._rows_to_track_records(rows)
            self.local_tracks = records
            self.local_pairs = unique_album_artist(records)

            spotify_path = Path(self.spotify_csv_var.get().strip())
            if spotify_path.exists():
                self.spotify_tracks = read_spotify_csv(spotify_path)
                self.spotify_pairs = unique_album_artist(self.spotify_tracks)
                self.missing_pairs = spotify_not_owned(self.local_tracks, self.spotify_tracks)
            else:
                self.spotify_tracks = []
                self.spotify_pairs = []
                self.missing_pairs = []

            output_csv = self.paths.output_dir / "local_music_tracks.csv"
            write_track_csv(output_csv, records)

            self.after(0, self._refresh_tables)
            self.after(0, self._update_progress, 100.0, f"NAS cached import complete. Tracks: {len(records)}")
        except RuntimeError as exc:
            if str(exc).lower().startswith("cancel"):
                self.after(0, self._update_progress, 0.0, "NAS cached import cancelled")
            else:
                self.logger.exception("NAS cached import failed")
                messagebox.showerror("NAS Import Failed", str(exc))
        except Exception as exc:
            self.logger.exception("NAS cached import failed")
            messagebox.showerror("NAS Import Failed", str(exc))
        finally:
            self.after(0, self._set_running_state, False)

    def _set_running_state(self, running: bool) -> None:
        self.scan_btn.configure(state=tk.DISABLED if running else tk.NORMAL)
        self.cancel_btn.configure(state=tk.NORMAL if running else tk.DISABLED)

    def _update_progress(self, value: float, status_text: str | None = None) -> None:
        bounded = max(0.0, min(100.0, value))
        self.progress_var.set(bounded)
        if status_text is not None:
            self.status_var.set(status_text)
        self.update_idletasks()

    def _scan_progress_callback(self, current: int, total: int, message: str) -> None:
        total_safe = max(total, 1)
        portion = (current / total_safe) * 80.0
        self.after(0, self._update_progress, portion, f"{message} ({current}/{total})")

    def cancel_compare(self) -> None:
        if self._worker_thread and self._worker_thread.is_alive():
            self._cancel_event.set()
            self._set_status("Cancelling job...")
            self.logger.info("Cancel requested by user")

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
        if self._worker_thread and self._worker_thread.is_alive():
            return

        CompareSourceDialog(self, self._start_compare_for_source)

    def _start_compare_for_source(self, source: str) -> None:
        if source == "Local":
            self._start_local_compare()
            return
        if source == "Jellyfin":
            self._start_jellyfin_compare()
            return

    def _start_local_compare(self) -> None:
        self._persist_current_inputs()
        self._cancel_event.clear()
        self.progress_bar.configure(mode="determinate")
        self._set_running_state(True)
        self._update_progress(0.0, "Starting compare job...")

        self._worker_thread = threading.Thread(target=self._run_compare_worker, daemon=True)
        self._worker_thread.start()

    def _start_jellyfin_compare(self) -> None:
        if not self.jellyfin_server_url_var.get().strip() or not self.jellyfin_api_key_var.get().strip():
            messagebox.showerror(
                "Jellyfin Configuration Required",
                "Open Settings > Preferences and set Jellyfin Server URL and API Key before using Jellyfin compare.",
            )
            return

        self._persist_current_inputs()
        self._cancel_event.clear()
        self._set_running_state(True)
        self.progress_bar.configure(mode="indeterminate")
        self.progress_bar.start(12)
        self._set_status("Starting Jellyfin compare...")

        self._worker_thread = threading.Thread(target=self._run_compare_worker_jellyfin, daemon=True)
        self._worker_thread.start()

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
            self.logger.info("Scan profile: %s", self.scan_profile_var.get())
            self.logger.info("Max scan workers: %s", self.max_scan_workers_var.get())

            self.local_tracks = scan_music_folder(
                local_path,
                on_progress=self._scan_progress_callback,
                should_cancel=self._cancel_event.is_set,
                cache_file=self.paths.config_dir / "local_index_cache.json",
                use_cache=not self.force_reindex_var.get(),
                max_workers=max(0, int(self.max_scan_workers_var.get().strip() or "0")) or None,
                scan_profile=self.scan_profile_var.get().strip().lower() or "auto",
            )
            self.local_pairs = unique_album_artist(self.local_tracks)

            if self._cancel_event.is_set():
                raise ScanCancelled("Compare job cancelled.")

            self.after(0, self._update_progress, 86.0, "Reading Spotify CSV...")
            self.spotify_tracks = read_spotify_csv(spotify_csv)
            self.spotify_pairs = unique_album_artist(self.spotify_tracks)

            if self._cancel_event.is_set():
                raise ScanCancelled("Compare job cancelled.")

            self.after(0, self._update_progress, 92.0, "Comparing local library vs Spotify...")
            self.missing_pairs = spotify_not_owned(self.local_tracks, self.spotify_tracks)

            output_dir.mkdir(parents=True, exist_ok=True)
            local_csv = output_dir / "local_music_tracks.csv"
            spotify_clean_csv = output_dir / "spotify_clean_tracks.csv"
            missing_csv = output_dir / "spotify_not_owned_albums_artists.csv"

            write_track_csv(local_csv, self.local_tracks)
            write_track_csv(spotify_clean_csv, self.spotify_tracks)
            write_album_artist_csv(missing_csv, self.missing_pairs)
            self.after(0, self._update_progress, 98.0, "Writing output CSV files...")
            self.logger.info("Wrote local CSV: %s", local_csv)
            self.logger.info("Wrote spotify-clean CSV: %s", spotify_clean_csv)
            self.logger.info("Wrote missing album/artist CSV: %s", missing_csv)

            self._refresh_tables()

            self.after(
                0,
                self._update_progress,
                100.0,
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
        except ScanCancelled:
            self.after(0, self._update_progress, 0.0, "Job cancelled")
            self.logger.info("Compare job cancelled")
        except Exception as exc:
            self._set_status("Failed")
            self.logger.exception("Compare run failed")
            messagebox.showerror("Error", str(exc))
        finally:
            self.after(0, self._set_running_state, False)

    def _run_compare_worker_jellyfin(self) -> None:
        try:
            spotify_csv = self.spotify_csv_var.get().strip()
            output_dir = self.paths.output_dir

            if not spotify_csv:
                raise ValueError("Spotify CSV path is required.")

            self.logger.info("Jellyfin compare run started")
            self.logger.info("Jellyfin server: %s", self.jellyfin_server_url_var.get().strip())
            self.logger.info("Spotify CSV: %s", spotify_csv)

            client = JellyfinClient(
                server_url=self.jellyfin_server_url_var.get().strip(),
                api_key=self.jellyfin_api_key_var.get().strip(),
            )

            user_id = self.jellyfin_user_id_var.get().strip()
            if not user_id:
                users = client.get_users()
                if not users:
                    raise RuntimeError("No Jellyfin users found.")
                user_id = str(users[0].get("Id") or "").strip()
                self.jellyfin_user_id_var.set(user_id)
                self._persist_current_inputs()

            def _progress(msg: str) -> None:
                self.after(0, self._set_status, msg)

            rows = client.get_audio_items(user_id=user_id, on_progress=_progress)
            self.local_tracks = self._rows_to_track_records(rows)
            self.local_pairs = unique_album_artist(self.local_tracks)

            if self._cancel_event.is_set():
                raise ScanCancelled("Compare job cancelled.")

            self.after(0, self._set_status, "Reading Spotify CSV...")
            self.spotify_tracks = read_spotify_csv(spotify_csv)
            self.spotify_pairs = unique_album_artist(self.spotify_tracks)

            if self._cancel_event.is_set():
                raise ScanCancelled("Compare job cancelled.")

            self.after(0, self._set_status, "Comparing Jellyfin library vs Spotify...")
            self.missing_pairs = spotify_not_owned(self.local_tracks, self.spotify_tracks)

            output_dir.mkdir(parents=True, exist_ok=True)
            local_csv = output_dir / "local_music_tracks.csv"
            spotify_clean_csv = output_dir / "spotify_clean_tracks.csv"
            missing_csv = output_dir / "spotify_not_owned_albums_artists.csv"

            write_track_csv(local_csv, self.local_tracks)
            write_track_csv(spotify_clean_csv, self.spotify_tracks)
            write_album_artist_csv(missing_csv, self.missing_pairs)

            self.after(0, self._refresh_tables)
            self.after(
                0,
                self._set_status,
                f"Done. Jellyfin tracks: {len(self.local_tracks)} | Spotify tracks: {len(self.spotify_tracks)} | Missing albums/artists: {len(self.missing_pairs)}",
            )
            self.logger.info(
                "Jellyfin compare completed: jellyfin=%s spotify=%s missing=%s",
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
        except ScanCancelled:
            self.after(0, self._set_status, "Job cancelled")
            self.logger.info("Jellyfin compare cancelled")
        except Exception as exc:
            self.logger.exception("Jellyfin compare failed")
            messagebox.showerror("Error", str(exc))
        finally:
            self.after(0, self.progress_bar.stop)
            self.after(0, lambda: self.progress_bar.configure(mode="determinate"))
            self.after(0, self._set_running_state, False)

    def _refresh_tables(self) -> None:
        self.clear_tables()

        for rec in self.local_pairs:
            self.local_table.insert("", "end", values=(rec.artist, rec.album))

        for rec in self.missing_pairs:
            self.spotify_table.insert("", "end", values=(rec.artist, rec.album))


def run_app(paths: RuntimePaths, config_store: ConfigStore, logger: logging.Logger) -> None:
    app = MusicCompareApp(paths=paths, config_store=config_store, logger=logger)
    app.mainloop()
