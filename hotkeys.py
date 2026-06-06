"""Brugerdefinerbare hotkeys til Stage Mode (live performance).

Lader brugeren binde hvilke som helst taster til hvilke som helst handlinger
i Stage Mode. Default-bindings matcher v1.4.7 så brugere der ikke gør noget
mærker INGEN forskel.

Arkitektur:
-----------
ACTIONS         — registry over alle handlinger (id → label + default keys)
KeyBindings     — load/save/query bindings (én JSON-fil på disk)
format_key()    — gør Tk-binding ('<space>') læselig ('Mellemrum')
event_to_binding() — gør et Tk Event → binding-streng vi kan gemme

Storage: ~/.setlist_manager/hotkeys.json (eller %APPDATA%/SetlistManager/)
samme mappe som model autosave bruger.

Eksempel:
    bindings = KeyBindings.load()
    for key in bindings.get_keys("next_song"):
        widget.bind(key, lambda e: do_next())
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional

from setlist_model import default_data_dir


# ===========================================================================
#  Handlings-registry — disse er de eneste ting brugeren kan binde til
# ===========================================================================
# Hver action har:
#   label    — vist til brugeren i konfigurations-dialogen (på dansk)
#   default  — liste af Tk binding-strenge der bruges hvis ingen
#              custom binding er sat
#   category — gruppering i UI ("Navigation", "Visning", "Andet")
ACTIONS: Dict[str, Dict] = {
    "next_song": {
        "label": "Næste sang",
        "default": ["<space>", "<Right>", "<Down>", "<Return>", "<KP_Enter>"],
        "category": "Navigation",
    },
    "prev_song": {
        "label": "Forrige sang",
        "default": ["<Left>", "<Up>", "<BackSpace>"],
        "category": "Navigation",
    },
    "first_song": {
        "label": "Første sang",
        "default": ["<Home>"],
        "category": "Navigation",
    },
    "last_song": {
        "label": "Sidste sang",
        "default": ["<End>"],
        "category": "Navigation",
    },
    "toggle_fullscreen": {
        "label": "Fuldskærm til/fra",
        "default": ["f", "F"],
        "category": "Visning",
    },
    "close": {
        "label": "Luk Stage Mode",
        "default": ["<Escape>", "q", "Q"],
        "category": "Andet",
    },
}

CATEGORIES_ORDER = ["Navigation", "Visning", "Andet"]


# ===========================================================================
#  Visning af binding-strenge for brugeren
# ===========================================================================
# Map fra Tk binding-syntaks til dansk visnings-navn
_DISPLAY_NAMES: Dict[str, str] = {
    "<space>": "Mellemrum",
    "<Return>": "Enter",
    "<KP_Enter>": "Enter (numpad)",
    "<BackSpace>": "Backspace",
    "<Escape>": "Esc",
    "<Tab>": "Tab",
    "<Left>": "← Venstre",
    "<Right>": "→ Højre",
    "<Up>": "↑ Op",
    "<Down>": "↓ Ned",
    "<Home>": "Home",
    "<End>": "End",
    "<Prior>": "Page Up",
    "<Next>": "Page Down",
    "<Insert>": "Insert",
    "<Delete>": "Delete",
    "<F1>": "F1", "<F2>": "F2", "<F3>": "F3", "<F4>": "F4",
    "<F5>": "F5", "<F6>": "F6", "<F7>": "F7", "<F8>": "F8",
    "<F9>": "F9", "<F10>": "F10", "<F11>": "F11", "<F12>": "F12",
    "<Button-1>": "Venstre-klik",
    "<Button-2>": "Midter-klik",
    "<Button-3>": "Højre-klik",
}


def format_key(binding: str) -> str:
    """Gør en Tk binding-streng læselig.

    >>> format_key("<space>")
    'Mellemrum'
    >>> format_key("F")
    'F'
    >>> format_key("<Control-s>")
    'Ctrl+S'
    """
    if not binding:
        return ""
    # Special-cases først
    if binding in _DISPLAY_NAMES:
        return _DISPLAY_NAMES[binding]

    # Modifier-kombinationer: <Control-s>, <Shift-Return>, <Alt-F4>
    if binding.startswith("<") and binding.endswith(">") and "-" in binding:
        inner = binding[1:-1]
        parts = inner.split("-")
        # Sidste del er tasten, resten er modifiers
        mods = parts[:-1]
        key = parts[-1]
        # Dansk modifier-navne
        mod_map = {
            "Control": "Ctrl",
            "Shift": "Shift",
            "Alt": "Alt",
            "Meta": "Cmd",
            "Command": "Cmd",
        }
        display_mods = [mod_map.get(m, m) for m in mods]
        # Slå keyspecifikke navne op (fx <Control-Return>)
        key_display = _DISPLAY_NAMES.get(f"<{key}>", key.upper() if len(key) == 1 else key)
        return "+".join(display_mods + [key_display])

    # Almindelig tast — vis bare den selv (store bogstaver mere læseligt)
    if len(binding) == 1:
        return binding.upper()
    # Fjern <> hvis vi ikke kender navnet
    if binding.startswith("<") and binding.endswith(">"):
        return binding[1:-1]
    return binding


def event_to_binding(event) -> Optional[str]:
    """Konvertér et Tkinter KeyPress-event til en binding-streng vi kan gemme.

    Returnerer None hvis tasten ikke er nyttig (fx kun en modifier alene).

    Eksempler på output:
        Tryk på A           → "a"  (lowercase, så Caps Lock er irrelevant)
        Tryk på Shift+A     → "<Shift-A>"
        Tryk på Mellemrum   → "<space>"
        Tryk på Ctrl+S      → "<Control-s>"
        Tryk på F5          → "<F5>"
        Tryk på højre pil   → "<Right>"
    """
    keysym = getattr(event, "keysym", "")
    if not keysym:
        return None

    # Ignorer modifier-only events (vi vil have rigtig tast bundet til)
    if keysym in ("Shift_L", "Shift_R", "Control_L", "Control_R",
                  "Alt_L", "Alt_R", "Meta_L", "Meta_R",
                  "Super_L", "Super_R", "Caps_Lock", "Num_Lock",
                  "ISO_Level3_Shift", "Mode_switch"):
        return None

    # Modifier-state: event.state bit-masker
    state = getattr(event, "state", 0)
    # Tkinter state-bits: 0x0001=Shift, 0x0004=Control, 0x0008=Alt(Linux)/0x20000=Alt(Win)
    # Mac Meta er typisk 0x0010 men varierer — vi bruger en safe heuristik
    has_shift = bool(state & 0x0001)
    has_ctrl = bool(state & 0x0004)
    has_alt = bool(state & 0x0008) or bool(state & 0x20000)
    has_meta = bool(state & 0x0010) and not has_alt  # macOS Cmd

    mods = []
    if has_ctrl:
        mods.append("Control")
    if has_alt:
        mods.append("Alt")
    if has_meta:
        mods.append("Meta")

    # Specifikke keysym → binding
    # Tk-konvention: angle brackets omkring named keys
    NAMED_KEYS = {
        "space", "Return", "KP_Enter", "BackSpace", "Escape", "Tab",
        "Left", "Right", "Up", "Down", "Home", "End", "Prior", "Next",
        "Insert", "Delete",
        "F1", "F2", "F3", "F4", "F5", "F6", "F7", "F8",
        "F9", "F10", "F11", "F12",
    }

    if keysym in NAMED_KEYS:
        if has_shift:
            mods.append("Shift")
        if mods:
            return f"<{'-'.join(mods)}-{keysym}>"
        return f"<{keysym}>"

    # Almindelige bogstaver/tal — brug event.char hvis det er printable
    char = getattr(event, "char", "")
    if len(keysym) == 1 and keysym.isprintable():
        # Hvis Shift er trykket OG der er en modifier (Ctrl/Alt), brug Shift- prefix
        # Ellers ignorer Shift — den er allerede reflekteret i char's case
        if mods:
            if has_shift:
                mods.append("Shift")
            return f"<{'-'.join(mods)}-{keysym.lower()}>"
        # Ingen modifiers: bare returnér char som-er (small/big bogstav matters)
        return keysym

    # Tal-tasterne 0-9 fra numpad: keysym = "KP_1" osv
    if keysym.startswith("KP_") and keysym[3:].isdigit():
        if mods:
            return f"<{'-'.join(mods)}-{keysym}>"
        return f"<{keysym}>"

    # Fallback: pak ind i <> hvis vi ikke ved
    if mods:
        return f"<{'-'.join(mods)}-{keysym}>"
    return f"<{keysym}>"


# ===========================================================================
#  KeyBindings — load/save fra disk
# ===========================================================================
def default_hotkeys_path() -> Path:
    return default_data_dir() / "hotkeys.json"


class KeyBindings:
    """Manager for brugerdefinerede hotkeys.

    Holder en dict {action_id: [key1, key2, ...]}.
    Hvis en action ikke har en custom binding, returneres dens default.
    """

    def __init__(self, custom: Optional[Dict[str, List[str]]] = None) -> None:
        # custom indeholder kun OVERRIDES — actions uden custom binding
        # falder tilbage til ACTIONS[id]["default"]
        self._custom: Dict[str, List[str]] = dict(custom or {})

    # --- Query --------------------------------------------------------
    def get_keys(self, action_id: str) -> List[str]:
        """Returnér liste af Tk binding-strenge for given action."""
        if action_id not in ACTIONS:
            return []
        if action_id in self._custom:
            return list(self._custom[action_id])
        return list(ACTIONS[action_id]["default"])

    def is_default(self, action_id: str) -> bool:
        """True hvis denne action bruger sin default binding."""
        return action_id not in self._custom

    def all_actions(self) -> List[str]:
        """Returnér alle action-ids i den rækkefølge kategorier kommer."""
        result = []
        for cat in CATEGORIES_ORDER:
            for aid, info in ACTIONS.items():
                if info["category"] == cat:
                    result.append(aid)
        return result

    # --- Mutate -------------------------------------------------------
    def set_keys(self, action_id: str, keys: List[str]) -> None:
        """Sæt en liste af bindings for en action. Tom liste = ingen tast."""
        if action_id not in ACTIONS:
            raise ValueError(f"Ukendt action: {action_id}")
        # Strip dubletter (bevar rækkefølge)
        seen: set[str] = set()
        cleaned: List[str] = []
        for k in keys:
            if k and k not in seen:
                seen.add(k)
                cleaned.append(k)
        self._custom[action_id] = cleaned

    def add_key(self, action_id: str, key: str) -> bool:
        """Tilføj en enkelt tast til en action. Returnerer False hvis tasten
        allerede er bundet til samme action (no-op)."""
        if action_id not in ACTIONS or not key:
            return False
        current = self.get_keys(action_id)
        if key in current:
            return False
        new_list = current + [key]
        self.set_keys(action_id, new_list)
        return True

    def remove_key(self, action_id: str, key: str) -> bool:
        """Fjern en enkelt tast fra en action. Returnerer True hvis den blev fjernet."""
        if action_id not in ACTIONS:
            return False
        current = self.get_keys(action_id)
        if key not in current:
            return False
        new_list = [k for k in current if k != key]
        self.set_keys(action_id, new_list)
        return True

    def reset_action(self, action_id: str) -> None:
        """Nulstil en action til dens default bindings."""
        if action_id in self._custom:
            del self._custom[action_id]

    def reset_all(self) -> None:
        """Nulstil ALLE actions til defaults."""
        self._custom.clear()

    def find_conflict(self, key: str, exclude_action: Optional[str] = None) -> Optional[str]:
        """Returnér action_id der allerede bruger denne tast (eller None).

        Bruges af UI til at advare brugeren før de overskriver et binding.
        """
        for aid in ACTIONS:
            if aid == exclude_action:
                continue
            if key in self.get_keys(aid):
                return aid
        return None

    # --- Persistence --------------------------------------------------
    def to_dict(self) -> Dict[str, List[str]]:
        """Serialisér til dict (kun custom overrides — defaults gemmes ikke)."""
        return {aid: list(keys) for aid, keys in self._custom.items()}

    def save(self, path: Optional[Path] = None) -> None:
        """Gem til JSON-fil. Default-sti er ~/.setlist_manager/hotkeys.json."""
        target = path or default_hotkeys_path()
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            with open(target, "w", encoding="utf-8") as f:
                json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)
        except OSError as e:
            # Vi crasher ikke hvis vi ikke kan gemme — brugeren får bare
            # ikke persisteret deres ændringer
            print(f"[hotkeys] Kunne ikke gemme: {e}")

    @classmethod
    def load(cls, path: Optional[Path] = None) -> "KeyBindings":
        """Indlæs fra JSON-fil. Returnerer tom KeyBindings hvis filen
        ikke findes eller er korrupt (alle actions falder så tilbage til
        deres defaults)."""
        target = path or default_hotkeys_path()
        if not target.exists():
            return cls()
        try:
            with open(target, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                return cls()
            # Validér: kun kendte actions, kun string-værdier
            clean: Dict[str, List[str]] = {}
            for aid, keys in data.items():
                if aid not in ACTIONS:
                    continue  # ukendt action (måske fra nyere/ældre version) — skip
                if not isinstance(keys, list):
                    continue
                clean[aid] = [str(k) for k in keys if isinstance(k, str) and k]
            return cls(clean)
        except (OSError, json.JSONDecodeError, ValueError):
            return cls()


# ===========================================================================
#  Hjælper til at vise alle keys for en action på én linje
# ===========================================================================
def format_keys_list(keys: List[str]) -> str:
    """Formattér en liste af bindings til en single-line visning.

    >>> format_keys_list(["<space>", "<Right>"])
    'Mellemrum  ·  → Højre'
    """
    if not keys:
        return "(ingen tast)"
    return "  ·  ".join(format_key(k) for k in keys)
