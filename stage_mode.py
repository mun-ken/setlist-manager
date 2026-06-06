"""Stage Mode — fuldskærm setliste-visning til live performance.

Sort baggrund, kæmpe hvid tekst, nuværende sang fremhævet midt på skærmen.
Designet til at blive vist på en bærbar/iPad på scenen — så hele bandet
let kan se hvilken sang der kommer næste.

Tastatur-kontroller:
    Mellemrum / →  / ↓  / Enter   → Næste sang
    ←  / ↑  / Backspace            → Forrige sang
    Home / End                     → Første / sidste sang
    1-9                            → Hop til sang nummer
    Esc / q                        → Luk Stage Mode
    Klik (venstre)                 → Næste sang
    Klik (højre)                   → Forrige sang
    F                              → Toggle fullscreen
"""

from __future__ import annotations

import tkinter as tk
from typing import List

from setlist_model import (
    SetlistModel,
    is_marker_item,
    item_marker_label,
    item_song_name,
    new_song,
)


# ===========================================================================
#  Farve-tema (mørkt — designet til en mørk scene)
# ===========================================================================
class StageColors:
    BG = "#0a0a0a"              # næsten sort hovedbaggrund
    BG_CURRENT = "#1a1a1a"      # let lysere bag current song
    BORDER_CURRENT = "#00d96c"  # grøn accent-stribe ved current

    FG_CURRENT = "#ffffff"      # nuværende sang — knaldhvid
    FG_NEXT = "#9a9a9f"         # kommende sange — dæmpet
    FG_PAST = "#3a3a3a"         # forbi sange — meget dæmpet
    FG_MARKER = "#e89e2a"       # markører — varmt orange
    FG_META = "#6e6e73"         # toneart/varighed når ikke current
    FG_META_CURRENT = "#d4d4d8" # toneart/varighed på current

    FG_TOP = "#aeaeb2"          # top-bar tekst
    FG_HINT = "#48484a"         # tastatur-hints
    FG_INDICATOR = "#00d96c"    # grøn ▶ ved current

    NOTES_BG = "#141414"
    NOTES_FG = "#e5e5ea"
    NOTES_FG_HINT = "#48484a"


