"""Setlist Manager — Tkinter GUI på dansk.

Multi-band support, søgning på tværs af bands, print-dialog med
valgfri kolonner, og import af sange fra MusicBrainz (internet).
"""

from __future__ import annotations

import base64
import io
import os
import sys
import tempfile
import threading
import webbrowser
from pathlib import Path

import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

try:
    from PIL import Image, ImageTk  # type: ignore[import-not-found]
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

import music_search
from setlist_model import (
    FONT_SIZES_PT,
    SetlistModel,
    default_autosave_path,
    default_print_options,
    format_modified_at,
    format_seconds,
    is_marker_item,
    item_marker_label,
    item_song_name,
    new_song,
)
from stage_mode import StageMode
import theme

import updater
from version import APP_VERSION

APP_TITLE = f"Setlist Manager {APP_VERSION}"
AUTOSAVE_DEBOUNCE_MS = 800
UPDATE_CHECK_DELAY_MS = 3000  # vent 3 s efter start før vi tjekker (ikke spærre GUI)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _center_on(window: tk.Toplevel, parent: tk.Misc) -> None:
    try:
        window.update_idletasks()
        x = parent.winfo_rootx() + (parent.winfo_width() // 2) - (window.winfo_width() // 2)
        y = parent.winfo_rooty() + (parent.winfo_height() // 2) - (window.winfo_height() // 2)
        window.geometry(f"+{max(x, 0)}+{max(y, 0)}")
    except tk.TclError:
        pass


# ---------------------------------------------------------------------------
# Tilføj/Rediger sang
# ---------------------------------------------------------------------------
class SongDialog(tk.Toplevel):
    def __init__(self, parent, title: str = "Sang", initial: dict | None = None) -> None:
        super().__init__(parent)
        self.title(title)
        self.transient(parent)
        self.resizable(False, False)
        self.result: dict | None = None

        initial = initial or {}
        self._vars = {
            "name": tk.StringVar(value=initial.get("name", "")),
            "key": tk.StringVar(value=initial.get("key", "")),
            "duration": tk.StringVar(value=initial.get("duration", "")),
        }

        frm = ttk.Frame(self, padding=12)
        frm.pack(fill=tk.BOTH, expand=True)

        rows = [
            ("Navn:", "name", 36),
            ("Toneart:", "key", 12),
            ("Længde (m:ss):", "duration", 12),
        ]
        for i, (label, field, width) in enumerate(rows):
            ttk.Label(frm, text=label).grid(row=i, column=0, sticky=tk.W, pady=4)
            entry = ttk.Entry(frm, textvariable=self._vars[field], width=width)
            entry.grid(row=i, column=1, sticky=tk.W + tk.E, pady=4, padx=(8, 0))
            if i == 0:
                entry.focus_set()
                entry.select_range(0, tk.END)

        ttk.Label(frm, text="Noter:").grid(row=len(rows), column=0, sticky=tk.NW, pady=4)
        self._notes = tk.Text(frm, width=36, height=4, wrap=tk.WORD)
        theme.style_text(self._notes)
        self._notes.insert("1.0", initial.get("notes", ""))
        self._notes.grid(row=len(rows), column=1, sticky=tk.W + tk.E, pady=4, padx=(8, 0))

        btns = ttk.Frame(frm)
        btns.grid(row=len(rows) + 1, column=0, columnspan=2, sticky=tk.E, pady=(10, 0))
        ttk.Button(btns, text="Annullér", command=self.destroy).pack(side=tk.RIGHT, padx=(6, 0))
        ttk.Button(btns, text="Gem", command=self._ok).pack(side=tk.RIGHT)

        self.bind("<Return>", lambda e: self._ok())
        self.bind("<Escape>", lambda e: self.destroy())

        _center_on(self, parent)
        self.grab_set()
        self.wait_window(self)

    def _ok(self) -> None:
        name = self._vars["name"].get().strip()
        if not name:
            messagebox.showerror("Fejl", "Sangen skal have et navn.", parent=self)
            return
        self.result = {
            "name": name,
            "key": self._vars["key"].get().strip(),
            "duration": self._vars["duration"].get().strip(),
            "notes": self._notes.get("1.0", tk.END).strip(),
        }
        self.destroy()


# ---------------------------------------------------------------------------
# Print A4 — med valg af kolonner, tekststørrelse, logo og LIVE forhåndsvisning
# ---------------------------------------------------------------------------
# Tekststørrelser brugt i selve previewet (skaleret ned fra de "rigtige" pt)
# Indekseret efter font_size key. Holdes tæt på FONT_SIZES_PT * 0.55
_PREVIEW_SIZES = {
    "xsmall": {"title": 11, "meta":  7, "table":  8, "total":  7},
    "small":  {"title": 13, "meta":  7, "table":  9, "total":  8},
    "medium": {"title": 16, "meta":  8, "table": 10, "total":  9},
    "large":  {"title": 19, "meta":  8, "table": 12, "total": 10},
    "xlarge": {"title": 23, "meta":  9, "table": 14, "total": 11},
}

_SIZE_LABELS = [
    ("Mini",   "xsmall"),
    ("Lille",  "small"),
    ("Mellem", "medium"),
    ("Stor",   "large"),
    ("Maxi",   "xlarge"),
]


class PrintDialog(tk.Toplevel):
    def __init__(
        self,
        parent,
        default_title: str,
        current_options: dict,
        model: "SetlistModel | None" = None,
    ) -> None:
        super().__init__(parent)
        self.title("Print A4")
        self.transient(parent)
        self.resizable(False, False)
        self.result: dict | None = None
        self.model = model  # bruges til preview + browser-forhåndsvisning

        defaults = default_print_options()
        merged = {**defaults, **(current_options or {})}
        # Normaliser ukendt font_size til "medium"
        fs = merged.get("font_size", "medium")
        if fs not in FONT_SIZES_PT:
            fs = "medium"

        self.title_var = tk.StringVar(value=default_title)
        self.font_size_var = tk.StringVar(value=fs)
        self.opts = {
            # Header
            "show_title":        tk.BooleanVar(value=bool(merged.get("show_title", True))),
            "show_meta":         tk.BooleanVar(value=bool(merged.get("show_meta", True))),
            "show_date":         tk.BooleanVar(value=bool(merged.get("show_date", True))),
            "show_logo":         tk.BooleanVar(value=bool(merged.get("show_logo", True))),
            # Tabel
            "show_table_header": tk.BooleanVar(value=bool(merged.get("show_table_header", True))),
            "show_number":       tk.BooleanVar(value=bool(merged.get("show_number", True))),
            "show_key":          tk.BooleanVar(value=bool(merged.get("show_key", True))),
            "show_duration":     tk.BooleanVar(value=bool(merged.get("show_duration", True))),
            "show_notes":        tk.BooleanVar(value=bool(merged.get("show_notes", True))),
            # Footer + sektioner
            "show_total_time":   tk.BooleanVar(value=bool(merged.get("show_total_time", True))),
            "show_markers":      tk.BooleanVar(value=bool(merged.get("show_markers", True))),
        }

        # Preview-state
        self._preview_logo_photo = None  # MÅ ikke garbage-collectes

        outer = ttk.Frame(self, padding=14)
        outer.pack(fill=tk.BOTH, expand=True)

        # ---- Venstre kolonne: kontrol-elementer ----
        left = ttk.Frame(outer)
        left.grid(row=0, column=0, sticky=tk.N + tk.W, padx=(0, 14))

        # Overskrift
        ttk.Label(left, text="Overskrift:").grid(row=0, column=0, sticky=tk.W, pady=(0, 4))
        entry = ttk.Entry(left, textvariable=self.title_var, width=34)
        entry.grid(row=0, column=1, sticky=tk.W + tk.E, pady=(0, 10), padx=(8, 0))
        entry.focus_set()
        entry.select_range(0, tk.END)

        # Tekststørrelse
        ttk.Label(
            left, text="Tekststørrelse:", font=("TkDefaultFont", 10, "bold"),
        ).grid(row=1, column=0, columnspan=2, sticky=tk.W, pady=(6, 2))
        size_row = ttk.Frame(left)
        size_row.grid(row=2, column=0, columnspan=2, sticky=tk.W, padx=(12, 0), pady=2)
        for label, value in _SIZE_LABELS:
            ttk.Radiobutton(
                size_row, text=label, value=value, variable=self.font_size_var
            ).pack(side=tk.LEFT, padx=(0, 8))

        # Hvad skal med — i grupper
        ttk.Label(
            left, text="Vis på arket:", font=("TkDefaultFont", 10, "bold"),
        ).grid(row=3, column=0, columnspan=2, sticky=tk.W, pady=(10, 2))

        # Knapper til "alt til" / "alt fra"
        toggle_row = ttk.Frame(left)
        toggle_row.grid(row=4, column=0, columnspan=2, sticky=tk.W, padx=(12, 0), pady=(0, 4))
        ttk.Button(
            toggle_row, text="Alt til", width=8,
            command=lambda: self._set_all_opts(True),
        ).pack(side=tk.LEFT)
        ttk.Button(
            toggle_row, text="Alt fra", width=8,
            command=lambda: self._set_all_opts(False),
        ).pack(side=tk.LEFT, padx=(4, 0))

        check_groups: list = [
            ("Øverst (header)", [
                ("show_title", "Titel/overskrift"),
                ("show_meta",  "Meta-linje (bandnavn · dato · antal sange)"),
                ("show_date",  "    └ Dato i meta-linjen"),
                ("show_logo",  "Bandets logo (øverste højre)"),
            ]),
            ("Tabel med sange", [
                ("show_table_header", "Kolonneoverskrifter (#, Sang, Toneart, …)"),
                ("show_number",       "Sangnummer (1, 2, 3, …)"),
                ("show_key",          "Toneart"),
                ("show_duration",     "Længde pr. sang"),
                ("show_notes",        "Noter"),
            ]),
            ("Nederst + sektioner", [
                ("show_total_time", "Samlet spilletid nederst"),
                ("show_markers",    "Sektion-markører (Ekstra-nummer, Slut, …)"),
            ]),
        ]
        next_row = 5
        for group_label, rows in check_groups:
            ttk.Label(
                left, text=group_label,
                font=("TkDefaultFont", 9, "bold"),
                foreground="#555",
            ).grid(row=next_row, column=0, columnspan=2, sticky=tk.W,
                   padx=(12, 0), pady=(8, 2))
            next_row += 1
            for key, label in rows:
                ttk.Checkbutton(left, text=label, variable=self.opts[key]).grid(
                    row=next_row, column=0, columnspan=2,
                    sticky=tk.W, padx=(24, 0), pady=1,
                )
                next_row += 1

        # Browser-forhåndsvisning (sekundær)
        browser_row = next_row
        if self.model is not None:
            ttk.Separator(left, orient=tk.HORIZONTAL).grid(
                row=browser_row, column=0, columnspan=2,
                sticky=tk.W + tk.E, pady=(12, 8),
            )
            ttk.Button(
                left, text="🌐  Åbn fuld forhåndsvisning i browser",
                command=self._preview_in_browser,
            ).grid(row=browser_row + 1, column=0, columnspan=2,
                   sticky=tk.W, padx=(12, 0))

        # ---- Højre kolonne: LIVE preview ----
        if self.model is not None:
            right = ttk.LabelFrame(outer, text="Forhåndsvisning", padding=8)
            right.grid(row=0, column=1, sticky=tk.N + tk.S)
            self._build_preview(right)

        # ---- Bund-knapper ----
        btns = ttk.Frame(outer)
        btns.grid(row=1, column=0, columnspan=2, sticky=tk.E, pady=(14, 0))
        ttk.Button(btns, text="Annullér", command=self.destroy).pack(side=tk.RIGHT, padx=(6, 0))
        ttk.Button(btns, text="Print →", command=self._ok).pack(side=tk.RIGHT)

        # Hook live-update på alle variabler
        if self.model is not None:
            self.title_var.trace_add("write", lambda *_: self._update_preview())
            self.font_size_var.trace_add("write", lambda *_: self._update_preview())
            for v in self.opts.values():
                v.trace_add("write", lambda *_: self._update_preview())
            self._update_preview()

        self.bind("<Return>", lambda e: self._ok())
        self.bind("<Escape>", lambda e: self.destroy())

        _center_on(self, parent)
        self.grab_set()
        self.wait_window(self)

    # ------------------------------------------------------------------
    # Preview-konstruktion + opdatering
    # ------------------------------------------------------------------
    def _build_preview(self, parent: ttk.LabelFrame) -> None:
        """Byg en mini-A4-side (210×297 → ~340×480 px) som opdateres live."""
        # Den hvide "papir"-firkant
        self._page = tk.Frame(
            parent, bg="white", width=340, height=480,
            highlightthickness=1, highlightbackground="#999",
        )
        self._page.pack()
        self._page.pack_propagate(False)

        # Indre padding på "papiret"
        inner = tk.Frame(self._page, bg="white")
        inner.pack(fill=tk.BOTH, expand=True, padx=14, pady=14)
        self._inner = inner

        # Header med titel/meta venstre + logo højre
        self._header = tk.Frame(inner, bg="white")
        self._header.pack(fill=tk.X)

        self._header_left = tk.Frame(self._header, bg="white")
        self._header_left.pack(side=tk.LEFT, fill=tk.X, expand=True, anchor=tk.NW)

        self._title_lbl = tk.Label(
            self._header_left, bg="white", anchor=tk.W, justify=tk.LEFT, text="",
        )
        self._title_lbl.pack(anchor=tk.W)
        self._meta_lbl = tk.Label(
            self._header_left, bg="white", anchor=tk.W, justify=tk.LEFT,
            text="", fg="#555",
        )
        self._meta_lbl.pack(anchor=tk.W, pady=(2, 0))

        self._logo_lbl = tk.Label(self._header, bg="white")
        self._logo_lbl.pack(side=tk.RIGHT, anchor=tk.NE, padx=(8, 0))

        # Tynd grå linje
        self._rule = tk.Frame(inner, bg="#ddd", height=1)
        self._rule.pack(fill=tk.X, pady=(8, 6))

        # Sange (scrollfri — viser kun de første N)
        self._songs_frame = tk.Frame(inner, bg="white")
        self._songs_frame.pack(fill=tk.BOTH, expand=True, anchor=tk.NW)

        # Footer (samlet tid)
        self._total_lbl = tk.Label(
            inner, bg="white", anchor=tk.W, justify=tk.LEFT, fg="#333", text="",
        )
        self._total_lbl.pack(fill=tk.X, side=tk.BOTTOM, pady=(6, 0))

    def _update_preview(self) -> None:
        """Tegn previewet om baseret på de aktuelle valg."""
        if self.model is None:
            return
        try:
            opts = {k: v.get() for k, v in self.opts.items()}
            fs = self.font_size_var.get()
            if fs not in _PREVIEW_SIZES:
                fs = "medium"
            sizes = _PREVIEW_SIZES[fs]
            title = self.title_var.get().strip() or self.model.current_setlist.get("name", "")

            # --- Titel ---
            if opts.get("show_title", True):
                self._title_lbl.configure(
                    text=title or " ",
                    font=("Helvetica", sizes["title"], "bold"),
                )
                self._title_lbl.pack(anchor=tk.W)
            else:
                self._title_lbl.pack_forget()

            # --- Meta ---
            if opts.get("show_meta", True):
                band = self.model.current_band.get("name", "")
                n = self.model.current_setlist_song_count()
                meta_bits = []
                if band:
                    meta_bits.append(band)
                if opts.get("show_date", True):
                    from datetime import datetime
                    meta_bits.append(f"{datetime.now().strftime('%d-%m-%Y')}")
                meta_bits.append(f"{n} sang{'e' if n != 1 else ''}")
                self._meta_lbl.configure(
                    text="  ·  ".join(meta_bits),
                    font=("Helvetica", sizes["meta"]),
                )
                self._meta_lbl.pack(anchor=tk.W, pady=(2, 0))
            else:
                self._meta_lbl.pack_forget()

            # --- Logo ---
            self._update_preview_logo(show=opts["show_logo"])

            # --- Tynd linje under header (skjul hvis ALT i header er skjult) ---
            any_header = (opts.get("show_title", True) or opts.get("show_meta", True)
                          or (opts.get("show_logo", True) and self.model.get_band_logo()))
            if any_header:
                self._rule.pack(fill=tk.X, pady=(8, 6))
            else:
                self._rule.pack_forget()

            # --- Sange + markører (clear + redraw) ---
            for child in self._songs_frame.winfo_children():
                child.destroy()
            self._draw_song_rows(opts, sizes)

            # --- Total ---
            if opts.get("show_total_time", True):
                secs = self.model.current_setlist_seconds()
                self._total_lbl.configure(
                    text=f"Samlet spilletid: {format_seconds(secs)}",
                    font=("Helvetica", sizes["total"], "bold"),
                )
                self._total_lbl.pack(fill=tk.X, side=tk.BOTTOM, pady=(6, 0))
            else:
                self._total_lbl.pack_forget()
        except tk.TclError:
            # Dialogen er muligvis ved at lukke — ignorer
            pass

    def _update_preview_logo(self, show: bool) -> None:
        data = self.model.get_band_logo() if (self.model and show) else ""
        if not data or not HAS_PIL:
            self._preview_logo_photo = None
            self._logo_lbl.configure(image="", text="")
            return
        img = _data_url_to_pil_image(data)
        if img is None:
            self._preview_logo_photo = None
            self._logo_lbl.configure(image="", text="")
            return
        disp = img.copy()
        disp.thumbnail((90, 50), Image.Resampling.LANCZOS)
        self._preview_logo_photo = ImageTk.PhotoImage(disp)
        self._logo_lbl.configure(image=self._preview_logo_photo, text="")

    def _draw_song_rows(self, opts: dict, sizes: dict) -> None:
        items = self.model.current_setlist["songs"]
        if not items:
            tk.Label(
                self._songs_frame, bg="white", fg="#999",
                text="(Ingen sange i setlisten endnu)",
                font=("Helvetica", sizes["table"], "italic"),
            ).pack(anchor=tk.W)
            return

        # Header-række hvis show_table_header er True OG der findes sange
        if opts.get("show_table_header", True):
            header = tk.Frame(self._songs_frame, bg="#f0f0f0")
            header.pack(fill=tk.X, pady=(0, 2))
            tk.Label(
                header, bg="#f0f0f0", fg="#666", text="SANG", anchor=tk.W,
                font=("Helvetica", max(6, sizes["table"] - 2), "bold"),
            ).pack(side=tk.LEFT, padx=(20 if opts["show_number"] else 4, 0))

        max_rows = 10
        shown = items[:max_rows]
        font_norm = ("Helvetica", sizes["table"])
        font_bold = ("Helvetica", sizes["table"], "bold")
        show_markers = opts.get("show_markers", True)

        song_num = 0
        for item in shown:
            # Sektion-markør
            if is_marker_item(item):
                if not show_markers:
                    continue
                label = item_marker_label(item)
                marker_row = tk.Frame(self._songs_frame, bg="#fff7d6", height=2)
                marker_row.pack(fill=tk.X, pady=(2, 2))
                tk.Label(
                    marker_row, bg="#fff7d6", fg="#6b4f00",
                    text=label.upper(), anchor=tk.CENTER,
                    font=("Helvetica", sizes["table"], "bold italic"),
                ).pack(fill=tk.X, padx=2, pady=2)
                continue

            # Almindelig sang
            name = item_song_name(item)
            if not name:
                continue
            song_num += 1
            song = self.model.get_song(name) or new_song(name)
            row = tk.Frame(self._songs_frame, bg="white")
            row.pack(fill=tk.X, pady=1)

            if opts["show_number"]:
                tk.Label(
                    row, bg="white", text=f"{song_num:>2}.", width=3, anchor=tk.E,
                    font=font_norm, fg="#666",
                ).pack(side=tk.LEFT, padx=(0, 6))

            tk.Label(
                row, bg="white", text=song["name"], anchor=tk.W,
                font=font_bold,
            ).pack(side=tk.LEFT, fill=tk.X, expand=True)

            if opts["show_duration"] and song.get("duration"):
                tk.Label(
                    row, bg="white", text=song["duration"], anchor=tk.E,
                    font=font_norm, fg="#555",
                ).pack(side=tk.RIGHT, padx=(4, 0))
            if opts["show_key"] and song.get("key"):
                tk.Label(
                    row, bg="white", text=song["key"], anchor=tk.E,
                    font=font_norm, fg="#555", width=4,
                ).pack(side=tk.RIGHT, padx=(4, 0))

            # Noter — vises som indrykket linje under sangen (kun hvis
            # show_notes er slået til OG sangen rent faktisk har noter).
            if opts.get("show_notes", True) and song.get("notes"):
                indent = 3 + 6 if opts["show_number"] else 0
                notes_text = song["notes"].replace("\n", " · ")
                tk.Label(
                    self._songs_frame, bg="white",
                    text=notes_text, anchor=tk.W, justify=tk.LEFT,
                    font=("Helvetica", sizes["notes"], "italic"),
                    fg="#666", wraplength=320,
                ).pack(fill=tk.X, padx=(indent * 6, 4), pady=(0, 2))

        if len(items) > max_rows:
            tk.Label(
                self._songs_frame, bg="white", fg="#888",
                text=f"…  + {len(items) - max_rows} elementer mere",
                font=("Helvetica", max(7, sizes["table"] - 2), "italic"),
            ).pack(anchor=tk.W, pady=(4, 0))

        # Hint hvis brugeren har slået "Noter" til, men ingen sange har noter
        # (typisk efter import fra MusicBrainz). Så ved de hvorfor de ikke
        # ser noget — og hvordan de tilføjer noter.
        if opts.get("show_notes", True):
            song_items = [it for it in items if not is_marker_item(it)]
            has_any_notes = any(
                (self.model.get_song(item_song_name(it)) or {}).get("notes")
                for it in song_items
            )
            if song_items and not has_any_notes:
                tk.Label(
                    self._songs_frame, bg="white", fg="#b88a00",
                    text="💡  Ingen sange har noter endnu — dobbeltklik en sang "
                         "i setlisten for at tilføje noter (fx 'capo 2', 'A-bro').",
                    font=("Helvetica", max(8, sizes["table"] - 2), "italic"),
                    wraplength=340, justify=tk.LEFT,
                ).pack(anchor=tk.W, pady=(6, 0), padx=2)

    # ------------------------------------------------------------------
    # Collect / OK / browser preview
    # ------------------------------------------------------------------
    def _set_all_opts(self, value: bool) -> None:
        """Slå alle vis/skjul-toggles til eller fra på én gang."""
        for v in self.opts.values():
            v.set(value)

    def _collect(self) -> dict:
        opts = {k: v.get() for k, v in self.opts.items()}
        opts["font_size"] = self.font_size_var.get()
        return {
            "title": self.title_var.get().strip(),
            "options": opts,
        }

    def _ok(self) -> None:
        self.result = self._collect()
        self.destroy()

    def _preview_in_browser(self) -> None:
        """Åbn HTML i browseren med de nuværende indstillinger uden at lukke dialogen."""
        if self.model is None:
            return
        data = self._collect()
        try:
            html = self.model.generate_html(data["title"], data["options"])
        except Exception as e:  # noqa: BLE001
            messagebox.showerror(
                "Fejl", f"Kunne ikke lave forhåndsvisning:\n{e}", parent=self
            )
            return
        try:
            tmp = tempfile.NamedTemporaryFile(
                delete=False, suffix=".html", mode="w", encoding="utf-8"
            )
            tmp.write(html)
            tmp.close()
            webbrowser.open("file://" + os.path.abspath(tmp.name))
        except Exception as e:  # noqa: BLE001
            messagebox.showerror(
                "Fejl", f"Kunne ikke åbne forhåndsvisning:\n{e}", parent=self
            )


# ---------------------------------------------------------------------------
# Søg på tværs af alle bands
# ---------------------------------------------------------------------------
class SearchAllBandsDialog(tk.Toplevel):
    def __init__(self, parent, app: "SetlistApp") -> None:
        super().__init__(parent)
        self.title("Søg sange i alle bands")
        self.transient(parent)
        self.app = app
        self.model = app.model
        self.geometry("760x460")

        frm = ttk.Frame(self, padding=10)
        frm.pack(fill=tk.BOTH, expand=True)

        top = ttk.Frame(frm)
        top.pack(fill=tk.X)
        ttk.Label(top, text="🔍 Søg:").pack(side=tk.LEFT)
        self.query_var = tk.StringVar()
        entry = ttk.Entry(top, textvariable=self.query_var)
        entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(6, 0))
        entry.focus_set()
        self.query_var.trace_add("write", lambda *_: self._refresh())

        cols = ("band", "sang", "toneart", "længde", "noter")
        self.tree = ttk.Treeview(frm, columns=cols, show="headings", selectmode="browse")
        widths = (140, 240, 80, 80, 180)
        for c, w in zip(cols, widths):
            self.tree.heading(c, text=c.capitalize())
            self.tree.column(c, width=w, anchor=tk.W)
        self.tree.pack(fill=tk.BOTH, expand=True, pady=(10, 0))
        self.tree.bind("<Double-1>", lambda e: self._copy())

        ttk.Label(
            frm,
            text="Tip: dobbeltklik en sang fra et andet band for at kopiere den til dit aktive band.",
            foreground="#666",
        ).pack(anchor=tk.W, pady=(6, 0))

        btns = ttk.Frame(frm)
        btns.pack(fill=tk.X, pady=(10, 0))
        ttk.Button(btns, text="Kopiér til aktivt band", command=self._copy).pack(side=tk.LEFT)
        self.count_var = tk.StringVar()
        ttk.Label(btns, textvariable=self.count_var, foreground="#555").pack(side=tk.LEFT, padx=12)
        ttk.Button(btns, text="Luk", command=self.destroy).pack(side=tk.RIGHT)

        self._results: list[tuple[int, int]] = []
        self._refresh()

        self.bind("<Escape>", lambda e: self.destroy())
        _center_on(self, parent)
        self.grab_set()

    def _refresh(self) -> None:
        for item in self.tree.get_children():
            self.tree.delete(item)
        self._results = []
        results = self.model.search_songs(self.query_var.get(), all_bands=True)
        for bi, si, song in results:
            band_name = self.model.bands[bi]["name"]
            tag = "active" if bi == self.model.active_band else "other"
            self.tree.insert(
                "",
                tk.END,
                values=(
                    band_name,
                    song["name"],
                    song.get("key", ""),
                    song.get("duration", ""),
                    (song.get("notes", "") or "").replace("\n", " ⏎ "),
                ),
                tags=(tag,),
            )
            self._results.append((bi, si))
        self.tree.tag_configure("active", background="#eaf3ff")
        self.count_var.set(f"{len(results)} sang(e) fundet")

    def _copy(self) -> None:
        sel = self.tree.selection()
        if not sel:
            return
        idx = self.tree.index(sel[0])
        if idx >= len(self._results):
            return
        bi, si = self._results[idx]
        if bi == self.model.active_band:
            messagebox.showinfo("Info", "Sangen er allerede i dit aktive band.", parent=self)
            return
        song_name = self.model.bands[bi]["library"][si]["name"]
        if self.model.copy_song_to_current_band(bi, si):
            messagebox.showinfo(
                "Kopieret",
                f'"{song_name}" tilføjet til "{self.model.current_band["name"]}".',
                parent=self,
            )
            self.app.refresh_library_view()
            self.app._schedule_autosave()
        else:
            messagebox.showinfo(
                "Info",
                f'"{song_name}" findes allerede i "{self.model.current_band["name"]}".',
                parent=self,
            )


# ---------------------------------------------------------------------------
# Importér sange fra internet (MusicBrainz)
# ---------------------------------------------------------------------------
class ImportFromWebDialog(tk.Toplevel):
    """To-trins dialog: 1) find bandet, 2) vælg sange der skal importeres."""

    def __init__(self, parent, app: "SetlistApp") -> None:
        super().__init__(parent)
        self.title("Importér sange fra internet")
        self.transient(parent)
        self.app = app
        self.model = app.model

        # Tilpas størrelsen til skærmen så bunden (Importér-knappen) altid
        # er synlig — selv på små Windows-VM'er / laptops med lav opløsning.
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        w = min(820, max(640, sw - 100))
        h = min(620, max(480, sh - 120))
        self.geometry(f"{w}x{h}")
        self.minsize(560, 440)
        self.resizable(True, True)

        self._artists: list[dict] = []
        self._tracks: list[dict] = []           # ALLE sange fra MusicBrainz
        self._visible_tracks: list[dict] = []   # Sange efter filter
        self._track_vars: list[tk.BooleanVar] = []
        self._busy = False
        self._artist_name = ""
        self.hide_live_var = tk.BooleanVar(value=True)  # Skjul live-versioner som default

        outer = ttk.Frame(self, padding=12)
        outer.pack(fill=tk.BOTH, expand=True)

        # VIGTIGT: bottom-knapperne (Importér, Vælg alle, ...) pakkes FØRST
        # med side=BOTTOM så de altid er synlige, uanset hvor lille vinduet
        # bliver. Resten af layoutet får så plads ovenover, og sangsliste-
        # boksen skrumper i stedet for at skjule Importér-knappen.
        bottom = ttk.Frame(outer)
        bottom.pack(side=tk.BOTTOM, fill=tk.X, pady=(10, 0))
        self.status_var = tk.StringVar(value="")
        ttk.Label(bottom, textvariable=self.status_var, foreground="#555").pack(side=tk.LEFT)
        self.import_btn = ttk.Button(
            bottom, text="Importér valgte sange  ✓", command=self._do_import, state=tk.DISABLED
        )
        self.import_btn.pack(side=tk.RIGHT)
        self.select_none_btn = ttk.Button(
            bottom, text="Vælg ingen", command=lambda: self._set_all_tracks(False), state=tk.DISABLED
        )
        self.select_none_btn.pack(side=tk.RIGHT, padx=(0, 4))
        self.select_all_btn = ttk.Button(
            bottom, text="Vælg alle", command=lambda: self._set_all_tracks(True), state=tk.DISABLED
        )
        self.select_all_btn.pack(side=tk.RIGHT, padx=(0, 4))

        # --- Trin 1: Søg ---
        ttk.Label(
            outer,
            text=f"Find sange til \"{self.model.current_band['name']}\"",
            font=("TkDefaultFont", 11, "bold"),
        ).pack(anchor=tk.W)
        ttk.Label(
            outer,
            text="Skriv bandets navn og tryk Enter. Sangene hentes fra MusicBrainz — verdens største frie musikdatabase.",
            foreground="#555",
            wraplength=780,
            justify=tk.LEFT,
        ).pack(anchor=tk.W, pady=(2, 8))

        search_row = ttk.Frame(outer)
        search_row.pack(fill=tk.X)
        ttk.Label(search_row, text="🎸 Band:").pack(side=tk.LEFT)
        self.query_var = tk.StringVar(value=self.model.current_band["name"])
        self.query_entry = ttk.Entry(search_row, textvariable=self.query_var)
        self.query_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(6, 6))
        self.query_entry.bind("<Return>", lambda e: self._do_search_artists())
        self.search_btn = ttk.Button(search_row, text="Søg", command=self._do_search_artists)
        self.search_btn.pack(side=tk.LEFT)

        # --- Trin 2: Vælg band ---
        ttk.Label(
            outer,
            text="1. Vælg det rigtige band (dobbeltklik for at hente sange):",
            font=("TkDefaultFont", 10, "bold"),
        ).pack(anchor=tk.W, pady=(12, 4))

        art_frame = ttk.Frame(outer)
        art_frame.pack(fill=tk.X)
        art_cols = ("navn", "land", "type", "info", "match")
        self.artist_tree = ttk.Treeview(
            art_frame, columns=art_cols, show="headings", height=6, selectmode="browse"
        )
        widths = (200, 60, 90, 360, 60)
        for c, w in zip(art_cols, widths):
            self.artist_tree.heading(c, text=c.capitalize())
            self.artist_tree.column(c, width=w, anchor=tk.W)
        self.artist_tree.pack(side=tk.LEFT, fill=tk.X, expand=True)
        scroll1 = ttk.Scrollbar(art_frame, orient=tk.VERTICAL, command=self.artist_tree.yview)
        scroll1.pack(side=tk.RIGHT, fill=tk.Y)
        self.artist_tree.config(yscrollcommand=scroll1.set)
        self.artist_tree.bind("<Double-1>", lambda e: self._do_fetch_tracks())

        self.fetch_btn = ttk.Button(
            outer, text="Hent sange for valgt band  ↓", command=self._do_fetch_tracks
        )
        self.fetch_btn.pack(anchor=tk.W, pady=(4, 0))

        # --- Trin 3: Vælg sange ---
        track_header = ttk.Frame(outer)
        track_header.pack(fill=tk.X, pady=(12, 4))
        ttk.Label(
            track_header,
            text="2. Vælg sange der skal importeres:",
            font=("TkDefaultFont", 10, "bold"),
        ).pack(side=tk.LEFT)
        ttk.Checkbutton(
            track_header,
            text="✂️  Skjul live-versioner",
            variable=self.hide_live_var,
            command=self._rebuild_track_list,
        ).pack(side=tk.RIGHT)

        tracks_box = ttk.Frame(outer)
        tracks_box.pack(fill=tk.BOTH, expand=True)
        self.tracks_canvas = tk.Canvas(tracks_box, highlightthickness=0, borderwidth=1, relief=tk.SOLID)
        self.tracks_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll2 = ttk.Scrollbar(tracks_box, orient=tk.VERTICAL, command=self.tracks_canvas.yview)
        scroll2.pack(side=tk.RIGHT, fill=tk.Y)
        self.tracks_canvas.configure(yscrollcommand=scroll2.set)
        self.tracks_inner = ttk.Frame(self.tracks_canvas)
        self.tracks_window = self.tracks_canvas.create_window(
            (0, 0), window=self.tracks_inner, anchor=tk.NW
        )
        self.tracks_inner.bind(
            "<Configure>",
            lambda e: self.tracks_canvas.configure(scrollregion=self.tracks_canvas.bbox("all")),
        )
        self.tracks_canvas.bind(
            "<Configure>",
            lambda e: self.tracks_canvas.itemconfig(self.tracks_window, width=e.width),
        )
        self.tracks_canvas.bind_all("<MouseWheel>", self._on_mousewheel)
        self.tracks_canvas.bind_all("<Button-4>", lambda e: self.tracks_canvas.yview_scroll(-3, "units"))
        self.tracks_canvas.bind_all("<Button-5>", lambda e: self.tracks_canvas.yview_scroll(3, "units"))

        self.bind("<Escape>", lambda e: self._on_close())
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        _center_on(self, parent)
        self.query_entry.focus_set()
        self.query_entry.select_range(0, tk.END)

    def _on_mousewheel(self, event) -> None:
        # Windows / macOS - delta er multiplum af 120 / småværdier
        delta = -1 if event.delta > 0 else 1
        self.tracks_canvas.yview_scroll(delta * 3, "units")

    def _on_close(self) -> None:
        # Frigør global mousewheel-binding
        try:
            self.tracks_canvas.unbind_all("<MouseWheel>")
            self.tracks_canvas.unbind_all("<Button-4>")
            self.tracks_canvas.unbind_all("<Button-5>")
        except tk.TclError:
            pass
        self.destroy()

    # ------------------------------------------------------------------
    # Trin 1: søg efter bands
    # ------------------------------------------------------------------
    def _do_search_artists(self) -> None:
        if self._busy:
            return
        name = self.query_var.get().strip()
        if not name:
            messagebox.showinfo("Info", "Skriv et bandnavn først.", parent=self)
            return
        self._busy = True
        self.search_btn.config(state=tk.DISABLED)
        self.fetch_btn.config(state=tk.DISABLED)
        self.status_var.set(f"Søger efter \"{name}\"…")
        self._clear_artists()
        self._clear_tracks()

        def worker():
            try:
                artists = music_search.search_artists(name)
                self.after(0, self._on_artists_result, artists, None)
            except music_search.MusicSearchError as e:
                self.after(0, self._on_artists_result, [], str(e))
            except Exception as e:  # noqa: BLE001
                self.after(0, self._on_artists_result, [], f"Uventet fejl: {e}")

        threading.Thread(target=worker, daemon=True).start()

    def _on_artists_result(self, artists: list, error: str | None) -> None:
        self._busy = False
        self.search_btn.config(state=tk.NORMAL)
        if error:
            self.status_var.set("")
            messagebox.showerror("Søgning fejlede", error, parent=self)
            return
        self._artists = artists
        if not artists:
            self.status_var.set("Ingen bands fundet. Prøv at stave anderledes.")
            return
        for a in artists:
            self.artist_tree.insert(
                "",
                tk.END,
                values=(
                    a.get("name", ""),
                    a.get("country", ""),
                    a.get("type", ""),
                    a.get("disambiguation", ""),
                    a.get("score", 0),
                ),
            )
        # Marker første automatisk
        children = self.artist_tree.get_children()
        if children:
            self.artist_tree.selection_set(children[0])
            self.artist_tree.focus(children[0])
        self.fetch_btn.config(state=tk.NORMAL)
        self.status_var.set(
            f"{len(artists)} band(e) fundet. Vælg det rigtige og tryk \"Hent sange\"."
        )

    # ------------------------------------------------------------------
    # Trin 2: hent sange for valgt band
    # ------------------------------------------------------------------
    def _do_fetch_tracks(self) -> None:
        if self._busy:
            return
        sel = self.artist_tree.selection()
        if not sel:
            messagebox.showinfo("Info", "Vælg et band fra listen først.", parent=self)
            return
        idx = self.artist_tree.index(sel[0])
        if idx < 0 or idx >= len(self._artists):
            return
        artist = self._artists[idx]
        mbid = artist.get("id")
        if not mbid:
            return

        self._busy = True
        self.search_btn.config(state=tk.DISABLED)
        self.fetch_btn.config(state=tk.DISABLED)
        self.import_btn.config(state=tk.DISABLED)
        self.select_all_btn.config(state=tk.DISABLED)
        self.select_none_btn.config(state=tk.DISABLED)
        self.status_var.set(f"Henter sange for \"{artist['name']}\" … (kan tage 5-30 sek)")
        self._clear_tracks()

        def progress(fetched: int, total: int) -> None:
            self.after(0, lambda: self.status_var.set(
                f"Henter sange … {min(fetched, total)} / {total}"
            ))

        def worker():
            try:
                tracks = music_search.fetch_recordings(mbid, progress_callback=progress)
                self.after(0, self._on_tracks_result, tracks, artist["name"], None)
            except music_search.MusicSearchError as e:
                self.after(0, self._on_tracks_result, [], artist["name"], str(e))
            except Exception as e:  # noqa: BLE001
                self.after(0, self._on_tracks_result, [], artist["name"], f"Uventet fejl: {e}")

        threading.Thread(target=worker, daemon=True).start()

    def _on_tracks_result(self, tracks: list, artist_name: str, error: str | None) -> None:
        self._busy = False
        self.search_btn.config(state=tk.NORMAL)
        self.fetch_btn.config(state=tk.NORMAL)
        if error:
            self.status_var.set("")
            messagebox.showerror("Hentning fejlede", error, parent=self)
            return
        self._tracks = tracks
        self._artist_name = artist_name
        if not tracks:
            self.status_var.set("Ingen sange fundet for dette band.")
            return
        self._rebuild_track_list()

    def _rebuild_track_list(self) -> None:
        """Bygger sang-listen op igen ud fra de hentede tracks og det aktuelle live-filter.
        Kaldes både efter hentning og når brugeren toggler 'Skjul live-versioner'."""
        # Ryd nuværende UI-rækker (men behold rådata i self._tracks)
        for child in self.tracks_inner.winfo_children():
            child.destroy()
        self._track_vars = []

        # Anvend filter
        hide_live = self.hide_live_var.get()
        if hide_live:
            self._visible_tracks = music_search.filter_out_live(self._tracks)
        else:
            self._visible_tracks = list(self._tracks)

        existing = {n.casefold() for n in self.model.song_names()}
        new_count = 0

        for t in self._visible_tracks:
            row = ttk.Frame(self.tracks_inner)
            row.pack(fill=tk.X, padx=4, pady=1)
            already_have = t["title"].casefold() in existing
            var = tk.BooleanVar(value=not already_have)
            self._track_vars.append(var)
            if not already_have:
                new_count += 1

            cb = ttk.Checkbutton(row, variable=var)
            cb.pack(side=tk.LEFT)
            dur = t["duration"] or "—:—"
            label_text = f"{t['title']}   ({dur})"
            if already_have:
                label_text += "    [findes allerede]"
            label = ttk.Label(
                row,
                text=label_text,
                foreground=("#888" if already_have else "#000"),
            )
            label.pack(side=tk.LEFT, padx=(4, 0))

        # Scroll til toppen efter genopbygning
        self.tracks_canvas.yview_moveto(0)

        # Aktivér knapperne hvis vi har noget at vise
        if self._visible_tracks:
            self.import_btn.config(state=tk.NORMAL)
            self.select_all_btn.config(state=tk.NORMAL)
            self.select_none_btn.config(state=tk.NORMAL)
        else:
            self.import_btn.config(state=tk.DISABLED)
            self.select_all_btn.config(state=tk.DISABLED)
            self.select_none_btn.config(state=tk.DISABLED)

        # Statusbar
        total_all = len(self._tracks)
        total_shown = len(self._visible_tracks)
        hidden = total_all - total_shown
        parts = [
            f'{total_shown} sange vises for "{self._artist_name}"',
            f"{new_count} nye, {total_shown - new_count} har du allerede",
        ]
        if hidden > 0:
            parts.append(f"{hidden} live-version(er) skjult")
        self.status_var.set("  ·  ".join(parts))

    def _set_all_tracks(self, value: bool) -> None:
        for v in self._track_vars:
            v.set(value)

    # ------------------------------------------------------------------
    # Trin 3: importér
    # ------------------------------------------------------------------
    def _do_import(self) -> None:
        added = 0
        skipped = 0
        for t, v in zip(self._visible_tracks, self._track_vars):
            if not v.get():
                continue
            if self.model.add_song(t["title"], duration=t["duration"] or ""):
                added += 1
            else:
                skipped += 1
        if added:
            self.app.refresh_library_view()
            self.app._schedule_autosave()
        messagebox.showinfo(
            "Færdig",
            f"{added} ny(e) sang(e) tilføjet til \"{self.model.current_band['name']}\".\n"
            f"{skipped} sang(e) var allerede i biblioteket.",
            parent=self,
        )
        self._on_close()

    # ------------------------------------------------------------------
    def _clear_artists(self) -> None:
        for item in self.artist_tree.get_children():
            self.artist_tree.delete(item)
        self._artists = []

    def _clear_tracks(self) -> None:
        for child in self.tracks_inner.winfo_children():
            child.destroy()
        self._tracks = []
        self._visible_tracks = []
        self._track_vars = []
        self.import_btn.config(state=tk.DISABLED)
        self.select_all_btn.config(state=tk.DISABLED)
        self.select_none_btn.config(state=tk.DISABLED)


