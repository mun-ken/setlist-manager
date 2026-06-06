"""Dialog til at konfigurere Stage Mode hotkeys.

Brugeren ser en liste af handlinger med deres nuværende tast-bindings.
For hver handling kan de:
    * Klikke på en eksisterende tast for at fjerne den
    * Klikke "+ Tilføj tast" og trykke på en tast for at binde
    * Klikke "Nulstil" for at vende tilbage til defaults

Layout:
    ┌──────────────────────────────────────────────────────────┐
    │  Tilpas Stage Mode hotkeys                          [X]  │
    ├──────────────────────────────────────────────────────────┤
    │  Navigation                                              │
    │    Næste sang         [Mellemrum] [→] [+ Tilføj]         │
    │    Forrige sang       [← Venstre] [↑] [+ Tilføj]         │
    │    Første sang        [Home] [+ Tilføj]                  │
    │    ...                                                   │
    │  Visning                                                 │
    │    Fuldskærm          [F] [+ Tilføj]                     │
    │  Andet                                                   │
    │    Luk Stage Mode     [Esc] [Q] [+ Tilføj]               │
    ├──────────────────────────────────────────────────────────┤
    │  [Nulstil alle til defaults]    [Annuller]  [Gem]        │
    └──────────────────────────────────────────────────────────┘
"""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk
from typing import Callable, Optional

from hotkeys import (
    ACTIONS, CATEGORIES_ORDER, KeyBindings, event_to_binding, format_key,
)


