"""'NDI Preview' vindue — viser hvad NDI sender + giver navigation.

VIGTIGT: Dette vindue STYRER IKKE broadcasten — det viser bare hvad der
sendes. Selve sendingen håndteres af NDIBroadcaster (en singleton i
hovedappen) som kører uafhængigt af om dette vindue er åbent.

Hvis du lukker dette vindue: NDI bliver ved med at sende.
Hvis du vil stoppe NDI: brug Live-menuen → "Stop NDI broadcast".

Layout:
    ┌──────────────────────────────────────────────────┐
    │  📡 Preview — sender som 'Setlist Manager Notes' │
    ├──────────────────────────────────────────────────┤
    │                                                  │
    │       [LIVE PREVIEW: hvad OBS modtager]          │
    │                                                  │
    ├──────────────────────────────────────────────────┤
    │  ◄ Forrige    Sang 5/12    Næste ►   [Luk]      │
    └──────────────────────────────────────────────────┘
"""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

try:
    from PIL import ImageTk  # type: ignore[import-not-found]
    _PIL_TK_OK = True
except ImportError:
    ImageTk = None  # type: ignore[assignment]
    _PIL_TK_OK = False

from setlist_model import SetlistModel, is_marker_item


# Preview-størrelse (vinduet skaleres derefter)
PREVIEW_WIDTH = 960
PREVIEW_HEIGHT = 540


