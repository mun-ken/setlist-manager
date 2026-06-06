"""Globale hotkeys — virker selv hvis et andet vindue (fx OBS) har focus.

Bruger `keyboard`-library på Windows og macOS. Det starter et lavt-niveau
keyboard hook der opfanger taste-events for HELE systemet (ikke kun vores
vindue). Det betyder at brugeren kan styre Stage Mode med pile-tasterne
mens de bruger OBS, vMix eller andre apps.

VIGTIGT om permissions:
-----------------------
* Windows: ingen admin nødvendig. Hook'en kører via SetWindowsHookEx.
* macOS:   kræver "Accessibility"-tilladelse (Sikkerhed & beskyttelse).
           Brugeren bliver bedt om det første gang. Hvis ikke givet:
           hotkeys virker IKKE, men appen crasher ikke.
* Linux:   kræver typisk root (læser fra /dev/input). Vi understøtter ikke
           Linux i dette modul.

Designprincippet er at det skal være SIKKERT:
* Modulet kan importeres uden at noget bliver hook'et.
* Hooks tilføjes først eksplicit via register() og fjernes via unregister_all().
* Hvis keyboard-library mangler eller fejler → vi falder pænt tilbage til
  Tkinter's lokale bind, og brugeren får en hjælpsom besked.

Eksempel:
    from global_hotkeys import GlobalHotkeys
    gh = GlobalHotkeys(root)
    gh.register("right", on_next_song)
    gh.register("left", on_prev_song)
    # ... senere når Stage Mode lukker:
    gh.unregister_all()
"""

from __future__ import annotations

import sys
from typing import Callable, Dict, List, Optional

try:
    import keyboard as _kb  # type: ignore[import-not-found]
    _KEYBOARD_AVAILABLE = True
    _KEYBOARD_IMPORT_ERROR: Optional[str] = None
except ImportError as e:
    _kb = None  # type: ignore[assignment]
    _KEYBOARD_AVAILABLE = False
    _KEYBOARD_IMPORT_ERROR = str(e)


# ===========================================================================
#  Konvertering: Tkinter binding-syntaks → keyboard-library syntaks
# ===========================================================================
# Tkinter bruger "<space>", "<Right>", etc. — keyboard bruger "space", "right"
_TK_TO_KEYBOARD: Dict[str, str] = {
    "<space>": "space",
    "<Return>": "enter",
    "<KP_Enter>": "enter",
    "<BackSpace>": "backspace",
    "<Escape>": "esc",
    "<Tab>": "tab",
    "<Left>": "left",
    "<Right>": "right",
    "<Up>": "up",
    "<Down>": "down",
    "<Home>": "home",
    "<End>": "end",
    "<Prior>": "page up",
    "<Next>": "page down",
    "<Insert>": "insert",
    "<Delete>": "delete",
    "<F1>": "f1", "<F2>": "f2", "<F3>": "f3", "<F4>": "f4",
    "<F5>": "f5", "<F6>": "f6", "<F7>": "f7", "<F8>": "f8",
    "<F9>": "f9", "<F10>": "f10", "<F11>": "f11", "<F12>": "f12",
}


def tk_binding_to_keyboard(tk_binding: str) -> Optional[str]:
    """Konverter en Tkinter-binding til keyboard-library format.

    Returnerer None hvis bindingen ikke kan oversættes (fx museknap eller
    custom modifier-kombinationer som vi ikke understøtter globalt endnu).

    Eksempler:
        "<space>"  → "space"
        "<Right>"  → "right"
        "f"        → "f"           (bogstaver er ens)
        "<Button-1>" → None        (museknap kan ikke være global)
    """
    if not tk_binding:
        return None

    # Direkte mapping for kendte specielle taster
    if tk_binding in _TK_TO_KEYBOARD:
        return _TK_TO_KEYBOARD[tk_binding]

    # Enkelt bogstav/tal (ikke pakket ind i < >)
    if len(tk_binding) == 1:
        return tk_binding.lower()

    # Museknapper ignoreres (kan ikke registreres globalt)
    if tk_binding.startswith("<Button-"):
        return None

    # Hvis ikke genkendt — prøv at strippe < > og bruge lowercase
    if tk_binding.startswith("<") and tk_binding.endswith(">"):
        inner = tk_binding[1:-1].lower()
        return inner

    return tk_binding.lower()


