"""Stage Mode — setliste-visning til live performance.

To modes:
  * "fullscreen" → tag hele skærmen (default, perfekt på scenen)
  * "window"     → almindeligt resizable vindue (godt til at øve på din PC)

I begge modes skalerer al tekst dynamisk efter vinduesstørrelsen — så det
ser pænt ud uanset om det er på en kæmpe TV-skærm eller et lille vindue
på laptoppen. F-tasten skifter mellem fullscreen og vindue når som helst.

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
    F                              → Toggle fullscreen ↔ vindue
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
    """Setliste-visning til live performance — fuldskærm eller vindue.

    Lukker med Esc. Toggler mellem fullscreen og vindue med F.
    """

    # Font-stack — falder pænt tilbage hvis Segoe UI ikke findes (Mac/Linux)
    FONT_FAMILY = "Segoe UI"

    # ------------------------------------------------------------------
    #  Skalering — alt skalerer proportionalt med vinduehøjden
    #  REF_HEIGHT er den "perfekte" højde (en typisk fuldskærm 1080p
    #  har ~1040px brugbar højde). Ved den højde får man de "kanoniske"
    #  font-størrelser herunder. Mindre/større vinduer skalerer pro rata.
    # ------------------------------------------------------------------
    REF_HEIGHT = 1000
    MIN_SCALE = 0.35   # selv et meget lille vindue skal stadig kunne læses
    MAX_SCALE = 1.6    # selv en kæmpe TV-skærm skal ikke se grotesk ud

    # Kanoniske font-størrelser ved REF_HEIGHT (pixels)
    BASE_FONTS = {
        "current_main":   72,   # nuværende sang (KÆMPE)
        "current_meta":   28,   # toneart/varighed på current
        "current_ind":    44,   # ▶ indikator
        "next_main":      36,   # kommende sange
        "next_meta":      19,   # meta på kommende
        "past_main":      24,   # forbi-sange (dæmpede)
        "past_meta":      14,   # meta på forbi-sange
        "marker":         24,   # ── PAUSE ── osv
        "top_bar":        16,   # "🎤 Setliste · Sang 3 af 12"
        "hint":           11,   # tastatur-hint i top højre
        "notes":          22,   # noter i bunden
    }

    # Padding ved current-row (også skaleret)
    BASE_PADY_CURRENT = 22
    BASE_PADY_NEXT = 8
    BASE_PADY_PAST = 4

    def __init__(
        self,
        parent: tk.Misc,
        model: SetlistModel,
        start_index: int = 0,
        mode: str = "fullscreen",
    ) -> None:
        """Åbn Stage Mode.

        Parameters
        ----------
        parent : tk.Misc
            Forældre-vinduet (typisk root)
        model : SetlistModel
            Modellen — vi læser kun, vi muterer ikke
        start_index : int
            Hvilken sang i setlisten der starter som "current"
        mode : str
            "fullscreen" (default) eller "window".
            I window-mode åbnes et resizable vindue på 1280x800 i stedet
            for at tage hele skærmen.
        """
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

        # Resize-debounce state
        self._resize_after_id: str | None = None
        self._last_built_scale: float = -1.0  # tving første build

        # === Vindue setup baseret på mode ===
        self.configure(bg=StageColors.BG)
        self.mode = mode
        self._setup_window_mode(mode)

        self.lift()
        self.focus_force()

        # Build UI + bind keys
        self._build_ui()
        self._bind_keys()
        # Vent et øjeblik så vinduet får sin størrelse, så bygger vi
        # første refresh med korrekt skala
        self.after(50, self._refresh)
        self._start_cursor_timer()

        # Grab så main-vinduet er låst mens vi er i stage mode
        try:
            self.grab_set()
        except tk.TclError:
            pass

    # ------------------------------------------------------------------
    #  Window mode setup
    # ------------------------------------------------------------------
    def _setup_window_mode(self, mode: str) -> None:
        """Sæt vinduet op enten som fuldskærm eller normalt vindue."""
        if mode == "fullscreen":
            try:
                self.attributes("-fullscreen", True)
                self._is_fullscreen = True
                return
            except tk.TclError:
                pass  # fald igennem til window-mode hvis fullscreen fejler

        # Window-mode (default eller fallback fra failed fullscreen)
        self._is_fullscreen = False
        # En behagelig default-størrelse — stor nok til at se rigtig ud,
        # men ikke så stor at det blokerer alt på en lille skærm
        try:
            # Brug max 90% af skærmen
            sw = self.winfo_screenwidth()
            sh = self.winfo_screenheight()
            w = min(1400, int(sw * 0.85))
            h = min(900, int(sh * 0.85))
            # Centrer
            x = (sw - w) // 2
            y = (sh - h) // 2
            self.geometry(f"{w}x{h}+{x}+{y}")
        except tk.TclError:
            self.geometry("1280x800")
        self.resizable(True, True)
        self.minsize(600, 400)

    # ------------------------------------------------------------------
    #  Skalerings-helpers
    # ------------------------------------------------------------------
    def _scale(self) -> float:
        """Returnerer skaleringsfaktor baseret på nuværende vindueshøjde.

        1.0 = REF_HEIGHT. Større vinduer → større tekst.
        Begrænset af MIN_SCALE / MAX_SCALE så det ikke bliver absurd.
        """
        try:
            h = self.winfo_height()
            if h < 100:
                return 1.0  # vinduet er ikke initialiseret endnu
            return max(self.MIN_SCALE, min(self.MAX_SCALE, h / self.REF_HEIGHT))
        except tk.TclError:
            return 1.0

    def _font(self, key: str, *, weight: str = "normal", italic: bool = False) -> tuple:
        """Returnér en font-tuple for given key (skaleret efter vinduet)."""
        size = max(8, int(self.BASE_FONTS[key] * self._scale()))
        styles = []
        if weight == "bold":
            styles.append("bold")
        if italic:
            styles.append("italic")
        if styles:
            return (self.FONT_FAMILY, size, " ".join(styles))
        return (self.FONT_FAMILY, size)

    def _padding(self, base: int) -> int:
        """Skalér en padding-værdi efter vinduet."""
        return max(2, int(base * self._scale()))

    # ------------------------------------------------------------------
    #  UI construction
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        # --- Top bar (lille — setliste-navn + sang X/Y + hint) ---
        self.top_bar = tk.Frame(self, bg=StageColors.BG)
        self.top_bar.pack(side=tk.TOP, fill=tk.X)

        self.top_left_var = tk.StringVar(value="")
        self.top_label = tk.Label(
            self.top_bar, textvariable=self.top_left_var,
            bg=StageColors.BG, fg=StageColors.FG_TOP,
            font=self._font("top_bar", weight="bold"),
            anchor="w",
        )
        self.top_label.pack(side=tk.LEFT, padx=32, pady=12)

        self.hint_label = tk.Label(
            self.top_bar,
            text="Esc=luk · Klik/Mellemrum=næste · Højre-klik/←=forrige · F=fullscreen",
            bg=StageColors.BG, fg=StageColors.FG_HINT,
            font=self._font("hint"),
        )
        self.hint_label.pack(side=tk.RIGHT, padx=32, pady=12)

        # --- Notes-area (BUNDEN) — pakkes FØR canvas så den ikke overlapper ---
        self.notes_frame = tk.Frame(self, bg=StageColors.NOTES_BG)
        self.notes_frame.pack(side=tk.BOTTOM, fill=tk.X)

        # En lille divider-linje
        tk.Frame(self.notes_frame, bg="#252528", height=1).pack(
            side=tk.TOP, fill=tk.X
        )

        self.notes_var = tk.StringVar(value="")
        self.notes_label = tk.Label(
            self.notes_frame, textvariable=self.notes_var,
            bg=StageColors.NOTES_BG, fg=StageColors.NOTES_FG,
            font=self._font("notes"),
            wraplength=2000, justify="left",
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
            # Opdater også notes wraplength så lange noter brydes pænt
            try:
                self.notes_label.configure(wraplength=max(400, event.width - 100))
            except tk.TclError:
                pass

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

        # --- Resize-binding: når vinduet ændres, skalér alt ---
        # Debounce med 200ms så vi ikke rebuild'er ved hver pixel under drag
        self.bind("<Configure>", self._on_resize_window)

    # ------------------------------------------------------------------
    #  Resize-handler — debounce og rebuild ved meningsfuld ændring
    # ------------------------------------------------------------------
    def _on_resize_window(self, event) -> None:
        """Kaldes når vinduet ændrer størrelse (drag eller mode-skift).

        Vi debouncer med 150ms så vi ikke rebuild'er widgets ved hver pixel
        under et drag. Rebuild kun hvis skalaen faktisk har ændret sig
        nævneværdigt (>5%) — så små bevægelser ignoreres.
        """
        # Kun resize-events fra selve top-level (ikke fra børn)
        if event.widget is not self:
            return
        if self._resize_after_id is not None:
            try:
                self.after_cancel(self._resize_after_id)
            except tk.TclError:
                pass
        self._resize_after_id = self.after(150, self._maybe_rebuild_after_resize)

    def _maybe_rebuild_after_resize(self) -> None:
        """Kaldes 150ms efter sidste resize. Rebuild kun hvis skalaen
        har ændret sig nævneværdigt — så vi sparer arbejde ved små
        bevægelser."""
        self._resize_after_id = None
        cur_scale = self._scale()
        if self._last_built_scale > 0:
            delta = abs(cur_scale - self._last_built_scale) / self._last_built_scale
            if delta < 0.03:  # mindre end 3% ændring → skip
                return
        self._refresh()

    # ------------------------------------------------------------------
    #  Bygger / opdaterer sang-widgets
    # ------------------------------------------------------------------
    def _refresh(self) -> None:
        """Genoptegn HELE listen — current-song fremhævet, top-bar opdateret."""
        # Slet eksisterende
        for w in self.song_widgets:
            w.destroy()
        self.song_widgets = []

        # Husk den skala vi byggede med — så _maybe_rebuild_after_resize
        # kan se om der er ændret nok til at retfærdiggøre genbygning
        self._last_built_scale = self._scale()

        # Opdater fonts på top + notes labels (de blev bygget i _build_ui)
        try:
            self.top_label.configure(font=self._font("top_bar", weight="bold"))
            self.hint_label.configure(font=self._font("hint"))
            self.notes_label.configure(font=self._font("notes"))
        except tk.TclError:
            pass

        song_num = 0
        for i, item in enumerate(self.items):
            if is_marker_item(item):
                w = self._make_marker_row(item_marker_label(item))
            else:
                song_num += 1
                w = self._make_song_row(item_song_name(item), i, song_num)
            w.pack(fill=tk.X, padx=self._padding(20), pady=0)
            self.song_widgets.append(w)

        # Lidt luft i bunden så sidste sang ikke klistrer
        spacer = tk.Frame(self.inner, bg=StageColors.BG, height=self._padding(300))
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
            font_main = self._font("current_main", weight="bold")
            font_meta = self._font("current_meta")
            fg_meta = StageColors.FG_META_CURRENT
            pady = self._padding(self.BASE_PADY_CURRENT)
        elif is_past:
            bg = StageColors.BG
            fg = StageColors.FG_PAST
            font_main = self._font("past_main")
            font_meta = self._font("past_meta")
            fg_meta = StageColors.FG_PAST
            pady = self._padding(self.BASE_PADY_PAST)
        else:
            bg = StageColors.BG
            fg = StageColors.FG_NEXT
            font_main = self._font("next_main")
            font_meta = self._font("next_meta")
            fg_meta = StageColors.FG_META
            pady = self._padding(self.BASE_PADY_NEXT)

        # Container (med evt. venstre-stribe ved current)
        outer = tk.Frame(self.inner, bg=bg)

        # Grøn accent-stribe ved current sang — skalér også bredden
        if is_current:
            stripe_w = max(3, int(6 * self._scale()))
            stripe = tk.Frame(outer, bg=StageColors.BORDER_CURRENT, width=stripe_w)
            stripe.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 0))

        inner = tk.Frame(outer, bg=bg)
        inner.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Sang-nummer
        tk.Label(
            inner, text=f"{song_num}.",
            bg=bg, fg=fg,
            font=font_main, width=4, anchor="e",
        ).pack(side=tk.LEFT, padx=(self._padding(20), self._padding(16)), pady=pady)

        # ▶ indikator kun ved current
        if is_current:
            tk.Label(
                inner, text="▶",
                bg=bg, fg=StageColors.FG_INDICATOR,
                font=self._font("current_ind", weight="bold"),
            ).pack(side=tk.LEFT, padx=(0, self._padding(16)), pady=pady)

        # Navn (venstre-justeret, fylder)
        tk.Label(
            inner, text=name,
            bg=bg, fg=fg,
            font=font_main, anchor="w",
        ).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, self._padding(20)), pady=pady)

        # Meta (toneart, varighed) til højre
        song = self.model.get_song(name) or new_song(name)
        extras = [x for x in (song.get("key", ""), song.get("duration", "")) if x]
        if extras:
            tk.Label(
                inner, text="   ·   ".join(extras),
                bg=bg, fg=fg_meta,
                font=font_meta,
            ).pack(side=tk.RIGHT, padx=(0, self._padding(32)), pady=pady)

        return outer

    def _make_marker_row(self, label: str) -> tk.Frame:
        frm = tk.Frame(self.inner, bg=StageColors.BG)
        tk.Label(
            frm, text=f"── {label} ──",
            bg=StageColors.BG, fg=StageColors.FG_MARKER,
            font=self._font("marker", weight="bold", italic=True),
        ).pack(pady=(self._padding(28), self._padding(16)))
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
        """Skift mellem fullscreen og vindue.

        Når man går FRA fullscreen TIL vindue: brug en pæn default-størrelse.
        Når man går FRA vindue TIL fullscreen: spring direkte til fullscreen.
        """
        try:
            self._is_fullscreen = not self._is_fullscreen
            if self._is_fullscreen:
                self.attributes("-fullscreen", True)
            else:
                # Gå tilbage til vindue — sæt en behagelig størrelse
                self.attributes("-fullscreen", False)
                try:
                    sw = self.winfo_screenwidth()
                    sh = self.winfo_screenheight()
                    w = min(1400, int(sw * 0.85))
                    h = min(900, int(sh * 0.85))
                    x = (sw - w) // 2
                    y = (sh - h) // 2
                    self.geometry(f"{w}x{h}+{x}+{y}")
                except tk.TclError:
                    pass
                self.resizable(True, True)
            # Den nye størrelse trigger _on_resize_window som rebuilder
            # med rette skala
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
