"""Modern UI theme for Setlist Manager.

Et samlet sted hvor vi definerer farver, fonts og TTK-stilarter.
Importér ``apply_theme(root)`` i main() — så får hele appen et konsistent
moderne udseende på Windows, Mac og Linux.

Designprincipper:
- Lys baggrund med rene hvide "kort" (LabelFrame/Treeview)
- Grøn accent-farve (passer til band/musik temaet)
- Generøs padding så ingenting føles klemt
- Subtile borders (1px solid) i stedet for 3D-relief
- System-fonts (Segoe UI på Win, SF Pro på Mac, Ubuntu på Linux)
"""

from __future__ import annotations

import sys
import tkinter as tk
from tkinter import ttk


# ===========================================================================
#  Farve-palette
# ===========================================================================
class Colors:
    # Baggrunde
    BG = "#f4f5f7"               # main background (let blå-grå)
    SURFACE = "#ffffff"          # cards / panels
    SURFACE_HOVER = "#f8f9fb"
    SURFACE_ALT = "#fafbfc"      # alternating rows

    # Borders / dividers
    BORDER = "#dfe1e6"
    BORDER_STRONG = "#c1c7d0"

    # Tekst
    TEXT = "#1a1a1f"             # primary
    TEXT_SECONDARY = "#5e6c84"   # labels, hints
    TEXT_MUTED = "#97a0af"       # placeholder, disabled
    TEXT_ON_ACCENT = "#ffffff"

    # Accent (primary action color) — grøn, passer til musik/band-tema
    ACCENT = "#0a7d2c"
    ACCENT_HOVER = "#086324"
    ACCENT_ACTIVE = "#054a1b"
    ACCENT_SOFT = "#e8f5ee"      # baggrund ved selected rows

    # Sekundære state-farver
    DANGER = "#de350b"
    DANGER_HOVER = "#bf2600"
    DANGER_SOFT = "#ffeae5"
    WARNING = "#ff8b00"
    INFO = "#0052cc"

    # Special
    SELECTED_BG = "#e8f5ee"
    SELECTED_FG = "#0a4318"
    MARKER_BG = "#fff7d6"
    MARKER_FG = "#6b4f00"
    MARKER_SELECTED_BG = "#b88a00"
    MARKER_SELECTED_FG = "#ffffff"
    IN_SETLIST_FG = "#a0a8b3"    # grayed out


# ===========================================================================
#  Fonts — system-fonts der ser native ud på hver platform
# ===========================================================================
def _font_family() -> str:
    if sys.platform.startswith("win"):
        return "Segoe UI"
    if sys.platform == "darwin":
        # SF Pro Text er Apple's system-font (siden Big Sur)
        return "SF Pro Text"
    # Linux
    return "Ubuntu"


FONT_FAMILY = _font_family()


class Fonts:
    DEFAULT = (FONT_FAMILY, 10)
    SMALL = (FONT_FAMILY, 9)
    BOLD = (FONT_FAMILY, 10, "bold")
    H3 = (FONT_FAMILY, 11, "bold")     # LabelFrame headers
    H2 = (FONT_FAMILY, 13, "bold")     # dialog titler
    H1 = (FONT_FAMILY, 17, "bold")     # store titler
    MONO_SMALL = ("Consolas" if sys.platform.startswith("win") else "Menlo", 9)