class HotkeysDialog(tk.Toplevel):
    """Modal dialog til at sætte custom hotkeys.

    Brug:
        dlg = HotkeysDialog(parent, current_bindings)
        dlg.wait_window()
        if dlg.result is not None:
            # Brugeren klikkede Gem
            new_bindings = dlg.result
    """

    def __init__(
        self,
        parent: tk.Misc,
        bindings: Optional[KeyBindings] = None,
        on_apply: Optional[Callable[[KeyBindings], None]] = None,
    ) -> None:
        super().__init__(parent)
        self.parent = parent
        # Vi arbejder på en KOPI så Cancel ikke ændrer originalen
        if bindings is None:
            bindings = KeyBindings.load()
        self.bindings = KeyBindings(bindings.to_dict())
        self.on_apply = on_apply  # callback hvis vi vil "Anvend" live

        self.result: Optional[KeyBindings] = None

        self.title("Tilpas Stage Mode hotkeys")
        self.transient(parent)
        self.resizable(True, True)
        self.minsize(560, 480)
        self.geometry("680x600")

        # Modal grab så hovedvinduet ikke kan klikkes på
        try:
            self.grab_set()
        except tk.TclError:
            pass

        self._build_ui()
        self._refresh_rows()

        # Esc lukker dialogen som "annuller"
        self.bind("<Escape>", lambda e: self._cancel())
        self.protocol("WM_DELETE_WINDOW", self._cancel)

        self.focus_set()

    # ------------------------------------------------------------------
    #  UI construction
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        # === Header ===
        header = ttk.Frame(self, padding=(20, 16, 20, 8))
        header.pack(side=tk.TOP, fill=tk.X)
        ttk.Label(
            header,
            text="⌨️  Tilpas Stage Mode hotkeys",
            font=("Segoe UI", 14, "bold"),
        ).pack(anchor="w")
        ttk.Label(
            header,
            text="Klik på en tast for at fjerne den. Klik '+ Tilføj' og tryk "
                 "på en tast for at binde den til handlingen.",
            foreground="#666",
            wraplength=620,
            justify="left",
        ).pack(anchor="w", pady=(4, 0))

        # === Hovedindhold: scrollende liste af handlinger ===
        main = ttk.Frame(self)
        main.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=20, pady=(8, 8))

        # Canvas + scrollbar for at kunne scrolle hvis mange actions
        self.canvas = tk.Canvas(main, highlightthickness=0, bd=0)
        vsb = ttk.Scrollbar(main, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Indre frame til rows
        self.rows_frame = ttk.Frame(self.canvas)
        self.canvas_window = self.canvas.create_window(
            (0, 0), window=self.rows_frame, anchor="nw",
        )

        def on_canvas_configure(e):
            self.canvas.itemconfig(self.canvas_window, width=e.width)
            self.canvas.configure(scrollregion=self.canvas.bbox("all"))

        def on_inner_configure(_e):
            self.canvas.configure(scrollregion=self.canvas.bbox("all"))

        self.canvas.bind("<Configure>", on_canvas_configure)
        self.rows_frame.bind("<Configure>", on_inner_configure)

        # Mousewheel scroll i listen
        def on_mw(event):
            if event.delta:
                self.canvas.yview_scroll(int(-event.delta / 30), "units")
        self.canvas.bind("<MouseWheel>", on_mw)

        # === Bottom: Reset + Cancel + Save ===
        bottom = ttk.Frame(self, padding=(20, 8, 20, 16))
        bottom.pack(side=tk.BOTTOM, fill=tk.X)

        ttk.Button(
            bottom, text="↺ Nulstil alle til defaults",
            command=self._reset_all,
        ).pack(side=tk.LEFT)

        ttk.Button(
            bottom, text="Annuller",
            command=self._cancel,
        ).pack(side=tk.RIGHT, padx=(8, 0))

        ttk.Button(
            bottom, text="💾 Gem",
            command=self._save,
        ).pack(side=tk.RIGHT)

    # ------------------------------------------------------------------
    #  Refresh / build action rows
    # ------------------------------------------------------------------
    def _refresh_rows(self) -> None:
        """Slet og genopbyg alle rows fra self.bindings."""
        for child in self.rows_frame.winfo_children():
            child.destroy()

        for cat in CATEGORIES_ORDER:
            # Category header
            cat_actions = [
                aid for aid, info in ACTIONS.items() if info["category"] == cat
            ]
            if not cat_actions:
                continue

            cat_label = ttk.Label(
                self.rows_frame, text=cat,
                font=("Segoe UI", 11, "bold"),
                foreground="#444",
            )
            cat_label.pack(anchor="w", pady=(12, 4), padx=4)

            for aid in cat_actions:
                self._build_action_row(aid)

    def _build_action_row(self, action_id: str) -> None:
        """Bygger én række for en handling med dens nuværende keys."""
        info = ACTIONS[action_id]
        row = ttk.Frame(self.rows_frame, padding=(8, 4, 8, 4))
        row.pack(fill=tk.X, padx=4, pady=2)

        # Venstre: label (fast bredde for at få keys på linje)
        label = ttk.Label(
            row, text=info["label"],
            font=("Segoe UI", 10),
            width=22, anchor="w",
        )
        label.pack(side=tk.LEFT)

        # Højre side: keys (som "chips") + "+ Tilføj" knap
        keys_frame = ttk.Frame(row)
        keys_frame.pack(side=tk.LEFT, fill=tk.X, expand=True)

        keys = self.bindings.get_keys(action_id)
        if not keys:
            ttk.Label(
                keys_frame, text="(ingen tast)",
                foreground="#999", font=("Segoe UI", 10, "italic"),
            ).pack(side=tk.LEFT, padx=(0, 6))
        else:
            for key in keys:
                self._make_key_chip(keys_frame, action_id, key)

        ttk.Button(
            keys_frame, text="+ Tilføj tast",
            command=lambda: self._add_key_for(action_id),
            width=14,
        ).pack(side=tk.LEFT, padx=(4, 0))

        # Hvis ikke default — vis "Reset" knap
        if not self.bindings.is_default(action_id):
            ttk.Button(
                row, text="↺",
                width=3,
                command=lambda: self._reset_action(action_id),
            ).pack(side=tk.RIGHT, padx=(4, 0))

    def _make_key_chip(self, parent: ttk.Frame, action_id: str, key: str) -> None:
        """Lav en lille 'chip' der viser tasten + ❌ for at fjerne."""
        chip = tk.Frame(parent, bg="#e8e8ed", bd=1, relief=tk.SOLID)
        chip.pack(side=tk.LEFT, padx=(0, 6))
        tk.Label(
            chip, text=format_key(key),
            bg="#e8e8ed", fg="#1a1a1d",
            font=("Segoe UI", 10),
            padx=8, pady=3,
        ).pack(side=tk.LEFT)
        # ❌-knap
        x_btn = tk.Label(
            chip, text="✕",
            bg="#e8e8ed", fg="#8a8a8e",
            font=("Segoe UI", 10, "bold"),
            cursor="hand2",
            padx=6, pady=3,
        )
        x_btn.pack(side=tk.LEFT)
        x_btn.bind(
            "<Button-1>",
            lambda e, a=action_id, k=key: self._remove_key(a, k),
        )

        # Hover effect
        def on_enter(_e):
            x_btn.configure(fg="#d70015", bg="#ffe5e8")
        def on_leave(_e):
            x_btn.configure(fg="#8a8a8e", bg="#e8e8ed")
        x_btn.bind("<Enter>", on_enter)
        x_btn.bind("<Leave>", on_leave)

    # ------------------------------------------------------------------
    #  Actions: add/remove/reset
    # ------------------------------------------------------------------
    def _add_key_for(self, action_id: str) -> None:
        """Åbn en lille dialog der venter på et tastetryk."""
        info = ACTIONS[action_id]
        capture = _KeyCaptureDialog(self, action_label=info["label"])
        self.wait_window(capture)
        if capture.captured_key is None:
            return  # bruger annullerede

        key = capture.captured_key

        # Tjek for konflikt med en ANDEN handling
        conflict_action = self.bindings.find_conflict(key, exclude_action=action_id)
        if conflict_action:
            conflict_label = ACTIONS[conflict_action]["label"]
            if not messagebox.askyesno(
                "Tast allerede brugt",
                f"Tasten '{format_key(key)}' er allerede bundet til "
                f"\"{conflict_label}\".\n\n"
                f"Vil du flytte den til \"{info['label']}\" i stedet?\n"
                f"(Den fjernes fra \"{conflict_label}\".)",
                parent=self,
            ):
                return
            # Fjern fra den anden action
            self.bindings.remove_key(conflict_action, key)

        # Tilføj til den valgte action
        added = self.bindings.add_key(action_id, key)
        if not added:
            # Allerede bundet til samme action — ingen ændring
            messagebox.showinfo(
                "Allerede bundet",
                f"Tasten '{format_key(key)}' er allerede bundet til "
                f"\"{info['label']}\".",
                parent=self,
            )
            return

        self._refresh_rows()

    def _remove_key(self, action_id: str, key: str) -> None:
        self.bindings.remove_key(action_id, key)
        self._refresh_rows()

    def _reset_action(self, action_id: str) -> None:
        self.bindings.reset_action(action_id)
        self._refresh_rows()

    def _reset_all(self) -> None:
        if not messagebox.askyesno(
            "Nulstil alle hotkeys",
            "Sikker på du vil sætte ALLE hotkeys tilbage til defaults?\n\n"
            "Dine egne ændringer går tabt.",
            parent=self,
        ):
            return
        self.bindings.reset_all()
        self._refresh_rows()

    # ------------------------------------------------------------------
    #  Save / cancel
    # ------------------------------------------------------------------
    def _save(self) -> None:
        # Persistér til disk
        self.bindings.save()
        self.result = self.bindings
        # Kald evt. on_apply så Stage Mode (hvis åben) opdaterer øjeblikkeligt
        if self.on_apply is not None:
            try:
                self.on_apply(self.bindings)
            except Exception:  # noqa: BLE001
                pass
        self._close()

    def _cancel(self) -> None:
        self.result = None
        self._close()

    def _close(self) -> None:
        try:
            self.grab_release()
        except tk.TclError:
            pass
        self.destroy()


# ===========================================================================
#  Lille subdialog: vent på ét tastetryk
# ===========================================================================
class _KeyCaptureDialog(tk.Toplevel):
    """Modal dialog der viser 'Tryk på en tast...' og fanger næste keypress."""

    def __init__(self, parent: tk.Misc, action_label: str) -> None:
        super().__init__(parent)
        self.captured_key: Optional[str] = None

        self.title("Tryk på en tast")
        self.transient(parent)
        self.resizable(False, False)

        # Center over parent
        try:
            self.geometry("420x180")
            px = parent.winfo_rootx() + parent.winfo_width() // 2 - 210
            py = parent.winfo_rooty() + parent.winfo_height() // 2 - 90
            self.geometry(f"+{px}+{py}")
        except tk.TclError:
            pass

        try:
            self.grab_set()
        except tk.TclError:
            pass

        # UI
        frm = ttk.Frame(self, padding=24)
        frm.pack(fill=tk.BOTH, expand=True)

        ttk.Label(
            frm, text=f"Bind tast til:",
            foreground="#666", font=("Segoe UI", 10),
        ).pack(anchor="w")
        ttk.Label(
            frm, text=action_label,
            font=("Segoe UI", 12, "bold"),
        ).pack(anchor="w", pady=(0, 16))

        self.status = ttk.Label(
            frm,
            text="⌨️  Tryk på en tast nu...",
            font=("Segoe UI", 11),
            foreground="#0066cc",
        )
        self.status.pack(anchor="center", pady=8)

        ttk.Label(
            frm, text="(Esc for at annullere)",
            foreground="#999", font=("Segoe UI", 9, "italic"),
        ).pack(anchor="center", pady=(4, 0))

        # Bind ALLE tastetryk til at fange
        # NB: <KeyPress> matcher alt — vi filtrerer i handler
        self.bind("<KeyPress>", self._on_keypress)
        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self.focus_set()

    def _on_keypress(self, event) -> None:
        # Esc = annuller (uden at gemme Esc som binding)
        if event.keysym == "Escape":
            self._cancel()
            return

        binding = event_to_binding(event)
        if binding is None:
            # Det var en modifier-only — vent på rigtig tast
            self.status.configure(
                text="⌨️  Tryk på en TAST (ikke kun Shift/Ctrl/Alt)...",
            )
            return

        self.captured_key = binding
        self._close()

    def _cancel(self) -> None:
        self.captured_key = None
        self._close()

    def _close(self) -> None:
        try:
            self.grab_release()
        except tk.TclError:
            pass
        self.destroy()