# ===========================================================================
#  GlobalHotkeys — hold styr på alle registrerede globale hooks
# ===========================================================================
class GlobalHotkeys:
    """Manager for system-wide keyboard hooks.

    En instans af denne klasse repræsenterer ÉN sæt globale hotkeys (typisk
    knyttet til Stage Mode). Når Stage Mode lukker kalder man unregister_all()
    for at fjerne alle hooks så de ikke blokerer keyboardet for andre apps.

    Lifecycle:
        gh = GlobalHotkeys(root)
        if gh.is_supported():
            gh.register("right", on_next)
            gh.register("left", on_prev)
        # ... senere:
        gh.unregister_all()
    """

    def __init__(self, root) -> None:
        """root: Tk root — bruges til at marshalle callbacks tilbage til
        main thread (keyboard-library kalder dem fra en background thread,
        og Tkinter er ikke thread-safe)."""
        self.root = root
        # Liste over hook handles vi har registreret (til oprydning)
        self._hook_handles: List = []
        # Map fra hotkey-streng → callback (for debugging / introspection)
        self._registered: Dict[str, Callable] = {}

    # ------------------------------------------------------------------
    @staticmethod
    def is_supported() -> bool:
        """True hvis platformen kan understøtte globale hotkeys."""
        if not _KEYBOARD_AVAILABLE:
            return False
        # Linux uden root virker ikke pålideligt — vi skipper
        if sys.platform.startswith("linux"):
            return False
        return True

    @staticmethod
    def get_unsupported_reason() -> str:
        """Hjælpsom besked om hvorfor globale hotkeys ikke virker."""
        if not _KEYBOARD_AVAILABLE:
            return (
                "Python-modulet 'keyboard' er ikke installeret.\n\n"
                "Installer med:  pip install keyboard\n\n"
                f"(Importfejl: {_KEYBOARD_IMPORT_ERROR})"
            )
        if sys.platform.startswith("linux"):
            return (
                "Globale hotkeys understøttes ikke på Linux i denne version "
                "(kræver typisk root-rettigheder). Brug Stage Mode med "
                "vindue-focus i stedet."
            )
        return ""

    # ------------------------------------------------------------------
    def register(self, hotkey: str, callback: Callable[[], None]) -> bool:
        """Registrer en global hotkey.

        Args:
            hotkey: keyboard-library format (fx "right", "ctrl+shift+n").
            callback: kaldes når tasten trykkes — på main thread via root.after.

        Returns:
            True hvis det lykkedes, False hvis platformen ikke understøtter
            globale hotkeys eller hvis registrering fejlede.
        """
        if not self.is_supported():
            return False

        # Wrap callback så det kører på Tk main thread (keyboard's hook er
        # en separat thread og Tkinter er ikke thread-safe)
        def _safe_callback():
            try:
                self.root.after(0, callback)
            except Exception:  # noqa: BLE001
                pass  # root er måske ved at lukke

        try:
            handle = _kb.add_hotkey(  # type: ignore[union-attr]
                hotkey, _safe_callback,
                suppress=False,  # tillad andre apps også at se tasten
                trigger_on_release=False,
            )
            self._hook_handles.append(handle)
            self._registered[hotkey] = callback
            return True
        except Exception as e:  # noqa: BLE001
            # Kan ske hvis hotkey-strengen er ugyldig
            print(f"[GlobalHotkeys] Kunne ikke registrere '{hotkey}': {e}")
            return False

    def register_many(
        self,
        bindings: Dict[str, Callable[[], None]],
    ) -> Dict[str, bool]:
        """Bekvem helper til at registrere flere hotkeys ad gangen.

        Returns: dict med hver hotkey → True/False for om det lykkedes.
        """
        return {hk: self.register(hk, cb) for hk, cb in bindings.items()}

    # ------------------------------------------------------------------
    def unregister_all(self) -> None:
        """Fjern alle registrerede hotkeys (kald før Stage Mode lukker)."""
        if not _KEYBOARD_AVAILABLE:
            return
        for handle in self._hook_handles:
            try:
                _kb.remove_hotkey(handle)  # type: ignore[union-attr]
            except (KeyError, ValueError):
                pass  # allerede fjernet
            except Exception as e:  # noqa: BLE001
                print(f"[GlobalHotkeys] Fejl ved unregister: {e}")
        self._hook_handles.clear()
        self._registered.clear()

    def get_registered(self) -> Dict[str, Callable]:
        """Returnér en kopi af alle aktuelt registrerede hotkeys."""
        return dict(self._registered)

    def __len__(self) -> int:
        return len(self._hook_handles)


# ===========================================================================
#  Settings: husk om brugeren vil have globale hotkeys aktive
# ===========================================================================
# Vi gemmer i samme directory som hotkeys.json så det er samlet
_SETTINGS_FILENAME = "global_hotkeys.json"


def _settings_path():
    """Sti til settings-filen."""
    from setlist_model import default_data_dir
    return default_data_dir() / _SETTINGS_FILENAME


def is_enabled() -> bool:
    """True hvis brugeren har slået globale hotkeys til."""
    import json
    try:
        path = _settings_path()
        if not path.exists():
            return False  # standard: slukket (opt-in)
        data = json.loads(path.read_text(encoding="utf-8"))
        return bool(data.get("enabled", False))
    except Exception:  # noqa: BLE001
        return False


def set_enabled(enabled: bool) -> None:
    """Gem brugerens valg."""
    import json
    try:
        path = _settings_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"enabled": bool(enabled)}, indent=2),
            encoding="utf-8",
        )
    except Exception as e:  # noqa: BLE001
        print(f"[GlobalHotkeys] Kunne ikke gemme settings: {e}")