# ===========================================================================
#  Apply theme — kald én gang fra main()
# ===========================================================================
def apply_theme(root: tk.Tk) -> None:
    """Anvend det moderne tema på alle TTK widgets i root.

    Kald denne én gang lige efter Tk-vinduet er oprettet og FØR du bygger
    nogen widgets — så følger de alle den nye stil.
    """
    style = ttk.Style(root)

    # 'clam' er den mest customizable ttk-theme. På Windows er 'vista'
    # default men den ignorerer mange style-options. På Mac er 'aqua'
    # default og næsten umulig at customize. Vi bruger 'clam' overalt
    # for konsistens.
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass

    c = Colors
    f = Fonts

    # Default font for ALLE classic tk widgets (Listbox, Text, etc.)
    root.option_add("*Font", f.DEFAULT)
    root.option_add("*selectBackground", c.SELECTED_BG)
    root.option_add("*selectForeground", c.SELECTED_FG)
    root.configure(bg=c.BG)

    # ----- TFrame -----
    style.configure("TFrame", background=c.BG)
    # Hvid "kort"-variant
    style.configure("Card.TFrame", background=c.SURFACE)

    # ----- TLabel -----
    style.configure(
        "TLabel",
        background=c.BG,
        foreground=c.TEXT,
        font=f.DEFAULT,
    )
    style.configure(
        "Secondary.TLabel",
        background=c.BG,
        foreground=c.TEXT_SECONDARY,
        font=f.SMALL,
    )
    style.configure(
        "Heading.TLabel",
        background=c.BG,
        foreground=c.TEXT,
        font=f.H2,
    )
    style.configure(
        "Muted.TLabel",
        background=c.BG,
        foreground=c.TEXT_MUTED,
        font=f.SMALL,
    )

    # ----- TLabelframe -----
    style.configure(
        "TLabelframe",
        background=c.BG,
        bordercolor=c.BORDER,
        lightcolor=c.BORDER,
        darkcolor=c.BORDER,
        borderwidth=1,
        relief="solid",
    )
    style.configure(
        "TLabelframe.Label",
        background=c.BG,
        foreground=c.TEXT_SECONDARY,
        font=f.H3,
        padding=(4, 0, 4, 0),
    )

    # ----- TButton (default) -----
    style.configure(
        "TButton",
        background=c.SURFACE,
        foreground=c.TEXT,
        bordercolor=c.BORDER,
        lightcolor=c.SURFACE,
        darkcolor=c.SURFACE,
        focuscolor=c.ACCENT,
        font=f.DEFAULT,
        padding=(12, 6),
        borderwidth=1,
        relief="solid",
        anchor="center",
    )
    style.map(
        "TButton",
        background=[
            ("disabled", c.BG),
            ("pressed", c.BORDER),
            ("active", c.SURFACE_HOVER),
        ],
        bordercolor=[
            ("focus", c.ACCENT),
            ("active", c.BORDER_STRONG),
        ],
        foreground=[
            ("disabled", c.TEXT_MUTED),
        ],
    )

    # ----- TButton: Accent / Primary action -----
    style.configure(
        "Accent.TButton",
        background=c.ACCENT,
        foreground=c.TEXT_ON_ACCENT,
        bordercolor=c.ACCENT,
        lightcolor=c.ACCENT,
        darkcolor=c.ACCENT,
        font=f.BOLD,
        padding=(14, 7),
    )
    style.map(
        "Accent.TButton",
        background=[
            ("disabled", c.TEXT_MUTED),
            ("pressed", c.ACCENT_ACTIVE),
            ("active", c.ACCENT_HOVER),
        ],
        bordercolor=[
            ("pressed", c.ACCENT_ACTIVE),
            ("active", c.ACCENT_HOVER),
        ],
        foreground=[("disabled", c.SURFACE)],
    )

    # ----- TButton: Danger -----
    style.configure(
        "Danger.TButton",
        background=c.SURFACE,
        foreground=c.DANGER,
        bordercolor=c.BORDER,
    )
    style.map(
        "Danger.TButton",
        background=[
            ("pressed", c.DANGER_SOFT),
            ("active", c.DANGER_SOFT),
        ],
        bordercolor=[("active", c.DANGER)],
        foreground=[("disabled", c.TEXT_MUTED)],
    )

    # ----- TButton: Subtle (helt flad, ingen border — til "Slet"/"Omdøb") -----
    style.configure(
        "Subtle.TButton",
        background=c.BG,
        foreground=c.TEXT_SECONDARY,
        bordercolor=c.BG,
        lightcolor=c.BG,
        darkcolor=c.BG,
        padding=(8, 5),
    )
    style.map(
        "Subtle.TButton",
        background=[("active", c.SURFACE_HOVER), ("pressed", c.BORDER)],
        foreground=[("active", c.TEXT)],
        bordercolor=[("active", c.BORDER)],
    )

    # ----- TEntry -----
    style.configure(
        "TEntry",
        fieldbackground=c.SURFACE,
        foreground=c.TEXT,
        bordercolor=c.BORDER,
        lightcolor=c.BORDER,
        darkcolor=c.BORDER,
        insertcolor=c.ACCENT,
        borderwidth=1,
        relief="solid",
        padding=(6, 5),
    )
    style.map(
        "TEntry",
        bordercolor=[("focus", c.ACCENT)],
        lightcolor=[("focus", c.ACCENT)],
        darkcolor=[("focus", c.ACCENT)],
    )

    # ----- TCombobox -----
    style.configure(
        "TCombobox",
        fieldbackground=c.SURFACE,
        background=c.SURFACE,
        foreground=c.TEXT,
        bordercolor=c.BORDER,
        lightcolor=c.BORDER,
        darkcolor=c.BORDER,
        arrowcolor=c.TEXT_SECONDARY,
        borderwidth=1,
        relief="solid",
        padding=(6, 4),
    )
    style.map(
        "TCombobox",
        fieldbackground=[
            ("readonly", c.SURFACE),
            ("focus", c.SURFACE),
        ],
        bordercolor=[("focus", c.ACCENT), ("active", c.BORDER_STRONG)],
        arrowcolor=[("active", c.ACCENT)],
    )
    # Dropdown-listen
    root.option_add("*TCombobox*Listbox.background", c.SURFACE)
    root.option_add("*TCombobox*Listbox.foreground", c.TEXT)
    root.option_add("*TCombobox*Listbox.selectBackground", c.ACCENT_SOFT)
    root.option_add("*TCombobox*Listbox.selectForeground", c.SELECTED_FG)
    root.option_add("*TCombobox*Listbox.font", f.DEFAULT)
    root.option_add("*TCombobox*Listbox.relief", "flat")
    root.option_add("*TCombobox*Listbox.borderWidth", 0)

    # ----- Treeview -----
    style.configure(
        "Treeview",
        background=c.SURFACE,
        fieldbackground=c.SURFACE,
        foreground=c.TEXT,
        bordercolor=c.BORDER,
        lightcolor=c.BORDER,
        darkcolor=c.BORDER,
        borderwidth=1,
        relief="solid",
        rowheight=28,
        font=f.DEFAULT,
    )
    style.configure(
        "Treeview.Heading",
        background=c.BG,
        foreground=c.TEXT_SECONDARY,
        font=f.BOLD,
        bordercolor=c.BORDER,
        relief="flat",
        padding=(10, 8),
    )
    style.map(
        "Treeview",
        background=[("selected", c.ACCENT_SOFT)],
        foreground=[("selected", c.SELECTED_FG)],
    )
    style.map(
        "Treeview.Heading",
        background=[("active", c.SURFACE_HOVER)],
        foreground=[("active", c.TEXT)],
    )

    # ----- Scrollbar -----
    style.configure(
        "Vertical.TScrollbar",
        background=c.BG,
        troughcolor=c.BG,
        bordercolor=c.BG,
        arrowcolor=c.TEXT_SECONDARY,
        lightcolor=c.BG,
        darkcolor=c.BG,
        gripcount=0,
    )
    style.map(
        "Vertical.TScrollbar",
        background=[("active", c.BORDER_STRONG), ("pressed", c.TEXT_MUTED)],
    )
    style.configure(
        "Horizontal.TScrollbar",
        background=c.BG,
        troughcolor=c.BG,
        bordercolor=c.BG,
        arrowcolor=c.TEXT_SECONDARY,
        lightcolor=c.BG,
        darkcolor=c.BG,
        gripcount=0,
    )

    # ----- Progressbar -----
    style.configure(
        "Horizontal.TProgressbar",
        background=c.ACCENT,
        troughcolor=c.BORDER,
        bordercolor=c.BG,
        lightcolor=c.ACCENT,
        darkcolor=c.ACCENT,
        borderwidth=0,
        thickness=8,
    )

    # ----- Separator -----
    style.configure("TSeparator", background=c.BORDER)