# ---------------------------------------------------------------------------
# Logo-dialog (vælg / vis / fjern logo for det aktive band)
# ---------------------------------------------------------------------------
def _data_url_to_pil_image(data_url: str):
    """Konverter en data-URL til et PIL Image. Returnerer None ved fejl."""
    if not HAS_PIL or not data_url:
        return None
    try:
        if "," in data_url:
            _, b64 = data_url.split(",", 1)
        else:
            b64 = data_url
        raw = base64.b64decode(b64)
        return Image.open(io.BytesIO(raw))
    except Exception:  # noqa: BLE001
        return None


def _pil_image_to_data_url(img, max_size: int = 600) -> str:
    """Konverter et PIL Image til PNG-data-URL. Skalerer ned hvis nødvendigt."""
    img = img.copy()
    # Konverter til RGBA for at undgå JPEG-mode-problemer
    if img.mode not in ("RGB", "RGBA", "L"):
        img = img.convert("RGBA")
    img.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/png;base64,{b64}"


class LogoDialog(tk.Toplevel):
    """Lille dialog hvor man kan vælge/se/fjerne logo for det aktive band."""

    def __init__(self, parent, app: "SetlistApp") -> None:
        super().__init__(parent)
        self.title(f"Logo for \"{app.model.current_band['name']}\"")
        self.transient(parent)
        self.app = app
        self.model = app.model
        self.resizable(False, False)

        self._preview_photo = None  # MÅ ikke garbage-collectes

        frm = ttk.Frame(self, padding=14)
        frm.pack(fill=tk.BOTH, expand=True)

        if not HAS_PIL:
            ttk.Label(
                frm,
                text="Pillow er ikke installeret.\nKør build_windows.bat for at installere det.",
                foreground="#c00",
            ).pack()
            ttk.Button(frm, text="Luk", command=self.destroy).pack(pady=(10, 0))
            _center_on(self, parent)
            self.grab_set()
            return

        ttk.Label(
            frm,
            text=f"Logoet vises i øverste højre hjørne, når du printer setlisten.",
            wraplength=360,
            foreground="#555",
        ).pack(anchor=tk.W, pady=(0, 10))

        self.preview_label = ttk.Label(
            frm,
            text="(Intet logo valgt)",
            anchor=tk.CENTER,
            relief=tk.SOLID,
            borderwidth=1,
            padding=8,
            width=32,
        )
        self.preview_label.pack(pady=(0, 10))

        btns = ttk.Frame(frm)
        btns.pack(fill=tk.X)
        ttk.Button(btns, text="Vælg billede…", command=self._choose_file).pack(
            side=tk.LEFT
        )
        self.remove_btn = ttk.Button(btns, text="Fjern logo", command=self._remove)
        self.remove_btn.pack(side=tk.LEFT, padx=(6, 0))
        ttk.Button(btns, text="Luk", command=self.destroy).pack(side=tk.RIGHT)

        self._refresh_preview()
        self.bind("<Escape>", lambda e: self.destroy())
        _center_on(self, parent)
        self.grab_set()

    def _refresh_preview(self) -> None:
        data = self.model.get_band_logo()
        img = _data_url_to_pil_image(data)
        if img is None:
            self.preview_label.config(image="", text="(Intet logo valgt)", width=32)
            self._preview_photo = None
            self.remove_btn.config(state=tk.DISABLED)
        else:
            disp = img.copy()
            disp.thumbnail((260, 160), Image.Resampling.LANCZOS)
            self._preview_photo = ImageTk.PhotoImage(disp)
            self.preview_label.config(image=self._preview_photo, text="", width=0)
            self.remove_btn.config(state=tk.NORMAL)

    def _choose_file(self) -> None:
        path = filedialog.askopenfilename(
            parent=self,
            title="Vælg logo",
            filetypes=[
                ("Billedfiler", "*.png *.jpg *.jpeg *.gif *.bmp *.webp"),
                ("Alle filer", "*.*"),
            ],
        )
        if not path:
            return
        try:
            img = Image.open(path)
            data_url = _pil_image_to_data_url(img)
        except Exception as e:  # noqa: BLE001
            messagebox.showerror(
                "Fejl", f"Kunne ikke læse billedet:\n{e}", parent=self
            )
            return
        self.model.set_band_logo(data_url)
        self.app._schedule_autosave()
        self._refresh_preview()

    def _remove(self) -> None:
        if not self.model.get_band_logo():
            return
        if messagebox.askyesno(
            "Fjern logo",
            f"Fjern logoet for \"{self.model.current_band['name']}\"?",
            parent=self,
        ):
            self.model.clear_band_logo()
            self.app._schedule_autosave()
            self._refresh_preview()