# ===========================================================================
#  Stage Mode dialog (Toplevel)
# ===========================================================================
class StageMode(tk.Toplevel):
    """Fuldskærms setliste-visning. Lukker med Esc."""

    # Font-stack — falder pænt tilbage hvis Segoe UI ikke findes (Mac/Linux)
    FONT_FAMILY = "Segoe UI"

    def __init__(
        self,
        parent: tk.Misc,
        model: SetlistModel,
        start_index: int = 0,
    ) -> None:
        super().__init__(parent)
        self.parent = parent
        self.model = model
        self.title("Setlist Manager — Stage Mode")

        # Snapshot af setlisten (vi rører ikke modellen herfra)
        self.items: List = list(model.current_setlist.get("songs", []))
        if not self.items:
            # Tom setliste — luk straks (kalder må have tjekket først)
            self.after(10, self.destroy)
            return

        # Beregn første gyldige sang-index (spring start-markører over)
        self.current_idx = max(0, min(start_index, len(self.items) - 1))
        if is_marker_item(self.items[self.current_idx]):
            self._skip_forward_to_song()

        # Beregn total antal sange (uden markører) — bruges i top bar
        self._total_songs = sum(1 for it in self.items if not is_marker_item(it))

        # Hold reference til alle widget-rows så vi kan opdatere/scrolle
        self.song_widgets: List[tk.Frame] = []

        # Cursor-hiding state
        self._cursor_hidden = False
        self._cursor_after_id: str | None = None

        # === Vindue setup ===
        self.configure(bg=StageColors.BG)
        # Sikkerhedsnet: hvis fullscreen fejler (sjældent, men sker i nogle
        # window managers) så maxer vi i stedet bare vinduet
        try:
            self.attributes("-fullscreen", True)
            self._is_fullscreen = True
        except tk.TclError:
            self.state("zoomed") if self._can_zoom() else self.geometry("1600x900")
            self._is_fullscreen = False

        self.lift()
        self.focus_force()

        # Build UI + bind keys
        self._build_ui()
        self._bind_keys()
        self._refresh()
        self._start_cursor_timer()

        # Grab så main-vinduet er låst mens vi er i stage mode
        try:
            self.grab_set()
        except tk.TclError:
            pass

    # ------------------------------------------------------------------
    #  Hjælpe-checks
    # ------------------------------------------------------------------
    def _can_zoom(self) -> bool:
        """state('zoomed') findes kun på Windows."""
        try:
            self.state("normal")
            return True
        except tk.TclError:
            return False

    # ------------------------------------------------------------------
    #  UI construction
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        # --- Top bar (lille — setliste-navn + sang X/Y + hint) ---
        top = tk.Frame(self, bg=StageColors.BG, height=60)
        top.pack(side=tk.TOP, fill=tk.X)
        top.pack_propagate(False)

        self.top_left_var = tk.StringVar(value="")
        tk.Label(
            top, textvariable=self.top_left_var,
            bg=StageColors.BG, fg=StageColors.FG_TOP,
            font=(self.FONT_FAMILY, 16, "bold"),
            anchor="w",
        ).pack(side=tk.LEFT, padx=32, pady=12)

        tk.Label(
            top,
            text="Esc = luk    ·    Klik / Mellemrum = næste    ·    Højre-klik / ← = forrige",
            bg=StageColors.BG, fg=StageColors.FG_HINT,
            font=(self.FONT_FAMILY, 11),
        ).pack(side=tk.RIGHT, padx=32)

        # --- Notes-area (BUNDEN) — pakkes FØR canvas så den ikke overlapper ---
        self.notes_frame = tk.Frame(self, bg=StageColors.NOTES_BG, height=140)
        self.notes_frame.pack(side=tk.BOTTOM, fill=tk.X)
        self.notes_frame.pack_propagate(False)

        # En lille divider-linje
        tk.Frame(self.notes_frame, bg="#252528", height=1).pack(
            side=tk.TOP, fill=tk.X
        )

        self.notes_var = tk.StringVar(value="")
        self.notes_label = tk.Label(
            self.notes_frame, textvariable=self.notes_var,
            bg=StageColors.NOTES_BG, fg=StageColors.NOTES_FG,
            font=(self.FONT_FAMILY, 20),
            wraplength=1600, justify="left",
            anchor="w",
        )
        self.notes_label.pack(fill=tk.BOTH, expand=True, padx=40, pady=14)

        # --- Hovedvisning (scrollende sang-liste) ---
        main = tk.Frame(self, bg=StageColors.BG)
        main.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        self.canvas = tk.Canvas(
            main, bg=StageColors.BG, highlightthickness=0, bd=0,
        )
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Indre frame der holder alle sang-labels
        self.inner = tk.Frame(self.canvas, bg=StageColors.BG)
        self.canvas_window = self.canvas.create_window(
            (0, 0), window=self.inner, anchor="nw",
        )

        def on_canvas_configure(event):
            # Indre frame skal følge canvas-bredden
            self.canvas.itemconfig(self.canvas_window, width=event.width)
            # Genberegn også scroll-region
            self.canvas.configure(scrollregion=self.canvas.bbox("all"))
            # Re-scroll til current efter resize
            self.after_idle(self._scroll_to_current)

        def on_inner_configure(_event):
            self.canvas.configure(scrollregion=self.canvas.bbox("all"))

        self.canvas.bind("<Configure>", on_canvas_configure)
        self.inner.bind("<Configure>", on_inner_configure)

        # Tillad scroll-hjul også (uden at det ændrer current song)
        def on_mousewheel(event):
            # Windows: event.delta = ±120 pr. notch
            # Mac: event.delta = ±1
            if event.delta:
                self.canvas.yview_scroll(int(-event.delta / 30), "units")

        self.canvas.bind("<MouseWheel>", on_mousewheel)
        self.bind_all("<MouseWheel>", on_mousewheel, add="+")

    # ------------------------------------------------------------------
    #  Bygger / opdaterer sang-widgets
    # ------------------------------------------------------------------
    def _refresh(self) -> None:
        """Genoptegn HELE listen — current-song fremhævet, top-bar opdateret."""
        # Slet eksisterende
        for w in self.song_widgets:
            w.destroy()
        self.song_widgets = []

        song_num = 0
        for i, item in enumerate(self.items):
            if is_marker_item(item):
                w = self._make_marker_row(item_marker_label(item))
            else:
                song_num += 1
                w = self._make_song_row(item_song_name(item), i, song_num)
            w.pack(fill=tk.X, padx=20, pady=0)
            self.song_widgets.append(w)

        # Lidt luft i bunden så sidste sang ikke klistrer
        spacer = tk.Frame(self.inner, bg=StageColors.BG, height=300)
        spacer.pack(fill=tk.X)
        self.song_widgets.append(spacer)

        # Top bar
        sl_name = self.model.current_setlist.get("name", "Setliste")
        cur_n = self._song_number_at(self.current_idx)
        if cur_n > 0:
            self.top_left_var.set(
                f"🎤  {sl_name}    ·    Sang {cur_n} af {self._total_songs}"
            )
        else:
            self.top_left_var.set(f"🎤  {sl_name}")

        # Notes
        self._update_notes()

        # Scroll så current er omkring 1/3 fra toppen
        self.after_idle(self._scroll_to_current)

    def _make_song_row(self, name: str, idx: int, song_num: int) -> tk.Frame:
        is_current = (idx == self.current_idx)
        is_past = (idx < self.current_idx)

        if is_current:
            bg = StageColors.BG_CURRENT
            fg = StageColors.FG_CURRENT
            font_main = (self.FONT_FAMILY, 64, "bold")
            font_meta = (self.FONT_FAMILY, 26)
            fg_meta = StageColors.FG_META_CURRENT
            pady = 22
        elif is_past:
            bg = StageColors.BG
            fg = StageColors.FG_PAST
            font_main = (self.FONT_FAMILY, 26)
            font_meta = (self.FONT_FAMILY, 15)
            fg_meta = StageColors.FG_PAST
            pady = 4
        else:
            bg = StageColors.BG
            fg = StageColors.FG_NEXT
            font_main = (self.FONT_FAMILY, 36)
            font_meta = (self.FONT_FAMILY, 19)
            fg_meta = StageColors.FG_META
            pady = 8

        # Container (med evt. venstre-stribe ved current)
        outer = tk.Frame(self.inner, bg=bg)

        # Grøn accent-stribe ved current sang
        if is_current:
            stripe = tk.Frame(outer, bg=StageColors.BORDER_CURRENT, width=6)
            stripe.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 0))

        inner = tk.Frame(outer, bg=bg)
        inner.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Sang-nummer
        tk.Label(
            inner, text=f"{song_num}.",
            bg=bg, fg=fg,
            font=font_main, width=4, anchor="e",
        ).pack(side=tk.LEFT, padx=(20, 16), pady=pady)

        # ▶ indikator kun ved current
        if is_current:
            tk.Label(
                inner, text="▶",
                bg=bg, fg=StageColors.FG_INDICATOR,
                font=(self.FONT_FAMILY, 36, "bold"),
            ).pack(side=tk.LEFT, padx=(0, 16), pady=pady)

        # Navn (venstre-justeret, fylder)
        tk.Label(
            inner, text=name,
            bg=bg, fg=fg,
            font=font_main, anchor="w",
        ).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 20), pady=pady)

        # Meta (toneart, varighed) til højre
        song = self.model.get_song(name) or new_song(name)
        extras = [x for x in (song.get("key", ""), song.get("duration", "")) if x]
        if extras:
            tk.Label(
                inner, text="   ·   ".join(extras),
                bg=bg, fg=fg_meta,
                font=font_meta,
            ).pack(side=tk.RIGHT, padx=(0, 32), pady=pady)

        return outer

    def _make_marker_row(self, label: str) -> tk.Frame:
        frm = tk.Frame(self.inner, bg=StageColors.BG)
        tk.Label(
            frm, text=f"── {label} ──",
            bg=StageColors.BG, fg=StageColors.FG_MARKER,
            font=(self.FONT_FAMILY, 22, "italic", "bold"),
        ).pack(pady=(28, 16))
        return frm

    # ------------------------------------------------------------------
    #  Notes for current song
    # ------------------------------------------------------------------
    def _update_notes(self) -> None:
        if not (0 <= self.current_idx < len(self.items)):
            self.notes_var.set("")
            return
        item = self.items[self.current_idx]
        if is_marker_item(item):
            self.notes_var.set("")
            return
        name = item_song_name(item)
        song = self.model.get_song(name) or new_song(name)
        notes = (song.get("notes") or "").strip()
        if notes:
            # Erstat newlines med ' · ' for at lave det til én linje på scenen
            one_line = notes.replace("\n", "   ·   ")
            self.notes_var.set(f"💬  {one_line}")
            self.notes_label.configure(fg=StageColors.NOTES_FG)
        else:
            self.notes_var.set("")

    # ------------------------------------------------------------------
    #  Scroll så current song er omkring 1/3 fra toppen
    # ------------------------------------------------------------------
    def _scroll_to_current(self) -> None:
        try:
            self.update_idletasks()
        except tk.TclError:
            return

        if not (0 <= self.current_idx < len(self.song_widgets)):
            return

        w = self.song_widgets[self.current_idx]
        try:
            self.canvas.configure(scrollregion=self.canvas.bbox("all"))
            inner_h = self.inner.winfo_height()
            canvas_h = self.canvas.winfo_height()
            if inner_h <= canvas_h or canvas_h <= 0:
                return
            w_y = w.winfo_y()
            # Target: placér current 1/3 fra toppen for at vise nogle
            # næste-sange under den
            target_y = max(0, w_y - canvas_h // 3)
            max_y = max(1, inner_h - canvas_h)
            fraction = min(1.0, target_y / max_y)
            self.canvas.yview_moveto(fraction)
        except (tk.TclError, ZeroDivisionError):
            pass

    # ------------------------------------------------------------------
    #  Navigation
    # ------------------------------------------------------------------
    def _song_number_at(self, idx: int) -> int:
        """1-baseret sang-nummer for item på position idx (0 hvis markør)."""
        if not (0 <= idx < len(self.items)) or is_marker_item(self.items[idx]):
            return 0
        return sum(1 for j in range(idx + 1) if not is_marker_item(self.items[j]))

    def _skip_forward_to_song(self) -> None:
        """Hvis current_idx er en markør, ryk frem til første sang."""
        while (self.current_idx < len(self.items)
               and is_marker_item(self.items[self.current_idx])):
            self.current_idx += 1
        if self.current_idx >= len(self.items):
            # Hele resten var markører — gå baglæns
            self.current_idx = len(self.items) - 1
            while (self.current_idx >= 0
                   and is_marker_item(self.items[self.current_idx])):
                self.current_idx -= 1
            self.current_idx = max(0, self.current_idx)

    def next_song(self, _event=None) -> None:
        """Hop til næste sang (spring markører over)."""
        i = self.current_idx + 1
        while i < len(self.items) and is_marker_item(self.items[i]):
            i += 1
        if i < len(self.items):
            self.current_idx = i
            self._refresh()

    def prev_song(self, _event=None) -> None:
        """Hop til forrige sang (spring markører over)."""
        i = self.current_idx - 1
        while i >= 0 and is_marker_item(self.items[i]):
            i -= 1
        if i >= 0:
            self.current_idx = i
            self._refresh()

    def go_to_first(self, _event=None) -> None:
        self.current_idx = 0
        if is_marker_item(self.items[0]):
            self._skip_forward_to_song()
        self._refresh()

    def go_to_last(self, _event=None) -> None:
        self.current_idx = len(self.items) - 1
        if is_marker_item(self.items[self.current_idx]):
            # gå baglæns til sidste sang
            while (self.current_idx >= 0
                   and is_marker_item(self.items[self.current_idx])):
                self.current_idx -= 1
            self.current_idx = max(0, self.current_idx)
        self._refresh()

    def go_to_song_number(self, n: int) -> None:
        """Hop direkte til sang nummer N (1-baseret, markører tæller ikke)."""
        seen = 0
        for i, item in enumerate(self.items):
            if not is_marker_item(item):
                seen += 1
                if seen == n:
                    self.current_idx = i
                    self._refresh()
                    return

    # ------------------------------------------------------------------
    #  Key bindings
    # ------------------------------------------------------------------
    def _bind_keys(self) -> None:
        # Næste sang
        for k in ("<space>", "<Right>", "<Down>", "<Return>", "<KP_Enter>"):
            self.bind(k, self.next_song)
        # Forrige sang
        for k in ("<Left>", "<Up>", "<BackSpace>"):
            self.bind(k, self.prev_song)
        # Hop først/sidst
        self.bind("<Home>", self.go_to_first)
        self.bind("<End>", self.go_to_last)
        # Hop til sang 1-9
        for n in range(1, 10):
            self.bind(str(n), lambda e, num=n: self.go_to_song_number(num))
        # Klik = næste, højre-klik = forrige
        # Brug bind på selve vinduet
        self.bind("<Button-1>", self.next_song)
        self.bind("<Button-3>", self.prev_song)
        self.bind("<Button-2>", self.prev_song)  # mac middle-click
        # Toggle fullscreen med F
        self.bind("f", self._toggle_fullscreen)
        self.bind("F", self._toggle_fullscreen)
        # Exit
        for k in ("<Escape>", "q", "Q"):
            self.bind(k, self.close)
        # Cursor reveal ved mouse motion
        self.bind("<Motion>", lambda e: self._show_cursor_briefly())

    def _toggle_fullscreen(self, _event=None) -> None:
        try:
            self._is_fullscreen = not self._is_fullscreen
            self.attributes("-fullscreen", self._is_fullscreen)
        except tk.TclError:
            pass

    def close(self, _event=None) -> None:
        self._stop_cursor_timer()
        try:
            self.attributes("-fullscreen", False)
        except tk.TclError:
            pass
        try:
            self.grab_release()
        except tk.TclError:
            pass
        self.destroy()

    # ------------------------------------------------------------------
    #  Auto-hide cursor efter 3 sekunders inaktivitet
    # ------------------------------------------------------------------
    def _start_cursor_timer(self) -> None:
        self._reset_cursor_timer()

    def _reset_cursor_timer(self) -> None:
        self._stop_cursor_timer()
        try:
            self._cursor_after_id = self.after(3000, self._hide_cursor)
        except tk.TclError:
            pass

    def _stop_cursor_timer(self) -> None:
        if self._cursor_after_id is not None:
            try:
                self.after_cancel(self._cursor_after_id)
            except tk.TclError:
                pass
            self._cursor_after_id = None

    def _hide_cursor(self) -> None:
        try:
            self.config(cursor="none")
            self._cursor_hidden = True
        except tk.TclError:
            pass

    def _show_cursor_briefly(self) -> None:
        if self._cursor_hidden:
            try:
                self.config(cursor="")
                self._cursor_hidden = False
            except tk.TclError:
                pass
        self._reset_cursor_timer()
