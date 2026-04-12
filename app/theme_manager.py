from __future__ import annotations

from dataclasses import dataclass
import tkinter as tk
from tkinter import ttk


@dataclass(frozen=True)
class ThemePalette:
    name: str
    colors: tuple[str, str, str, str]


THEMES: dict[str, ThemePalette] = {
    "palette_1": ThemePalette("Palette 1", ("#18230F", "#27391C", "#255F38", "#1F7D53")),
    "palette_2": ThemePalette("Palette 2", ("#090040", "#471396", "#B13BFF", "#FFCC00")),
    "palette_3": ThemePalette("Palette 3", ("#1B3C53", "#234C6A", "#456882", "#D2C1B6")),
    "palette_4": ThemePalette("Palette 4", ("#091413", "#285A48", "#408A71", "#B0E4CC")),
    "palette_5": ThemePalette("Palette 5", ("#0D1A63", "#1A2CA3", "#2845D6", "#F6F8F0")),
    "palette_6": ThemePalette("Palette 6", ("#222831", "#393E46", "#948979", "#DFD0B8")),
    "palette_7": ThemePalette("Palette 7", ("#021526", "#03346E", "#6EACDA", "#E2E2B6")),
    "palette_8": ThemePalette("Palette 8", ("#2E073F", "#7A1CAC", "#AD49E1", "#EBD3F8")),
    "palette_9": ThemePalette("Palette 9", ("#17153B", "#2E236C", "#433D8B", "#C8ACD6")),
    "palette_10": ThemePalette("Palette 10", ("#402E7A", "#4C3BCF", "#4B70F5", "#3DC2EC")),
    "palette_11": ThemePalette("Palette 11", ("#240750", "#344C64", "#577B8D", "#57A6A1")),
    "palette_12": ThemePalette("Palette 12", ("#070F2B", "#1B1A55", "#535C91", "#9290C3")),
    "palette_13": ThemePalette("Palette 13", ("#030637", "#3C0753", "#720455", "#910A67")),
    "palette_14": ThemePalette("Palette 14", ("#092635", "#1B4242", "#5C8374", "#9EC8B9")),
}


def theme_keys() -> list[str]:
    return list(THEMES.keys())


def theme_labels() -> list[str]:
    return [f"{key}: {THEMES[key].name}" for key in THEMES]


def _to_label(theme_key: str) -> str:
    palette = THEMES.get(theme_key)
    if not palette:
        return f"{theme_key}: Unknown"
    return f"{theme_key}: {palette.name}"


def label_to_key(label: str) -> str:
    if ":" in label:
        key = label.split(":", 1)[0].strip()
        if key in THEMES:
            return key
    return "palette_1"


def key_to_label(theme_key: str) -> str:
    return _to_label(theme_key if theme_key in THEMES else "palette_1")


def apply_theme(root: tk.Tk, style: ttk.Style, theme_key: str, menus: list[tk.Menu] | None = None) -> str:
    key = theme_key if theme_key in THEMES else "palette_1"
    c1, c2, c3, c4 = THEMES[key].colors

    try:
        style.theme_use("clam")
    except tk.TclError:
        pass

    root.configure(bg=c1)
    root.option_add("*Font", "TkDefaultFont 10")

    style.configure(".", background=c1, foreground=c4)
    style.configure("TFrame", background=c1)
    style.configure("TLabelframe", background=c1, foreground=c4)
    style.configure("TLabelframe.Label", background=c1, foreground=c4)
    style.configure("TLabel", background=c1, foreground=c4)

    style.configure("TButton", background=c3, foreground=c4, bordercolor=c2, focuscolor=c3)
    style.map(
        "TButton",
        background=[("active", c2), ("disabled", c2)],
        foreground=[("disabled", "#aaaaaa")],
    )

    style.configure("TEntry", fieldbackground=c2, foreground=c4, bordercolor=c3, insertcolor=c4)
    style.configure("TCombobox", fieldbackground=c2, foreground=c4, background=c3, arrowsize=14)
    style.map("TCombobox", fieldbackground=[("readonly", c2)], foreground=[("readonly", c4)])

    style.configure("Treeview", background=c2, foreground=c4, fieldbackground=c2, bordercolor=c3)
    style.map("Treeview", background=[("selected", c3)], foreground=[("selected", c4)])
    style.configure("Treeview.Heading", background=c3, foreground=c4)
    style.map("Treeview.Heading", background=[("active", c2)])

    style.configure("TScrollbar", background=c2, troughcolor=c1, arrowcolor=c4, bordercolor=c3)
    style.configure("Horizontal.TProgressbar", background=c3, troughcolor=c2)

    root.tk_setPalette(background=c1, foreground=c4, activeBackground=c3, activeForeground=c4)

    if menus:
        for menu in menus:
            try:
                menu.configure(bg=c1, fg=c4, activebackground=c3, activeforeground=c4)
            except tk.TclError:
                continue

    return key