# ===========================================================================
#  Helpers til at style "classic" tk-widgets (Listbox, Text) der ikke
#  går igennem ttk.Style
# ===========================================================================
def style_listbox(lb: tk.Listbox) -> None:
    """Anvend det moderne tema på en tk.Listbox."""
    c = Colors
    lb.configure(
        bg=c.SURFACE,
        fg=c.TEXT,
        selectbackground=c.ACCENT_SOFT,
        selectforeground=c.SELECTED_FG,
        relief="solid",
        borderwidth=1,
        highlightthickness=1,
        highlightbackground=c.BORDER,
        highlightcolor=c.ACCENT,
        font=Fonts.DEFAULT,
        activestyle="none",
    )


def style_text(t: tk.Text) -> None:
    """Anvend det moderne tema på en tk.Text."""
    c = Colors
    t.configure(
        bg=c.SURFACE,
        fg=c.TEXT,
        insertbackground=c.ACCENT,
        selectbackground=c.ACCENT_SOFT,
        selectforeground=c.SELECTED_FG,
        relief="solid",
        borderwidth=1,
        highlightthickness=1,
        highlightbackground=c.BORDER,
        highlightcolor=c.ACCENT,
        font=Fonts.DEFAULT,
        padx=8,
        pady=6,
    )


def style_menu(m: tk.Menu) -> None:
    """Anvend det moderne tema på en tk.Menu."""
    c = Colors
    m.configure(
        bg=c.SURFACE,
        fg=c.TEXT,
        activebackground=c.ACCENT_SOFT,
        activeforeground=c.SELECTED_FG,
        relief="flat",
        borderwidth=0,
        font=Fonts.DEFAULT,
    )