class NDIPreviewWindow(tk.Toplevel):
    """Passivt preview-vindue der lytter på en NDIBroadcaster.

    Adskilt fra broadcaster så vinduet kan lukkes uden at stoppe NDI.
    """

    def __init__(
        self,
        parent: tk.Misc,
        model: SetlistModel,
        broadcaster,  # NDIBroadcaster — undgår circular import
    ) -> None:
        super().__init__(parent)
        self.parent = parent
        self.model = model
        self.broadcaster = broadcaster
        self._closed = False
        self._last_preview_image = None  # holder ref så GC ikke spiser den

        self.title(
            f"🎙 NDI Preview — '{broadcaster.get_ndi_name() or 'Setlist Manager'}'"
        )
        self.geometry(f"{PREVIEW_WIDTH + 40}x{PREVIEW_HEIGHT + 160}")
        self.minsize(640, 460)
        self.configure(bg="#1a1a1d")

        self._build_ui()
        self._bind_keys()

        # Lyt på broadcaster — vi får hver ny frame leveret af den
        self.broadcaster.add_frame_listener(self._on_new_frame)
        self.broadcaster.add_status_listener(self._on_status_change)

        # Vis straks cached frame hvis broadcaster allerede er i gang
        cached = self.broadcaster.get_last_frame()
        if cached is not None:
            self._on_new_frame(cached)
        self._update_position_label()

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
            top,
            text=f"📡  Streamer over NDI som  '{self.broadcaster.get_ndi_name()}'",
            bg="#1a1a1d", fg="#e8e8ed",
            font=("Segoe UI", 11, "bold"),
        ).pack(side=tk.LEFT)

        self.status_var = tk.StringVar(value="● LIVE")
        self.status_label = tk.Label(
            top, textvariable=self.status_var,
            bg="#1a1a1d", fg="#00d96c",
            font=("Segoe UI", 11, "bold"),
        )
        self.status_label.pack(side=tk.RIGHT)

        # Preview-område
        preview_frame = tk.Frame(self, bg="#000", bd=1, relief=tk.SOLID)
        preview_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=12, pady=6)

        self.preview_label = tk.Label(
            preview_frame, bg="#000",
            text="(venter på første frame...)", fg="#666",
            font=("Segoe UI", 11, "italic"),
        )
        self.preview_label.pack(fill=tk.BOTH, expand=True)

        # Kontrol-bar i bunden
        bottom = tk.Frame(self, bg="#1a1a1d")
        bottom.pack(side=tk.BOTTOM, fill=tk.X, padx=12, pady=(6, 6))

        ttk.Button(bottom, text="◄ Forrige", command=self.prev_song).pack(side=tk.LEFT)

        self.position_var = tk.StringVar(value="")
        tk.Label(
            bottom, textvariable=self.position_var,
            bg="#1a1a1d", fg="#aeaeb2",
            font=("Segoe UI", 11),
        ).pack(side=tk.LEFT, expand=True)

        ttk.Button(bottom, text="Næste ►", command=self.next_song).pack(side=tk.LEFT)

        ttk.Button(bottom, text="Luk preview", command=self.close).pack(
            side=tk.RIGHT, padx=(8, 0),
        )

        # Hint
        tk.Label(
            self,
            text="💡 NDI fortsætter med at sende selvom du lukker dette vindue. "
                 "Stop via Live → Stop NDI broadcast.",
            bg="#1a1a1d", fg="#6e6e73",
            font=("Segoe UI", 9, "italic"),
            wraplength=900, justify="left",
        ).pack(side=tk.BOTTOM, pady=(0, 8), padx=12, fill=tk.X)

    def _bind_keys(self) -> None:
        for k in ("<space>", "<Right>", "<Down>", "<Return>"):
            self.bind(k, lambda e: self.next_song())
        for k in ("<Left>", "<Up>", "<BackSpace>"):
            self.bind(k, lambda e: self.prev_song())
        self.bind("<Escape>", lambda e: self.close())
        self.bind("<Home>", lambda e: self.go_to_first())
        self.bind("<End>", lambda e: self.go_to_last())

    # ------------------------------------------------------------------
    #  Navigation — opdaterer broadcaster's current_idx
    # ------------------------------------------------------------------
    def next_song(self) -> None:
        items = self.model.current_setlist.get("songs", [])
        i = self.broadcaster.get_current_index() + 1
        while i < len(items) and is_marker_item(items[i]):
            i += 1
        if i < len(items):
            self.broadcaster.set_current_index(i)
            self._update_position_label()

    def prev_song(self) -> None:
        items = self.model.current_setlist.get("songs", [])
        i = self.broadcaster.get_current_index() - 1
        while i >= 0 and is_marker_item(items[i]):
            i -= 1
        if i >= 0:
            self.broadcaster.set_current_index(i)
            self._update_position_label()

    def go_to_first(self) -> None:
        items = self.model.current_setlist.get("songs", [])
        i = 0
        while i < len(items) and is_marker_item(items[i]):
            i += 1
        if i < len(items):
            self.broadcaster.set_current_index(i)
            self._update_position_label()

    def go_to_last(self) -> None:
        items = self.model.current_setlist.get("songs", [])
        i = len(items) - 1
        while i >= 0 and is_marker_item(items[i]):
            i -= 1
        if i >= 0:
            self.broadcaster.set_current_index(i)
            self._update_position_label()

    def _update_position_label(self) -> None:
        items = self.model.current_setlist.get("songs", [])
        cur = self.broadcaster.get_current_index()
        song_num = sum(
            1 for it in items[: cur + 1] if not is_marker_item(it)
        )
        total = sum(1 for it in items if not is_marker_item(it))
        if song_num > 0:
            self.position_var.set(f"Sang {song_num} af {total}")
        else:
            self.position_var.set("")

    # ------------------------------------------------------------------
    #  Frame + status callbacks (kaldes af broadcaster)
    # ------------------------------------------------------------------
    def _on_new_frame(self, pil_image) -> None:
        """Kaldes af broadcaster når ny frame er renderet."""
        if self._closed or not _PIL_TK_OK or pil_image is None:
            return
        try:
            preview_img = pil_image.resize(
                (PREVIEW_WIDTH, PREVIEW_HEIGHT),
                resample=1,  # BILINEAR
            )
            self._last_preview_image = ImageTk.PhotoImage(preview_img)
            self.preview_label.configure(image=self._last_preview_image, text="")
            self._update_position_label()
        except tk.TclError:
            pass  # vinduet er måske ved at lukke
        except Exception as e:  # noqa: BLE001
            print(f"[NDI Preview] Frame display fejl: {e}")

    def _on_status_change(self) -> None:
        """Kaldes når broadcaster's state ændres."""
        if self._closed:
            return
        try:
            if not self.broadcaster.is_active():
                self.status_var.set("● STOPPET")
                self.status_label.configure(fg="#d70015")
                self.preview_label.configure(
                    image="",
                    text="(NDI broadcast stoppet)",
                )
            elif self.broadcaster.get_last_error():
                self.status_var.set("⚠ FEJL")
                self.status_label.configure(fg="#ff9500")
            else:
                self.status_var.set("● LIVE")
                self.status_label.configure(fg="#00d96c")
        except tk.TclError:
            pass

    # ------------------------------------------------------------------
    #  Cleanup — stopper IKKE broadcaster
    # ------------------------------------------------------------------
    def close(self) -> None:
        if self._closed:
            return
        self._closed = True

        # Frabed listeners så vi ikke får dead callbacks
        try:
            self.broadcaster.remove_frame_listener(self._on_new_frame)
            self.broadcaster.remove_status_listener(self._on_status_change)
        except Exception:  # noqa: BLE001
            pass

        try:
            self.destroy()
        except tk.TclError:
            pass


