"""'NDI Notes' vindue — broadcaster sang-noter til OBS/vMix.

Adskilt fra Stage Mode: dette vindue er specifikt designet til
broadcast-output via NDI. Det viser et live-preview af det der bliver
sendt over NDI plus knapper til at navigere setlisten.

Layout:
    ┌─────────────────────────────────────────────────┐
    │  🎙 NDI Notes  ·  Streamer som: 'Setlist Mgr'  │
    ├─────────────────────────────────────────────────┤
    │                                                 │
    │          [PREVIEW: viser hvad OBS får]          │
    │                                                 │
    ├─────────────────────────────────────────────────┤
    │  ◄ Forrige   Sang 5/12   Næste ►   [Luk]       │
    └─────────────────────────────────────────────────┘

Frame-rate: ~10fps (det er noter — de ændres ikke 60 gange/sek).
NDI-modtagere holder selv frame'n synlig mellem updates.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk
from typing import Optional

try:
    from PIL import ImageTk  # type: ignore[import-not-found]
    _PIL_TK_OK = True
except ImportError:
    ImageTk = None  # type: ignore[assignment]
    _PIL_TK_OK = False

from setlist_model import SetlistModel, is_marker_item
import ndi_output
from ndi_renderer import get_current_and_next, render_notes_frame


# Frame-rate i ms — 100ms = 10fps (rigeligt for noter)
RENDER_INTERVAL_MS = 100

# Preview-størrelse (vinduet skaleres derefter)
PREVIEW_WIDTH = 960
PREVIEW_HEIGHT = 540

# NDI output-størrelse (broadcast 1080p)
NDI_WIDTH = 1920
NDI_HEIGHT = 1080


class NDINotesWindow(tk.Toplevel):
    """Toplevel-vindue der streamer sang-noter over NDI.

    Lifecycle:
        win = NDINotesWindow(parent, model)
        # vinduet kører selv indtil brugeren lukker det
    """

    def __init__(
        self,
        parent: tk.Misc,
        model: SetlistModel,
        ndi_name: str = "Setlist Manager Notes",
        start_index: int = 0,
    ) -> None:
        super().__init__(parent)
        self.parent = parent
        self.model = model
        self.ndi_name = ndi_name

        # State
        self.current_idx: int = self._first_song_index_at_or_after(start_index)
        self._sender: Optional[ndi_output.NDISender] = None
        self._render_after_id: Optional[str] = None
        self._closed = False
        self._last_preview_image = None  # holder en ref så GC ikke spiser den

        # === Tjek at NDI er tilgængeligt — ellers vis hjælp og luk ===
        if not ndi_output.is_available():
            messagebox.showerror(
                "NDI ikke tilgængeligt",
                ndi_output.get_install_help(),
                parent=parent,
            )
            self.after(10, self.destroy)
            return

        # === Tjek at vi har sange overhovedet ===
        if not self.model.current_setlist.get("songs"):
            messagebox.showinfo(
                "Tom setliste",
                "Tilføj nogle sange før du starter NDI Notes.",
                parent=parent,
            )
            self.after(10, self.destroy)
            return

        # === Start NDI-sender ===
        try:
            self._sender = ndi_output.NDISender(name=ndi_name)
        except ndi_output.NDIError as e:
            messagebox.showerror(
                "Kunne ikke starte NDI",
                str(e),
                parent=parent,
            )
            self.after(10, self.destroy)
            return

        self.title(f"🎙 NDI Notes — broadcaster som '{ndi_name}'")
        self.geometry(f"{PREVIEW_WIDTH + 40}x{PREVIEW_HEIGHT + 140}")
        self.minsize(640, 420)
        self.configure(bg="#1a1a1d")

        self._build_ui()
        self._bind_keys()

        # Start render-loop
        self._schedule_next_render()

        # Cleanup ved lukning
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.focus_set()

    # ------------------------------------------------------------------
    #  UI
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        # Top-bar: NDI-navn + status
        top = tk.Frame(self, bg="#1a1a1d")
        top.pack(side=tk.TOP, fill=tk.X, padx=12, pady=(10, 6))

        tk.Label(
            top, text=f"📡  Streamer over NDI som  '{self.ndi_name}'",
            bg="#1a1a1d", fg="#e8e8ed",
            font=("Segoe UI", 11, "bold"),
        ).pack(side=tk.LEFT)

        self.status_var = tk.StringVar(value="● LIVE")
        tk.Label(
            top, textvariable=self.status_var,
            bg="#1a1a1d", fg="#00d96c",
            font=("Segoe UI", 11, "bold"),
        ).pack(side=tk.RIGHT)

        # Preview-område
        preview_frame = tk.Frame(self, bg="#000", bd=1, relief=tk.SOLID)
        preview_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=12, pady=6)

        self.preview_label = tk.Label(preview_frame, bg="#000")
        self.preview_label.pack(fill=tk.BOTH, expand=True)

        # Kontrol-bar i bunden
        bottom = tk.Frame(self, bg="#1a1a1d")
        bottom.pack(side=tk.BOTTOM, fill=tk.X, padx=12, pady=(6, 10))

        ttk.Button(bottom, text="◄ Forrige", command=self.prev_song).pack(side=tk.LEFT)

        self.position_var = tk.StringVar(value="")
        tk.Label(
            bottom, textvariable=self.position_var,
            bg="#1a1a1d", fg="#aeaeb2",
            font=("Segoe UI", 11),
        ).pack(side=tk.LEFT, expand=True)

        ttk.Button(bottom, text="Næste ►", command=self.next_song).pack(side=tk.LEFT)

        ttk.Button(bottom, text="Luk", command=self.close).pack(side=tk.RIGHT, padx=(8, 0))

        # Hint
        tk.Label(
            self,
            text="Tip: brug pile-tasterne / mellemrum til at navigere · "
                 "OBS-side: 'Tilføj kilde' → 'NDI Source' → vælg navnet ovenfor",
            bg="#1a1a1d", fg="#6e6e73",
            font=("Segoe UI", 9, "italic"),
        ).pack(side=tk.BOTTOM, pady=(0, 6))

    def _bind_keys(self) -> None:
        for k in ("<space>", "<Right>", "<Down>", "<Return>"):
            self.bind(k, lambda e: self.next_song())
        for k in ("<Left>", "<Up>", "<BackSpace>"):
            self.bind(k, lambda e: self.prev_song())
        self.bind("<Escape>", lambda e: self.close())
        self.bind("<Home>", lambda e: self.go_to_first())
        self.bind("<End>", lambda e: self.go_to_last())

    # ------------------------------------------------------------------
    #  Navigation
    # ------------------------------------------------------------------
    def _first_song_index_at_or_after(self, idx: int) -> int:
        items = self.model.current_setlist.get("songs", [])
        i = max(0, min(idx, len(items) - 1))
        while i < len(items) and is_marker_item(items[i]):
            i += 1
        if i >= len(items):
            # Ingen sang efter — find sidste sang
            i = len(items) - 1
            while i >= 0 and is_marker_item(items[i]):
                i -= 1
        return max(0, i)

    def next_song(self) -> None:
        items = self.model.current_setlist.get("songs", [])
        i = self.current_idx + 1
        while i < len(items) and is_marker_item(items[i]):
            i += 1
        if i < len(items):
            self.current_idx = i
            self._render_now()  # render straks (i stedet for at vente på interval)

    def prev_song(self) -> None:
        items = self.model.current_setlist.get("songs", [])
        i = self.current_idx - 1
        while i >= 0 and is_marker_item(items[i]):
            i -= 1
        if i >= 0:
            self.current_idx = i
            self._render_now()

    def go_to_first(self) -> None:
        self.current_idx = self._first_song_index_at_or_after(0)
        self._render_now()

    def go_to_last(self) -> None:
        items = self.model.current_setlist.get("songs", [])
        i = len(items) - 1
        while i >= 0 and is_marker_item(items[i]):
            i -= 1
        self.current_idx = max(0, i)
        self._render_now()

    # ------------------------------------------------------------------
    #  Render-loop: lave billede + send over NDI + opdatér preview
    # ------------------------------------------------------------------
    def _schedule_next_render(self) -> None:
        if self._closed:
            return
        self._render_now()
        self._render_after_id = self.after(RENDER_INTERVAL_MS, self._schedule_next_render)

    def _render_now(self) -> None:
        """Render én frame, send over NDI, vis preview."""
        if self._closed or self._sender is None:
            return

        try:
            current, nxt = get_current_and_next(self.model, self.current_idx)

            # Beregn 1-baseret position til top-bar
            items = self.model.current_setlist.get("songs", [])
            song_num = sum(1 for it in items[:self.current_idx + 1] if not is_marker_item(it))
            total = sum(1 for it in items if not is_marker_item(it))
            pos_str = f"Sang {song_num} af {total}" if song_num > 0 else ""

            sl_name = self.model.current_setlist.get("name", "")

            # Render fuld broadcast-størrelse til NDI
            ndi_img = render_notes_frame(
                current_song=current,
                next_song=nxt,
                setlist_name=sl_name,
                song_position=pos_str,
                width=NDI_WIDTH,
                height=NDI_HEIGHT,
            )
            if ndi_img is None:
                self.status_var.set("⚠ Pillow mangler")
                return

            # Send over NDI
            try:
                self._sender.send_pil_image(ndi_img, fps=10.0)
            except ndi_output.NDIError as e:
                self.status_var.set(f"⚠ NDI fejl: {e}")
                return

            # Opdatér lokal preview (skaleret ned)
            preview_img = ndi_img.resize(
                (PREVIEW_WIDTH, PREVIEW_HEIGHT),
                resample=1,  # PIL Image.LANCZOS = 1 i ældre, BILINEAR = 2
            )
            if _PIL_TK_OK:
                self._last_preview_image = ImageTk.PhotoImage(preview_img)
                self.preview_label.configure(image=self._last_preview_image)

            # Opdatér bottom-bar position
            self.position_var.set(pos_str)
            self.status_var.set("● LIVE")

        except Exception as e:  # noqa: BLE001
            # Vi vil aldrig crashe pga en render-fejl — bare vis i status
            self.status_var.set(f"⚠ Render-fejl")
            print(f"[NDI Notes] Render-fejl: {e}")

    # ------------------------------------------------------------------
    #  Cleanup
    # ------------------------------------------------------------------
    def close(self) -> None:
        if self._closed:
            return
        self._closed = True

        # Stop render-loop
        if self._render_after_id is not None:
            try:
                self.after_cancel(self._render_after_id)
            except tk.TclError:
                pass
            self._render_after_id = None

        # Luk NDI-sender pænt
        if self._sender is not None:
            try:
                self._sender.close()
            except Exception:  # noqa: BLE001
                pass
            self._sender = None

        try:
            self.destroy()
        except tk.TclError:
            pass
