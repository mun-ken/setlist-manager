"""Headless NDI broadcaster — kører i baggrunden uafhængigt af UI-vinduer.

Designprincippet er at NDI-stream'en altid afspejler hvad-end brugeren har
valgt i hovedappen, OGSÅ når preview-vinduet er lukket. OBS/vMix-modtagere
ser et stabilt billede så længe broadcasten er aktiv.

State-machine:
    OFF       → ingen NDI sender oprettet
    STARTING  → forsøger at oprette sender (kan fejle hvis NDI mangler)
    RUNNING   → sender frames hver RENDER_INTERVAL_MS
    ERROR     → render eller send fejlede; venter på næste tick

Brugen er pege-let:
    bc = NDIBroadcaster(root, model)
    bc.start("notes")  # eller "stage_capture"
    bc.set_current_index(5)
    bc.stop()
    bc.is_active()  # for status-indikator
"""

from __future__ import annotations

import tkinter as tk
from typing import Callable, Optional

from setlist_model import SetlistModel, is_marker_item
import ndi_output
from ndi_renderer import get_current_and_next, render_notes_frame


# Frame-rate: 100ms = 10fps (rigeligt for noter — NDI receivers holder
# frame'n synlig mellem updates)
RENDER_INTERVAL_MS = 100

# Broadcast-størrelse (1080p — standard for OBS/vMix)
NDI_WIDTH = 1920
NDI_HEIGHT = 1080

# Render-modes
MODE_NOTES = "notes"                # Pænt formaterede sang-noter
MODE_STAGE_CAPTURE = "stage_capture"  # Screen-grab af Stage Mode vinduet