# ======================================================================
#  Bagudkompatibilitet — gamle navn 'NDINotesWindow' bruges af tests og
#  evt. eksterne kaldere fra v1.5.0-v1.5.2. Wrapperen opretter en LOKAL
#  broadcaster der lukker når vinduet lukker — så opførslen matcher 1:1.
# ======================================================================
class NDINotesWindow(NDIPreviewWindow):
    """Bagudkompatibel wrapper — opretter egen broadcaster.

    Brug helst NDIPreviewWindow direkte med en delt NDIBroadcaster.
    """

    def __init__(
        self,
        parent: tk.Misc,
        model: SetlistModel,
        ndi_name: str = "Setlist Manager Notes",
        start_index: int = 0,
    ) -> None:
        # Importer her for at undgå circular import
        from ndi_broadcaster import NDIBroadcaster, MODE_NOTES
        import ndi_output

        # Tjek NDI-tilgængelighed først (matching v1.5.0 opførsel)
        if not ndi_output.is_available():
            messagebox.showerror(
                "NDI ikke tilgængeligt",
                ndi_output.get_install_help(),
                parent=parent,
            )
            # Vi skal stadig oprette en Toplevel + planlægge destroy
            tk.Toplevel.__init__(self, parent)
            self._closed = True
            self.after(10, self.destroy)
            return

        # Tjek at vi har sange
        if not model.current_setlist.get("songs"):
            messagebox.showinfo(
                "Tom setliste",
                "Tilføj nogle sange før du starter NDI.",
                parent=parent,
            )
            tk.Toplevel.__init__(self, parent)
            self._closed = True
            self.after(10, self.destroy)
            return

        bc = NDIBroadcaster(parent, model)
        if not bc.start(
            mode=MODE_NOTES, ndi_name=ndi_name, start_index=start_index
        ):
            messagebox.showerror(
                "Kunne ikke starte NDI",
                bc.get_last_error(),
                parent=parent,
            )
            tk.Toplevel.__init__(self, parent)
            self._closed = True
            self.after(10, self.destroy)
            return

        # Init normalt med vores lokale broadcaster
        super().__init__(parent, model, bc)
        self._owns_broadcaster = True

    def close(self) -> None:
        # Når vi ejer broadcasten skal den også stoppes ved luk
        if getattr(self, "_owns_broadcaster", False):
            try:
                self.broadcaster.stop()
            except Exception:  # noqa: BLE001
                pass
        super().close()