# ---------------------------------------------------------------------------
# Opdaterings-dialog (når der findes en nyere version)
# ---------------------------------------------------------------------------
class UpdateDialog(tk.Toplevel):
    """Dialog der vises når updater har fundet en nyere version.

    Tre stadier:
      1. Spørg (vis release-noter + knapper Spring over / Senere / Download)
      2. Downloader (vis progress bar)
      3. Klar (vis "Installer nu" — kører installeren og lukker programmet)
    """

    def __init__(self, parent, info: "updater.UpdateInfo", app: "SetlistApp | None" = None) -> None:
        super().__init__(parent)
        self.title("Ny version af Setlist Manager")
        self.transient(parent)
        self.resizable(False, False)
        self.info = info
        self.app = app
        self.installer_path: Path | None = None
        self._download_thread = None
        self._cancelled = False

        frm = ttk.Frame(self, padding=16)
        frm.pack(fill=tk.BOTH, expand=True)
        self._frm = frm

        ttk.Label(
            frm,
            text=f"🎉  Der er en ny version!",
            font=("TkDefaultFont", 13, "bold"),
        ).grid(row=0, column=0, columnspan=2, sticky=tk.W)

        ttk.Label(
            frm,
            text=f"Din version:    {info.current}",
            foreground="#555",
        ).grid(row=1, column=0, columnspan=2, sticky=tk.W, pady=(8, 0))
        ttk.Label(
            frm,
            text=f"Nyeste version: {info.latest}",
            font=("TkDefaultFont", 10, "bold"),
            foreground="#0a7d2c",
        ).grid(row=2, column=0, columnspan=2, sticky=tk.W)

        # Release-noter (max 12 linjer, scrollbart)
        if info.body:
            ttk.Label(
                frm, text="Hvad er nyt:", font=("TkDefaultFont", 10, "bold"),
            ).grid(row=3, column=0, columnspan=2, sticky=tk.W, pady=(12, 4))
            notes_frame = ttk.Frame(frm)
            notes_frame.grid(row=4, column=0, columnspan=2, sticky=tk.W + tk.E)
            scrollbar = ttk.Scrollbar(notes_frame, orient=tk.VERTICAL)
            scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
            txt = tk.Text(
                notes_frame, width=58, height=10, wrap=tk.WORD,
                yscrollcommand=scrollbar.set, font=("TkDefaultFont", 9),
                background="#f7f7f7", relief=tk.FLAT, padx=8, pady=6,
            )
            txt.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
            scrollbar.config(command=txt.yview)
            txt.insert("1.0", info.body)
            txt.configure(state=tk.DISABLED)

        # --- Status (skjult indtil download starter) ---
        self.status_var = tk.StringVar(value="")
        self.status_lbl = ttk.Label(
            frm, textvariable=self.status_var, foreground="#555",
            font=("TkDefaultFont", 9),
        )
        # Pakkes først når download starter

        # --- Progress bar (skjult indtil download starter) ---
        self.progress = ttk.Progressbar(
            frm, mode="determinate", length=520, maximum=100,
        )
        # Pakkes først når download starter

        # --- Knap-række ---
        self.btns = ttk.Frame(frm)
        self.btns.grid(row=7, column=0, columnspan=2, sticky=tk.E + tk.W, pady=(14, 0))

        self.skip_btn = ttk.Button(
            self.btns, text="Spring denne over",
            command=self._skip,
        )
        self.skip_btn.pack(side=tk.LEFT)
        self.later_btn = ttk.Button(
            self.btns, text="Senere",
            command=self.destroy,
        )
        self.later_btn.pack(side=tk.RIGHT, padx=(6, 0))
        self.action_btn = ttk.Button(
            self.btns, text="⬇  Download og installer",
            command=self._start_download,
        )
        self.action_btn.pack(side=tk.RIGHT)

        # Lille link til release-siden som "manuel fallback"
        self.browser_link = ttk.Label(
            frm, text="(eller åbn release-siden i browser)",
            foreground="#0066cc", cursor="hand2", font=("TkDefaultFont", 8, "underline"),
        )
        self.browser_link.grid(row=8, column=0, columnspan=2, sticky=tk.W, pady=(8, 0))
        self.browser_link.bind("<Button-1>", lambda e: self._open_in_browser())

        self.bind("<Escape>", lambda e: self._on_close())
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        _center_on(self, parent)
        self.grab_set()

    # ------------------------------------------------------------------
    # Stadie 1 → 2: Start download i baggrundstråd
    # ------------------------------------------------------------------
    def _start_download(self) -> None:
        url = self.info.installer_url
        if not url:
            # Ingen installer-asset — fallback til browser
            messagebox.showinfo(
                "Ingen installer",
                "Denne version har ingen direkte installer-fil. "
                "Åbner release-siden i browseren i stedet.",
                parent=self,
            )
            self._open_in_browser()
            self.destroy()
            return

        # Vis status + progress
        self.status_lbl.grid(row=5, column=0, columnspan=2, sticky=tk.W, pady=(12, 2))
        self.progress.grid(row=6, column=0, columnspan=2, sticky=tk.W + tk.E)
        self.status_var.set("Forbereder download…")
        self.progress["value"] = 0

        # Skjul Spring over, ændre knapper
        self.skip_btn.pack_forget()
        self.action_btn.configure(text="⏸  Afbryd", command=self._cancel_download)
        self.later_btn.pack_forget()

        # Filplacering
        filename = updater.installer_filename_from_url(url)
        self.installer_path = updater.default_download_dir() / filename

        # Start download i baggrundstråd
        import threading
        self._cancelled = False
        self._download_thread = threading.Thread(
            target=self._download_worker, args=(url, self.installer_path),
            daemon=True, name="download-installer",
        )
        self._download_thread.start()

    def _download_worker(self, url: str, dest: Path) -> None:
        """Kører i baggrundstråden — må IKKE røre Tkinter direkte."""
        ok = updater.download_file(url, dest, progress_callback=self._on_progress)
        # Resultat tilbage til main-tråden
        if self._cancelled:
            return  # ignorer hvis brugeren afbrød
        self.after(0, lambda: self._on_download_done(ok))

    def _on_progress(self, downloaded: int, total: int) -> None:
        """Kaldes fra baggrundstråd — marshal til main-tråd via after()."""
        if self._cancelled:
            return
        self.after(0, lambda: self._update_progress(downloaded, total))

    def _update_progress(self, downloaded: int, total: int) -> None:
        try:
            if total > 0:
                pct = (downloaded / total) * 100
                self.progress["value"] = pct
                self.status_var.set(
                    f"Henter… {_format_mb(downloaded)} / {_format_mb(total)} "
                    f"({pct:.0f}%)"
                )
            else:
                # Ukendt total
                self.progress.configure(mode="indeterminate")
                self.progress.start(20)
                self.status_var.set(f"Henter… {_format_mb(downloaded)}")
        except tk.TclError:
            pass  # dialogen lukket

    def _cancel_download(self) -> None:
        """Brugeren trykkede Afbryd. Vi sætter et flag; download-tråden
        kører videre lidt endnu, men ignorerer resultatet."""
        self._cancelled = True
        # Ryd partial fil hvis den findes
        if self.installer_path:
            partial = self.installer_path.with_suffix(self.installer_path.suffix + ".partial")
            if partial.exists():
                try:
                    partial.unlink()
                except OSError:
                    pass
        self.destroy()

    # ------------------------------------------------------------------
    # Stadie 2 → 3: Download færdig
    # ------------------------------------------------------------------
    def _on_download_done(self, ok: bool) -> None:
        try:
            self.progress.stop()
            self.progress.configure(mode="determinate")
        except tk.TclError:
            pass

        if not ok:
            err = getattr(updater, "last_error", "") or "ukendt fejl"
            if messagebox.askyesno(
                "Download fejlede",
                f"Kunne ikke hente installeren.\n\nDetalje: {err}\n\n"
                "Vil du åbne release-siden i din browser i stedet?",
                parent=self,
            ):
                self._open_in_browser()
            self.destroy()
            return

        # Success! Skift knap til "Installer nu"
        try:
            self.progress["value"] = 100
            size_mb = _format_mb(self.installer_path.stat().st_size) if self.installer_path else ""
            self.status_var.set(f"✅ Download færdig ({size_mb}) — klar til installation")
            self.action_btn.configure(
                text="🚀  Installer nu (lukker programmet)",
                command=self._launch_installer,
            )
            # Vis 'Senere' igen så brugeren kan vente med at installere
            self.later_btn.pack(side=tk.RIGHT, padx=(6, 0))
        except tk.TclError:
            pass

    # ------------------------------------------------------------------
    # Stadie 3: Start installer + luk programmet
    # ------------------------------------------------------------------
    def _launch_installer(self) -> None:
        if not self.installer_path or not self.installer_path.exists():
            messagebox.showerror(
                "Fejl", "Installations-filen findes ikke længere.", parent=self,
            )
            return

        # Bekræft + forklar flow
        if not messagebox.askyesno(
            "Installer ny version",
            "Sådan kører det:\n\n"
            "1. Programmet lukker nu\n"
            "2. Installeren åbner — klik 'Næste' / 'Installér'\n"
            "3. Windows beder evt. om tilladelse (klik 'Ja')\n"
            "4. Til sidst kan du sætte flueben i\n"
            "   '✔ Start Setlist Manager' så åbner den nye version\n\n"
            "Dine sange og setlister er automatisk gemt — de er der\n"
            "stadig når du åbner programmet igen.\n\n"
            "Klar?",
            parent=self,
        ):
            return

        # Gem en sidste gang for en sikkerheds skyld
        if self.app is not None:
            try:
                self.app.model.autosave()
            except Exception:  # noqa: BLE001
                pass

        # Start installeren (IKKE silent — brugeren ser wizarden)
        ok = updater.launch_installer(self.installer_path, silent=False)
        if not ok:
            err = getattr(updater, "last_error", "") or "ukendt fejl"
            messagebox.showerror(
                "Fejl ved start af installer",
                f"Kunne ikke starte installeren.\n\n"
                f"Detalje: {err}\n\n"
                f"Filen ligger her — du kan dobbeltklikke den manuelt:\n"
                f"{self.installer_path}",
                parent=self,
            )
            return

        # Luk programmet så installeren kan overskrive filerne.
        # VIGTIGT: vi giver installeren et øjeblik til at starte op FØR vi
        # dræber processen — så installer-vinduet er klart synligt for
        # brugeren før vores main-vindue forsvinder. Det giver også
        # PyInstaller's _MEI temp-mappe tid til at blive ryddet op pænt.
        self.destroy()
        if self.app is not None:
            try:
                # 1.5 sekund — nok til at installer-wizarden er fuldt åben
                self.app.root.after(1500, self.app.root.destroy)
            except Exception:  # noqa: BLE001
                self.app.root.destroy()

    # ------------------------------------------------------------------
    # Backup-handlinger
    # ------------------------------------------------------------------
    def _open_in_browser(self) -> None:
        url = self.info.release_url or self.info.installer_url
        if url:
            try:
                webbrowser.open(url)
            except Exception:  # noqa: BLE001
                pass

    def _skip(self) -> None:
        try:
            updater.mark_skipped(self.info.latest)
        except Exception:  # noqa: BLE001
            pass
        self.destroy()

    def _on_close(self) -> None:
        """Lukker dialogen — afbryder evt. download."""
        if self._download_thread is not None and self._download_thread.is_alive():
            self._cancelled = True
        self.destroy()