class NDIBroadcaster:
    """Background NDI sender — kører uafhængigt af UI-vinduer.

    Lifecycle:
        bc = NDIBroadcaster(root, model)
        bc.start(MODE_NOTES, ndi_name="Setlist Manager Notes")
        # ... bruger arbejder i appen, broadcast kører i baggrunden ...
        bc.set_current_index(7)  # opdaterer hvilken sang der vises
        bc.stop()

    Hver instans kan kun have ÉN aktiv broadcast ad gangen. Hvis du
    kalder start() mens en allerede kører, bliver den gamle stoppet
    automatisk først.
    """

    def __init__(self, root: tk.Tk, model: SetlistModel) -> None:
        self.root = root
        self.model = model

        # State
        self._sender: Optional[ndi_output.NDISender] = None
        self._mode: Optional[str] = None
        self._ndi_name: str = ""
        self._after_id: Optional[str] = None
        self._current_idx: int = 0
        self._stage_window_ref: Optional[tk.Toplevel] = None  # for stage_capture mode
        self._last_error: str = ""

        # Observers — kaldes når state ændrer sig (status indicator bruger dette)
        self._status_listeners: list = []
        # Frame observers — kaldes når en ny frame er renderet (preview bruger dette)
        self._frame_listeners: list = []
        self._last_frame = None  # cached til preview-vinduer der åbnes senere

    # ------------------------------------------------------------------
    #  Listeners (observer pattern for UI)
    # ------------------------------------------------------------------
    def add_status_listener(self, callback: Callable[[], None]) -> None:
        """Tilføj en callback der kaldes hver gang start/stop/fejl-state ændres.

        Bruges typisk af status-indikatoren i hovedvinduet.
        """
        if callback not in self._status_listeners:
            self._status_listeners.append(callback)

    def remove_status_listener(self, callback: Callable[[], None]) -> None:
        if callback in self._status_listeners:
            self._status_listeners.remove(callback)

    def add_frame_listener(self, callback: Callable) -> None:
        """Tilføj en callback der får hver renderet PIL-frame leveret.

        Bruges af preview-vindue der vil vise live-billede uden at lave
        sin egen render-loop (vi har allerede én kørende).
        """
        if callback not in self._frame_listeners:
            self._frame_listeners.append(callback)

    def remove_frame_listener(self, callback: Callable) -> None:
        if callback in self._frame_listeners:
            self._frame_listeners.remove(callback)

    def _notify_status(self) -> None:
        for cb in list(self._status_listeners):
            try:
                cb()
            except Exception as e:  # noqa: BLE001
                print(f"[NDIBroadcaster] status listener fejl: {e}")

    def _notify_frame(self, frame) -> None:
        for cb in list(self._frame_listeners):
            try:
                cb(frame)
            except Exception as e:  # noqa: BLE001
                print(f"[NDIBroadcaster] frame listener fejl: {e}")

    # ------------------------------------------------------------------
    #  Public API
    # ------------------------------------------------------------------
    def is_active(self) -> bool:
        """True hvis broadcasten kører lige nu."""
        return self._sender is not None and not self._sender.closed

    def get_mode(self) -> Optional[str]:
        """Returnér nuværende mode ('notes' / 'stage_capture') eller None."""
        return self._mode if self.is_active() else None

    def get_ndi_name(self) -> str:
        """Det NDI-navn vi annoncerer os som (synligt i OBS)."""
        return self._ndi_name if self.is_active() else ""

    def get_last_error(self) -> str:
        """Sidste fejl-besked (tom streng hvis ingen)."""
        return self._last_error

    def get_last_frame(self):
        """Returnér den senest renderede PIL-frame (eller None hvis ingen)."""
        return self._last_frame

    def get_current_index(self) -> int:
        return self._current_idx

    def set_current_index(self, idx: int) -> None:
        """Skift hvilken sang der vises som 'NUVÆRENDE' i NDI-feed'et.

        Effekt'en mærkes i næste render-tick (max 100ms).
        """
        items = self.model.current_setlist.get("songs", [])
        if not items:
            return
        idx = max(0, min(idx, len(items) - 1))
        # Spring markører over
        while idx < len(items) and is_marker_item(items[idx]):
            idx += 1
        if idx >= len(items):
            return
        self._current_idx = idx

    def set_stage_window(self, stage_window: Optional[tk.Toplevel]) -> None:
        """Når mode = stage_capture: hvilken Toplevel vi skal grabbe."""
        self._stage_window_ref = stage_window

    def start(
        self,
        mode: str = MODE_NOTES,
        ndi_name: str = "Setlist Manager",
        start_index: Optional[int] = None,
    ) -> bool:
        """Start broadcasten. Returnerer True hvis det lykkedes.

        Hvis NDI ikke er tilgængeligt eller sender-oprettelse fejler,
        returneres False og _last_error sættes med detaljer.
        """
        # Stop evt. tidligere broadcast først
        if self.is_active():
            self.stop()

        if not ndi_output.is_available():
            self._last_error = ndi_output.get_install_help()
            self._notify_status()
            return False

        try:
            self._sender = ndi_output.NDISender(name=ndi_name)
        except ndi_output.NDIError as e:
            self._last_error = str(e)
            self._sender = None
            self._notify_status()
            return False
        except Exception as e:  # noqa: BLE001
            self._last_error = f"Uventet fejl: {type(e).__name__}: {e}"
            self._sender = None
            self._notify_status()
            return False

        self._mode = mode
        self._ndi_name = ndi_name
        if start_index is not None:
            self.set_current_index(start_index)
        self._last_error = ""

        # Start render-loop
        self._schedule_next_tick()
        self._notify_status()
        return True

    def stop(self) -> None:
        """Stop broadcasten og ryd NDI-sender op."""
        # Stop loop først
        if self._after_id is not None:
            try:
                self.root.after_cancel(self._after_id)
            except tk.TclError:
                pass
            self._after_id = None

        # Luk sender
        if self._sender is not None:
            try:
                self._sender.close()
            except Exception:  # noqa: BLE001
                pass
            self._sender = None

        self._mode = None
        self._ndi_name = ""
        self._last_frame = None
        self._stage_window_ref = None
        self._notify_status()

    # ------------------------------------------------------------------
    #  Render loop
    # ------------------------------------------------------------------
    def _schedule_next_tick(self) -> None:
        if not self.is_active():
            return
        try:
            self._after_id = self.root.after(RENDER_INTERVAL_MS, self._tick)
        except tk.TclError:
            # Root er ved at lukke ned — stop pænt
            self.stop()

    def _tick(self) -> None:
        """Render én frame + send."""
        if not self.is_active():
            return

        try:
            if self._mode == MODE_NOTES:
                self._render_and_send_notes()
            elif self._mode == MODE_STAGE_CAPTURE:
                self._capture_and_send_stage()
            else:
                # Ukendt mode — stop for at undgå tight loop
                self.stop()
                return
        except Exception as e:  # noqa: BLE001
            self._last_error = f"Render-fejl: {type(e).__name__}: {e}"
            self._notify_status()

        # Re-schedule (også selvom denne tick fejlede — vi vil prøve igen)
        self._schedule_next_tick()

    def _render_and_send_notes(self) -> None:
        """MODE_NOTES: render pænt notes-billede og send."""
        current, nxt = get_current_and_next(self.model, self._current_idx)

        items = self.model.current_setlist.get("songs", [])
        song_num = sum(
            1 for it in items[: self._current_idx + 1] if not is_marker_item(it)
        )
        total = sum(1 for it in items if not is_marker_item(it))
        pos_str = f"Sang {song_num} af {total}" if song_num > 0 else ""

        sl_name = self.model.current_setlist.get("name", "")

        img = render_notes_frame(
            current_song=current,
            next_song=nxt,
            setlist_name=sl_name,
            song_position=pos_str,
            width=NDI_WIDTH,
            height=NDI_HEIGHT,
        )
        if img is None:
            self._last_error = "Pillow mangler — kan ikke rendere"
            self._notify_status()
            return

        try:
            self._sender.send_pil_image(img, fps=10.0)
            self._last_error = ""
        except ndi_output.NDIError as e:
            self._last_error = f"NDI send fejl: {e}"
            self._notify_status()
            return

        self._last_frame = img
        self._notify_frame(img)

    def _capture_and_send_stage(self) -> None:
        """MODE_STAGE_CAPTURE: screen-grab af Stage Mode vinduet og send."""
        try:
            from PIL import ImageGrab  # type: ignore[import-not-found]
        except ImportError:
            self._last_error = "Pillow ImageGrab mangler — kan ikke fange skærm"
            self._notify_status()
            return

        win = self._stage_window_ref
        if win is None:
            self._last_error = "Ingen Stage Mode-vindue at fange"
            self._notify_status()
            return

        try:
            if not win.winfo_exists():
                # Stage Mode lukket — stop broadcast
                self.stop()
                return
        except tk.TclError:
            self.stop()
            return

        try:
            x = win.winfo_rootx()
            y = win.winfo_rooty()
            w = win.winfo_width()
            h = win.winfo_height()
            if w < 10 or h < 10:
                return  # vinduet er ikke klar endnu

            grabbed = ImageGrab.grab(bbox=(x, y, x + w, y + h))
            self._sender.send_pil_image(grabbed, fps=10.0)
            self._last_error = ""
            self._last_frame = grabbed
            self._notify_frame(grabbed)
        except Exception as e:  # noqa: BLE001
            self._last_error = f"Capture fejl: {e}"
            self._notify_status()