def _format_mb(b: int) -> str:
    """Formatér bytes som MB med én decimal."""
    if b < 0:
        return "?"
    return f"{b / (1024 * 1024):.1f} MB"


# ---------------------------------------------------------------------------
# Main application
# ---------------------------------------------------------------------------
class SetlistApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        root.title(APP_TITLE)
        root.geometry("1080x680")
        root.minsize(860, 540)

        self.model = SetlistModel()
        self._autosave_job: str | None = None
        self._drag_index: int | None = None

        self._build_menu()
        self._build_top_bar()
        self._build_main_area()
        self._build_bottom_bar()

        if not self.model.load_autosave_if_exists():
            self._load_sample()

        self.refresh_all()
        root.protocol("WM_DELETE_WINDOW", self._on_close)

        # Tjek for opdateringer i baggrunden (lidt efter GUI er klar)
        self.root.after(UPDATE_CHECK_DELAY_MS, self._maybe_auto_check_update)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------
    def _build_menu(self) -> None:
        menubar = tk.Menu(self.root)

        m_file = tk.Menu(menubar, tearoff=0)
        m_file.add_command(label="Gem som…", accelerator="Ctrl+S", command=self.save_as)
        m_file.add_command(label="Åbn…", accelerator="Ctrl+O", command=self.load_from)
        m_file.add_separator()
        m_file.add_command(label="Print A4…", accelerator="Ctrl+P", command=self.export_print)
        m_file.add_separator()
        m_file.add_command(label="Afslut", command=self._on_close)
        menubar.add_cascade(label="Filer", menu=m_file)

        m_band = tk.Menu(menubar, tearoff=0)
        m_band.add_command(label="Nyt band…", command=self.add_band)
        m_band.add_command(label="Omdøb dette band…", command=self.rename_band)
        m_band.add_command(label="Slet dette band…", command=self.delete_band)
        m_band.add_separator()
        m_band.add_command(label="🔍 Søg sange i alle bands…", command=self.open_search_all_bands)
        menubar.add_cascade(label="Bands", menu=m_band)

        # NYT: Live-menu for performance-features
        m_live = tk.Menu(menubar, tearoff=0)
        m_live.add_command(
            label="🎬 Start Stage Mode (fuldskærm)",
            accelerator="F5",
            command=self.open_stage_mode,
        )
        m_live.add_command(
            label="🪟 Start Stage Mode (i vindue)",
            accelerator="F6",
            command=self.open_stage_mode_window,
        )
        m_live.add_separator()
        m_live.add_command(
            label="💡 Tip: tryk F i Stage Mode for at skifte mellem fuldskærm/vindue",
            state=tk.DISABLED,
        )
        menubar.add_cascade(label="Live", menu=m_live)

        m_help = tk.Menu(menubar, tearoff=0)
        m_help.add_command(
            label="🔄 Søg efter opdateringer…",
            command=self.check_for_updates_manual,
        )
        m_help.add_separator()
        m_help.add_command(label="Om Setlist Manager", command=self._show_about)
        menubar.add_cascade(label="Hjælp", menu=m_help)

        self.root.config(menu=menubar)
        self.root.bind("<Control-s>", lambda e: self.save_as())
        self.root.bind("<Control-o>", lambda e: self.load_from())
        self.root.bind("<Control-p>", lambda e: self.export_print())
        self.root.bind("<Control-f>", lambda e: self._focus_search())
        self.root.bind("<F5>", lambda e: self.open_stage_mode())
        self.root.bind("<F6>", lambda e: self.open_stage_mode_window())

    def _build_top_bar(self) -> None:
        wrap = ttk.Frame(self.root, padding=(8, 6, 8, 2))
        wrap.pack(side=tk.TOP, fill=tk.X)

        # Row 1: Band
        row1 = ttk.Frame(wrap)
        row1.pack(fill=tk.X)
        ttk.Label(row1, text="🎸 Band:", width=10).pack(side=tk.LEFT)
        self.band_var = tk.StringVar()
        self.band_combo = ttk.Combobox(
            row1, textvariable=self.band_var, state="readonly", width=28
        )
        self.band_combo.pack(side=tk.LEFT, padx=(0, 6))
        self.band_combo.bind("<<ComboboxSelected>>", self._on_band_changed)
        ttk.Button(row1, text="Nyt band", command=self.add_band).pack(side=tk.LEFT, padx=2)
        ttk.Button(row1, text="Omdøb", command=self.rename_band).pack(side=tk.LEFT, padx=2)
        ttk.Button(row1, text="Slet", command=self.delete_band).pack(side=tk.LEFT, padx=2)
        ttk.Button(row1, text="🖼️ Logo…", command=self.open_logo_dialog).pack(
            side=tk.LEFT, padx=2
        )
        ttk.Button(
            row1,
            text="🔍 Søg i alle bands…",
            command=self.open_search_all_bands,
        ).pack(side=tk.LEFT, padx=(16, 2))

        # Row 2: Setlist
        row2 = ttk.Frame(wrap)
        row2.pack(fill=tk.X, pady=(4, 0))
        ttk.Label(row2, text="📋 Setliste:", width=10).pack(side=tk.LEFT)
        self.setlist_var = tk.StringVar()
        self.setlist_combo = ttk.Combobox(
            row2, textvariable=self.setlist_var, state="readonly", width=28
        )
        self.setlist_combo.pack(side=tk.LEFT, padx=(0, 6))
        self.setlist_combo.bind("<<ComboboxSelected>>", self._on_setlist_changed)
        ttk.Button(row2, text="Ny setliste", command=self.add_setlist).pack(side=tk.LEFT, padx=2)
        ttk.Button(row2, text="📋 Kopiér", command=self.duplicate_setlist).pack(side=tk.LEFT, padx=2)
        ttk.Button(row2, text="Omdøb", command=self.rename_setlist).pack(side=tk.LEFT, padx=2)
        ttk.Button(row2, text="Slet", command=self.delete_setlist).pack(side=tk.LEFT, padx=2)

        # Stage Mode-knapper til højre — accent-styled så de er let at se
        # Hovedknap = fuldskærm (mest brugt på scenen)
        # Lille knap ved siden af = vindue-mode (godt til at øve)
        ttk.Button(
            row2, text="🪟  Vindue",
            style="Subtle.TButton",
            command=self.open_stage_mode_window,
        ).pack(side=tk.RIGHT, padx=(2, 0))
        ttk.Button(
            row2, text="🎬  Stage Mode",
            style="Accent.TButton",
            command=self.open_stage_mode,
        ).pack(side=tk.RIGHT)

        self.status_var = tk.StringVar(value="")
        ttk.Label(
            row2, textvariable=self.status_var, style="Secondary.TLabel",
        ).pack(side=tk.RIGHT, padx=(0, 12))

    def _build_main_area(self) -> None:
        main = ttk.Frame(self.root, padding=8)
        main.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        # ---------- Library (left) ----------
        left = ttk.LabelFrame(main, text="Sangbibliotek", padding=6)
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 4))

        search_row = ttk.Frame(left)
        search_row.pack(fill=tk.X, pady=(0, 4))
        ttk.Label(search_row, text="🔍").pack(side=tk.LEFT)
        self.lib_search_var = tk.StringVar()
        self.lib_search_entry = ttk.Entry(search_row, textvariable=self.lib_search_var)
        self.lib_search_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(4, 2))
        self.lib_search_var.trace_add("write", lambda *_: self.refresh_library_view())
        ttk.Button(
            search_row,
            text="✕",
            width=3,
            command=lambda: self.lib_search_var.set(""),
        ).pack(side=tk.LEFT)

        cols = ("navn", "toneart", "længde")
        self.lib_tree = ttk.Treeview(left, columns=cols, show="headings", selectmode="extended")
        for c, w, anchor in zip(cols, (300, 80, 80), (tk.W, tk.W, tk.W)):
            self.lib_tree.heading(c, text=c.capitalize())
            self.lib_tree.column(c, width=w, anchor=anchor)
        self.lib_tree.pack(fill=tk.BOTH, expand=True)
        self.lib_tree.bind("<Double-1>", lambda e: self.edit_library_song())
        self.lib_tree.bind("<Return>", lambda e: self.add_selected_to_setlist())

        lib_btns = ttk.Frame(left)
        lib_btns.pack(fill=tk.X, pady=(6, 0))
        ttk.Button(lib_btns, text="Tilføj sang…", command=self.add_song_dialog).pack(side=tk.LEFT)
        ttk.Button(
            lib_btns,
            text="🌐 Importér fra internet…",
            command=self.open_import_dialog,
        ).pack(side=tk.LEFT, padx=(4, 0))
        ttk.Button(lib_btns, text="Rediger…", command=self.edit_library_song).pack(
            side=tk.LEFT, padx=(4, 0)
        )
        ttk.Button(lib_btns, text="Slet", command=self.remove_song_from_library).pack(
            side=tk.LEFT, padx=(4, 0)
        )
        ttk.Button(lib_btns, text="Ryd alt", command=self.clear_library).pack(side=tk.RIGHT)

        # ---------- Middle (add/remove) ----------
        mid = ttk.Frame(main)
        mid.pack(side=tk.LEFT, fill=tk.Y, padx=4)
        ttk.Label(mid, text="").pack(pady=(50, 0))
        ttk.Button(
            mid, text="Tilføj  ▶", command=self.add_selected_to_setlist, width=12
        ).pack(pady=4)
        ttk.Button(
            mid, text="◀  Fjern", command=self.remove_selected_from_setlist, width=12
        ).pack(pady=4)

        # ---------- Setlist (right) ----------
        right = ttk.LabelFrame(
            main, text="Aktuel setliste  (træk sange op/ned for at sortere)", padding=6
        )
        right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(4, 0))

        self.set_listbox = tk.Listbox(right, selectmode=tk.SINGLE, activestyle="none")
        theme.style_listbox(self.set_listbox)
        self.set_listbox.pack(fill=tk.BOTH, expand=True)
        self.set_listbox.bind("<Button-1>", self._dnd_press)
        self.set_listbox.bind("<B1-Motion>", self._dnd_motion)
        self.set_listbox.bind("<ButtonRelease-1>", self._dnd_release)
        self.set_listbox.bind("<Double-1>", lambda e: self._on_setlist_double_click())
        self.set_listbox.bind("<Delete>", lambda e: self.remove_selected_from_setlist())
        self.set_listbox.bind("<BackSpace>", lambda e: self.remove_selected_from_setlist())

        set_btns = ttk.Frame(right)
        set_btns.pack(fill=tk.X, pady=(6, 0))
        ttk.Button(set_btns, text="▲ Op", command=self.move_up).pack(side=tk.LEFT)
        ttk.Button(set_btns, text="▼ Ned", command=self.move_down).pack(side=tk.LEFT, padx=(4, 0))
        ttk.Button(
            set_btns, text="🎬 Ekstra-nummer",
            command=lambda: self.add_marker_to_setlist("EKSTRA-NUMMER"),
        ).pack(side=tk.LEFT, padx=(12, 0))
        ttk.Button(
            set_btns, text="🏁 Slut",
            command=lambda: self.add_marker_to_setlist("— SLUT —"),
        ).pack(side=tk.LEFT, padx=(4, 0))
        ttk.Button(
            set_btns, text="➕ Markør…",
            command=self.add_custom_marker,
        ).pack(side=tk.LEFT, padx=(4, 0))
        ttk.Button(set_btns, text="Ryd setliste", command=self.clear_current_setlist).pack(
            side=tk.RIGHT
        )

    def _build_bottom_bar(self) -> None:
        bottom = ttk.Frame(self.root, padding=(8, 4, 8, 8))
        bottom.pack(side=tk.BOTTOM, fill=tk.X)
        ttk.Button(bottom, text="💾 Gem som…", command=self.save_as).pack(side=tk.LEFT)
        ttk.Button(bottom, text="📂 Åbn…", command=self.load_from).pack(side=tk.LEFT, padx=(4, 0))
        ttk.Button(bottom, text="🖨️  Print A4…", command=self.export_print).pack(
            side=tk.LEFT, padx=(4, 0)
        )
        ttk.Label(
            bottom,
            text=f"Auto-gem: {default_autosave_path()}",
            foreground="#888",
            font=("TkDefaultFont", 9),
        ).pack(side=tk.RIGHT)

    # ------------------------------------------------------------------
    # Sample data on first start
    # ------------------------------------------------------------------
    def _load_sample(self) -> None:
        self.model.rename_band(0, "Mit band")
        for n, k, d in [
            ("Wonderwall", "F#m", "4:30"),
            ("Sweet Child O' Mine", "D", "5:55"),
            ("Hey Jude", "F", "7:11"),
            ("Smoke on the Water", "Gm", "5:40"),
        ]:
            self.model.add_song(n, key=k, duration=d)

    # ------------------------------------------------------------------
    # Band actions
    # ------------------------------------------------------------------
    def _refresh_band_combo(self) -> None:
        names = self.model.band_names()
        self.band_combo["values"] = names
        if names:
            self.band_combo.current(self.model.active_band)

    def _on_band_changed(self, _event=None) -> None:
        idx = self.band_combo.current()
        if idx >= 0 and idx != self.model.active_band:
            self.model.set_active_band(idx)
            self.lib_search_var.set("")  # clear search when switching bands
            self.refresh_all()
            self._schedule_autosave()

    def add_band(self) -> None:
        name = simpledialog.askstring(
            "Nyt band",
            "Hvad hedder bandet?",
            parent=self.root,
            initialvalue="Nyt band",
        )
        if name and name.strip():
            self.model.add_band(name.strip())
            self.refresh_all()
            self._schedule_autosave()

    def rename_band(self) -> None:
        current = self.model.current_band["name"]
        name = simpledialog.askstring(
            "Omdøb band", "Nyt navn på bandet:", parent=self.root, initialvalue=current
        )
        if name and name.strip():
            self.model.rename_band(self.model.active_band, name.strip())
            self._refresh_band_combo()
            self._schedule_autosave()

    def delete_band(self) -> None:
        if len(self.model.bands) <= 1:
            messagebox.showinfo(
                "Info",
                "Du kan ikke slette dit sidste band.\nOpret et nyt band først.",
                parent=self.root,
            )
            return
        name = self.model.current_band["name"]
        if messagebox.askyesno(
            "Slet band",
            f'Vil du slette bandet "{name}"?\n\n'
            "Alle sange og setlister i dette band slettes.\n"
            "Andre bands påvirkes ikke.",
            parent=self.root,
        ):
            self.model.delete_band(self.model.active_band)
            self.refresh_all()
            self._schedule_autosave()

    def open_search_all_bands(self) -> None:
        SearchAllBandsDialog(self.root, self)

    def open_logo_dialog(self) -> None:
        LogoDialog(self.root, self)

    def open_stage_mode(self) -> None:
        """Åbn fuldskærms Stage Mode til live performance.

        Hvis den aktive setliste er tom, vis en venlig besked i stedet.
        Hvis brugeren har valgt en sang i setlisten, start dér — ellers
        start fra første sang.
        """
        self._launch_stage_mode("fullscreen")

    def open_stage_mode_window(self) -> None:
        """Åbn Stage Mode i et resizable vindue (ikke fuldskærm).

        Praktisk når man øver foran computeren og samtidig vil have
        andre vinduer synlige."""
        self._launch_stage_mode("window")

    def _launch_stage_mode(self, mode: str) -> None:
        """Fælles launcher for både fullscreen og window mode."""
        songs = self.model.current_setlist.get("songs", [])
        if not songs:
            messagebox.showinfo(
                "Tom setliste",
                "Tilføj nogle sange til setlisten før du starter Stage Mode.",
                parent=self.root,
            )
            return
        # Brug evt. valgt sang som startpunkt
        sel = self.set_listbox.curselection()
        start_idx = sel[0] if sel else 0
        # Gem inden vi går i scenelyset (for en sikkerheds skyld)
        self.model.autosave()
        StageMode(self.root, self.model, start_index=start_idx, mode=mode)

    def _focus_search(self) -> None:
        self.lib_search_entry.focus_set()
        self.lib_search_entry.select_range(0, tk.END)

    # ------------------------------------------------------------------
    # Setlist actions
    # ------------------------------------------------------------------
    def _refresh_setlist_combo(self) -> None:
        names = [sl["name"] for sl in self.model.setlists]
        self.setlist_combo["values"] = names
        if names:
            self.setlist_combo.current(self.model.active_setlist)

    def _on_setlist_changed(self, _event=None) -> None:
        idx = self.setlist_combo.current()
        if idx >= 0:
            self.model.set_active(idx)
            self.refresh_setlist_view()
            self.refresh_library_view()  # opdater grå markering ved setliste-skift
            self._schedule_autosave()

    def add_setlist(self) -> None:
        name = simpledialog.askstring(
            "Ny setliste",
            "Navn på setliste:",
            parent=self.root,
            initialvalue="Ny setliste",
        )
        if name and name.strip():
            self.model.add_setlist(name.strip())
            self._refresh_setlist_combo()
            self.refresh_setlist_view()
            self.refresh_library_view()  # opdater grå markering
            self._schedule_autosave()

    def duplicate_setlist(self) -> None:
        """Lav en kopi af den aktive setliste (alle sange + markører).
        Den nye kopi får navnet "<original> (kopi)" og bliver aktiv."""
        idx = self.model.active_setlist
        current = self.model.setlists[idx]
        suggested = f"{current['name']} (kopi)"
        name = simpledialog.askstring(
            "Kopiér setliste",
            f"Kopiér \"{current['name']}\".\n\nNavn på den nye kopi:",
            parent=self.root,
            initialvalue=suggested,
        )
        if not name or not name.strip():
            return
        song_count = sum(1 for it in current["songs"] if not is_marker_item(it))
        new_idx = self.model.duplicate_setlist(idx, name.strip())
        if new_idx < 0:
            messagebox.showerror(
                "Fejl", "Kunne ikke kopiere setlisten.", parent=self.root
            )
            return
        self._refresh_setlist_combo()
        self.refresh_setlist_view()
        self.refresh_library_view()  # opdater grå markering
        self._schedule_autosave()
        messagebox.showinfo(
            "Kopiéret",
            f'Kopi oprettet: "{name.strip()}" med {song_count} sang(e).',
            parent=self.root,
        )

    def rename_setlist(self) -> None:
        idx = self.model.active_setlist
        current = self.model.setlists[idx]["name"]
        name = simpledialog.askstring(
            "Omdøb setliste", "Nyt navn:", parent=self.root, initialvalue=current
        )
        if name and name.strip():
            self.model.rename_setlist(idx, name.strip())
            self._refresh_setlist_combo()
            self.refresh_setlist_view()  # opdater status-bar med ny dato
            self._schedule_autosave()

    def delete_setlist(self) -> None:
        if len(self.model.setlists) <= 1:
            messagebox.showinfo(
                "Info", "Du kan ikke slette den sidste setliste.", parent=self.root
            )
            return
        idx = self.model.active_setlist
        name = self.model.setlists[idx]["name"]
        if messagebox.askyesno("Slet setliste", f'Slet setlisten "{name}"?', parent=self.root):
            self.model.delete_setlist(idx)
            self._refresh_setlist_combo()
            self.refresh_setlist_view()
            self._schedule_autosave()

    # ------------------------------------------------------------------
    # Library actions
    # ------------------------------------------------------------------
    def add_song_dialog(self) -> None:
        dlg = SongDialog(self.root, title="Tilføj sang")
        if dlg.result:
            r = dlg.result
            if not self.model.add_song(r["name"], r["duration"], r["key"], r["notes"]):
                messagebox.showinfo(
                    "Info", "Sangen findes allerede i biblioteket.", parent=self.root
                )
            else:
                self.refresh_library_view()
                self._schedule_autosave()

    def open_import_dialog(self) -> None:
        ImportFromWebDialog(self.root, self)

    def edit_library_song(self) -> None:
        sel = self.lib_tree.selection()
        if not sel:
            return
        try:
            idx = int(sel[0])
        except ValueError:
            return
        if idx < 0 or idx >= len(self.model.library):
            return
        song = self.model.library[idx]
        dlg = SongDialog(self.root, title="Rediger sang", initial=song)
        if dlg.result:
            r = dlg.result
            ok = self.model.update_song(
                song["name"], r["name"], r["duration"], r["key"], r["notes"]
            )
            if not ok:
                messagebox.showerror(
                    "Fejl",
                    "Kunne ikke gemme — findes der allerede en sang med samme navn?",
                    parent=self.root,
                )
            else:
                self.refresh_all()
                self._schedule_autosave()

    def remove_song_from_library(self) -> None:
        sel = self.lib_tree.selection()
        if not sel:
            return
        if not messagebox.askyesno(
            "Slet sange",
            f"Slet {len(sel)} sang(e) fra biblioteket?\nDe fjernes også fra alle setlister i dette band.",
            parent=self.root,
        ):
            return
        try:
            indices = sorted((int(s) for s in sel), reverse=True)
        except ValueError:
            return
        for i in indices:
            self.model.remove_song_by_index(i)
        self.refresh_all()
        self._schedule_autosave()

    def clear_library(self) -> None:
        if messagebox.askyesno(
            "Ryd bibliotek",
            "Slet alle sange fra dette bands bibliotek?\nAlle setlister i bandet tømmes også for sange.",
            parent=self.root,
        ):
            self.model.clear_library()
            self.refresh_all()
            self._schedule_autosave()

    # ------------------------------------------------------------------
    # Setlist song actions
    # ------------------------------------------------------------------
    def add_selected_to_setlist(self) -> None:
        sel = self.lib_tree.selection()
        if not sel:
            return
        added = 0
        skipped = 0
        for s in sel:
            try:
                idx = int(s)
            except ValueError:
                continue
            if self.model.add_to_setlist_by_index(idx):
                added += 1
            else:
                skipped += 1
        if added == 0 and skipped > 0:
            messagebox.showinfo(
                "Allerede tilføjet",
                "De valgte sange er allerede i setlisten.",
                parent=self.root,
            )
            return
        self.refresh_setlist_view()
        self.refresh_library_view()  # opdater grå markering
        self._schedule_autosave()

    def remove_selected_from_setlist(self) -> None:
        sel = self.set_listbox.curselection()
        if not sel:
            return
        for i in reversed(sel):
            self.model.remove_from_setlist_by_index(i)
        self.refresh_setlist_view()
        self.refresh_library_view()  # opdater grå markering
        self._schedule_autosave()

    def move_up(self) -> None:
        sel = self.set_listbox.curselection()
        if not sel:
            return
        new_i = self.model.move_up(sel[0])
        self.refresh_setlist_view()
        self.set_listbox.selection_set(new_i)
        self.set_listbox.activate(new_i)
        self._schedule_autosave()

    def move_down(self) -> None:
        sel = self.set_listbox.curselection()
        if not sel:
            return
        new_i = self.model.move_down(sel[0])
        self.refresh_setlist_view()
        self.set_listbox.selection_set(new_i)
        self.set_listbox.activate(new_i)
        self._schedule_autosave()

    def clear_current_setlist(self) -> None:
        if messagebox.askyesno(
            "Ryd setliste", "Fjern alle sange fra denne setliste?", parent=self.root
        ):
            self.model.clear_current_setlist()
            self.refresh_setlist_view()
            self.refresh_library_view()  # opdater grå markering
            self._schedule_autosave()

    # ------------------------------------------------------------------
    # Sektion-markører (Ekstra-nummer, Slut, brugerdefineret)
    # ------------------------------------------------------------------
    def add_marker_to_setlist(self, label: str) -> None:
        """Indsæt en markør EFTER det valgte element (eller til sidst)."""
        sel = self.set_listbox.curselection()
        if sel:
            position = sel[0] + 1  # efter valgte
        else:
            position = None  # til sidst
        new_idx = self.model.add_marker_to_setlist(label, position=position)
        if new_idx < 0:
            return
        self.refresh_setlist_view()
        self.set_listbox.selection_clear(0, tk.END)
        self.set_listbox.selection_set(new_idx)
        self.set_listbox.activate(new_idx)
        self.set_listbox.see(new_idx)
        self._schedule_autosave()

    def add_custom_marker(self) -> None:
        label = simpledialog.askstring(
            "Ny markør",
            "Skriv markør-tekst (fx 'PAUSE', 'Andet sæt', 'Encore'):",
            parent=self.root,
        )
        if label and label.strip():
            self.add_marker_to_setlist(label.strip())

    def _on_setlist_double_click(self) -> None:
        """Dobbeltklik på en markør → rediger label.
        Dobbeltklik på en sang → åbn Rediger-dialog (god til at tilføje noter)."""
        sel = self.set_listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        items = self.model.current_setlist["songs"]
        if not (0 <= idx < len(items)):
            return
        if is_marker_item(items[idx]):
            # Rediger markør
            current = item_marker_label(items[idx])
            new_label = simpledialog.askstring(
                "Rediger markør",
                "Ny tekst:",
                parent=self.root,
                initialvalue=current,
            )
            if new_label and new_label.strip():
                self.model.update_marker_label(idx, new_label.strip())
                self.refresh_setlist_view()
                self.set_listbox.selection_set(idx)
                self._schedule_autosave()
            return

        # Sang — åbn Rediger-dialog så man let kan tilføje/ændre noter
        name = item_song_name(items[idx])
        song = self.model.get_song(name)
        if not song:
            return
        dlg = SongDialog(self.root, title=f"Rediger sang: {name}", initial=song)
        if dlg.result:
            r = dlg.result
            ok = self.model.update_song(
                song["name"], r["name"], r["duration"], r["key"], r["notes"]
            )
            if not ok:
                messagebox.showerror(
                    "Fejl",
                    "Kunne ikke gemme — findes der allerede en sang med samme navn?",
                    parent=self.root,
                )
            else:
                self.refresh_all()
                self._schedule_autosave()

    # ------------------------------------------------------------------
    # Drag and drop in the setlist
    # ------------------------------------------------------------------
    def _dnd_press(self, event) -> None:
        idx = self.set_listbox.nearest(event.y)
        if 0 <= idx < len(self.model.current_setlist["songs"]):
            self._drag_index = idx
        else:
            self._drag_index = None

    def _dnd_motion(self, event) -> None:
        if self._drag_index is None:
            return
        new_idx = self.set_listbox.nearest(event.y)
        if new_idx < 0 or new_idx >= len(self.model.current_setlist["songs"]):
            return
        if new_idx == self._drag_index:
            return
        self.model.move_to(self._drag_index, new_idx)
        self._drag_index = new_idx
        self.refresh_setlist_view()
        self.set_listbox.selection_clear(0, tk.END)
        self.set_listbox.selection_set(new_idx)
        self.set_listbox.activate(new_idx)

    def _dnd_release(self, _event) -> None:
        if self._drag_index is not None:
            self._drag_index = None
            self._schedule_autosave()

    # ------------------------------------------------------------------
    # View refresh
    # ------------------------------------------------------------------
    def refresh_all(self) -> None:
        self._refresh_band_combo()
        self._refresh_setlist_combo()
        self.refresh_library_view()
        self.refresh_setlist_view()

    def refresh_library_view(self) -> None:
        q = self.lib_search_var.get().strip().lower()
        # Preserve selection by iid (library index)
        selected_iids = set(self.lib_tree.selection())
        for item in self.lib_tree.get_children():
            self.lib_tree.delete(item)
        # Konfigurer tag for sange der allerede er i setlisten — vis dem grå
        self.lib_tree.tag_configure("in_setlist", foreground=theme.Colors.IN_SETLIST_FG)
        # NB: setlisten kan indeholde både sang-strenge OG markør-dicts
        # ({"marker": "EKSTRA"}). Dicts er ikke hashable, så vi MÅ ikke
        # putte hele listen ind i en set() — vi tager kun sang-navnene.
        in_set = {item_song_name(it)
                  for it in self.model.current_setlist["songs"]
                  if not is_marker_item(it)}
        shown = 0
        for idx, s in enumerate(self.model.library):
            if q and not self._lib_song_matches(s, q):
                continue
            iid = str(idx)
            tags = ("in_setlist",) if s["name"] in in_set else ()
            self.lib_tree.insert(
                "", tk.END, iid=iid, values=(s["name"], s["key"], s["duration"]),
                tags=tags,
            )
            if iid in selected_iids:
                self.lib_tree.selection_add(iid)
            shown += 1
        # Reflect filter status in the LabelFrame title
        total = len(self.model.library)
        in_set_count = sum(1 for s in self.model.library if s["name"] in in_set)
        if q:
            text = f"Sangbibliotek  ({shown} af {total} vises · {in_set_count} på setliste)"
        else:
            text = f"Sangbibliotek  ({total} sange · {in_set_count} på setliste)"
        # Walk up to find LabelFrame
        parent = self.lib_tree.master
        if isinstance(parent, ttk.LabelFrame):
            parent.configure(text=text)

    @staticmethod
    def _lib_song_matches(song: dict, q: str) -> bool:
        return any(
            q in (song.get(f) or "").lower() for f in ("name", "key", "notes")
        )

    def refresh_setlist_view(self) -> None:
        self.set_listbox.delete(0, tk.END)
        song_num = 0
        for idx, item in enumerate(self.model.current_setlist["songs"]):
            if is_marker_item(item):
                # Sektion-markør — vis fed/farve via itemconfig nedenfor
                label = item_marker_label(item)
                self.set_listbox.insert(tk.END, f"   ─── {label} ───")
                self.set_listbox.itemconfig(
                    idx,
                    foreground=theme.Colors.MARKER_FG,
                    background=theme.Colors.MARKER_BG,
                    selectforeground=theme.Colors.MARKER_SELECTED_FG,
                    selectbackground=theme.Colors.MARKER_SELECTED_BG,
                )
            else:
                # Almindelig sang — vis nummer, navn, toneart/længde
                # og en lille tekst-snippet af noter (hvis der er nogen).
                song_num += 1
                name = item_song_name(item)
                song = self.model.get_song(name) or new_song(name)
                extras = [x for x in (song["key"], song["duration"]) if x]
                suffix = f"   ({' · '.join(extras)})" if extras else ""
                # Noter som ekstra suffix — gør \n til ' · ' og forkort
                notes = (song.get("notes") or "").strip()
                notes_suffix = ""
                if notes:
                    one_line = notes.replace("\n", " · ")
                    if len(one_line) > 50:
                        one_line = one_line[:47] + "…"
                    notes_suffix = f"   💬 {one_line}"
                self.set_listbox.insert(
                    tk.END, f"{song_num:>2}.  {song['name']}{suffix}{notes_suffix}"
                )

        count = self.model.current_setlist_song_count()
        markers = sum(1 for it in self.model.current_setlist["songs"] if is_marker_item(it))
        secs = self.model.current_setlist_seconds()
        text = f"{count} sange"
        if markers:
            text += f"  ·  {markers} markør{'er' if markers != 1 else ''}"
        if secs:
            text += f"  ·  {format_seconds(secs)}"
        # "Sidst ændret"-tidspunkt — kun hvis vi har det (nye setlister får
        # det automatisk; gamle setlister fra v1/v2 har ikke noget før de
        # bliver ændret første gang)
        modified_iso = self.model.get_setlist_modified_at()
        if modified_iso:
            modified_human = format_modified_at(modified_iso)
            if modified_human:
                text += f"   ·   ✏️ Sidst ændret: {modified_human}"
        self.status_var.set(text)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------
    def save_as(self) -> None:
        path = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("Setlist-fil", "*.json")],
            initialfile="setlister.json",
            parent=self.root,
        )
        if not path:
            return
        try:
            self.model.save_to_path(path)
            messagebox.showinfo("Gemt", f"Gemt til:\n{path}", parent=self.root)
        except OSError as e:
            messagebox.showerror("Fejl", str(e), parent=self.root)

    def load_from(self) -> None:
        path = filedialog.askopenfilename(
            filetypes=[("Setlist-fil", "*.json")], parent=self.root
        )
        if not path:
            return
        try:
            self.model.load_from_path(path)
            self.lib_search_var.set("")
            self.refresh_all()
            self._schedule_autosave()
            messagebox.showinfo("Indlæst", f"Indlæst fra:\n{path}", parent=self.root)
        except (OSError, ValueError) as e:
            messagebox.showerror("Fejl", str(e), parent=self.root)

    def _schedule_autosave(self) -> None:
        if self._autosave_job is not None:
            try:
                self.root.after_cancel(self._autosave_job)
            except tk.TclError:
                pass
        self._autosave_job = self.root.after(AUTOSAVE_DEBOUNCE_MS, self._do_autosave)

    def _do_autosave(self) -> None:
        self._autosave_job = None
        self.model.autosave()

    def _on_close(self) -> None:
        self.model.autosave()
        self.root.destroy()

    # ------------------------------------------------------------------
    # Print A4
    # ------------------------------------------------------------------
    def export_print(self) -> None:
        if not self.model.current_setlist["songs"]:
            messagebox.showinfo(
                "Tom setliste", "Tilføj sange før du printer.", parent=self.root
            )
            return
        default_title = self.model.current_setlist["name"]
        dlg = PrintDialog(
            self.root, default_title, self.model.print_options, model=self.model
        )
        if not dlg.result:
            return
        title = dlg.result["title"]
        options = dlg.result["options"]
        # Save options as the new default for next time
        self.model.print_options = dict(options)
        self._schedule_autosave()

        html = self.model.generate_html(title, options)
        tmp = tempfile.NamedTemporaryFile(
            delete=False, suffix=".html", mode="w", encoding="utf-8"
        )
        tmp.write(html)
        tmp.close()
        webbrowser.open("file://" + os.path.abspath(tmp.name))
        messagebox.showinfo(
            "Klar til print",
            "Setlisten er åbnet i din browser.\n\n"
            "Tryk Ctrl+P i browseren og vælg A4.",
            parent=self.root,
        )

    def _show_about(self) -> None:
        messagebox.showinfo(
            "Om Setlist Manager",
            f"Setlist Manager v{APP_VERSION}\n\n"
            "Et simpelt program til at holde styr på dine bands' sange "
            "og bygge setlister til koncerter.\n\n"
            "Funktioner:\n"
            " • Flere bands i samme fil\n"
            " • Sangbibliotek med toneart, længde og noter\n"
            " • Flere setlister pr. band\n"
            " • Sektion-markører (Ekstra-nummer, Slut, …)\n"
            " • Søg sange — også på tværs af alle bands\n"
            " • Importer fra MusicBrainz (internet)\n"
            " • Logo pr. band på printet\n"
            " • Live forhåndsvisning af A4-print\n"
            " • 🎬 Stage Mode — fuldskærm til koncerten (F5)\n"
            " • Auto-opdatering — tjekker GitHub for nye versioner\n"
            " • Auto-gem så du aldrig mister noget",
            parent=self.root,
        )

    # ------------------------------------------------------------------
    # Opdaterings-tjek
    # ------------------------------------------------------------------
    def check_for_updates_manual(self) -> None:
        """Manuel kontrol fra menuen — viser altid et resultat."""
        self._run_update_check(silent=False)

    def _maybe_auto_check_update(self) -> None:
        """Stille auto-tjek ved opstart — kun hvis vi ikke har tjekket i 24t."""
        try:
            if not updater.should_auto_check():
                return
        except Exception:  # noqa: BLE001
            return
        self._run_update_check(silent=True)

    def _run_update_check(self, silent: bool) -> None:
        """Tjek for opdateringer i baggrundstråd så GUI ikke fryser."""
        import threading

        def worker():
            info = updater.check_for_update()
            # Resultat tilbage til main-tråden
            self.root.after(0, lambda: self._on_update_check_done(info, silent))

        threading.Thread(target=worker, daemon=True, name="update-check").start()

    def _on_update_check_done(self, info, silent: bool) -> None:
        """Kaldes på main-tråden når tjekket er færdigt."""
        # Husk at vi har tjekket (uanset resultat)
        try:
            updater.mark_checked(info=info)
        except Exception:  # noqa: BLE001
            pass

        if info is None:
            # Netværksfejl
            if not silent:
                detail = getattr(updater, "last_error", "") or "ukendt fejl"
                releases_url = (
                    f"https://github.com/{updater.GITHUB_OWNER}"
                    f"/{updater.GITHUB_REPO}/releases/latest"
                )
                msg = (
                    "Kunne ikke kontakte GitHub for at tjekke efter opdateringer.\n\n"
                    f"Detalje: {detail}\n\n"
                    "Vil du åbne release-siden i din browser i stedet?\n"
                    f"({releases_url})"
                )
                if messagebox.askyesno("Ingen forbindelse", msg, parent=self.root):
                    try:
                        import webbrowser
                        webbrowser.open(releases_url)
                    except Exception:  # noqa: BLE001
                        pass
            return

        if not info.is_newer:
            if not silent:
                messagebox.showinfo(
                    "Ingen opdatering",
                    f"Du kører den nyeste version (v{info.current}). ✅",
                    parent=self.root,
                )
            return

        # Ny version fundet
        if silent and updater.is_skipped(info.latest):
            # Brugeren har sprunget over — vis ikke igen før næste version
            return

        UpdateDialog(self.root, info, app=self)


def main() -> int:
    root = tk.Tk()
    # Anvend det moderne tema FØR vi bygger nogen widgets
    try:
        theme.apply_theme(root)
    except tk.TclError:
        pass

    icon_path = Path(getattr(sys, "_MEIPASS", Path(__file__).parent)) / "assets" / "app.ico"
    if icon_path.exists():
        try:
            root.iconbitmap(default=str(icon_path))
        except tk.TclError:
            pass

    SetlistApp(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
